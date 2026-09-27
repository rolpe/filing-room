"""Local web UI: a small JSON API over the project's files, plus the static frontend in ui/.

Private by construction:
  - binds to 127.0.0.1 only (not reachable from other machines);
  - rejects requests whose Host isn't this server (blocks DNS-rebinding from other websites);
  - POSTs must carry an X-Filing-Room header, which a cross-site page can't send without a CORS
    preflight this server never grants.
Everything is free except POST /api/ask, which calls Claude and is capped per day (UI_MAX_USD_PER_DAY).
Ask never writes checklist runs or eval results, so it is open for every company, including Box.
"""

import json
import os
import re
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import answer, checklist, config, edgar, golden, llm
from .index import Index

UI_DIR = config.ROOT / "ui"
SPEND_LEDGER = config.DATA / "ui_spend.json"
UI_MAX_USD_PER_DAY = float(os.environ.get("UI_MAX_USD_PER_DAY", "1.00"))
ASK_ESTIMATE_USD = 0.05  # generous per-question estimate used for the pre-check
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".woff2": "font/woff2", ".ico": "image/x-icon"}

_indexes: dict[str, Index] = {}
_lock = threading.Lock()


def _index(ticker: str) -> Index:
    with _lock:
        if ticker not in _indexes:
            _indexes[ticker] = Index(ticker)
        return _indexes[ticker]


# ---------------------------------------------------------------- data

def _eval_results() -> list[dict]:
    out = []
    for p in sorted(config.RESULTS.glob("*.json")):
        r = json.loads(p.read_text())
        if "rows" in r:
            r["name"] = p.stem
            out.append(r)
    return out


def _latest_eval_rows(ticker: str) -> tuple[str | None, dict[str, dict]]:
    for r in reversed(_eval_results()):
        rows = {row["qid"]: row for row in r["rows"] if row["ticker"] == ticker}
        if rows:
            return r["name"], rows
    return None, {}


def _latest_run(ticker: str):
    runs = sorted(p for p in config.RUNS.glob(f"{ticker}_*.json") if not p.stem.endswith("_memo"))
    return runs[-1] if runs else None


def _slim_citations(cits: list[dict]) -> list[dict]:
    return [{k: c.get(k) for k in ("chunk_id", "quote", "verified", "url", "doc_id", "section")} for c in cits]


def companies() -> list[dict]:
    out = []
    for t, co in config.companies().items():
        try:
            filings = edgar.manifest(t)
        except SystemExit:
            filings = []
        name, rows = _latest_eval_rows(t)
        graded = [r for r in rows.values() if r["correct"] is not None]
        out.append({
            **co,
            "filings": [{k: f[k] for k in ("doc_id", "form", "period", "filing_date", "url")} for f in filings],
            "periods": checklist.periods(t) if filings else None,
            "eval": {"run": name, "graded": len(graded), "correct": sum(r["correct"] for r in graded)} if rows else None,
            "situation": co.get("why", ""),
            "has_run": _latest_run(t) is not None,
            "has_memo": any(config.RUNS.glob(f"{t}_*_memo.json")),
        })
    return out


def checklist_view(ticker: str) -> dict:
    """Answers for every checklist question: from the latest full run, else from the latest eval."""
    qs = checklist.load()
    eval_name, eval_rows = _latest_eval_rows(ticker)
    run = _latest_run(ticker)
    if run:
        data = json.loads(run.read_text())
        answers = {a["qid"]: a for a in data["answers"]}
        source = {"kind": "run", "name": run.stem, "model": data["meta"]["model"],
                  "cost_usd": data["meta"]["cost_usd"]}
    else:
        answers = eval_rows
        source = {"kind": "eval", "name": eval_name, "model": next(iter(eval_rows.values()))["model"] if eval_rows else None}
    items = []
    for q in qs:
        a = answers.get(q["id"])
        g = eval_rows.get(q["id"])
        items.append({
            "qid": q["id"], "category": q["category"], "question": q["question"], "answer_type": q["answer_type"],
            "answer": a and {k: a.get(k) for k in ("status", "answer", "value", "unit", "period", "confidence")},
            "citations": _slim_citations(a["citations"]) if a else [],
            "graded": g and {"correct": g["correct"], "grade": g["grade"], "supported": g["supported"],
                             "expected": g["expected"], "judge_reason": g.get("judge_reason", ""),
                             "eval_run": eval_name},
        })
    return {"ticker": ticker, "source": source, "items": items}


