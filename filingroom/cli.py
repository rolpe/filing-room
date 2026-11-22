"""filing-room CLI. Run ./fr --help."""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import answer, checklist, config, edgar, evaluate, golden, index, llm, memo, parse, pipeline, report


def _tickers(arg: str, final: bool, allow_holdout: bool = False) -> list[str]:
    cos = config.companies()
    if arg.lower() == "all":
        return [t for t, c in cos.items() if c["split"] == "tune" or (final and c["split"] == "holdout")]
    t = config.company(arg)["ticker"]
    if cos[t]["split"] == "holdout" and not (final or allow_holdout):
        sys.exit(f"{t} is the held-out company. Pass --final to use it (only for the final report).")
    return [t]


def _model_args(p):
    p.add_argument("--model", default=answer.DEFAULT_MODEL)
    p.add_argument("--effort", default=answer.DEFAULT_EFFORT, help="low|medium|high|xhigh|max, or 'none'")
    p.add_argument("--k", type=int, default=answer.DEFAULT_K, help="chunks retrieved per question")
    p.add_argument("--expand", type=int, default=answer.DEFAULT_EXPAND,
                   help="also include the neighbors of the top-N hits")


def _effort(e: str) -> str | None:
    return None if e == "none" else e


def _mode_args(p):
    from . import modes
    from .agent import DEFAULT_MAX_MODEL_CALLS, DEFAULT_MAX_TOKENS, DEFAULT_MAX_TOOL_CALLS  # no framework import
    p.add_argument("--mode", choices=modes.MODES, default="pipeline",
                   help="pipeline: code retrieves, one model call; agent: the model searches with tools in a loop; "
                        "hybrid: the pipeline first, then agent mode only when the pipeline's answer is not_found "
                        "or unsupported (the agent flags below apply to that second step)")
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_MODEL_CALLS,
                   help="agent and hybrid modes: model calls per agent question, the final answer included")
    p.add_argument("--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS,
                   help="agent and hybrid modes: per agent question")
    p.add_argument("--max-tokens-per-question", type=int, default=DEFAULT_MAX_TOKENS,
                   help="agent and hybrid modes: exploration budget (input + cached input + output over all calls)")
    p.add_argument("--repair", action="store_true",
                   help="agent and hybrid modes: one agent retry when no quote verifies")


def _agent_opts(a) -> dict:
    return {} if a.mode == "pipeline" else dict(max_model_calls=a.max_steps, max_tool_calls=a.max_tool_calls,
                                                 max_tokens=a.max_tokens_per_question, repair=a.repair)


def _answer_fn(a):
    """answer_question for the chosen mode, with the same call signature."""
    from . import modes
    return modes.answerer(a.mode, **_agent_opts(a))


def _agent_line(r: dict) -> str:
    ag = r["agent"]
    seconds = r["hybrid"]["agent_seconds"] if "hybrid" in r else r["seconds"]
    return (f"agent: {ag['model_calls']} model calls, {ag['tool_calls']} tool calls, {ag['tokens']:,} tokens, "
            f"stop={ag['stop']}, ${ag['usd']:.4f}, {seconds} s, {len(r['retrieved'])} chunks seen"
            + (f", verified quotes from unseen chunks: {ag['cited_unseen']}" if ag["cited_unseen"] else ""))


def _uses_agent(r: dict) -> bool:
    """The row's answer came from an agent loop, so its trace and `retrieved` describe that loop."""
    return r.get("mode") == "agent" or r.get("hybrid", {}).get("used") == "agent"


def _hybrid_line(r: dict) -> str:
    h = r["hybrid"]
    line = f"hybrid: pipeline {h['pipeline_status']} in {h['pipeline_seconds']} s"
    if not h["escalated"]:
        return line + ", not escalated"
    return (line + f"; agent mode {h['agent_status']} in {h['agent_seconds']} s; kept the {h['used']} answer"
            + (f" (agent error: {h['agent_error']})" if h.get("agent_error") else ""))


