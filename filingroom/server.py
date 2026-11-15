"""Local web app: a JSON API over the app store (store.py) and the engine, plus the built frontend in web/dist.

Private by construction:
  - binds to 127.0.0.1 only (not reachable from other machines);
  - rejects requests whose Host isn't this server (blocks DNS rebinding from other websites);
  - POSTs must carry an X-Filing-Room header, which a cross-site page can't send without a CORS preflight this
    server never grants.
Paid actions (screening a company, asking a question) need the caller to confirm the estimated cost in the request,
and are capped per day in ledgers under data/ that don't depend on which app store is in use.
"""

import json
import os
import re
import shutil
import threading
import time
import uuid
import webbrowser
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import answer, checklist, config, devtools, edgar, financials, findings, llm, memo, pipeline, present, store
from .index import Index

WEB_DIST = config.ROOT / "web" / "dist"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".woff2": "font/woff2", ".ico": "image/x-icon", ".json": "application/json", ".txt": "text/plain"}

# Spend ledgers ({date: usd}); real money, so they live in data/ whatever FILINGROOM_APP_DIR says.
ASK_LEDGER = config.DATA / "ui_spend.json"
RUN_LEDGER = config.DATA / "run_spend.json"
ASK_MAX_USD_PER_DAY = float(os.environ.get("UI_MAX_USD_PER_DAY", "1.00"))
RUN_MAX_USD_PER_DAY = float(os.environ.get("RUN_MAX_USD_PER_DAY", "3.00"))
ASK_ESTIMATE_USD = 0.05   # generous per-question estimate (typical is ~$0.03)
ASK_LIMIT_USD = 0.25      # hard stop for one question
RUN_LIMIT_USD = 2.50      # hard stop for one screening
PER_ANSWER_USD = 0.025    # 40 answers ~ $1.00
MEMO_USD = 0.20           # memo + claim check
PRESENT_USD = 0.05        # presentation pass (small model)

STAGES = {  # stage -> (label, progress fraction at start)
    "queued": ("Starting", 0.0), "register": ("Checking filings", 0.02), "fetch": ("Downloading filings", 0.05),
    "parse": ("Reading filings", 0.12), "index": ("Indexing", 0.17), "answer": ("Answering", 0.2),
    "present": ("Summarizing findings", 0.82), "memo": ("Drafting screening memo", 0.88), "done": ("Done", 1.0),
}

_indexes: dict[str, Index] = {}
_cache: dict[tuple, tuple] = {}
_lock = threading.RLock()
_job_lock = threading.Lock()
_running: dict[str, dict] = {}


class Busy(Exception):
    pass


def _index(t: str) -> Index:
    with _lock:
        if t not in _indexes:
            _indexes[t] = Index(t)
        return _indexes[t]


def _cached(key: tuple, path, build):
    """Memoize build() on a file's mtime (company facts are MBs of JSON)."""
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    val = build()
    _cache[key] = (mtime, val)
    return val


def _qs() -> list[dict]:
    return checklist.load()


def _today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------- ledgers

def _ledger(path) -> dict:
    return store.read_json(path, {}) or {}


def _charge(path, usd: float) -> None:
    with _lock:
        led = _ledger(path)
        led[_today()] = round(led.get(_today(), 0.0) + usd, 6)
        store.write_json(path, led)


def usage_view() -> dict:
    ask, run = _ledger(ASK_LEDGER), _ledger(RUN_LEDGER)
    ev = devtools.ledger_by_day() if devtools.ENABLED else {}
    days = [{"date": d, "questions_usd": round(ask.get(d, 0.0), 4), "screening_usd": round(run.get(d, 0.0), 4),
             "evals_usd": round(ev.get(d, 0.0), 4)}
            for d in sorted(set(ask) | set(run) | set(ev), reverse=True)]
    by_company = []
    for t in store.coverage():
        run_meta = (store.get(t, "run.json") or {}).get("meta", {})
        memo_meta = (store.get(t, "memo.json") or {}).get("meta", {})
        pres = store.get(t, "present.json") or {}
        job = store.get(t, "job.json") or {}
        screening = job.get("cost_usd")
        if screening is None:  # imported runs: what the run and memo recorded
            screening = (run_meta.get("cost_usd") or 0) + (memo_meta.get("cost_usd") or 0) + (pres.get("cost_usd") or 0)
        qs = store.read_jsonl(store.path(t, "questions.jsonl"))
        by_company.append({"ticker": t, "name": (store.get(t, "company.json") or {}).get("name", t),
                           "screening_usd": round(screening, 4), "questions": len(qs),
                           "questions_usd": round(sum(q.get("cost_usd", 0) for q in qs), 4)})
    return {"days": days, "total_usd": round(sum(ask.values()) + sum(run.values()) + sum(ev.values()), 4),
            "evals": devtools.spend_view() if devtools.ENABLED else None,
            "caps": {"questions": {"today_usd": round(ask.get(_today(), 0.0), 4), "cap_usd": ASK_MAX_USD_PER_DAY,
                                   "estimate_usd": ASK_ESTIMATE_USD},
                     "screening": {"today_usd": round(run.get(_today(), 0.0), 4), "cap_usd": RUN_MAX_USD_PER_DAY,
                                   "per_run_limit_usd": RUN_LIMIT_USD}},
            "by_company": by_company}


