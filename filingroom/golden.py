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


def build(tickers: list[str]) -> list[dict]:
    qs = checklist.load()
    items = []
    for t in tickers:
        facts = edgar.company_facts(config.company(t))
        P = checklist.periods(t)
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
                                         "source": {"method": "derived", "op": d["op"],
                                                    "from": [d["of"], d["base"]]}}
        for qid, r in resolved.items():
            q = next(x for x in qs if x["id"] == qid)
            items.append({"id": f"{t}:{qid}", "ticker": t, "qid": qid, "answer_type": q["answer_type"],
                          "grade": "numeric", "expected": {k: r[k] for k in ("value", "unit", "period")},
                          "tolerance": TOLERANCE[q["answer_type"]], "source": r["source"],
                          "verified": "xbrl-auto"})
    if MANUAL.exists():
        for line in MANUAL.read_text().splitlines():
            if line.strip() and not line.startswith("//"):
                item = json.loads(line)
                if item["ticker"] in tickers:
                    items.append(item)
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
