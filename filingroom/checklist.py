"""Load the checklist and resolve each question's period for a given company's corpus."""

import json
from datetime import date

from . import config, edgar


def load() -> list[dict]:
    return json.loads(config.CHECKLIST.read_text())["questions"]


def by_id() -> dict[str, dict]:
    return {q["id"]: q for q in load()}


def periods(ticker: str) -> dict:
    """Concrete periods for this company's corpus (e.g. latest_fy -> FY2026)."""
    co = config.company(ticker)
    docs = edgar.manifest(ticker)
    tenks = sorted([d for d in docs if d["form"] == "10-K"], key=lambda d: d["report_date"], reverse=True)
    release = max((d for d in docs if d["form"] == "8-K"), key=lambda d: d["filing_date"])
    proxy = max((d for d in docs if d["form"] == "DEF 14A"), key=lambda d: d["filing_date"])
    fye_before_proxy = max(e for e in [date.fromisoformat(t["report_date"]) for t in tenks]
                           + [date(y, int(co["fiscal_year_end"][:2]), int(co["fiscal_year_end"][2:]))
                              for y in range(2020, 2030)]
                           if e < date.fromisoformat(proxy["filing_date"]))
    latest_doc = max(docs, key=lambda d: d["filing_date"])
    return {
        "latest_fy": tenks[0]["period"], "latest_fy_end": tenks[0]["report_date"],
        "latest_fy_doc": tenks[0]["doc_id"],
        "prior_fy": tenks[1]["period"], "prior_fy_end": tenks[1]["report_date"],
        "latest_release": release["period"], "latest_release_doc": release["doc_id"],
        "latest_proxy": f"FY{edgar.fiscal_year_of(fye_before_proxy, co['fiscal_year_end'])}",
        "latest_proxy_doc": proxy["doc_id"],
        "latest_filing": latest_doc["filing_date"],
    }


def describe_period(q: dict, P: dict) -> str:
    p = q["period"]
    if p == "latest_fy":
        return f"fiscal year {P['latest_fy']} (ended {P['latest_fy_end']}), the most recent 10-K ({P['latest_fy_doc']})"
    if p == "prior_fy":
        return (f"fiscal year {P['prior_fy']} (ended {P['prior_fy_end']}). Note this prior year also appears "
                f"as the comparative column in the {P['latest_fy']} 10-K")
    if p == "latest_fy_end":
        return f"as of {P['latest_fy_end']}, the end of fiscal year {P['latest_fy']}"
    if p == "latest_release":
        return f"the quarter {P['latest_release']}, covered by the latest earnings release ({P['latest_release_doc']})"
    if p == "latest_proxy":
        return f"fiscal year {P['latest_proxy']}, covered by the latest proxy statement ({P['latest_proxy_doc']})"
    return f"the most recent period disclosed in any filing (latest filing: {P['latest_filing']})"


def target_periods(q: dict, P: dict) -> list[str] | None:
    """Period labels to boost in retrieval (soft preference, never a hard filter)."""
    return {"latest_fy": [P["latest_fy"]], "latest_fy_end": [P["latest_fy"]],
            "prior_fy": [P["prior_fy"], P["latest_fy"]], "latest_release": [P["latest_release"]],
            }.get(q["period"])