def main() -> None:
    ap = argparse.ArgumentParser(prog="fr", description="Diligence checklist agent over SEC filings.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, help_ in [("fetch", "download filings from EDGAR (cached)"), ("parse", "HTML -> sectioned text"),
                        ("index", "chunk + BM25 index"), ("build", "fetch + parse + index")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("ticker", help="ticker or 'all'")
        p.add_argument("--final", action="store_true", help="include the held-out company in 'all'")

    p = sub.add_parser("add", help="add any SEC-registered company (free): check eligibility, fetch, parse, index")
    p.add_argument("ticker")

    p = sub.add_parser("golden", help="rebuild golden/golden.jsonl from XBRL + golden/manual.jsonl")
    p.add_argument("--final", action="store_true")

    p = sub.add_parser("search", help="debug retrieval: show top chunks for a query")
    p.add_argument("ticker")
    p.add_argument("query")
    p.add_argument("--form", action="append")
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--full", action="store_true", help="print full chunk text")

    p = sub.add_parser("ask", help="answer one checklist question (by id) or a free-text question")
    p.add_argument("ticker")
    p.add_argument("question", help="checklist id (e.g. rev_total) or a question in quotes")
    p.add_argument("--final", action="store_true")
    _model_args(p)
    _mode_args(p)

    p = sub.add_parser("run", help="answer the full checklist -> runs/<TICKER>_<time>.md/.json")
    p.add_argument("ticker")
    p.add_argument("--final", action="store_true")
    p.add_argument("--workers", type=int, default=6)
    _model_args(p)
    _mode_args(p)

    p = sub.add_parser("memo", help="IC memo from the latest checklist run (or --run), with a claim check")
    p.add_argument("ticker")
    p.add_argument("--run", help="path to a runs/<TICKER>_<time>.json (default: latest)")
    p.add_argument("--model", default=memo.DEFAULT_MODEL)
    p.add_argument("--effort", default=memo.DEFAULT_EFFORT)
    p.add_argument("--no-check", action="store_true")
    p.add_argument("--final", action="store_true")
    p.add_argument("--note", default="", help="what changed (logged with the claim check)")

    p = sub.add_parser("eval", help="answer + grade the golden set; writes results/ and CHANGELOG-evals.md")
    p.add_argument("--final", action="store_true", help="include the held-out company")
    p.add_argument("--label", default="", help="short name for this run, e.g. 'k12'")
    p.add_argument("--note", default="", help="what changed since the last run")
    p.add_argument("--judge-model", default=evaluate.JUDGE_MODEL)
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--only", help="comma-separated golden ids to run (for debugging; not logged)")
    p.add_argument("--ids", help="agent and hybrid modes: comma-separated golden ids (or @file, one per line) to run, "
                                 "grade and record in results/agent/ (a measured subset)")
    p.add_argument("--full", action="store_true", help="agent and hybrid modes: allow a full eval without --ids")
    p.add_argument("--companies", help="comma-separated tickers (default: tuning set, or all with --final)")
    _model_args(p)
    _mode_args(p)

    p = sub.add_parser("compare", help="free: compare two eval results files on their shared items (e.g. pipeline vs agent)")
    p.add_argument("base", help="results file, e.g. results/2026-09-27_1616_recency.json")
    p.add_argument("other", help="results file, e.g. results/agent/<stamp>_<label>.json")
    p.add_argument("--out", help="also write the table to this .md file")

    p = sub.add_parser("ui", help="local web UI on 127.0.0.1 (only this Mac can reach it)")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--no-open", action="store_true", help="don't open a browser tab")

    p = sub.add_parser("retrieval", help="LLM-free check: is the golden number in the top-k chunks?")
    p.add_argument("--final", action="store_true")
    p.add_argument("--k", type=int, default=answer.DEFAULT_K)
    p.add_argument("--expand", type=int, default=answer.DEFAULT_EXPAND)

    a = ap.parse_args()

    if a.cmd in ("fetch", "parse", "index", "build"):
        for t in _tickers(a.ticker, a.final, allow_holdout=True):
            print(t)
            if a.cmd in ("fetch", "build"):
                edgar.fetch_company(t)
            if a.cmd in ("parse", "build"):
                parse.parse_company(t)
            if a.cmd in ("index", "build"):
                index.build_index(t)

    elif a.cmd == "add":
        pv = pipeline.preview(a.ticker)
        print(f"{pv['ticker']} · {pv['name']} · {pv['sic'] or 'industry n/a'} · fiscal year ends {pv['fiscal_year_end']}")
        if not pv["eligible"]:
            sys.exit(pv["reason"])
        pipeline.register(pv["ticker"])
        pipeline.build(pv["ticker"])
        print(f"Added {pv['ticker']}. Answer its checklist with: ./fr run {pv['ticker']}  (~${pipeline.RUN_ESTIMATE_USD:.2f})")

    elif a.cmd == "golden":
        items = golden.build(evaluate.eval_tickers(a.final))
        (config.ROOT / "golden" / "REVIEW.md").write_text(golden.review_sheet())
        print(f"{len(items)} golden items -> {config.GOLDEN.relative_to(config.ROOT)} (+ golden/REVIEW.md)")

    elif a.cmd == "search":
        ix = index.Index(config.company(a.ticker)["ticker"])
        for h in ix.search(a.query, k=a.k, forms=a.form):
            c = h.chunk
            print(f"\n{h.score:6.1f}  {c['chunk_id']}  [{c['subheading'][:60]}]")
            print(c["text"] if a.full else c["text"][:300].replace("\n", " ⏎ "))

    elif a.cmd == "ask":
        t = _tickers(a.ticker, a.final, allow_holdout=True)[0]  # asking never writes runs or results
        qs = checklist.by_id()
        q = qs.get(a.question) or {"id": "adhoc", "category": "Ad hoc", "question": a.question,
                                   "answer_type": "text", "period": "current", "where": {}}
        meter = llm.CostMeter()
        r = _answer_fn(a)(t, q, index.Index(t), meter, model=a.model, effort=_effort(a.effort), k=a.k,
                          expand=a.expand)
        print(json.dumps({k: r[k] for k in ("status", "answer", "value", "unit", "period", "confidence",
                                            "citations", "error")}, indent=2))
        if _uses_agent(r):
            ag = r["agent"]
            for t_ in ag["trace"]:
                print(f"  turn {t_['turn']}: {t_['tool']} {json.dumps(t_['input'])} -> "
                      f"{len(t_['shown'])} new, {len(t_['refs']) - len(t_['shown'])} already shown"
                      f"{' (error)' if t_['error'] else ''}")
            print(_agent_line(r))
        if "hybrid" in r:
            print(_hybrid_line(r))
        if "agent" in r:
            print(f"usage: {json.dumps(meter.summary()['by_model'])}")
        print(f"cost ${meter.cost():.4f}")

    elif a.cmd == "run":
        t = _tickers(a.ticker, a.final)[0]
        meter = llm.CostMeter()
        print(f"answering {len(checklist.load())} questions for {t} with {a.model} in {a.mode} mode ...")
        path = pipeline.run_checklist(t, meter, model=a.model, effort=_effort(a.effort), k=a.k, expand=a.expand,
                                      workers=a.workers, mode=a.mode, agent_opts=_agent_opts(a))
        data = json.loads(path.read_text())
        counts = {s: sum(r["status"] == s for r in data["answers"]) for s in ("answered", "not_found", "unsupported", "error")}
        nc = data["meta"]["number_check"]
        esc = ""
        if a.mode == "hybrid":
            hy = [r["hybrid"] for r in data["answers"]]
            esc = (f" · escalated to agent mode: {sum(h['escalated'] for h in hy)} "
                   f"(agent answer kept for {sum(h.get('used') == 'agent' for h in hy)})")
        print(f"{counts}{esc} · numbers matching SEC data: {nc['matched']}/{nc['checked']} · ${meter.cost():.2f} -> {path.with_suffix('.md').relative_to(config.ROOT)}")

    elif a.cmd == "memo":
        t = _tickers(a.ticker, a.final)[0]
        from pathlib import Path
        runs = sorted(p for p in config.RUNS.glob(f"{t}_*.json") if not p.stem.endswith("_memo"))
        if not (a.run or runs):
            sys.exit(f"No checklist run for {t}. Run: ./fr run {t}")
        path = Path(a.run) if a.run else runs[-1]
        print(f"composing memo for {t} from {path.name} with {a.model} ...")
        r = memo.run(t, path, a.model, _effort(a.effort), do_check=not a.no_check, note=a.note)
        if r["check"]:
            c = r["check"]
            print(f"claim check: {len(c['unsupported'])}/{c['n_sentences']} sentences unsupported "
                  f"({c['unsupported_rate']}%), mechanical violations: {len(c['mechanical_violations'])}")
            for v in c["judged"]:
                if v["verdict"] != "supported":
                    print(f"  ⚠ sentence {v['n']}: {v['reason']}")
        print(f"${r['meta']['cost_usd']:.2f} -> {r['path'].relative_to(config.ROOT)}")

    elif a.cmd == "eval":
        tickers = evaluate.eval_tickers(a.final)
        if a.companies:
            tickers = [t for c in a.companies.split(",") for t in _tickers(c.strip(), a.final)]
        if a.only:
            # Debug path: run a subset without writing results or the changelog.
            ids = set(a.only.split(","))
            qs, meter, fn = checklist.by_id(), llm.CostMeter(), _answer_fn(a)
            for item in [i for i in golden.load(tickers) if i["id"] in ids]:
                r = fn(item["ticker"], qs[item["qid"]], index.Index(item["ticker"]), meter,
                       model=a.model, effort=_effort(a.effort), k=a.k, expand=a.expand)
                print(json.dumps({"id": item["id"], "expected": item["expected"], "status": r["status"],
                                  "answer": r["answer"], "value": r["value"], "citations": r["citations"],
                                  "retrieved": r["retrieved"], **({"agent": r["agent"]} if "agent" in r else {}),
                                  **({"hybrid": r["hybrid"]} if "hybrid" in r else {})},
                                 indent=2))
                if _uses_agent(r):
                    print(_agent_line(r))
                if "hybrid" in r:
                    print(_hybrid_line(r))
            print(f"cost ${meter.cost():.4f}")
            return
        if a.mode in ("agent", "hybrid"):  # measured runs kept apart from the pipeline's history
            ids = None
            if a.ids:
                from pathlib import Path
                raw = Path(a.ids[1:]).read_text().split() if a.ids.startswith("@") else a.ids.split(",")
                ids = {i.strip() for i in raw if i.strip()}
                known = {i["id"] for i in golden.load(tickers)}
                if ids - known:
                    sys.exit(f"Not golden ids for {', '.join(tickers)}: {', '.join(sorted(ids - known))}")
            elif not a.full and a.mode == "agent":
                sys.exit("A full agent-mode eval (80 items) is estimated at $4-6, above the $3 per-command cap. "
                         "Run a subset with --ids, or raise FILINGROOM_MAX_USD and pass --full.")
            elif not a.full:
                sys.exit("A full hybrid-mode eval (80 items) is estimated at about $3 with grading, at the $3 "
                         "per-command cap. Run a subset with --ids, or raise FILINGROOM_MAX_USD and pass --full.")
            evaluate.run(tickers, a.model, _effort(a.effort), a.k, a.expand, judge_model=a.judge_model,
                         label=a.label, note=a.note, workers=a.workers, use_judge=not a.no_judge, only=ids,
                         mode=a.mode, agent_opts=_agent_opts(a))
            return
        if a.ids or a.full:
            sys.exit("--ids and --full are for --mode agent or hybrid.")
        evaluate.run(tickers, a.model, _effort(a.effort), a.k, a.expand, judge_model=a.judge_model, label=a.label,
                     note=a.note, workers=a.workers, use_judge=not a.no_judge)

    elif a.cmd == "compare":
        c = evaluate.compare(json.loads(open(a.base).read()), json.loads(open(a.other).read()))
        md = evaluate.compare_md(c)
        print(md)
        if a.out:
            open(a.out, "w").write(md + "\n")

    elif a.cmd == "ui":
        from . import server
        server.serve(a.port, open_browser=not a.no_open)

    elif a.cmd == "retrieval":
        evaluate.retrieval_check(evaluate.eval_tickers(a.final), a.k, a.expand)
