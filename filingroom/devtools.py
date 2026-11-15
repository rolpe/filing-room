"""The app's Evaluation area (developer tools): recorded eval runs, the golden set, and starting runs.

Everything here sits behind one switch (FILINGROOM_DEV_TOOLS, default on) and one URL prefix (/api/dev/), so turning
it off hides it completely. It reads the eval harness's own files (results/, golden/, data/raw|parsed|index) and
never the app's filing cache. Runs are executed by filingroom.evaljob in a child process, so they produce exactly
what the CLI produces.
"""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import date, datetime
from pathlib import Path

from . import answer, checklist, config, evaljob, evalstats, evaluate, findings, golden, store

def switch_on(value: str | None) -> bool:
    """FILINGROOM_DEV_TOOLS: on unless set to 0, false, off or no."""
    return (value or "1").strip().lower() not in ("0", "false", "off", "no")


ENABLED = switch_on(os.environ.get("FILINGROOM_DEV_TOOLS"))
EVAL_LEDGER = config.DATA / "eval_spend.json"
EVAL_MAX_USD_PER_DAY = float(os.environ.get("EVAL_MAX_USD_PER_DAY", "3.00"))
EVAL_RUN_LIMIT_USD = float(os.environ.get("EVAL_RUN_LIMIT_USD", "3.00"))  # hard stop for one run
JOBS_DIR = config.DATA / "evals" / "jobs"
SPOT_DIR = evaljob.SPOT_DIR
EVAL_INDEX = config.DATA / "index"     # the eval corpus, whatever the app's filing cache is
EVAL_RAW = config.CLI_RAW
MAX_SPOT_ITEMS = 10
FALLBACK_PER_ITEM_USD = 0.031          # used only if no recorded run can give a better estimate

# The bar the project set before building (README "How accuracy was measured").
PASS_BAR = {"accuracy": (">=", 85.0), "citation_support_rate": (">=", 90.0), "unsupported_claim_rate": ("<=", 10.0)}
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")

_lock = threading.RLock()
_cache: dict[Path, tuple[float, dict]] = {}
_index_cache: dict[str, tuple[float, dict]] = {}
other_busy = lambda: None  # noqa: E731  set by the server: returns a message when a screening is running


# ---------------------------------------------------------------- files

def _read(path: Path) -> dict:
    mtime = path.stat().st_mtime
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    val = json.loads(path.read_text())
    _cache[path] = (mtime, val)
    return val


def _dir(kind: str) -> Path:
    if kind == "results":
        return config.RESULTS
    if kind == "spot":
        return SPOT_DIR
    raise KeyError(kind)


def load_run(kind: str, name: str) -> dict:
    if not NAME_RE.fullmatch(name or ""):
        raise KeyError(name)
    p = _dir(kind) / f"{name}.json"
    if not p.is_file():
        raise KeyError(name)
    r = _read(p)
    if "rows" not in r:
        raise KeyError(name)
    return r


def _runs(kind: str) -> list[tuple[str, dict]]:
    d = _dir(kind)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            r = _read(p)
        except (json.JSONDecodeError, OSError):
            continue
        if "rows" in r:
            out.append((p.stem, r))
    return out


def _companies() -> dict[str, dict]:
    return config.companies()


def holdout_tickers() -> set[str]:
    return {t for t, c in _companies().items() if c.get("split") == "holdout"}


def tune_tickers() -> list[str]:
    return [t for t, c in _companies().items() if c.get("split") == "tune"]


# ---------------------------------------------------------------- pure helpers (unit-tested)

def passes(metrics: dict) -> dict:
    """Each pass-bar metric against its threshold, plus `all`. A missing metric doesn't pass."""
    out = {}
    for key, (op, bar) in PASS_BAR.items():
        v = metrics.get(key)
        out[key] = v is not None and (v >= bar if op == ">=" else v <= bar)
    out["all"] = all(out[k] for k in PASS_BAR)
    return out


def total_cost(metrics: dict) -> float:
    c = metrics.get("cost_usd") or {}
    return round((c.get("answer") or 0) + (c.get("judge") or 0), 4)


