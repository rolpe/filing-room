"""Adding a company beyond the three case studies, and running its checklist end to end.

Used by the CLI (`./fr add`, `./fr run`) and the local UI's "Add a company" flow. Companies added this way
get split "user": they never enter evals or the golden set (they have no hand-built answer key), but their
numeric answers are checked automatically against the SEC's structured XBRL data.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import answer, checklist, config, edgar, golden, index, llm, parse, report

NEEDED = {"10-K": 2, "10-Q": 1, "DEF 14A": 1, "8-K": 1}  # what the checklist's periods and questions rely on
RUN_ESTIMATE_USD = 1.20  # 40 answers (~$1.00) + memo and claim check (~$0.15-0.20)


# ---------------------------------------------------------------- SEC company search

def _sec_tickers() -> list[dict]:
    path = config.DATA / "sec_tickers.json"
    if not path.exists() or time.time() - path.stat().st_mtime > 86400:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(edgar._get("https://www.sec.gov/files/company_tickers.json"))
    return list(json.loads(path.read_text()).values())


def search(q: str, limit: int = 12) -> list[dict]:
    q = q.strip().lower()
    if not q:
        return []
    rows = _sec_tickers()
    def rank(r):
        t, name = r["ticker"].lower(), r["title"].lower()
        if t == q:
            return 0
        if name.startswith(q):
            return 1
        if t.startswith(q):
            return 2
        if any(w.startswith(q) for w in name.split()):
            return 3
        return 4 if q in name else None
    scored = [(rk, i, r) for i, r in enumerate(rows) if (rk := rank(r)) is not None]  # i keeps SEC's size order
    scored.sort(key=lambda x: (x[0], x[1]))
    return [{"ticker": r["ticker"], "name": nice_name(r["title"]), "cik": r["cik_str"]} for _, _, r in scored[:limit]]


def _lookup(ticker: str) -> dict:
    t = ticker.upper()
    for r in _sec_tickers():
        if r["ticker"].upper() == t:
            return {"ticker": t, "name": nice_name(r["title"]), "cik": r["cik_str"]}
    raise KeyError(f"No SEC-registered company with ticker {t}")


KEEP_CAPS = {"LLC", "LP", "LLP", "NV", "N.V.", "SA", "S.A.", "AG", "PLC", "USA", "US", "II", "III", "IV", "REIT", "AI", "ADR"}


def nice_name(name: str) -> str:
    """SEC names are often all capitals ("WORKIVA INC"); present them as "Workiva Inc"."""
    if not name or not name.isupper():
        return name
    return " ".join(w if w in KEEP_CAPS or any(ch.isdigit() for ch in w) else w.capitalize() for w in name.split())


def preview(ticker: str) -> dict:
    """Who the company is and whether its filings can support the checklist. Free: EDGAR metadata only."""
    base = _lookup(ticker)
    sub = edgar.submissions({"ticker": base["ticker"], "cik": base["cik"]}, refresh=True)
    r = sub["filings"]["recent"]
    have = {"10-K": 0, "10-Q": 0, "DEF 14A": 0, "8-K": 0}
    for form, items in zip(r["form"], r["items"]):
        if form == "8-K" and "2.02" not in items.split(","):
            continue
        if form in have:
            have[form] += 1
    missing = [f"{n - min(have[f], n)} more {f}" for f, n in NEEDED.items() if have[f] < n]
    foreign = any(f in ("20-F", "40-F", "6-K") for f in r["form"])
    reason = ""
    if foreign and not have["10-K"]:
        reason = "This company files as a foreign issuer (20-F or 40-F), not with 10-Ks, so the checklist can't run on it."
    elif missing:
        reason = "Its recent EDGAR filings are missing what the checklist needs: " + ", ".join(missing) + "."
    known = config.companies().get(base["ticker"])
    return {
        **base, "name": nice_name(sub.get("name") or base["name"]),
        "sic": sub.get("sicDescription") or "", "fiscal_year_end": sub.get("fiscalYearEnd") or "",
        "filings": have, "eligible": not reason, "reason": reason,
        "added": bool(known), "split": known["split"] if known else None,
    }


def register(ticker: str) -> dict:
    """Add a company to data/companies_user.json (idempotent). The three case studies can't be re-added."""
    p = preview(ticker)
    if not p["eligible"]:
        raise ValueError(p["reason"])
    existing = config.companies().get(p["ticker"])
    if existing:
        return existing
    entry = {"ticker": p["ticker"], "name": p["name"], "cik": p["cik"], "fiscal_year_end": p["fiscal_year_end"],
             "split": "user", "why": f"Added from search{' · ' + p['sic'] if p['sic'] else ''}.",
             "added": datetime.now().strftime("%Y-%m-%d")}
    config.add_user_company(entry)
    return entry


# ---------------------------------------------------------------- checklist run + number check

def number_check(ticker: str, rows: list[dict]) -> dict:
    """Compare numeric answers with the SEC's XBRL figures (the same source as the golden set's numbers)."""
    from .evaluate import grade_numeric  # local import: evaluate imports answer/golden too
    by_qid = {r["qid"]: r for r in rows}
    items = []
    for it in golden.numeric_items(ticker):
        ans = by_qid.get(it["qid"])
        if not ans:
            continue
        items.append({"qid": it["qid"], "expected": it["expected"], "source": it["source"],
                      "got": ans["parsed_value"], "status": ans["status"], "match": grade_numeric(it, ans)})
    return {"checked": len(items), "matched": sum(i["match"] for i in items), "items": items}


def run_checklist(ticker: str, meter: llm.CostMeter, *, model: str = answer.DEFAULT_MODEL,
                  effort: str | None = answer.DEFAULT_EFFORT, k: int = answer.DEFAULT_K,
                  expand: int = answer.DEFAULT_EXPAND, workers: int = 6, progress=None):
    """Answer all 40 questions, add the number check, write runs/<TICKER>_<stamp>.json/.md. Returns the json path."""
    ix = index.Index(ticker)
    qs = checklist.load()
    done = 0

    def one(q):
        nonlocal done
        r = answer.answer_question(ticker, q, ix, meter, model=model, effort=effort, k=k, expand=expand)
        done += 1
        if progress:
            progress(done, len(qs))
        return r

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, qs))
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    meta = {"timestamp": stamp, "model": model, "cost_usd": meter.cost(), "n_filings": len(edgar.manifest(ticker)),
            "usage": meter.summary(), "number_check": number_check(ticker, rows)}
    config.RUNS.mkdir(exist_ok=True)
    path = config.RUNS / f"{ticker}_{stamp}.json"
    path.write_text(json.dumps({"meta": meta, "answers": rows}, indent=1))
    (config.RUNS / f"{ticker}_{stamp}.md").write_text(report.checklist_md(ticker, rows, meta))
    return path


def build(ticker: str, stage=None) -> None:
    """Fetch + parse + index (free)."""
    if stage:
        stage("fetch")
    edgar.fetch_company(ticker)
    if stage:
        stage("parse")
    parse.parse_company(ticker)
    if stage:
        stage("index")
    index.build_index(ticker)
