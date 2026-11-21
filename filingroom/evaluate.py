"""Eval runner: answer every golden item, grade it, write a dated results file, append to CHANGELOG-evals.md.

Grading:
  numeric      value within tolerance of the golden value (mechanical)
  judged       LLM judge compares against the golden text
  abstain      correct iff the answer is not_found
Citation support is judged for every answered item, using only quotes that verified against the source.
"""

import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import answer, checklist, config, golden, llm, modes
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
# Agent mode results live apart, so the pipeline's history, trend and "previous run" comparisons stay clean.
AGENT_RESULTS = config.RESULTS / "agent"
AGENT_CHANGELOG = config.ROOT / "CHANGELOG-agent-evals.md"


def eval_tickers(final: bool) -> list[str]:
    return [t for t, c in config.companies().items() if c["split"] == "tune" or (final and c["split"] == "holdout")]


# ---------------------------------------------------------------- grading

def grade_numeric(item: dict, ans: dict) -> bool:
    v = ans["parsed_value"]
    if ans["status"] != "answered" or v is None:  # strict: an answer with no verified citation doesn't count
        return False
    tol = item.get("tolerance", {})
    for gold in [item["expected"]["value"]] + item.get("also_accept", []):
        if "abs" in tol and abs(v - gold) <= tol["abs"]:
            return True
        if "abs" not in tol and abs(v - gold) <= abs(gold) * tol.get("rel", 0.005) + 1e-9:
            return True
    return False


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

def run(tickers: list[str], model: str, effort: str | None, k: int, expand: int = 0, judge_model: str = JUDGE_MODEL,
        label: str = "", note: str = "", workers: int = 6, use_judge: bool = True,
        only: set[str] | None = None, progress=None, out_dir=None, changelog: bool = True,
        mode: str = "pipeline", agent_opts: dict | None = None) -> dict:
    """Optional hooks (used by the app's evaluation area; the CLI passes none of them):
    only       golden ids to run instead of the whole set (a spot check)
    progress   called with (items done, items total) as each item is graded
    out_dir    write the results files (and the rows backup) here instead of results/ (and runs/)
    changelog  False to skip the CHANGELOG-evals.md line

    mode="agent" answers through agent mode (agent_opts: its budget settings) and writes to results/agent/ and
    CHANGELOG-agent-evals.md instead; the result records the mode, the settings, the ids run, and agent metrics.
    """
    ask = modes.answerer(mode, **(agent_opts or {}))
    agent = mode != "pipeline"
    t0 = time.time()
    items = golden.load(tickers)
    if only is not None:
        items = [i for i in items if i["id"] in only]
    qs = checklist.by_id()
    ixs = {t: Index(t) for t in tickers}
    answer_meter, judge_meter = llm.CostMeter(), llm.CostMeter()
    if agent:
        k = expand = None  # the agent chooses its own searches
        print(f"eval: {len(items)} golden items over {', '.join(tickers)} | {mode} mode, model={model} "
              f"effort={effort} {agent_opts or {}}")
    else:
        print(f"eval: {len(items)} golden items over {', '.join(tickers)} | model={model} effort={effort} k={k} expand={expand}")

    def work(item):
        ans = ask(item["ticker"], qs[item["qid"]], ixs[item["ticker"]], answer_meter,
                  model=model, effort=effort, k=k, expand=expand)
        grade = item["grade"]
        correct, supported, reason = None, None, ""
        if grade == "numeric":
            correct = grade_numeric(item, ans)
        elif grade == "abstain":
            correct = ans["status"] == "not_found"
        need_judge_correct = grade == "judged" and ans["model_status"] == "answered"
        if grade == "judged" and not need_judge_correct:
            # not_found is wrong for a judged item, unless the golden says the filings only imply the answer
            correct = bool(item.get("accept_not_found")) and ans["status"] == "not_found"
        if use_judge and ans["model_status"] == "answered":
            j = judge(item, ans, need_judge_correct, judge_meter, judge_model)
            supported, reason = j["supported"], j["reason"]
            if need_judge_correct:
                correct = j["correct"] == "yes"
        mark = {True: "✓", False: "✗", None: "·"}[correct]
        print(f"  {mark} {item['id']:<28} {ans['status']:<11} {(ans['answer'] or ans['error'] or '')[:90]}")
        if progress:
            with progress_lock:
                done[0] += 1
                progress(done[0], len(items))
        return {**ans, "id": item["id"], "grade": grade, "expected": item["expected"],
                "golden_verified": item.get("verified"), "correct": correct, "supported": supported,
                "judge_reason": reason, "value_in_context": value_in_context(item, ans, ixs[item["ticker"]])}

    done, progress_lock = [0], threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(work, items))
    # Save the paid-for answers before anything else can fail.
    rows_dir = out_dir or config.RUNS
    rows_dir.mkdir(parents=True, exist_ok=True)
    (rows_dir / ("last_agent_eval_rows.json" if agent else "last_eval_rows.json")).write_text(json.dumps(rows))
    m = metrics(rows)
    m["cost_usd"] = {"answer": round(answer_meter.cost(), 4), "judge": round(judge_meter.cost(), 4)}
    m["cost_per_company_usd"] = round(answer_meter.cost() / len(tickers), 4)
    m["wall_seconds"] = round(time.time() - t0, 1)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    result = {"timestamp": stamp, "label": label, "note": note, "tickers": tickers, "model": model,
              "effort": effort, "k": k, "expand": expand, "judge_model": judge_model if use_judge else None,
              "metrics": m, "usage": {"answer": answer_meter.summary(), "judge": judge_meter.summary()},
              "rows": rows}
    if agent:
        result.update(mode=mode, agent_opts={k_: v for k_, v in (agent_opts or {}).items() if k_ != "call_model"},
                      only=sorted(only) if only is not None else None)
        m["agent"] = agent_metrics(rows)
        prev = latest_result(tickers, directory=AGENT_RESULTS, ids={r["id"] for r in rows})
    else:
        prev = latest_result(tickers)
    res_dir = out_dir or (AGENT_RESULTS if agent else config.RESULTS)
    res_dir.mkdir(parents=True, exist_ok=True)
    name = f"{stamp}{'_' + label if label else ''}"
    (res_dir / f"{name}.json").write_text(json.dumps(result, indent=1))
    (res_dir / f"{name}.md").write_text(report_md(result, prev))
    if changelog:
        (append_agent_changelog if agent else append_changelog)(result)
    print(report_md(result, prev, brief=True))
    print(f"wrote {res_dir.relative_to(config.ROOT) if res_dir.is_relative_to(config.ROOT) else res_dir}/{name}.json and .md")
    result["name"] = name
    return result