def flips(rows: list[dict], prev_rows: list[dict]) -> list[dict]:
    """Items graded in both runs whose correctness changed."""
    before = {r["id"]: r.get("correct") for r in prev_rows}
    return [{"id": r["id"], "before": before[r["id"]], "after": r.get("correct")}
            for r in rows if r["id"] in before and before[r["id"]] != r.get("correct")]


def per_item_estimate(runs: list[dict]) -> float:
    """Average answering + judging cost per graded item over the latest (up to three) recorded full runs."""
    recent = [r for r in runs if len(r.get("rows", [])) >= 20][-3:]
    costs = [total_cost(r["metrics"]) / len(r["rows"]) for r in recent if total_cost(r["metrics"]) > 0]
    return round(sum(costs) / len(costs), 4) if costs else FALLBACK_PER_ITEM_USD


def estimate_usd(n_items: int, per_item: float) -> float:
    return round(max(0.01, n_items * per_item), 2)


def expected_text(expected: dict) -> str:
    if expected.get("not_found"):
        return "Not in the filings" + (f": {expected['text']}" if expected.get("text") else "")
    if expected.get("text"):
        return expected["text"]
    v, unit = expected.get("value"), expected.get("unit")
    if v is None:
        return ""
    if unit == "USD":
        s = f"${abs(v) / 1e6:,.1f}M"
        s = f"({s})" if v < 0 else s
    elif unit == "percent":
        s = f"{v:g}%"
    else:
        s = f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)
    return f"{s}{' · ' + expected['period'] if expected.get('period') else ''}"


# ---------------------------------------------------------------- views

def _docs_by_ticker(tickers: list[str]) -> dict[str, dict]:
    return {t: _eval_docs(t) for t in tickers}


def _summary(kind: str, name: str, r: dict) -> dict:
    m = r["metrics"]
    gold = _golden_by_id()
    status = review_status()
    tr = evalstats.trust(r["rows"], gold, _docs_by_ticker(r["tickers"]))
    tr.pop("statuses")
    key = evalstats.checked_share(r["rows"], status)
    key["from_sec"] = sum(1 for x in r["rows"] if x.get("correct") is not None
                          and (gold.get(x["id"], {}).get("source") or {}).get("method") in ("xbrl", "derived")
                          and status.get(x["id"]) != "human")
    return {"kind": kind, "name": name, "rates": evalstats.counts(r["rows"]), "trust": tr, "key": key, "label": r.get("label", ""), "note": r.get("note", ""),
            "timestamp": r.get("timestamp", name[:15]), "tickers": r["tickers"], "n_items": len(r["rows"]),
            "holdout": bool(set(r["tickers"]) & holdout_tickers()),
            "model": r.get("model"), "effort": r.get("effort"), "k": r.get("k"), "expand": r.get("expand", 0),
            "judge_model": r.get("judge_model"),
            "metrics": {k: m.get(k) for k in ("accuracy", "citation_support_rate", "unsupported_claim_rate",
                                               "abstention_precision", "abstention_recall", "retrieval_recall",
                                               "false_abstentions", "citation_verified_rate", "errors")},
            "by_grade": m.get("by_grade", {}), "cost_usd": total_cost(m), "wall_seconds": m.get("wall_seconds"),
            "passes": passes(m)}


def _memo_checks() -> list[dict]:
    out = []
    for p in sorted(config.RESULTS.glob("*_memo_*.json"), reverse=True):
        r = _read(p)
        c = r.get("check") or {}
        out.append({"name": p.stem, "ticker": p.stem.rsplit("_", 1)[-1], "note": r.get("note", ""),
                    "timestamp": p.stem[:15], "sentences": c.get("n_sentences"),
                    "unsupported": len(c.get("unsupported", [])), "rate": c.get("unsupported_rate"),
                    "cost_usd": (r.get("meta") or {}).get("cost_usd")})
    return out


def overview() -> dict:
    full = _runs("results")
    spot = _runs("spot")
    return {"runs": [_summary("results", n, r) for n, r in reversed(full)],
            "spot": [_summary("spot", n, r) for n, r in reversed(spot)],
            "memo_checks": _memo_checks(),
            "pass_bar": {k: {"op": op, "value": v} for k, (op, v) in PASS_BAR.items()},
            "job": job_view()}