def memo_view(ticker: str) -> dict | None:
    memos = sorted(config.RUNS.glob(f"{ticker}_*_memo.json"))
    if not memos:
        return None
    m = json.loads(memos[-1].read_text())
    src = config.RUNS / m["meta"]["source_run"]
    answers = {a["qid"]: a for a in json.loads(src.read_text())["answers"]} if src.exists() else {}
    refs = {r for s in m["memo"]["sections"] for x in s["sentences"] for r in x["refs"]}
    sources = {qid: {"question": answers[qid]["question"], "answer": answers[qid]["answer"],
                     "citations": _slim_citations([c for c in answers[qid]["citations"] if c["verified"]])}
               for qid in refs if qid in answers}
    return {"ticker": ticker, "name": memos[-1].stem, "meta": m["meta"], "memo": m["memo"], "check": m["check"],
            "sources": sources}


def evals_view() -> dict:
    runs = [{"name": r["name"], "timestamp": r["timestamp"], "label": r["label"], "note": r["note"],
             "tickers": r["tickers"], "model": r["model"], "effort": r["effort"], "k": r["k"],
             "expand": r.get("expand", 0), "metrics": r["metrics"]} for r in _eval_results()]
    memo_checks = []
    for p in sorted(config.RESULTS.glob("*_memo_*.json")):
        r = json.loads(p.read_text())
        memo_checks.append({"name": p.stem, "ticker": p.stem.rsplit("_", 1)[-1], "note": r.get("note", ""),
                            "unsupported": len(r["check"]["unsupported"]), "sentences": r["check"]["n_sentences"],
                            "rate": r["check"]["unsupported_rate"]})
    return {"runs": runs, "memo_checks": memo_checks}


def eval_detail(name: str) -> dict | None:
    path = config.RESULTS / f"{name}.json"
    if not path.exists() or path.parent != config.RESULTS:
        return None
    r = json.loads(path.read_text())
    rows = [{k: row.get(k) for k in ("id", "ticker", "qid", "question", "category", "grade", "status", "answer",
                                     "value", "period", "correct", "supported", "judge_reason", "expected",
                                     "value_in_context")} | {"citations": _slim_citations(row["citations"])}
            for row in r.get("rows", [])]
    return {k: r[k] for k in ("timestamp", "label", "note", "tickers", "model", "metrics")} | {"name": name, "rows": rows}


_QUOTE_MAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _norm_index(text: str) -> tuple[str, list[int]]:
    """Lowercase, unify quotes/dashes, drop whitespace, '$' and '|'; keep a map back to original offsets."""
    chars, idx = [], []
    for i, ch in enumerate(text.translate(_QUOTE_MAP)):
        if ch.isspace() or ch in "$|":
            continue
        chars.append(ch.lower())
        idx.append(i)
    return "".join(chars), idx


def quote_spans(text: str, quote: str) -> list[tuple[int, int]]:
    """Where a (possibly '...'-elided) quote sits in the text, as original-offset spans."""
    norm, idx = _norm_index(text)
    spans, pos = [], 0
    for frag in re.split(r"\.\.\.|…", quote):
        f, _ = _norm_index(frag)
        if len(f) < 3:
            continue
        i = norm.find(f, pos)
        if i < 0:
            return []
        spans.append((idx[i], idx[i + len(f) - 1] + 1))
        pos = i + len(f)
    return spans


def _segments(text: str, start: int, spans: list[tuple[int, int, int]]) -> list[dict]:
    """Split one line (starting at `start` in the chunk) into runs; q = index of the quote marking it."""
    end = start + len(text)
    cuts = sorted({start, end} | {max(start, min(end, x)) for s in spans for x in s[:2]})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if a == b:
            continue
        q = next((qi for s, e, qi in spans if s < b and e > a), None)
        if out and out[-1]["q"] == q:
            out[-1]["t"] += text[a - start:b - start]
        else:
            out.append({"t": text[a - start:b - start], "m": q is not None, "q": q})
    return out


