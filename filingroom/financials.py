"""Multi-year financials from the SEC's XBRL company facts (free; cached by edgar.company_facts).

Concepts come from the checklist's `xbrl` mappings (the same ones the number check uses). Each fiscal year's
figure is the value as reported in that year's own 10-K (the earliest-filed annual fact for that period end), and
each year links to that 10-K on sec.gov. A row is left out when the company doesn't report the concept.
"""

from datetime import date, timedelta

from . import checklist, edgar

DURATION_DAYS = (350, 380)   # annual periods, including 52/53-week years
END_SLACK_DAYS = 10          # 52/53-week years can end a few days either side of the nominal year-end

ROWS = [  # key, label, kind, source
    ("revenue", "Revenue", "usd", "rev_total"),
    ("growth", "Revenue growth", "pct", None),
    ("gross_profit", "Gross profit", "usd", "gm_gross_profit"),
    ("gross_margin", "Gross margin", "pct", None),
    ("op_income", "Operating income", "usd", "op_income"),
    ("op_margin", "Operating margin", "pct", None),
    ("net_income", "Net income", "usd", "net_income"),
    ("ocf", "Operating cash flow", "usd", "cf_ocf"),
    ("capex", "Capital expenditures", "usd", "cf_capex"),
    ("fcf", "Free cash flow", "usd", None),
    ("fcf_margin", "Free cash flow margin", "pct", None),
    ("cash", "Cash and equivalents", "usd", "bs_cash"),
]


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _nominal_end(end: date, fye: str) -> date | None:
    """The nominal fiscal year-end (from the company's MMDD) this period end belongs to, if within the slack."""
    m, d = int(fye[:2]), int(fye[2:])
    for y in (end.year - 1, end.year, end.year + 1):
        try:
            nominal = date(y, m, d)
        except ValueError:  # Feb 29
            nominal = date(y, m, 28)
        if abs((end - nominal).days) <= END_SLACK_DAYS:
            return nominal
    return None


def _usd_rows(facts: dict, concept: str) -> list[dict]:
    return facts.get("facts", {}).get("us-gaap", {}).get(concept, {}).get("units", {}).get("USD", [])


def _annual(r: dict) -> bool:
    return "start" in r and DURATION_DAYS[0] <= (_d(r["end"]) - _d(r["start"])).days <= DURATION_DAYS[1]


def fiscal_year_ends(facts: dict, fye: str, concepts: list[str]) -> list[str]:
    """Period-end dates of annual periods reported in 10-Ks, newest first."""
    ends = set()
    for c in concepts:
        for r in _usd_rows(facts, c):
            if r.get("form", "").startswith("10-K") and _annual(r) and _nominal_end(_d(r["end"]), fye):
                ends.add(r["end"])
    return sorted(ends, reverse=True)


def as_reported(facts: dict, concept: str, kind: str, end: str) -> dict | None:
    """The fact for `concept` ending on `end` from the earliest 10-K that reports it (that year's own 10-K)."""
    rows = [r for r in _usd_rows(facts, concept) if r["end"] == end and r.get("form", "").startswith("10-K")]
    rows = [r for r in rows if _annual(r)] if kind == "duration" else [r for r in rows if "start" not in r]
    return min(rows, key=lambda r: (r["filed"], r.get("accn", ""))) if rows else None


def _value(facts: dict, x: dict, end: str) -> tuple[float | None, dict | None]:
    found = [f for c in x["concepts"] if (f := as_reported(facts, c, x["kind"], end))]
    if not found:
        return None, None
    if x.get("combine") == "sum":
        return float(sum(f["val"] for f in found)), found[0]
    return float(found[0]["val"]), found[0]


def _pct(a, b):
    return round(a / b * 100, 2) if a is not None and b else None


def filing_index_url(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{accn}-index.htm"


def table(facts: dict, fye: str, cik: int, qs: list[dict] | None = None, years: int = 5) -> dict:
    """{years: [{fy, end, url}], rows: [{key, label, kind, values}]}, newest year first."""
    qs = {q["id"]: q for q in (qs or checklist.load())}
    rev_x = qs["rev_total"]["xbrl"]
    ends = fiscal_year_ends(facts, fye, rev_x["concepts"])[: years + 1]  # one extra for the oldest year's growth
    if not ends:
        return {"years": [], "rows": []}
    raw: dict[str, list] = {}
    cols = []
    for end in ends:
        accn = None
        for key, _, _, src in ROWS:
            if src:
                v, fact = _value(facts, qs[src]["xbrl"], end)
                raw.setdefault(key, []).append(v)
                if key == "revenue" and fact:
                    accn = fact.get("accn")
        nominal = _nominal_end(_d(end), fye)
        cols.append({"fy": f"FY{edgar.fiscal_year_of(nominal, fye)}", "end": end,
                     "url": filing_index_url(cik, accn) if accn else None})
    n = len(ends)
    rev, gp, op, ocf, capex = raw["revenue"], raw["gross_profit"], raw["op_income"], raw["ocf"], raw["capex"]
    fcf = [o - c if o is not None and c is not None else None for o, c in zip(ocf, capex)]
    raw["fcf"] = fcf
    raw["growth"] = [round((rev[i] / rev[i + 1] - 1) * 100, 2) if i + 1 < n and rev[i] is not None and rev[i + 1]
                     else None for i in range(n)]
    raw["gross_margin"] = [_pct(g, r) for g, r in zip(gp, rev)]
    raw["op_margin"] = [_pct(o, r) for o, r in zip(op, rev)]
    raw["fcf_margin"] = [_pct(f, r) for f, r in zip(fcf, rev)]
    shown = min(years, n)
    rows = []
    for key, label, kind, _ in ROWS:
        values = raw[key][:shown]
        if any(v is not None for v in values):
            rows.append({"key": key, "label": label, "kind": kind, "values": values})
    return {"years": cols[:shown], "rows": rows}


def latest(tbl: dict) -> dict:
    """The newest column as {key: value}, plus its fiscal year label."""
    if not tbl["years"]:
        return {}
    out = {r["key"]: r["values"][0] for r in tbl["rows"]}
    return {**out, "fy": tbl["years"][0]["fy"], "end": tbl["years"][0]["end"], "url": tbl["years"][0]["url"]}


def fye_label(fye: str) -> str:
    """'0630' -> 'Jun 30'."""
    try:
        return (date(2001, int(fye[:2]), 1) + timedelta(days=int(fye[2:]) - 1)).strftime("%b %-d")
    except (ValueError, TypeError):
        return ""