def _labels() -> dict[str, str]:
    return {q["id"]: q.get("label", q["id"]) for q in checklist.load()}


def _prev_comparable(kind: str, name: str, r: dict) -> tuple[str, dict] | None:
    """The latest full run before this one over the same companies."""
    for n, pr in reversed(_runs("results")):
        if (kind == "spot" or n < name) and sorted(pr["tickers"]) == sorted(r["tickers"]) and n != name:
            return n, pr
    return None


def detail(kind: str, name: str) -> dict:
    r = load_run(kind, name)
    labels = _labels()
    prev = _prev_comparable(kind, name, r)
    fl = flips(r["rows"], prev[1]["rows"]) if prev else []
    flipped = {f["id"]: f["before"] for f in fl}
    rows = [{"id": x["id"], "ticker": x["ticker"], "qid": x["qid"], "label": labels.get(x["qid"], x["qid"]),
             "grade": x["grade"], "status": x["status"], "correct": x.get("correct"), "supported": x.get("supported"),
             "answer": x.get("answer", ""), "expected": expected_text(x.get("expected") or {}),
             "value_in_context": x.get("value_in_context"), "flipped": x["id"] in flipped,
             "before": flipped.get(x["id"])} for x in r["rows"]]
    better = sum(1 for f in fl if f["after"] and not f["before"])
    worse = sum(1 for f in fl if f["before"] and not f["after"])
    status = review_status()
    app = evalstats.trust(r["rows"], _golden_by_id(), _docs_by_ticker(r["tickers"]))["statuses"]
    for row in rows:
        row["app_status"] = app.get(row["id"])
        row["key"] = status.get(row["id"], "")
    return {**_summary(kind, name, r),
            "prev": _summary("results", prev[0], prev[1]) if prev else None,
            "flips": [{**f, "label": labels.get(f["id"].split(":", 1)[-1], f["id"])} for f in fl],
            "flip_test": {"better": better, "worse": worse, "p": round(evalstats.sign_test(better, worse), 4),
                          "statement": evalstats.flip_statement(better, worse)} if prev else None,
            "rows": rows}


def _golden_by_id() -> dict[str, dict]:
    p = config.GOLDEN
    return {i["id"]: i for i in (json.loads(l) for l in p.read_text().splitlines() if l.strip())} if p.exists() else {}


def _eval_docs(t: str) -> dict[str, dict]:
    p = EVAL_RAW / t / "manifest.json"
    return findings.doc_meta(json.loads(p.read_text())) if p.exists() else {}


def _golden_source(g: dict | None) -> dict | None:
    if not g:
        return None
    src = g.get("source") or {}
    quotes = ([{"doc_id": src["doc_id"], "quote": src["quote"]}] if src.get("quote") else []) + \
             [{"doc_id": q.get("doc_id"), "quote": q.get("quote")} for q in src.get("quotes", [])]
    return {"method": src.get("method") or ("quote" if quotes else ""), "quotes": quotes,
            "concepts": src.get("concepts"), "end": src.get("end"), "note": g.get("note", ""),
            "verified": g.get("verified")}


def item(kind: str, name: str, item_id: str) -> dict:
    r = load_run(kind, name)
    x = next((x for x in r["rows"] if x["id"] == item_id), None)
    if not x:
        raise KeyError(item_id)
    docs = _eval_docs(x["ticker"])
    q = checklist.by_id().get(x["qid"], {})
    return {"id": x["id"], "ticker": x["ticker"], "qid": x["qid"], "label": q.get("label", x["qid"]),
            "question": x.get("question") or q.get("question", ""), "grade": x["grade"],
            "expected": expected_text(x.get("expected") or {}), "golden": _golden_source(_golden_by_id().get(x["id"])),
            "status": x["status"], "answer": x.get("answer", ""), "value": x.get("value", ""),
            "period": x.get("period", ""), "confidence": x.get("confidence"), "correct": x.get("correct"),
            "supported": x.get("supported"), "judge_reason": x.get("judge_reason", ""),
            "value_in_context": x.get("value_in_context"), "error": x.get("error"),
            "citations": [findings.citation_view(i, c, docs) for i, c in enumerate(x.get("citations", []))]}