# ---------------------------------------------------------------- company context

def _manifest(t: str) -> list[dict]:
    try:
        return edgar.manifest(t)
    except SystemExit:
        return []


def _financials(t: str, co: dict) -> dict:
    p = config.RAW / t / "companyfacts.json"
    return _cached(("fin", t), p, lambda: financials.table(
        json.loads(p.read_text()), co["fiscal_year_end"], co["cik"])) or {"years": [], "rows": []}


def _company(t: str) -> dict:
    co = store.get(t, "company.json") or {}
    if not co.get("cik"):
        reg = config.companies().get(t, {})
        co = {**reg, **co}
    return {"ticker": t, "name": co.get("name", t), **co}


def _ctx(t: str) -> dict:
    run = store.get(t, "run.json") or {}
    rows = {r["qid"]: r for r in run.get("answers", [])}
    nc = {i["qid"]: i for i in (run.get("meta", {}).get("number_check") or {}).get("items", [])}
    return {"company": _company(t), "run": run, "rows": rows, "sec": nc,
            "present": (store.get(t, "present.json") or {}).get("items", {}),
            "ann": store.get(t, "annotations.json", {}) or {},
            "docs": findings.doc_meta(_manifest(t)), "qs": _qs()}


def _finding_rows(ctx: dict) -> list[dict]:
    return [findings.finding_row(q, ctx["rows"].get(q["id"]), ctx["present"].get(q["id"]), ctx["sec"].get(q["id"]),
                                 ctx["ann"].get(q["id"]), ctx["docs"]) for q in findings.visible(ctx["qs"])]


def _job_view(t: str) -> dict | None:
    job = _running.get(t) or store.get(t, "job.json")
    if not job or job.get("state") == "done":
        return None
    label, frac = STAGES.get(job.get("stage"), ("Working", 0.0))
    if job.get("stage") == "answer" and job.get("total"):
        label = f"Answering, {job.get('done', 0)} of {job['total']}"
        frac = 0.2 + 0.6 * job.get("done", 0) / job["total"]
    return {**{k: job.get(k) for k in ("state", "stage", "done", "total", "error", "started", "cost_usd")},
            "label": label, "fraction": round(frac, 3)}


def _state(t: str) -> str:
    job = _job_view(t)
    if job and job["state"] == "running":
        return "processing"
    if store.get(t, "run.json"):
        return "ready"
    return "failed"


def _latest_filing(manifest: list[dict]) -> dict | None:
    if not manifest:
        return None
    d = max(manifest, key=lambda d: d["filing_date"])
    return {"form": d["form"], "period": d["period"], "date": d["filing_date"], "url": d["url"]}


def coverage_row(t: str) -> dict:
    co = _company(t)
    state = _state(t)
    man = _manifest(t)
    fin = financials.latest(_financials(t, co)) if co.get("cik") else {}
    row = {"ticker": t, "name": co.get("name", t), "state": state, "job": _job_view(t),
           "fy": fin.get("fy"), "fy_end": financials.fye_label(co.get("fiscal_year_end", "")),
           "revenue": fin.get("revenue"), "growth": fin.get("growth"), "gross_margin": fin.get("gross_margin"),
           "op_margin": fin.get("op_margin"), "fcf_margin": fin.get("fcf_margin"),
           "latest_filing": _latest_filing(man), "updated": co.get("updated") or co.get("added"), "findings": None}
    if state == "ready":
        c = findings.counts(_finding_rows(_ctx(t)))
        row["findings"] = {**c, "answered": c["total"] - c["not_disclosed"]}
    return row