def latest_result(tickers: list[str], directory=None, ids: set[str] | None = None) -> dict | None:
    """Newest results file for these tickers (in results/ unless `directory`); with `ids`, only one that ran
    exactly those golden items (agent subsets are compared with the same subset)."""
    for p in sorted((directory or config.RESULTS).glob("*.json"), reverse=True):
        r = json.loads(p.read_text())
        if "rows" in r and sorted(r["tickers"]) == sorted(tickers):  # skip memo claim-check files
            if ids is None or {row["id"] for row in r["rows"]} == ids:
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
             f"expand={r.get('expand', 0)} · "
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
                f"({r['model']}, {r['effort']}, k={r['k']}, expand={r.get('expand', 0)}) | {_fmt(m['accuracy'])} | "
                f"{_fmt(m['citation_support_rate'])} | {_fmt(m['unsupported_claim_rate'])} | "
                f"{_fmt(m['abstention_precision'])}/{_fmt(m['abstention_recall'])} | "
                f"{_fmt(m['retrieval_recall'])} | {m['cost_usd']['answer']}/{m['cost_usd']['judge']} |\n")


# ---------------------------------------------------------------- agent mode: metrics, changelog, comparison

def _pctile(xs: list[float], q: float) -> float | None:
    """Nearest-rank percentile."""
    if not xs:
        return None
    xs = sorted(xs)
    return xs[max(0, min(len(xs) - 1, math.ceil(round(q * len(xs), 9)) - 1))]


def latency(rows: list[dict]) -> dict:
    xs = [r["seconds"] for r in rows if r.get("seconds") is not None]
    if not xs:
        return {"mean": None, "median": None, "p90": None}
    return {"mean": round(sum(xs) / len(xs), 1), "median": _pctile(xs, 0.5), "p90": _pctile(xs, 0.9)}