def _eval_index(t: str) -> dict[str, dict]:
    p = EVAL_INDEX / f"{t}.jsonl"
    if not p.exists():
        return {}
    mtime = p.stat().st_mtime
    hit = _index_cache.get(t)
    if hit and hit[0] == mtime:
        return hit[1]
    by_id = {c["chunk_id"]: c for c in (json.loads(l) for l in p.read_text().splitlines() if l.strip())}
    _index_cache[t] = (mtime, by_id)
    return by_id


def _step(chunk_id: str, d: int) -> str | None:
    base, _, n = chunk_id.rpartition("#")
    try:
        return f"{base}#{int(n) + d:03d}"
    except ValueError:
        return None


def passage(kind: str, name: str, item_id: str, chunk_id: str) -> dict:
    """A cited passage from the eval corpus, with the item's quotes highlighted."""
    r = load_run(kind, name)
    x = next((x for x in r["rows"] if x["id"] == item_id), None)
    if not x:
        raise KeyError(item_id)
    cits = x.get("citations", [])
    quotes = [(i + 1, c["quote"]) for i, c in enumerate(cits) if c.get("chunk_id") == chunk_id]
    ix = _eval_index(x["ticker"])
    c = ix.get(chunk_id)
    if not c:
        cited = next((c for c in cits if c.get("chunk_id") == chunk_id), None)
        if not cited:
            raise KeyError(chunk_id)
        d = findings.doc_info(cited.get("doc_id"), _eval_docs(x["ticker"]))
        return {"chunk_id": chunk_id, "doc_id": cited.get("doc_id"), "form": d.get("form", ""),
                "period": d.get("period", ""), "filing_date": d.get("filing_date", ""), "heading": "", "subheading": "",
                "url": cited.get("url", ""), "form_label": findings.FORM_LABELS.get(d.get("form", ""), "Filing"),
                "blocks": [], "found": [], "quotes_here": [n for n, _ in quotes], "prev_chunk": None,
                "next_chunk": None, "missing": True}
    p = findings.passage(c, quotes)
    prev_id, next_id = _step(chunk_id, -1), _step(chunk_id, 1)
    heading = c["heading"] if c["heading"] not in ("proxy", "press_release") else ""
    return {**{k: c[k] for k in ("chunk_id", "doc_id", "form", "period", "filing_date", "subheading", "url")},
            "heading": heading, "form_label": findings.FORM_LABELS.get(c["form"], c["form"]), **p,
            "quotes_here": [n for n, _ in quotes], "prev_chunk": prev_id if prev_id in ix else None,
            "next_chunk": next_id if next_id in ix else None, "missing": False}


def golden_view() -> dict:
    labels = _labels()
    items = list(_golden_by_id().values())
    manual = _manual_items()
    cos = _companies()
    out = []
    for t in sorted({i["ticker"] for i in items}, key=lambda t: (cos.get(t, {}).get("split") != "tune", t)):
        rows = []
        for i in items:
            if i["ticker"] != t:
                continue
            m = manual.get(i["id"])
            rows.append({"id": i["id"], "qid": i["qid"], "label": labels.get(i["qid"], i["qid"]), "grade": i["grade"],
                         "expected": expected_text(i.get("expected") or {}), "source": _golden_source(i),
                         "review": m.get("verified", "claude-draft") if m else "sec-data",
                         "review_note": (m or {}).get("review_note", "")})
        out.append({"ticker": t, "name": cos.get(t, {}).get("name", t), "holdout": t in holdout_tickers(),
                    "items": rows})
    status = [m.get("verified") for m in manual.values()]
    return {"companies": out, "total": len(items),
            "progress": {"manual": len(manual), "checked": status.count("human"), "needs_fix": status.count("needs-fix"),
                         "from_sec": len(items) - len(manual)}}


# ---------------------------------------------------------------- answer-key review (golden/manual.jsonl)

REVIEW_STATES = {"checked": "human", "needs_fix": "needs-fix", "undo": "claude-draft"}