def coverage_view() -> dict:
    rows = [coverage_row(t) for t in store.coverage()]
    counts = {"all": len(rows), "ready": sum(r["state"] == "ready" for r in rows),
              "processing": sum(r["state"] == "processing" for r in rows),
              "failed": sum(r["state"] == "failed" for r in rows),
              "review": sum(bool(r["findings"] and r["findings"]["review"]) for r in rows)}
    return {"companies": rows, "counts": counts, "busy": _busy_ticker(), "dev_tools": devtools.ENABLED}


def company_view(t: str) -> dict:
    co = _company(t)
    man = _manifest(t)
    fin = financials.latest(_financials(t, co)) if co.get("cik") else {}
    ctx = _ctx(t)
    figures = []
    if fin.get("revenue") is not None:
        figures.append({"key": "revenue", "label": f"Revenue, {fin['fy']}", "value": fin["revenue"], "kind": "usd",
                        "sub": fin.get("growth"), "sub_kind": "pct_change"})
    for key, label in (("gross_margin", "Gross margin"), ("op_income", "Operating income")):
        if fin.get(key) is not None:
            figures.append({"key": key, "label": label, "value": fin[key], "kind": "pct" if "margin" in key else "usd"})
    if fin.get("fcf") is not None:
        figures.append({"key": "fcf", "label": "Free cash flow", "value": fin["fcf"], "kind": "usd",
                        "sub": fin.get("fcf_margin"), "sub_kind": "pct"})
    if fin.get("cash") is not None:
        figures.append({"key": "cash", "label": "Cash", "value": fin["cash"], "kind": "usd"})
    for qid, label, kind in (("debt_instruments", "Debt principal", "usd"), ("emp_count", "Employees", "count")):
        r = ctx["rows"].get(qid)
        if r and r.get("status") == "answered" and isinstance(r.get("parsed_value"), (int, float)):
            figures.append({"key": qid, "label": label, "value": r["parsed_value"], "kind": kind, "qid": qid})
    rows = _finding_rows(ctx)
    return {"ticker": t, "name": co.get("name", t), "cik": co.get("cik"), "sic": co.get("sic", ""),
            "fy_end": financials.fye_label(co.get("fiscal_year_end", "")), "fy": fin.get("fy"),
            "filings": len(man), "latest_filing": _latest_filing(man),
            "latest_10k": _latest_filing([d for d in man if d["form"] == "10-K"]),
            "updated": co.get("updated") or co.get("added"), "state": _state(t), "job": _job_view(t),
            "figures": figures, "counts": findings.counts(rows),
            "has_memo": bool(store.get(t, "memo.json")),
            "questions": len(store.read_jsonl(store.path(t, "questions.jsonl")))}


def findings_view(t: str) -> dict:
    rows = _finding_rows(_ctx(t))
    return {"groups": findings.group_rows(rows), "counts": findings.counts(rows)}


def _visible_q(qid: str) -> dict:
    q = next((q for q in findings.visible(_qs()) if q["id"] == qid), None)
    if not q:
        raise KeyError(qid)
    return q


def finding_view(t: str, qid: str) -> dict:
    ctx = _ctx(t)
    q = _visible_q(qid)
    return findings.finding_detail(q, ctx["rows"].get(qid), ctx["present"].get(qid), ctx["sec"].get(qid),
                                   ctx["ann"].get(qid), ctx["docs"])


def _source_citations(t: str, source: str) -> list[dict]:
    """The citation list behind a source reference: finding:<qid>, memo:<n> (footnote) or question:<id>."""
    kind, _, ref = source.partition(":")
    if kind == "finding":
        _visible_q(ref)
        return (_ctx(t)["rows"].get(ref) or {}).get("citations", [])
    if kind == "memo":
        m = store.get(t, "memo.json")
        if not m:
            raise KeyError(source)
        ctx = _ctx(t)
        mv = findings.memo_view(m, list(ctx["rows"].values()), {q["id"]: q for q in ctx["qs"]})
        note = next((n for n in mv["notes"] if str(n["n"]) == ref), None)
        if not note:
            raise KeyError(source)
        return ctx["rows"][note["qid"]].get("citations", [])
    if kind == "question":
        q = next((q for q in store.read_jsonl(store.path(t, "questions.jsonl")) if q.get("id") == ref), None)
        if not q:
            raise KeyError(source)
        return q.get("citations", [])
    raise KeyError(source)