def passage_view(ticker: str, chunk_id: str, quotes: list[str]) -> dict | None:
    ix = _index(ticker)
    c = ix.by_id.get(chunk_id)
    if not c:
        return None
    text = c["text"]
    spans = [(s, e, qi) for qi, q in enumerate(quotes) for s, e in quote_spans(text, q)]
    blocks, pos, table = [], 0, None
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        if line == "[TABLE]":
            table = {"type": "table", "rows": []}
            blocks.append(table)
            continue
        if line == "[/TABLE]":
            table = None
            continue
        if not line.strip():
            continue
        if table is not None:
            cells, cpos = [], start
            for cell in line.split(" | "):
                cells.append(_segments(cell, cpos, spans))
                cpos += len(cell) + 3
            table["rows"].append(cells)
        else:
            blocks.append({"type": "p", "segments": _segments(line, start, spans)})
    base, _, n = chunk_id.rpartition("#")
    prev_id, next_id = f"{base}#{int(n) - 1:03d}", f"{base}#{int(n) + 1:03d}"
    return {**{k: c[k] for k in ("chunk_id", "doc_id", "form", "period", "filing_date", "heading", "subheading", "url")},
            "blocks": blocks, "found": bool(spans),
            "prev_id": prev_id if prev_id in ix.by_id else None, "next_id": next_id if next_id in ix.by_id else None}


def search_view(ticker: str, q: str, form: str | None) -> list[dict]:
    hits = _index(ticker).search(q, k=10, forms=[form] if form else None)
    return [{"score": round(h.score, 1), **{k: h.chunk[k] for k in ("chunk_id", "doc_id", "form", "period",
                                                                     "heading", "subheading", "url", "text")}}
            for h in hits]


def _manual_lines() -> list[str]:
    return golden.MANUAL.read_text().splitlines()


def golden_view() -> list[dict]:
    qs = checklist.by_id()
    out = []
    for line in _manual_lines():
        if line.strip() and not line.startswith("//"):
            it = json.loads(line)
            out.append({**it, "question": qs[it["qid"]]["question"], "category": qs[it["qid"]]["category"]})
    return out


def golden_verify(item_id: str, verified: bool) -> dict:
    lines, found = [], None
    for line in _manual_lines():
        if line.strip() and not line.startswith("//"):
            it = json.loads(line)
            if it["id"] == item_id:
                it["verified"] = "human" if verified else "claude-draft"
                line, found = json.dumps(it, ensure_ascii=False), it
        lines.append(line)
    if not found:
        raise KeyError(item_id)
    golden.MANUAL.write_text("\n".join(lines) + "\n")
    golden.build(list(config.companies()))  # keep golden.jsonl in sync
    (config.ROOT / "golden" / "REVIEW.md").write_text(golden.review_sheet())
    return {"id": item_id, "verified": found["verified"]}


# ---------------------------------------------------------------- paid: ask