def _manual_items() -> dict[str, dict]:
    if not golden.MANUAL.exists():
        return {}
    return {o["id"]: o for o in (json.loads(l) for l in golden.MANUAL.read_text().splitlines()
                                 if l.strip() and not l.startswith("//"))}


def review_status() -> dict[str, str]:
    """Current check state per golden id: human / claude-draft / needs-fix for hand-built items, sec-data otherwise."""
    return {i: m.get("verified", "claude-draft") for i, m in _manual_items().items()}


def edit_manual_line(text: str, item_id: str, verified: str, note: str | None) -> str:
    """Return manual.jsonl with only one item's `verified` (and `review_note`) changed. Every other line, comment and
    blank is kept byte for byte; the edited line keeps its key order (review_note goes last when added)."""
    out, found = [], False
    for line in text.split("\n"):
        if line.strip() and not line.startswith("//"):
            obj = json.loads(line)
            if obj.get("id") == item_id:
                found = True
                obj["verified"] = verified
                if note:
                    obj["review_note"] = note
                else:
                    obj.pop("review_note", None)
                line = json.dumps(obj, ensure_ascii=False)
        out.append(line)
    if not found:
        raise KeyError(item_id)
    return "\n".join(out)


def review(item_id: str, action: str, note: str = "") -> dict:
    """Mark a hand-built answer-key item as checked, as needing a fix (with a note), or undo. Writes in place."""
    if action not in REVIEW_STATES:
        raise ValueError("Unknown review action.")
    note = " ".join(str(note or "").split())[:300]
    if action == "needs_fix" and not note:
        raise ValueError("Say what needs fixing.")
    with _lock:
        text = golden.MANUAL.read_text()
        new = edit_manual_line(text, item_id, REVIEW_STATES[action], note if action == "needs_fix" else None)
        tmp = golden.MANUAL.with_name(f".{golden.MANUAL.name}.tmp")
        tmp.write_text(new)
        os.replace(tmp, golden.MANUAL)
    return golden_item(item_id)


def _locate(doc_id: str, quote: str, ticker: str) -> str | None:
    """The eval-corpus chunk where a golden quote appears, if any."""
    for cid, c in _eval_index(ticker).items():
        if c["doc_id"] == doc_id and findings.quote_spans(c["text"], quote):
            return cid
    return None


def golden_item(item_id: str) -> dict:
    g = _golden_by_id().get(item_id)
    if not g:
        raise KeyError(item_id)
    m = _manual_items().get(item_id)
    q = checklist.by_id().get(g["qid"], {})
    src = _golden_source(g)
    quotes = [{"n": i + 1, "doc_id": x["doc_id"], "quote": x["quote"], "chunk_id": _locate(x["doc_id"], x["quote"], g["ticker"]),
               **{k: v for k, v in findings.doc_info(x["doc_id"], _eval_docs(g["ticker"])).items() if k in ("form", "period", "url")}}
              for i, x in enumerate(src["quotes"] if src else [])]
    return {"id": item_id, "ticker": g["ticker"], "qid": g["qid"], "label": q.get("label", g["qid"]),
            "question": q.get("question", ""), "grade": g["grade"], "expected": expected_text(g.get("expected") or {}),
            "source": src, "quotes": quotes, "note": g.get("note", ""),
            "review": m.get("verified", "claude-draft") if m else "sec-data", "review_note": (m or {}).get("review_note", ""),
            "editable": m is not None}


def golden_passage(item_id: str, chunk_id: str) -> dict:
    g = golden_item(item_id)
    quotes = [(x["n"], x["quote"]) for x in g["quotes"] if x["chunk_id"] == chunk_id]
    c = _eval_index(g["ticker"]).get(chunk_id)
    if not c or not quotes:
        raise KeyError(chunk_id)
    p = findings.passage(c, quotes)
    prev_id, next_id = _step(chunk_id, -1), _step(chunk_id, 1)
    ix = _eval_index(g["ticker"])
    heading = c["heading"] if c["heading"] not in ("proxy", "press_release") else ""
    return {**{k: c[k] for k in ("chunk_id", "doc_id", "form", "period", "filing_date", "subheading", "url")},
            "heading": heading, "form_label": findings.FORM_LABELS.get(c["form"], c["form"]), **p,
            "quotes_here": [n for n, _ in quotes], "prev_chunk": prev_id if prev_id in ix else None,
            "next_chunk": next_id if next_id in ix else None, "missing": False}