def passage_view(t: str, chunk_id: str, source: str) -> dict:
    if not chunk_id.startswith(t + "_"):
        raise KeyError(chunk_id)
    ix = _index(t)
    c = ix.by_id.get(chunk_id)
    cits = _source_citations(t, source)
    quotes = [(i + 1, x["quote"]) for i, x in enumerate(cits) if x.get("chunk_id") == chunk_id]
    if not c:
        # A cited passage that isn't in the current index: its filing was replaced by a newer one (or the passage
        # moved). Say so plainly; the quotes themselves still show in the panel.
        cited = next((x for x in cits if x.get("chunk_id") == chunk_id), None)
        if not cited:
            raise KeyError(chunk_id)
        docs = findings.doc_meta(_manifest(t))
        d = findings.doc_info(cited.get("doc_id"), docs)
        return {"chunk_id": chunk_id, "doc_id": cited.get("doc_id"), "form": d.get("form", ""), "period": d.get("period", ""),
                "filing_date": d.get("filing_date", ""), "heading": "", "subheading": "", "url": cited.get("url", ""),
                "form_label": findings.FORM_LABELS.get(d.get("form", ""), d.get("form", "") or "Filing"),
                "blocks": [], "found": [], "quotes_here": [n for n, _ in quotes], "prev_chunk": None,
                "next_chunk": None, "missing": True, "in_set": d["in_set"]}
    p = findings.passage(c, quotes)
    neighbors = {n["chunk_id"] for n in ix.neighbors(chunk_id)}
    prev_id = next((n for n in neighbors if n < chunk_id), None)
    next_id = next((n for n in neighbors if n > chunk_id), None)
    heading = c["heading"] if c["heading"] not in ("proxy", "press_release") else ""  # whole-document sections
    return {**{k: c[k] for k in ("chunk_id", "doc_id", "form", "period", "filing_date", "subheading", "url")},
            "heading": heading,
            "form_label": findings.FORM_LABELS.get(c["form"], c["form"]), **p,
            "quotes_here": [n for n, _ in quotes], "prev_chunk": prev_id, "next_chunk": next_id, "missing": False}


def memo_api(t: str) -> dict | None:
    m = store.get(t, "memo.json")
    if not m:
        return None
    ctx = _ctx(t)
    return findings.memo_view(m, list(ctx["rows"].values()), {q["id"]: q for q in ctx["qs"]})


def filings_view(t: str) -> list[dict]:
    return sorted([{k: d.get(k) for k in ("doc_id", "form", "period", "report_date", "filing_date", "url")}
                   | {"form_label": findings.FORM_LABELS.get(d["form"], d["form"])} for d in _manifest(t)],
                  key=lambda d: d["filing_date"], reverse=True)


def export_findings_csv(t: str) -> str:
    ctx = _ctx(t)
    details = [findings.finding_detail(q, ctx["rows"].get(q["id"]), ctx["present"].get(q["id"]), ctx["sec"].get(q["id"]),
                                       ctx["ann"].get(q["id"]), ctx["docs"]) for q in findings.visible(ctx["qs"])]
    return findings.findings_csv(t, details)


def export_memo_md(t: str) -> str | None:
    mv = memo_api(t)
    if not mv:
        return None
    return findings.memo_markdown(_company(t)["name"], t, mv, list(_ctx(t)["rows"].values()))


# ---------------------------------------------------------------- annotations

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def set_note(t: str, qid: str, text: str) -> dict:
    _visible_q(qid)
    text = text.strip()[:4000]
    store.annotate(t, qid, note=text or None, note_at=_now() if text else None)
    return finding_view(t, qid)


def set_flag(t: str, qid: str, flagged: bool) -> dict:
    _visible_q(qid)
    store.annotate(t, qid, flagged=True if flagged else None, flagged_at=_now() if flagged else None)
    return finding_view(t, qid)


def set_reviewed(t: str, qid: str, reviewed: bool) -> dict:
    _visible_q(qid)
    store.annotate(t, qid, reviewed_at=_now() if reviewed else None)
    return finding_view(t, qid)


# ---------------------------------------------------------------- questions (paid)

def questions_view(t: str) -> dict:
    qs = store.read_jsonl(store.path(t, "questions.jsonl"))
    docs = findings.doc_meta(_manifest(t))
    out = [{**q, "citations": [findings.citation_view(i, c, docs) for i, c in enumerate(q.get("citations", []))]}
           for q in qs]
    led = _ledger(ASK_LEDGER)
    return {"questions": out, "spend": {"today_usd": round(led.get(_today(), 0.0), 4), "cap_usd": ASK_MAX_USD_PER_DAY,
                                        "estimate_usd": ASK_ESTIMATE_USD}}


