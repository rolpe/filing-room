"""Statistics for the evaluation area: error margins, a paired-flip test, and the trust metric.

- wilson(k, n): 95% Wilson score interval for a rate (well-behaved at 0%, 100% and small n).
- sign_test(better, worse): exact two-sided sign test on paired flips between two runs.
- counts(rows): numerator/denominator for each rate evaluate.metrics reports, so each can carry an interval.
- trust(rows, ...): the app's own status function (findings.derive_status) applied to each graded eval row.
"""

import math

from . import findings

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """95% Wilson interval for k successes in n trials, as percentages; None when n is 0."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(100 * max(0.0, centre - half), 1), round(100 * min(1.0, centre + half), 1)


def rate(k: int, n: int) -> dict:
    """{k, n, pct, ci} for display."""
    return {"k": k, "n": n, "pct": round(100 * k / n, 1) if n else None, "ci": wilson(k, n)}


def sign_test(better: int, worse: int) -> float:
    """Exact two-sided sign test p-value for paired flips (ties, i.e. unchanged items, are ignored)."""
    n = better + worse
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(better, worse) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def flip_statement(better: int, worse: int, alpha: float = 0.05) -> str:
    n = better + worse
    if n == 0:
        return "No item changed its grade."
    parts = f"{n} {'item' if n == 1 else 'items'} changed ({better} better, {worse} worse)"
    p = sign_test(better, worse)
    if p < alpha:
        return f"{parts}; unlikely to be noise (sign test p = {p:.3f})."
    return f"{parts}; too few to tell from noise (sign test p = {p:.2f})."


# ---------------------------------------------------------------- counts behind evaluate.metrics

def counts(rows: list[dict]) -> dict:
    """The same definitions as evaluate.metrics, kept as counts so each rate can carry an interval."""
    graded = [r for r in rows if r.get("correct") is not None]
    answered = [r for r in rows if r.get("model_status") == "answered"]
    supported = [r for r in answered if r.get("citations_verified", 0) > 0 and r.get("supported") == "yes"]
    unsupported = [r for r in answered if r.get("citations_verified", 0) == 0 or r.get("supported") == "no"]
    exp_nf = [r for r in rows if r.get("grade") == "abstain"]
    pred_nf = [r for r in rows if r.get("status") == "not_found"]
    tp = [r for r in exp_nf if r.get("status") == "not_found"]
    retr = [r for r in rows if r.get("value_in_context") is not None]
    return {
        "accuracy": rate(sum(bool(r["correct"]) for r in graded), len(graded)),
        "citation_support_rate": rate(len(supported), len(answered)),
        "unsupported_claim_rate": rate(len(unsupported), len(answered)),
        "abstention_precision": rate(len(tp), len(pred_nf)),
        "abstention_recall": rate(len(tp), len(exp_nf)),
        "retrieval_recall": rate(sum(bool(r["value_in_context"]) for r in retr), len(retr)),
    }


# ---------------------------------------------------------------- trust metric

def app_status(row: dict, sec: dict | None, docs: dict | None) -> str:
    """What the app would show for this answer: verified, review or not_disclosed (findings.derive_status)."""
    return findings.derive_status(row, sec, None, docs)["status"]


def sec_check_for(row: dict, golden_item: dict | None) -> dict | None:
    """The app's SEC number check compares numeric answers with SEC XBRL data. For items whose answer key *is* that
    XBRL figure, the check's result equals the numeric grade, so it costs nothing to reproduce; elsewhere it's None."""
    src = (golden_item or {}).get("source") or {}
    if row.get("grade") == "numeric" and src.get("method") in ("xbrl", "derived") and row.get("status") == "answered":
        return {"match": bool(row.get("correct"))}
    return None


def trust(rows: list[dict], golden_by_id: dict[str, dict], docs_by_ticker: dict[str, dict]) -> dict:
    """How far the app's own statuses can be trusted, on graded items (support_only items have no correctness).

    verified_wrong   of answers the app would mark Verified, how many were wrong
    wrong_caught     of wrong answers, how many the app would mark To review
    false_not_found  of items the filings do answer (not abstention items), how many came back not found
    """
    graded = [r for r in rows if r.get("correct") is not None and r.get("grade") != "support_only"]
    st = {r["id"]: app_status(r, sec_check_for(r, golden_by_id.get(r["id"])), docs_by_ticker.get(r.get("ticker")))
          for r in graded}
    verified = [r for r in graded if st[r["id"]] == "verified"]
    wrong = [r for r in graded if not r["correct"]]
    answerable = [r for r in rows if r.get("grade") in ("numeric", "judged", "support_only")]
    false_nf = [r for r in answerable if r.get("status") == "not_found"]
    return {
        "verified_wrong": rate(sum(not r["correct"] for r in verified), len(verified)),
        "wrong_caught": rate(sum(st[r["id"]] == "review" for r in wrong), len(wrong)),
        "wrong_by_status": {s: sum(st[r["id"]] == s for r in wrong) for s in ("verified", "review", "not_disclosed")},
        "false_not_found": rate(len(false_nf), len(answerable)),
        "false_not_found_ids": [r["id"] for r in false_nf],
        "statuses": st,
    }


# ---------------------------------------------------------------- checked answer key

def checked_share(rows: list[dict], status_by_id: dict[str, str]) -> dict:
    """Graded items whose answer key a person has checked, and accuracy on just those."""
    graded = [r for r in rows if r.get("correct") is not None]
    checked = [r for r in graded if status_by_id.get(r["id"]) == "human"]
    return {"checked": rate(len(checked), len(graded)),
            "accuracy_checked": rate(sum(bool(r["correct"]) for r in checked), len(checked))}