# ---------------------------------------------------------------- spend + jobs

def _ledger() -> dict:
    return store.read_json(EVAL_LEDGER, {}) or {}


def _charge(usd: float) -> None:
    with _lock:
        led = _ledger()
        led[date.today().isoformat()] = round(led.get(date.today().isoformat(), 0.0) + usd, 6)
        store.write_json(EVAL_LEDGER, led)


def spend_view() -> dict:
    led = _ledger()
    today = led.get(date.today().isoformat(), 0.0)
    return {"today_usd": round(today, 4), "cap_usd": EVAL_MAX_USD_PER_DAY,
            "remaining_usd": round(max(0.0, EVAL_MAX_USD_PER_DAY - today), 4), "run_limit_usd": EVAL_RUN_LIMIT_USD}


def ledger_by_day() -> dict:
    return _ledger()


def _job_file() -> Path:
    return JOBS_DIR / "current.json"


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _reconcile() -> dict | None:
    """Current job with its child's status; charges the ledger once when the job ends."""
    with _lock:
        job = store.read_json(_job_file())
        if not job:
            return None
        st = store.read_json(Path(job["dir"]) / "status.json") or {"state": "running", "done": 0,
                                                                     "total": job["spec"]["total"], "cost_usd": 0.0}
        if st["state"] == "running" and not _alive(job.get("pid")):
            st = {**st, "state": "failed", "error": st.get("error") or "The run stopped before finishing."}
        if st["state"] != "running" and not job.get("charged"):
            _charge(st.get("cost_usd") or 0.0)
            job["charged"] = True
            job["final"] = st
            store.write_json(_job_file(), job)
        return {**job, "status": st}


def job_view() -> dict | None:
    j = _reconcile()
    if not j:
        return None
    st = j["status"]
    return {"id": j["id"], "kind": j["spec"]["kind"], "tickers": j["spec"]["tickers"], "label": j["spec"].get("label", ""),
            "started": j["started"], "estimate_usd": j["estimate_usd"], "state": st["state"], "done": st.get("done", 0),
            "total": st.get("total", j["spec"]["total"]), "cost_usd": st.get("cost_usd", 0.0), "error": st.get("error"),
            "result": st.get("result")}


def running() -> bool:
    j = job_view()
    return bool(j and j["state"] == "running")


def busy_message() -> str | None:
    return "An evaluation run is in progress. One paid job at a time: try again when it finishes." if running() else None


def _validate(spec: dict) -> dict:
    tickers = [t for t in spec.get("tickers", []) if isinstance(t, str)]
    tune = tune_tickers()
    if not tickers:
        raise ValueError("Choose at least one company.")
    for t in tickers:
        if t in holdout_tickers():
            raise ValueError(f"{t} is the held-out company: it was run once on the frozen system and stays that way.")
        if t not in tune:
            raise ValueError(f"{t} isn't one of the evaluation companies.")
    tickers = [t for t in tune if t in tickers]
    golden_ids = [i["id"] for i in golden.load(tickers)]
    kind = spec.get("kind")
    if kind == "full":
        ids = golden_ids
    elif kind == "spot":
        ids = [i for i in spec.get("ids", []) if i in set(golden_ids)]
        if not ids:
            raise ValueError("Choose the items to spot-check.")
        if len(ids) > MAX_SPOT_ITEMS:
            raise ValueError(f"A spot check takes at most {MAX_SPOT_ITEMS} items; run the full set instead.")
    else:
        raise ValueError("Choose a full run or a spot check.")
    label = re.sub(r"[^A-Za-z0-9\-]+", "-", str(spec.get("label", "")).strip())[:40].strip("-")
    note = str(spec.get("note", "")).strip().replace("|", "/")[:300]
    if kind == "spot":
        label = f"spot{'-' + label if label else ''}"
    return {"kind": kind, "tickers": tickers, "ids": ids, "total": len(ids), "label": label, "note": note}