def ask(t: str, question: str, max_usd: float) -> dict:
    if _state(t) != "ready":
        raise RuntimeError("Questions open once this company's screening has finished.")
    if max_usd + 1e-9 < ASK_ESTIMATE_USD:
        raise ValueError(f"Confirm the estimated cost (${ASK_ESTIMATE_USD:.2f}) to ask.")
    with _lock:
        spent = _ledger(ASK_LEDGER).get(_today(), 0.0)
        if spent + ASK_ESTIMATE_USD > ASK_MAX_USD_PER_DAY:
            raise PermissionError(f"Today's question budget is used (${spent:.2f} of ${ASK_MAX_USD_PER_DAY:.2f}). "
                                  "Raise UI_MAX_USD_PER_DAY in .env to ask more today.")
    q = {"id": "adhoc", "category": "Ad hoc", "question": question[:500], "answer_type": "text",
         "period": "current", "where": {}}
    meter = llm.CostMeter(limit=ASK_LIMIT_USD)
    try:
        r = answer.answer_question(t, q, _index(t), meter)
    finally:
        _charge(ASK_LEDGER, meter.cost())
    rec = {"id": uuid.uuid4().hex[:10], "asked_at": _now(), "question": q["question"],
           **{k: r[k] for k in ("status", "answer", "value", "unit", "period", "confidence", "error")},
           "citations": [{k: c.get(k) for k in ("chunk_id", "quote", "verified", "url", "doc_id", "section")}
                         for c in r["citations"]],
           "cost_usd": round(meter.cost(), 4), "model": r["model"]}
    store.append_jsonl(store.path(t, "questions.jsonl"), rec)
    return questions_view(t)


# ---------------------------------------------------------------- screening jobs (paid)

def _busy_ticker() -> str | None:
    return next((t for t, j in _running.items() if j.get("state") == "running"), None)


def _screening_busy_message() -> str | None:
    t = _busy_ticker()
    return f"{t} is being screened. One paid job at a time: try again when it finishes." if t else None


devtools.other_busy = _screening_busy_message


def estimate(t: str | None) -> dict:
    """Cost of what's left to do for this company (a fresh screening if nothing is stored)."""
    total = len(_qs())
    done, need_present, need_memo = 0, True, True
    if t and store.in_coverage(t):
        if store.get(t, "run.json"):
            done = total
        else:
            done = len(pipeline.load_partial(store.path(t, "answers.partial.jsonl")))
        need_present = not store.get(t, "present.json")
        need_memo = not store.get(t, "memo.json")
    usd = PER_ANSWER_USD * (total - done) + (PRESENT_USD if need_present else 0) + (MEMO_USD if need_memo else 0)
    return {"usd": round(usd, 2), "minutes": "a few minutes", "answers_done": done, "answers_total": total}


def preview_view(t: str) -> dict:
    p = pipeline.preview(t)
    led = _ledger(RUN_LEDGER).get(_today(), 0.0)
    ins = store.in_coverage(p["ticker"])
    return {**{k: p[k] for k in ("ticker", "name", "cik", "sic", "filings", "eligible", "reason")},
            "fy_end": financials.fye_label(p.get("fiscal_year_end", "")), "in_coverage": ins,
            "state": _state(p["ticker"]) if ins else None,
            "estimate": estimate(p["ticker"] if ins else None),
            "cap": {"today_usd": round(led, 4), "cap_usd": RUN_MAX_USD_PER_DAY,
                    "remaining_usd": round(max(0.0, RUN_MAX_USD_PER_DAY - led), 4)},
            "busy": _busy_ticker() or ("an evaluation run" if devtools.running() else None)}


def search_view(q: str) -> list[dict]:
    cov = set(store.coverage())
    return [{**r, "in_coverage": r["ticker"] in cov} for r in pipeline.search(q)]


def _check_can_start(t: str, confirm_usd: float) -> dict:
    est = estimate(t if store.in_coverage(t) else None)
    if confirm_usd + 1e-9 < est["usd"]:
        raise ValueError(f"Confirm the estimated cost (${est['usd']:.2f}) to start.")
    spent = _ledger(RUN_LEDGER).get(_today(), 0.0)
    if spent + est["usd"] > RUN_MAX_USD_PER_DAY:
        raise PermissionError(f"Today's screening budget is used (${spent:.2f} of ${RUN_MAX_USD_PER_DAY:.2f}). "
                              "Raise RUN_MAX_USD_PER_DAY in .env to screen more today.")
    busy = _busy_ticker()
    if busy:
        raise Busy(f"{busy} is being screened. One company at a time; try again when it finishes.")
    if devtools.running():
        raise Busy(devtools.busy_message())
    return est