def agent_metrics(rows: list[dict]) -> dict:
    """Per-question loop statistics from the rows' `agent` blocks (pipeline rows: 1 model call, 0 tool calls)."""
    ag = [r["agent"] for r in rows if "agent" in r]
    n = len(ag)
    if not n:
        return {"n": 0}
    stops: dict[str, int] = {}
    for a in ag:
        stops[a["stop"]] = stops.get(a["stop"], 0) + 1
    return {
        "n": n,
        "model_calls_mean": round(sum(a["model_calls"] for a in ag) / n, 2),
        "tool_calls_mean": round(sum(a["tool_calls"] for a in ag) / n, 2),
        "tokens_mean": round(sum(a["tokens"] for a in ag) / n),
        "tokens_max": max(a["tokens"] for a in ag),
        "usd_per_question": round(sum(a["usd"] for a in ag) / n, 4),
        "hit_limit": sum(a["stop"] in ("step_limit", "token_limit") for a in ag),
        "stops": stops,
        "repairs": sum(a.get("repairs", 0) for a in ag),
        "cited_unseen": sum(len(a.get("cited_unseen", [])) for a in ag),
        "latency_s": latency(rows),
    }


def append_agent_changelog(r: dict) -> None:
    m, a = r["metrics"], r["metrics"]["agent"]
    if not AGENT_CHANGELOG.exists():
        AGENT_CHANGELOG.write_text(
            "# Agent mode eval changelog\n\nOne line per agent-mode eval run (results in results/agent/). "
            "The pipeline's runs are in CHANGELOG-evals.md.\n\n"
            "| Run | Companies | Items | Change | Acc % | Unsupported % | Abstain P/R | Calls/tools per q | "
            "Hit limit | $ per q | $ answer/judge |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
    with open(AGENT_CHANGELOG, "a") as f:
        f.write(f"| {r['timestamp']} {r['label']} | {','.join(r['tickers'])} | {m['n_items']}"
                f"{' (subset)' if r.get('only') else ''} | {r['note'] or '-'} ({r['model']}, {r['effort']}, "
                f"{json.dumps(r.get('agent_opts') or {})}) | {_fmt(m['accuracy'])} | {_fmt(m['unsupported_claim_rate'])} | "
                f"{_fmt(m['abstention_precision'])}/{_fmt(m['abstention_recall'])} | "
                f"{a['model_calls_mean']}/{a['tool_calls_mean']} | {a['hit_limit']} | {a['usd_per_question']} | "
                f"{m['cost_usd']['answer']}/{m['cost_usd']['judge']} |\n")


def compare(base: dict, other: dict) -> dict:
    """Free: two results files (e.g. the pipeline and agent mode) on the items both graded, paired by golden id.

    Returns {n, ids, sides: {name: {...}}, flips: {better, worse, statement}} where each side has accuracy (overall
    and by grade, with 95% intervals), unsupported, abstention and trust rates, cost per question, latency, and
    loop statistics. `base` is the reference: "better" means right in `other` and wrong in `base`."""
    from . import devtools, evalstats
    ids = sorted({r["id"] for r in base["rows"]} & {r["id"] for r in other["rows"]})
    gold = devtools._golden_by_id()
    out = {"n": len(ids), "ids": ids, "sides": {}}
    for name, res in (("base", base), ("other", other)):
        rows = [r for r in res["rows"] if r["id"] in set(ids)]
        tickers = sorted({r["ticker"] for r in rows})
        c = evalstats.counts(rows)
        graded = [r for r in rows if r.get("correct") is not None]
        by_grade = {g: evalstats.rate(sum(bool(r["correct"]) for r in graded if r["grade"] == g),
                                      sum(r["grade"] == g for r in graded)) for g in ("numeric", "judged", "abstain")}
        tr = evalstats.trust(rows, gold, devtools._docs_by_ticker(tickers))
        tr.pop("statuses")
        ag = agent_metrics(rows)
        if ag["n"]:
            usd_q, usd_note = round(sum(r["agent"]["usd"] for r in rows) / len(rows), 4), "sum over these items"
            calls, tools_, hit = ag["model_calls_mean"], ag["tool_calls_mean"], ag["hit_limit"]
        else:
            usd_q = round(res["metrics"]["cost_usd"]["answer"] / max(len(res["rows"]), 1), 4)
            usd_note = f"run average over its {len(res['rows'])} items"
            calls, tools_, hit = 1, 0, 0
        out["sides"][name] = {
            "label": f"{res.get('timestamp', '')} {res.get('label', '')}".strip(), "mode": res.get("mode", "pipeline"),
            "accuracy": c["accuracy"], "by_grade": by_grade, "unsupported": c["unsupported_claim_rate"],
            "abstention_precision": c["abstention_precision"], "abstention_recall": c["abstention_recall"],
            "trust": tr, "usd_per_question": usd_q, "usd_note": usd_note, "latency": latency(rows),
            "model_calls": calls, "tool_calls": tools_, "hit_limit": hit, "agent": ag}
    b = {r["id"]: r.get("correct") for r in base["rows"]}
    o = {r["id"]: r.get("correct") for r in other["rows"]}
    better = [i for i in ids if o[i] is True and b[i] is False]
    worse = [i for i in ids if o[i] is False and b[i] is True]
    out["flips"] = {"better": better, "worse": worse, "p": evalstats.sign_test(len(better), len(worse)),
                    "statement": evalstats.flip_statement(len(better), len(worse))}
    return out


def _rate(x: dict) -> str:
    if not x or x.get("pct") is None:
        return "–"
    lo, hi = x["ci"]
    return f"{x['pct']}% ({x['k']}/{x['n']}; {lo}–{hi})"


def _lat(x: dict) -> str:
    return " / ".join("–" if x[k] is None else str(x[k]) for k in ("mean", "median", "p90"))


def compare_md(c: dict) -> str:
    b, o = c["sides"]["base"], c["sides"]["other"]
    rows = [("Accuracy", _rate(b["accuracy"]), _rate(o["accuracy"]))]
    rows += [(f"Accuracy: {g}", _rate(b["by_grade"][g]), _rate(o["by_grade"][g])) for g in ("numeric", "judged", "abstain")]
    rows += [("Unsupported claims (of answered)", _rate(b["unsupported"]), _rate(o["unsupported"])),
             ("Abstention precision", _rate(b["abstention_precision"]), _rate(o["abstention_precision"])),
             ("Abstention recall", _rate(b["abstention_recall"]), _rate(o["abstention_recall"])),
             ("Verified but wrong (app status)", _rate(b["trust"]["verified_wrong"]), _rate(o["trust"]["verified_wrong"])),
             ("Wrong answers caught as To review", _rate(b["trust"]["wrong_caught"]), _rate(o["trust"]["wrong_caught"])),
             ("False not found", _rate(b["trust"]["false_not_found"]), _rate(o["trust"]["false_not_found"])),
             ("Answer cost per question ($)", f"{b['usd_per_question']} ({b['usd_note']})",
              f"{o['usd_per_question']} ({o['usd_note']})"),
             ("Latency mean / median / p90 (s)", _lat(b["latency"]), _lat(o["latency"])),
             ("Model calls / tool calls per question", f"{b['model_calls']} / {b['tool_calls']}",
              f"{o['model_calls']} / {o['tool_calls']}"),
             ("Questions that hit a limit", str(b["hit_limit"]), str(o["hit_limit"]))]
    lines = [f"# Comparison on {c['n']} paired items", "",
             f"Base: {b['label']} ({b['mode']}) · Other: {o['label']} ({o['mode']})", "",
             "| Metric | Base | Other |", "|---|---|---|"] + [f"| {a} | {x} | {y} |" for a, x, y in rows]
    f = c["flips"]
    lines += ["", f"Flips: {f['statement']}"]
    if f["better"]:
        lines.append(f"- Right only in other: {', '.join(f['better'])}")
    if f["worse"]:
        lines.append(f"- Right only in base: {', '.join(f['worse'])}")
    lines += ["", "Rates show the count and a 95% Wilson interval. Judge cost is not included in answer cost."]
    return "\n".join(lines)


def retrieval_check(tickers: list[str], k: int, expand: int = 0) -> dict:
    """No API calls: for numeric golden items, is the expected number anywhere in the top-k chunks?
    Prints as before and also returns {k, expand, hits, total, recall, items: [{id, ok, top}]}."""
    qs = checklist.by_id()
    hits, total, out = 0, 0, []
    for t in tickers:
        ix = Index(t)
        P = checklist.periods(t)
        for item in golden.load([t]):
            fake = {"retrieved": [h.chunk["chunk_id"] for h in answer.retrieve(ix, qs[item["qid"]], P, k, expand)]}
            ok = value_in_context(item, fake, ix)
            if ok is None:
                continue
            total += 1
            hits += ok
            out.append({"id": item["id"], "ok": bool(ok), "top": fake["retrieved"][0]})
            print(f"  {'✓' if ok else '✗'} {item['id']:<28} top: {fake['retrieved'][0]}")
    print(f"retrieval recall@{k} (expand={expand}): {hits}/{total} = {_pct(hits, total)}%")
    return {"k": k, "expand": expand, "hits": hits, "total": total, "recall": _pct(hits, total), "items": out}