def estimate(spec: dict) -> dict:
    s = _validate(spec)
    per = per_item_estimate([r for _, r in _runs("results")])
    return {"usd": estimate_usd(s["total"], per), "per_item_usd": per, "items": s["total"], "spend": spend_view(),
            "model": answer.DEFAULT_MODEL, "effort": answer.DEFAULT_EFFORT, "k": answer.DEFAULT_K,
            "expand": answer.DEFAULT_EXPAND, "judge_model": evaluate.JUDGE_MODEL}


def start(spec: dict, confirm_usd: float) -> dict:
    with _lock:
        s = _validate(spec)
        msg = other_busy() or busy_message()
        if msg:
            raise RuntimeError(msg)
        est = estimate(spec)
        if confirm_usd + 1e-9 < est["usd"]:
            raise ValueError(f"Confirm the estimated cost (${est['usd']:.2f}) to start.")
        sp = spend_view()
        if est["usd"] > sp["remaining_usd"]:
            raise PermissionError(f"Today's evaluation budget is used (${sp['today_usd']:.2f} of ${sp['cap_usd']:.2f}). "
                                  "Raise EVAL_MAX_USD_PER_DAY in .env to run more today.")
        limit = round(min(EVAL_RUN_LIMIT_USD, sp["remaining_usd"]), 2)
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        d = JOBS_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        store.write_json(d / "spec.json", {**s, "limit_usd": limit})
        env = {k: v for k, v in os.environ.items() if k != "FILINGROOM_APP_DIR"}
        proc = subprocess.Popen([sys.executable, "-m", "filingroom.evaljob", "run", str(d)], cwd=config.ROOT, env=env,
                                stdout=subprocess.DEVNULL, stderr=open(d / "stderr.log", "w"))
        store.write_json(_job_file(), {"id": job_id, "dir": str(d), "pid": proc.pid, "spec": s, "limit_usd": limit,
                                       "estimate_usd": est["usd"], "started": datetime.now().isoformat(timespec="seconds"),
                                       "charged": False})
        threading.Thread(target=lambda: (proc.wait(), _reconcile()), daemon=True).start()
    return job_view()


def retrieval(tickers: list[str]) -> dict:
    """Free check in a child process (it needs the eval corpus): is the golden number in the retrieved passages?"""
    tune = tune_tickers()
    tickers = [t for t in tune if t in tickers] or tune
    env = {k: v for k, v in os.environ.items() if k != "FILINGROOM_APP_DIR"}
    p = subprocess.run([sys.executable, "-m", "filingroom.evaljob", "retrieval", ",".join(tickers)], cwd=config.ROOT,
                       env=env, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("The retrieval check failed: " + (p.stderr.strip().splitlines() or ["no output"])[-1])
    r = json.loads(p.stdout.strip().splitlines()[-1])
    labels = _labels()
    for it in r["items"]:
        it["label"] = labels.get(it["id"].split(":", 1)[-1], it["id"])
        it["ticker"] = it["id"].split(":", 1)[0]
    return {**r, "tickers": tickers, "at": datetime.now().isoformat(timespec="seconds")}


def config_view() -> dict:
    """What the run form needs: companies, golden items per company, estimate basis, spend, current job."""
    cos = _companies()
    per = per_item_estimate([r for _, r in _runs("results")])
    items = [{"id": i["id"], "ticker": i["ticker"], "qid": i["qid"], "label": _labels().get(i["qid"], i["qid"]),
              "grade": i["grade"]} for i in golden.load(tune_tickers())]
    counts: dict[str, int] = {}
    for g in _golden_by_id().values():
        counts[g["ticker"]] = counts.get(g["ticker"], 0) + 1
    return {"companies": [{"ticker": t, "name": c.get("name", t), "split": c.get("split"),
                           "items": counts.get(t, 0)}
                          for t, c in cos.items() if c.get("split") in ("tune", "holdout")],
            "items": items, "per_item_usd": per, "max_spot_items": MAX_SPOT_ITEMS, "spend": spend_view(),
            "model": answer.DEFAULT_MODEL, "effort": answer.DEFAULT_EFFORT, "k": answer.DEFAULT_K,
            "expand": answer.DEFAULT_EXPAND, "judge_model": evaluate.JUDGE_MODEL, "job": job_view()}