def _ledger() -> dict:
    try:
        return json.loads(SPEND_LEDGER.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def spend_view() -> dict:
    today = date.today().isoformat()
    led = _ledger()
    return {"today_usd": round(led.get(today, 0.0), 4), "cap_usd": UI_MAX_USD_PER_DAY,
            "total_usd": round(sum(led.values()), 4), "ask_estimate_usd": ASK_ESTIMATE_USD}


def ask(ticker: str, question: str) -> dict:
    today = date.today().isoformat()
    with _lock:
        led = _ledger()
        if led.get(today, 0.0) + ASK_ESTIMATE_USD > UI_MAX_USD_PER_DAY:
            raise PermissionError(f"Daily UI budget reached (${led.get(today, 0.0):.2f} of "
                                  f"${UI_MAX_USD_PER_DAY:.2f}). Raise UI_MAX_USD_PER_DAY in .env to continue.")
    qs = checklist.by_id()
    q = qs.get(question) or {"id": "adhoc", "category": "Ad hoc", "question": question[:500],
                             "answer_type": "text", "period": "current", "where": {}}
    meter = llm.CostMeter()
    r = answer.answer_question(ticker, q, _index(ticker), meter)
    cost = meter.cost()
    with _lock:
        led = _ledger()
        led[today] = led.get(today, 0.0) + cost
        SPEND_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        SPEND_LEDGER.write_text(json.dumps(led, indent=1))
    return {"question": q["question"], "cost_usd": round(cost, 4),
            **{k: r[k] for k in ("status", "answer", "value", "unit", "period", "confidence", "error")},
            "citations": _slim_citations(r["citations"]), "spend": spend_view()}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "filing-room"

    def log_message(self, fmt, *args):  # quiet: only log errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _error(self, status: int, msg: str) -> None:
        self._json({"error": msg}, status)

    def _ticker(self, t: str) -> str | None:
        t = t.upper()
        return t if t in config.companies() else None

    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "forbidden host")
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
        qs = parse_qs(url.query)
        try:
            if not parts or parts[0] != "api":
                return self._static(url.path)
            route = parts[1:] if len(parts) > 1 else []
            if route == ["companies"]:
                return self._json(companies())
            if route == ["evals"]:
                return self._json(evals_view())
            if route == ["spend"]:
                return self._json(spend_view())
            if route == ["golden"]:
                return self._json(golden_view())
            if len(route) == 2 and route[0] == "evals":
                d = eval_detail(route[1])
                return self._json(d) if d else self._error(404, "no such eval")
            if len(route) == 2 and route[0] == "passage":
                t = self._ticker(route[1])
                cid = qs.get("id", [""])[0]
                if not t or not cid.startswith(t + "_"):
                    return self._error(404, "unknown passage")
                p = passage_view(t, cid, qs.get("q", []))
                return self._json(p) if p else self._error(404, "unknown passage")
            if len(route) == 2 and route[0] in ("checklist", "memo", "search"):
                t = self._ticker(route[1])
                if not t:
                    return self._error(404, "unknown ticker")
                if route[0] == "checklist":
                    return self._json(checklist_view(t))
                if route[0] == "memo":
                    m = memo_view(t)
                    return self._json(m) if m else self._error(404, "no memo yet")
                q = qs.get("q", [""])[0].strip()
                return self._json(search_view(t, q, qs.get("form", [None])[0]) if q else [])
            return self._error(404, "not found")
        except SystemExit as e:  # e.g. an index that hasn't been built
            return self._error(409, str(e))

    def do_POST(self):
        if not self._host_ok():
            return self._error(403, "forbidden host")
        if self.headers.get("X-Filing-Room") != "1":
            return self._error(403, "missing X-Filing-Room header")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 10_000:
            return self._error(413, "too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._error(400, "bad json")
        parts = [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p]
        try:
            if parts[:2] == ["api", "ask"] and len(parts) == 3:
                t = self._ticker(parts[2])
                if not t:
                    return self._error(404, "unknown ticker")
                question = str(body.get("question", "")).strip()
                if not question:
                    return self._error(400, "empty question")
                return self._json(ask(t, question))
            if parts[:2] == ["api", "golden"] and len(parts) == 4 and parts[3] == "verify":
                return self._json(golden_verify(parts[2], bool(body.get("verified"))))
            return self._error(404, "not found")
        except PermissionError as e:
            return self._error(402, str(e))
        except KeyError as e:
            return self._error(404, f"unknown id {e}")
        except SystemExit as e:
            return self._error(409, str(e))

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (UI_DIR / rel).resolve()
        if UI_DIR.resolve() not in target.parents or not target.is_file():
            target = UI_DIR / "index.html"  # single-page app: unknown paths get the shell
        if not target.exists():
            return self._error(404, "ui not built")
        self._send(HTTPStatus.OK, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))


def serve(port: int = 8787, open_browser: bool = True) -> None:
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        raise SystemExit(f"Port {port} is already in use (maybe the UI is already running?). Try ./fr ui --port {port + 1}")
    url = f"http://127.0.0.1:{port}/"
    print(f"filing-room UI on {url}  (local only; Ctrl-C to stop)")
    print(f"paid actions capped at ${UI_MAX_USD_PER_DAY:.2f}/day (UI_MAX_USD_PER_DAY)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
