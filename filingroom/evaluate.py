"""Eval runner: answer every golden item, grade it, write a dated results file, append to CHANGELOG-evals.md.

Grading:
  numeric      value within tolerance of the golden value (mechanical)
  judged       LLM judge compares against the golden text
  abstain      correct iff the answer is not_found
Citation support is judged for every answered item, using only quotes that verified against the source.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import answer, checklist, config, golden, llm
from .index import Index

JUDGE_MODEL = "claude-opus-5"
JUDGE_EFFORT = "low"
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "correct": {"type": "string", "enum": ["yes", "no", "n/a"]},
        "supported": {"type": "string", "enum": ["yes", "partial", "no"]},
        "reason": {"type": "string"},
    },
    "required": ["correct", "supported", "reason"],
    "additionalProperties": False,
}
CHANGELOG = config.ROOT / "CHANGELOG-evals.md"


def eval_tickers(final: bool) -> list[str]:
    return [t for t, c in config.companies().items() if final or c["split"] == "tune"]


# ---------------------------------------------------------------- grading

def grade_numeric(item: dict, ans: dict) -> bool:
    v = ans["parsed_value"]
    if ans["status"] != "answered" or v is None:  # strict: an answer with no verified citation doesn't count
        return False
    gold = item["expected"]["value"]
    tol = item.get("tolerance", {})
    if "abs" in tol:
        return abs(v - gold) <= tol["abs"]
    return abs(v - gold) <= abs(gold) * tol.get("rel", 0.005) + 1e-9


def judge(item: dict, ans: dict, need_correct: bool, meter: llm.CostMeter, model: str) -> dict:
    quotes = [c for c in ans["citations"] if c["verified"]]
    user = (f"Question: {ans['question']}\n\n"
            f"Expected answer: {item['expected'].get('text') or item['expected']}\n\n"
            f"Assistant's answer: {ans['answer']} (value: {ans['value'] or '-'}, period: {ans['period'] or '-'})\n\n"
            "Cited quotes:\n" + ("\n".join(f"- [{c['chunk_id']}] {c['quote']}" for c in quotes) or "(none)") +
            ("" if need_correct else "\n\nCorrectness is graded elsewhere: set correct to \"n/a\"."))
    try:
        return llm.complete_json(model, answer.load_prompt("judge.md"), user, JUDGE_SCHEMA, meter,
                                 effort=JUDGE_EFFORT, max_tokens=8000)
    except llm.LLMError as e:
        return {"correct": "no", "supported": "no", "reason": f"judge error: {e}"}


def value_in_context(item: dict, ans: dict, ix: Index) -> bool | None:
    """LLM-free retrieval check: did any retrieved chunk contain the golden number (as filings print it)?"""
    if item["grade"] != "numeric" or item["expected"].get("unit") not in ("USD", "count"):
        return None
    if item.get("computed") or len(item["source"].get("concepts", [])) > 1:
        return None  # a sum of several figures never appears verbatim
    n = abs(item["expected"]["value"])
    variants = {f"{n:,.0f}", f"{n / 1e6:,.1f}", f"{n / 1e6:,.2f}", f"{n / 1e9:,.2f}"}
    if n % 1000 == 0:
        variants.add(f"{n / 1000:,.0f}")
    pats = [re.compile(r"(?<![\d,.])" + re.escape(v) + r"(?![\d])") for v in variants]
    texts = [ix.by_id[cid]["text"] for cid in ans["retrieved"] if cid in ix.by_id]
    return any(p.search(t) for p in pats for t in texts)


# ---------------------------------------------------------------- metrics

def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def metrics(rows: list[dict]) -> dict:
    graded = [r for r in rows if r["correct"] is not None]
    answered = [r for r in rows if r["model_status"] == "answered"]
    supported = [r for r in answered if r["citations_verified"] > 0 and r["supported"] == "yes"]
    unsupported = [r for r in answered if r["citations_verified"] == 0 or r["supported"] == "no"]
    exp_nf = [r for r in rows if r["grade"] == "abstain"]
    pred_nf = [r for r in rows if r["status"] == "not_found"]
    tp = [r for r in exp_nf if r["status"] == "not_found"]
    retr = [r for r in rows if r["value_in_context"] is not None]
    by_grade = {}
    for g in ("numeric", "judged", "abstain"):
        rs = [r for r in graded if r["grade"] == g]
        by_grade[g] = {"n": len(rs), "accuracy": _pct(sum(r["correct"] for r in rs), len(rs))}
    return {
        "n_items": len(rows),
        "accuracy": _pct(sum(r["correct"] for r in graded), len(graded)),
        "by_grade": by_grade,
        "citation_verified_rate": _pct(sum(r["citations_verified"] > 0 for r in answered), len(answered)),
        "citation_support_rate": _pct(len(supported), len(answered)),
        "unsupported_claim_rate": _pct(len(unsupported), len(answered)),
        "abstention_precision": _pct(len(tp), len(pred_nf)),
        "abstention_recall": _pct(len(tp), len(exp_nf)),
        "false_abstentions": len(pred_nf) - len(tp),
        "retrieval_recall": _pct(sum(r["value_in_context"] for r in retr), len(retr)),
        "errors": sum(r["status"] == "error" for r in rows),
    }


# ---------------------------------------------------------------- driver

def run(tickers: list[str], model: str, effort: str | None, k: int, judge_model: str = JUDGE_MODEL,
        label: str = "", note: str = "", workers: int = 6, use_judge: bool = True) -> dict:
    t0 = time.time()
    items = golden.load(tickers)
    qs = checklist.by_id()
    ixs = {t: Index(t) for t in tickers}
    answer_meter, judge_meter = llm.CostMeter(), llm.CostMeter()
    print(f"eval: {len(items)} golden items over {', '.join(tickers)} | model={model} effort={effort} k={k}")

    def work(item):
        ans = answer.answer_question(item["ticker"], qs[item["qid"]], ixs[item["ticker"]], answer_meter,
                                     model=model, effort=effort, k=k)
        grade = item["grade"]
        correct, supported, reason = None, None, ""
        if grade == "numeric":
            correct = grade_numeric(item, ans)
        elif grade == "abstain":
            correct = ans["status"] == "not_found"
        need_judge_correct = grade == "judged" and ans["model_status"] == "answered"
        if grade == "judged" and not need_judge_correct:
            correct = False
        if use_judge and ans["model_status"] == "answered":
            j = judge(item, ans, need_judge_correct, judge_meter, judge_model)
            supported, reason = j["supported"], j["reason"]
            if need_judge_correct:
                correct = j["correct"] == "yes"
        mark = {True: "✓", False: "✗", None: "·"}[correct]
        print(f"  {mark} {item['id']:<28} {ans['status']:<11} {(ans['answer'] or ans['error'] or '')[:90]}")
        return {**ans, "id": item["id"], "grade": grade, "expected": item["expected"],
                "golden_verified": item.get("verified"), "correct": correct, "supported": supported,
                "judge_reason": reason, "value_in_context": value_in_context(item, ans, ixs[item["ticker"]])}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(work, items))
    m = metrics(rows)
    m["cost_usd"] = {"answer": round(answer_meter.cost(), 4), "judge": round(judge_meter.cost(), 4)}
    m["cost_per_company_usd"] = round(answer_meter.cost() / len(tickers), 4)
    m["wall_seconds"] = round(time.time() - t0, 1)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    result = {"timestamp": stamp, "label": label, "note": note, "tickers": tickers, "model": model,
              "effort": effort, "k": k, "judge_model": judge_model if use_judge else None,
              "metrics": m, "usage": {"answer": answer_meter.summary(), "judge": judge_meter.summary()},
              "rows": rows}
    prev = latest_result(tickers)
    config.RESULTS.mkdir(exist_ok=True)
    name = f"{stamp}{'_' + label if label else ''}"
    (config.RESULTS / f"{name}.json").write_text(json.dumps(result, indent=1))
    (config.RESULTS / f"{name}.md").write_text(report_md(result, prev))
    append_changelog(result)
    print(report_md(result, prev, brief=True))
    print(f"wrote results/{name}.json and .md")
    return result


def latest_result(tickers: list[str]) -> dict | None:
    for p in sorted(config.RESULTS.glob("*.json"), reverse=True):
        r = json.loads(p.read_text())
        if sorted(r["tickers"]) == sorted(tickers):
            return r
    return None


def _fmt(v) -> str:
    return "–" if v is None else f"{v}"


def report_md(r: dict, prev: dict | None, brief: bool = False) -> str:
    m = r["metrics"]
    pm = prev["metrics"] if prev else {}
    keys = [("accuracy", "Accuracy %"), ("citation_verified_rate", "Citations verified %"),
            ("citation_support_rate", "Citation support %"), ("unsupported_claim_rate", "Unsupported claims %"),
            ("abstention_precision", "Abstention precision %"), ("abstention_recall", "Abstention recall %"),
            ("retrieval_recall", "Retrieval recall (numeric) %")]
    lines = [f"# Eval {r['timestamp']} {r['label']}", "",
             f"{', '.join(r['tickers'])} · model `{r['model']}` · effort `{r['effort']}` · k={r['k']} · "
             f"judge `{r['judge_model']}`", ""]
    if r["note"]:
        lines += [f"Change: {r['note']}", ""]
    lines += ["| Metric | This run | Previous |", "|---|---|---|"]
    for key, name in keys:
        lines.append(f"| {name} | {_fmt(m[key])} | {_fmt(pm.get(key))} |")
    for g, v in m["by_grade"].items():
        lines.append(f"| Accuracy: {g} (n={v['n']}) | {_fmt(v['accuracy'])} | "
                     f"{_fmt(pm.get('by_grade', {}).get(g, {}).get('accuracy'))} |")
    lines.append(f"| Cost: answering / judging ($) | {m['cost_usd']['answer']} / {m['cost_usd']['judge']} | "
                 f"{pm.get('cost_usd', {}).get('answer', '–')} / {pm.get('cost_usd', {}).get('judge', '–')} |")
    lines.append(f"| Wall time (s) | {m['wall_seconds']} | {pm.get('wall_seconds', '–')} |")
    if prev:
        before = {row["id"]: row["correct"] for row in prev["rows"]}
        flips = [(row["id"], before.get(row["id"]), row["correct"]) for row in r["rows"]
                 if row["id"] in before and before[row["id"]] != row["correct"]]
        if flips:
            lines += ["", "Items that changed: " + ", ".join(f"{i} ({'✓' if b else '✗'}→{'✓' if a else '✗'})"
                                                        for i, b, a in flips)]
    if brief:
        return "\n".join(lines)
    lines += ["", "## Failures", ""]
    for row in r["rows"]:
        if row["correct"] is False or row["supported"] in ("no", "partial") or row["status"] == "unsupported":
            exp = row["expected"].get("text") or row["expected"].get("value")
            lines += [f"**{row['id']}** — {row['status']}, correct={row['correct']}, supported={row['supported']}, "
                      f"value in retrieved context={row['value_in_context']}",
                      f"- Expected: {exp}", f"- Got: {row['answer']} (value `{row['value']}`, period {row['period']})",
                      f"- Judge: {row['judge_reason']}" if row["judge_reason"] else "",
                      f"- Cited: {', '.join(c['chunk_id'] + ('' if c['verified'] else ' (quote NOT verified)') for c in row['citations']) or 'none'}",
                      ""]
    return "\n".join(l for l in lines if l is not None)


def append_changelog(r: dict) -> None:
    m = r["metrics"]
    if not CHANGELOG.exists():
        CHANGELOG.write_text("# Eval changelog\n\nOne line per eval run: what changed, what moved.\n\n"
                             "| Run | Companies | Change | Acc % | Cite support % | Unsupported % | "
                             "Abstain P/R | Retrieval % | $ answer/judge |\n|---|---|---|---|---|---|---|---|---|\n")
    with open(CHANGELOG, "a") as f:
        f.write(f"| {r['timestamp']} {r['label']} | {','.join(r['tickers'])} | {r['note'] or '-'} "
                f"({r['model']}, {r['effort']}, k={r['k']}) | {_fmt(m['accuracy'])} | "
                f"{_fmt(m['citation_support_rate'])} | {_fmt(m['unsupported_claim_rate'])} | "
                f"{_fmt(m['abstention_precision'])}/{_fmt(m['abstention_recall'])} | "
                f"{_fmt(m['retrieval_recall'])} | {m['cost_usd']['answer']}/{m['cost_usd']['judge']} |\n")


def retrieval_check(tickers: list[str], k: int) -> None:
    """No API calls: for numeric golden items, is the expected number anywhere in the top-k chunks?"""
    qs = checklist.by_id()
    hits, total = 0, 0
    for t in tickers:
        ix = Index(t)
        P = checklist.periods(t)
        for item in golden.load([t]):
            fake = {"retrieved": [h.chunk["chunk_id"] for h in answer.retrieve(ix, qs[item["qid"]], P, k)]}
            ok = value_in_context(item, fake, ix)
            if ok is None:
                continue
            total += 1
            hits += ok
            print(f"  {'✓' if ok else '✗'} {item['id']:<28} top: {fake['retrieved'][0]}")
    print(f"retrieval recall@{k}: {hits}/{total} = {_pct(hits, total)}%")