def start(t: str, confirm_usd: float) -> dict:
    t = t.upper()
    if not store.valid_ticker(t):
        raise KeyError(t)
    with _job_lock:
        if store.in_coverage(t):
            raise RuntimeError(f"{t} is already in coverage.")
        _check_can_start(t, confirm_usd)
        p = pipeline.preview(t)  # free; EDGAR metadata only
        if not p["eligible"]:
            raise RuntimeError(p["reason"])
        store.add(t)
        store.put(t, "company.json", {"ticker": t, "name": p["name"], "cik": p["cik"],
                                      "fiscal_year_end": p["fiscal_year_end"], "sic": p["sic"], "added": _today()})
        return _launch(t)


def retry(t: str, confirm_usd: float) -> dict:
    with _job_lock:
        if _state(t) == "ready" and store.get(t, "present.json") and store.get(t, "memo.json"):
            raise RuntimeError(f"{t} is already screened.")
        _check_can_start(t, confirm_usd)
        return _launch(t)


def _launch(t: str) -> dict:
    prev = store.get(t, "job.json") or {}
    job = {"state": "running", "stage": "queued", "done": 0, "total": len(_qs()), "error": None,
           "started": _now(), "cost_usd": round(prev.get("cost_usd") or 0.0, 4)}
    _running[t] = job
    store.put(t, "job.json", job)
    threading.Thread(target=_run_job, args=(t,), daemon=True).start()
    return coverage_row(t)


def _run_job(t: str) -> None:
    job = _running[t]
    meter = llm.CostMeter(limit=RUN_LIMIT_USD)
    base_cost = job["cost_usd"]
    last_write = [0.0]

    def save(force=True):
        job["cost_usd"] = round(base_cost + meter.cost(), 4)
        if force or time.time() - last_write[0] > 1.0:
            last_write[0] = time.time()
            store.put(t, "job.json", job)

    def stage(s):
        job["stage"] = s
        save()

    work = store.path(t, ".work")
    try:
        stage("register")
        entry = pipeline.register(t)
        co = store.get(t, "company.json") or {}
        store.put(t, "company.json", {**co, "name": entry["name"], "cik": entry["cik"],
                                      "fiscal_year_end": entry["fiscal_year_end"]})
        store.seed_raw(t)  # filings the CLI cache already holds are copied, not downloaded again
        pipeline.build(t, stage=stage)
        with _lock:
            _indexes.pop(t, None)
        qs = _qs()
        run_path = store.path(t, "run.json")
        if not store.get(t, "run.json"):
            stage("answer")
            work.mkdir(parents=True, exist_ok=True)

            def progress(d, n):
                job.update(done=d, total=n)
                save(force=False)
            out = pipeline.run_checklist(t, meter, progress=progress, out_dir=work,
                                         partial=store.path(t, "answers.partial.jsonl"))
            with store.lock:
                os.replace(out, run_path)
            store.path(t, "answers.partial.jsonl").unlink(missing_ok=True)
        rows = store.get(t, "run.json")["answers"]
        if not store.get(t, "present.json"):
            stage("present")
            before = meter.cost()
            pres = present.present_all(qs, rows, meter)
            store.put(t, "present.json", {**pres, "cost_usd": round(meter.cost() - before, 4), "at": _now()})
        if not store.get(t, "memo.json"):
            stage("memo")
            work.mkdir(parents=True, exist_ok=True)
            res = memo.run(t, run_path, memo.DEFAULT_MODEL, memo.DEFAULT_EFFORT, do_check=True, log=False,
                           meter=meter, out_dir=work)
            store.put(t, "memo.json", {"meta": res["meta"], "memo": res["memo"], "check": res["check"]})
        store.put(t, "company.json", {**(store.get(t, "company.json") or {}), "updated": _today()})
        job["state"] = "done"
        stage("done")
    except BaseException as e:  # SystemExit from a limit, parser and network errors: report, don't crash
        job["state"] = "failed"
        job["error"] = str(e) or e.__class__.__name__
    finally:
        _charge(RUN_LEDGER, meter.cost())
        shutil.rmtree(work, ignore_errors=True)
        try:
            save()
        except KeyError:  # removed while running
            pass
        _running.pop(t, None)


