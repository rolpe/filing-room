"""filing-room CLI. Run ./fr --help."""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import answer, checklist, config, edgar, evaluate, golden, index, llm, parse, report


def _tickers(arg: str, final: bool, allow_holdout: bool = False) -> list[str]:
    cos = config.companies()
    if arg.lower() == "all":
        return [t for t, c in cos.items() if final or c["split"] == "tune"]
    t = config.company(arg)["ticker"]
    if cos[t]["split"] == "holdout" and not (final or allow_holdout):
        sys.exit(f"{t} is the held-out company. Pass --final to use it (only for the final report).")
    return [t]


def _model_args(p):
    p.add_argument("--model", default=answer.DEFAULT_MODEL)
    p.add_argument("--effort", default=answer.DEFAULT_EFFORT, help="low|medium|high|xhigh|max, or 'none'")
    p.add_argument("--k", type=int, default=answer.DEFAULT_K, help="chunks retrieved per question")


def _effort(e: str) -> str | None:
    return None if e == "none" else e


def main() -> None:
    ap = argparse.ArgumentParser(prog="fr", description="Diligence checklist agent over SEC filings.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, help_ in [("fetch", "download filings from EDGAR (cached)"), ("parse", "HTML -> sectioned text"),
                        ("index", "chunk + BM25 index"), ("build", "fetch + parse + index")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("ticker", help="ticker or 'all'")
        p.add_argument("--final", action="store_true", help="include the held-out company in 'all'")

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

    p = sub.add_parser("run", help="answer the full checklist -> runs/<TICKER>_<time>.md/.json")
    p.add_argument("ticker")
    p.add_argument("--final", action="store_true")
    p.add_argument("--workers", type=int, default=6)
    _model_args(p)

    p = sub.add_parser("eval", help="answer + grade the golden set; writes results/ and CHANGELOG-evals.md")
    p.add_argument("--final", action="store_true", help="include the held-out company")
    p.add_argument("--label", default="", help="short name for this run, e.g. 'k12'")
    p.add_argument("--note", default="", help="what changed since the last run")
    p.add_argument("--judge-model", default=evaluate.JUDGE_MODEL)
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--only", help="comma-separated golden ids to run (for debugging; not logged)")
    _model_args(p)

    p = sub.add_parser("retrieval", help="LLM-free check: is the golden number in the top-k chunks?")
    p.add_argument("--final", action="store_true")
    p.add_argument("--k", type=int, default=answer.DEFAULT_K)

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

    elif a.cmd == "golden":
        items = golden.build(evaluate.eval_tickers(a.final))
        print(f"{len(items)} golden items -> {config.GOLDEN.relative_to(config.ROOT)}")

    elif a.cmd == "search":
        ix = index.Index(config.company(a.ticker)["ticker"])
        for h in ix.search(a.query, k=a.k, forms=a.form):
            c = h.chunk
            print(f"\n{h.score:6.1f}  {c['chunk_id']}  [{c['subheading'][:60]}]")
            print(c["text"] if a.full else c["text"][:300].replace("\n", " ⏎ "))

    elif a.cmd == "ask":
        t = _tickers(a.ticker, a.final)[0]
        qs = checklist.by_id()
        q = qs.get(a.question) or {"id": "adhoc", "category": "Ad hoc", "question": a.question,
                                   "answer_type": "text", "period": "current", "where": {}}
        meter = llm.CostMeter()
        r = answer.answer_question(t, q, index.Index(t), meter, model=a.model, effort=_effort(a.effort), k=a.k)
        print(json.dumps({k: r[k] for k in ("status", "answer", "value", "unit", "period", "confidence",
                                            "citations", "error")}, indent=2))
        print(f"cost ${meter.cost():.4f}")

    elif a.cmd == "run":
        t = _tickers(a.ticker, a.final)[0]
        ix, meter = index.Index(t), llm.CostMeter()
        qs = checklist.load()
        print(f"answering {len(qs)} questions for {t} with {a.model} ...")
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            rows = list(pool.map(lambda q: answer.answer_question(t, q, ix, meter, model=a.model,
                                                                  effort=_effort(a.effort), k=a.k), qs))
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        meta = {"timestamp": stamp, "model": a.model, "cost_usd": meter.cost(),
                "n_filings": len(edgar.manifest(t)), "usage": meter.summary()}
        config.RUNS.mkdir(exist_ok=True)
        (config.RUNS / f"{t}_{stamp}.json").write_text(json.dumps({"meta": meta, "answers": rows}, indent=1))
        (config.RUNS / f"{t}_{stamp}.md").write_text(report.checklist_md(t, rows, meta))
        counts = {s: sum(r["status"] == s for r in rows) for s in ("answered", "not_found", "unsupported", "error")}
        print(f"{counts} · ${meter.cost():.2f} -> runs/{t}_{stamp}.md")

    elif a.cmd == "eval":
        tickers = evaluate.eval_tickers(a.final)
        if a.only:
            # Debug path: run a subset without writing results or the changelog.
            ids = set(a.only.split(","))
            qs, meter = checklist.by_id(), llm.CostMeter()
            for item in [i for i in golden.load(tickers) if i["id"] in ids]:
                r = answer.answer_question(item["ticker"], qs[item["qid"]], index.Index(item["ticker"]), meter,
                                           model=a.model, effort=_effort(a.effort), k=a.k)
                print(json.dumps({"id": item["id"], "expected": item["expected"], "status": r["status"],
                                  "answer": r["answer"], "value": r["value"], "citations": r["citations"],
                                  "retrieved": r["retrieved"]}, indent=2))
            print(f"cost ${meter.cost():.4f}")
            return
        evaluate.run(tickers, a.model, _effort(a.effort), a.k, judge_model=a.judge_model, label=a.label,
                     note=a.note, workers=a.workers, use_judge=not a.no_judge)

    elif a.cmd == "retrieval":
        evaluate.retrieval_check(evaluate.eval_tickers(a.final), a.k)
