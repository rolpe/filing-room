"""Build the golden set: numeric answers from XBRL company facts, plus hand-verified items.

golden/manual.jsonl  - hand-written items (text answers, not_found items, any numeric XBRL can't give)
golden/golden.jsonl  - generated: XBRL-derived items + manual items. Rebuild with `./fr golden`.
"""

import json
from datetime import date

from . import checklist, config, edgar

MANUAL = config.ROOT / "golden" / "manual.jsonl"
TOLERANCE = {"currency": {"rel": 0.005}, "count": {"rel": 0.005}, "percent": {"abs": 0.6}}


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def xbrl_fact(facts: dict, concept: str, kind: str, end: str) -> dict | None:
    """The fact for `concept` ending on `end`, from the most recently filed 10-K that reports it."""
    rows = facts["facts"].get("us-gaap", {}).get(concept, {}).get("units", {}).get("USD", [])
    rows = [r for r in rows if r["end"] == end and r.get("form", "").startswith("10-K")]
    if kind == "duration":
        rows = [r for r in rows if "start" in r and 350 <= _days(r["start"], end) <= 380]
    else:
        rows = [r for r in rows if "start" not in r]
    return max(rows, key=lambda r: r["filed"]) if rows else None


def _resolve(q: dict, facts: dict, P: dict) -> dict | None:
    x = q["xbrl"]
    end = P["prior_fy_end"] if q["period"] == "prior_fy" else P["latest_fy_end"]
    found = [(c, f) for c in x["concepts"] if (f := xbrl_fact(facts, c, x["kind"], end))]
    if not found:
        return None
    if x.get("combine") == "sum":
        value = sum(f["val"] for _, f in found)
        concepts = [c for c, _ in found]
    else:
        concepts, value = [found[0][0]], found[0][1]["val"]
    period = P["prior_fy"] if q["period"] == "prior_fy" else P["latest_fy"]
    return {"value": value, "unit": "USD", "period": period,
            "source": {"method": "xbrl", "concepts": concepts, "end": end, "accn": found[0][1]["accn"]}}


def numeric_items(ticker: str) -> list[dict]:
    """XBRL-derived numeric answers (plus derived growth/margin) for one company."""
    qs = checklist.load()
    facts = edgar.company_facts(config.company(ticker))
    P = checklist.periods(ticker)
    resolved: dict[str, dict] = {}
    for q in qs:
        if "xbrl" in q and (r := _resolve(q, facts, P)):
            resolved[q["id"]] = r
    for q in qs:
        if "derive" in q:
            d = q["derive"]
            a, b = resolved.get(d["of"]), resolved.get(d["base"])
            if a and b and b["value"]:
                v = (a["value"] / b["value"] - 1) * 100 if d["op"] == "growth" else a["value"] / b["value"] * 100
                resolved[q["id"]] = {"value": round(v, 2), "unit": "percent", "period": P["latest_fy"],
                                     "source": {"method": "derived", "op": d["op"], "from": [d["of"], d["base"]]}}
    items = []
    for qid, r in resolved.items():
        q = next(x for x in qs if x["id"] == qid)
        items.append({"id": f"{ticker}:{qid}", "ticker": ticker, "qid": qid, "answer_type": q["answer_type"],
                      "grade": "numeric", "expected": {k: r[k] for k in ("value", "unit", "period")},
                      "tolerance": TOLERANCE[q["answer_type"]], "source": r["source"], "verified": "xbrl-auto"})
    return items


def build(tickers: list[str]) -> list[dict]:
    items = [i for t in tickers for i in numeric_items(t)]
    if MANUAL.exists():
        for line in MANUAL.read_text().splitlines():
            if line.strip() and not line.startswith("//"):
                item = json.loads(line)
                if item["ticker"] in tickers:
                    items.append(item)
    overrides = {i["id"] for i in items if i.get("override_xbrl")}
    items = [i for i in items if not (i["id"] in overrides and i.get("verified") == "xbrl-auto")]
    ids = [i["id"] for i in items]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"Duplicate golden ids (manual overrides an XBRL item?): {sorted(dupes)}")
    config.GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    config.GOLDEN.write_text("".join(json.dumps(i) + "\n" for i in items))
    return items


def load(tickers: list[str] | None = None) -> list[dict]:
    items = [json.loads(line) for line in config.GOLDEN.read_text().splitlines() if line.strip()]
    return [i for i in items if tickers is None or i["ticker"] in tickers]


def review_sheet() -> str:
    """golden/REVIEW.md: every hand-drafted item as a checklist a human can verify against the quote."""
    qs = checklist.by_id()
    items = [json.loads(l) for l in MANUAL.read_text().splitlines() if l.strip() and not l.startswith("//")]
    lines = ["# Golden set review", "",
             "Hand-drafted golden answers. For each: read the quote, confirm it says what the expected answer "
             "claims for the right period, then change `\"verified\": \"claude-draft\"` to `\"human\"` for that id "
             "in `golden/manual.jsonl`. Regenerate this sheet with `./fr golden --final`.", ""]
    for t in sorted({i["ticker"] for i in items}):
        todo = [i for i in items if i["ticker"] == t]
        done = sum(i.get("verified") == "human" for i in todo)
        lines += [f"## {t} ({done}/{len(todo)} verified)", ""]
        for i in todo:
            exp = i["expected"]
            answer = ("NOT IN FILINGS: " + exp.get("text", "")) if exp.get("not_found") else (
                exp.get("text") or f"{exp.get('value'):,} {exp.get('unit', '')} ({exp.get('period', '')})")
            src = i.get("source", {})
            quotes = ([(src["doc_id"], src["quote"])] if src.get("quote") else []) + \
                     [(q["doc_id"], q["quote"]) for q in src.get("quotes", [])]
            box = "x" if i.get("verified") == "human" else " "
            lines += [f"- [{box}] **{i['id']}** ({i['grade']}): {qs[i['qid']]['question']}",
                      f"  - Expected: {answer}"]
            lines += [f"  - Quote ({d}): “{q}”" for d, q in quotes[:3]] or [f"  - Method: {src.get('method', '')}"]
            if i.get("note"):
                lines.append(f"  - Note: {i['note']}")
            lines.append("")
    return "\n".join(lines)