def remove(t: str) -> dict:
    with _job_lock:
        if _busy_ticker() == t:
            raise Busy(f"{t} is being screened; wait for it to finish before removing it.")
        store.remove(t)
        with _lock:
            _indexes.pop(t, None)
    return coverage_view()


def recover_interrupted() -> None:
    """A job left 'running' by a previous server process was interrupted; mark it so it can be resumed."""
    for t in store.coverage():
        job = store.get(t, "job.json")
        if job and job.get("state") == "running":
            store.put(t, "job.json", {**job, "state": "failed",
                                      "error": "Interrupted: the app was closed while this company was processing."})


# ---------------------------------------------------------------- HTTP

_ROUTE_T = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")


class Handler(BaseHTTPRequestHandler):
    server_version = "filing-room"

    def log_message(self, fmt, *args):  # quiet: only log errors
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _error(self, status: int, msg: str) -> None:
        self._json({"error": msg}, status)

    def _download(self, text: str, name: str, ctype: str) -> None:
        self._send(200, text.encode(), ctype, {"Content-Disposition": f'attachment; filename="{name}"'})

    def _company(self, seg: str) -> str:
        """A ticker path segment that is in coverage, or KeyError."""
        t = seg.upper()
        if not _ROUTE_T.fullmatch(seg) or not store.in_coverage(t):
            raise KeyError(seg)
        return t

    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "forbidden host")
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
        qs = parse_qs(url.query)
        arg = lambda k, d="": qs.get(k, [d])[0]  # noqa: E731
        try:
            if not parts or parts[0] != "api":
                return self._static(url.path)
            r = parts[1:]
            if r == ["coverage"]:
                return self._json(coverage_view())
            if r == ["usage"]:
                return self._json(usage_view())
            if r[:1] == ["dev"]:
                return self._dev_get(r[1:], arg)
            if r == ["sec", "search"]:
                return self._json(search_view(arg("q")))
            if len(r) == 3 and r[:2] == ["sec", "preview"]:
                if not _ROUTE_T.fullmatch(r[2]):
                    raise KeyError(r[2])
                return self._json(preview_view(r[2].upper()))
            if len(r) >= 2 and r[0] == "companies":
                t = self._company(r[1])
                rest = r[2:]
                if rest == []:
                    return self._json(company_view(t))
                if rest == ["financials"]:
                    return self._json(_financials(t, _company(t)))
                if rest == ["findings"]:
                    return self._json(findings_view(t))
                if len(rest) == 2 and rest[0] == "findings":
                    return self._json(finding_view(t, rest[1]))
                if rest == ["passage"]:
                    return self._json(passage_view(t, arg("chunk"), arg("source")))
                if rest == ["memo"]:
                    m = memo_api(t)
                    return self._json(m) if m else self._error(404, "No screening memo for this company yet.")
                if rest == ["questions"]:
                    return self._json(questions_view(t))
                if rest == ["filings"]:
                    return self._json(filings_view(t))
                if rest == ["export", "findings.csv"]:
                    return self._download(export_findings_csv(t), f"{t}-findings.csv", "text/csv; charset=utf-8")
                if rest == ["export", "memo.md"]:
                    md = export_memo_md(t)
                    return self._download(md, f"{t}-screening-memo.md", "text/markdown; charset=utf-8") if md \
                        else self._error(404, "No screening memo for this company yet.")
            return self._error(404, "not found")
        except KeyError:
            return self._error(404, "not found")
        except SystemExit as e:  # e.g. an index that hasn't been built
            return self._error(409, str(e))

    def _dev_get(self, r: list[str], arg):
        """Developer tools (evaluation area). One switch: when off, everything under /api/dev/ is a 404."""
        if not devtools.ENABLED or r[:1] != ["evals"]:
            return self._error(404, "not found")
        r = r[1:]
        if r == []:
            return self._json(devtools.overview())
        if r == ["config"]:
            return self._json(devtools.config_view())
        if r == ["golden"]:
            return self._json(devtools.golden_view())
        if r == ["job"]:
            return self._json({"job": devtools.job_view(), "spend": devtools.spend_view()})
        if len(r) == 3 and r[0] == "runs":
            return self._json(devtools.detail(r[1], r[2]))
        if len(r) == 5 and r[0] == "runs" and r[3] == "items":
            return self._json(devtools.item(r[1], r[2], r[4]))
        if len(r) == 4 and r[0] == "runs" and r[3] == "passage":
            return self._json(devtools.passage(r[1], r[2], arg("item"), arg("chunk")))
        return self._error(404, "not found")

    def _dev_post(self, r: list[str], body: dict):
        if not devtools.ENABLED or r[:1] != ["evals"]:
            return self._error(404, "not found")
        r = r[1:]
        spec = body.get("spec") if isinstance(body.get("spec"), dict) else {}
        if r == ["estimate"]:
            return self._json(devtools.estimate(spec))
        if r == ["start"]:
            if _busy_ticker():
                raise Busy(_screening_busy_message())
            return self._json(devtools.start(spec, float(body.get("confirm_usd") or 0)))
        if r == ["retrieval"]:
            tickers = body.get("tickers") if isinstance(body.get("tickers"), list) else []
            return self._json(devtools.retrieval([str(t) for t in tickers]))
        return self._error(404, "not found")

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
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._error(400, "bad json")
        r = [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p][1:]
        num = lambda k: float(body.get(k) or 0)  # noqa: E731
        try:
            if r[:1] == ["dev"]:
                return self._dev_post(r[1:], body)
            if r == ["companies"]:
                return self._json(start(str(body.get("ticker", "")), num("confirm_usd")))
            if len(r) >= 3 and r[0] == "companies":
                t = self._company(r[1])
                rest = r[2:]
                if rest == ["retry"]:
                    return self._json(retry(t, num("confirm_usd")))
                if rest == ["remove"]:
                    return self._json(remove(t))
                if rest == ["questions"]:
                    question = str(body.get("question", "")).strip()
                    if not question:
                        return self._error(400, "Type a question first.")
                    return self._json(ask(t, question, num("max_usd")))
                if len(rest) == 3 and rest[0] == "findings":
                    qid, action = rest[1], rest[2]
                    if action == "note":
                        return self._json(set_note(t, qid, str(body.get("text", ""))))
                    if action == "flag":
                        return self._json(set_flag(t, qid, bool(body.get("flagged"))))
                    if action == "review":
                        return self._json(set_reviewed(t, qid, bool(body.get("reviewed"))))
            return self._error(404, "not found")
        except PermissionError as e:
            return self._error(402, str(e))
        except Busy as e:
            return self._error(409, str(e))
        except (RuntimeError, ValueError) as e:
            return self._error(409, str(e))
        except KeyError:
            return self._error(404, "not found")
        except SystemExit as e:
            return self._error(409, str(e))

    def _static(self, path: str) -> None:
        dist = WEB_DIST.resolve()
        index = dist / "index.html"
        if not index.exists():
            return self._send(503, b"The app isn't built. Run: npm --prefix web install && npm --prefix web run build",
                              "text/plain; charset=utf-8")
        rel = path.lstrip("/")
        target = (dist / rel).resolve() if rel else index
        if dist not in target.parents or not target.is_file():
            target = index  # single-page app: unknown paths get the shell
        self._send(HTTPStatus.OK, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))


def serve(port: int = 8787, open_browser: bool = True) -> None:
    llm.MAX_USD_PER_COMMAND = float("inf")  # long-lived process: per-job limits and daily ledgers apply instead
    if not (WEB_DIST / "index.html").exists():
        print("The web app isn't built yet. Build it with:\n  npm --prefix web install && npm --prefix web run build")
    store.use_filing_cache()  # the app's own filings; the CLI's data/raw|parsed|index stay as the evals left them
    recover_interrupted()
    if devtools.ENABLED:
        devtools.job_view()  # settle an eval run that finished (or stopped) while the server was down
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        raise SystemExit(f"Port {port} is already in use (maybe the app is already running?). Try ./fr ui --port {port + 1}")
    url = f"http://127.0.0.1:{port}/"
    print(f"filing-room on {url}  (local only; Ctrl-C to stop)")
    print(f"app data: {store.root()} (filings cached in {store.filings_root()})")
    print(f"paid actions: questions ${ASK_MAX_USD_PER_DAY:.2f}/day (UI_MAX_USD_PER_DAY), "
          f"screenings ${RUN_MAX_USD_PER_DAY:.2f}/day (RUN_MAX_USD_PER_DAY)"
          + (f", evals ${devtools.EVAL_MAX_USD_PER_DAY:.2f}/day (EVAL_MAX_USD_PER_DAY)" if devtools.ENABLED
             else "; developer tools off (FILINGROOM_DEV_TOOLS)"))
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
