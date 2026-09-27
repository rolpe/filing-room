"""IC-style memo composed only from answered checklist items, plus an unsupported-claim check.

Every sentence comes back as structured data with the checklist ids it relies on, so the check is:
  1. mechanical — fact sentences must cite at least one id, and only ids that were answered with a verified quote;
  2. judged    — one judge call reads each sentence against the answers it cites.
"""

import json

from . import answer, config, llm

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "medium"
CHECK_MODEL = "claude-opus-5"

MEMO_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "heading": {"type": "string"},
                "sentences": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "kind": {"type": "string", "enum": ["fact", "judgment"]},
                        "refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "kind", "refs"], "additionalProperties": False}},
            },
            "required": ["heading", "sentences"], "additionalProperties": False}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "sections", "open_questions"],
    "additionalProperties": False,
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "verdict": {"type": "string", "enum": ["supported", "unsupported"]},
            "reason": {"type": "string"},
        },
        "required": ["n", "verdict", "reason"], "additionalProperties": False}}},
    "required": ["verdicts"],
    "additionalProperties": False,
}

CHECK_SYSTEM = """You audit an investment memo for unsupported claims. Each numbered sentence lists the checklist answers it cites; each answer comes with the verified filing quotes behind it.

For each sentence, verdict "supported" if every fact it states (numbers, dates, names, events, comparisons, characterizations like "declined" or "largest") follows from the cited answers, allowing for reasonable rounding and simple arithmetic on cited figures. Verdict "unsupported" if it states any fact the cited answers don't establish, misstates a number or period, or cites nothing while stating a fact. Judgment sentences (opinions, implications) are "supported" as long as they don't slip in new facts. Give a short reason for every "unsupported"."""


def usable(rows: list[dict]) -> dict[str, dict]:
    """Checklist answers the memo may rely on: answered, with at least one verified quote."""
    return {r["qid"]: r for r in rows if r["status"] == "answered" and r["citations_verified"] > 0}


def compose(ticker: str, rows: list[dict], meter: llm.CostMeter, model: str = DEFAULT_MODEL,
            effort: str | None = DEFAULT_EFFORT) -> dict:
    co = config.company(ticker)
    ok = usable(rows)
    facts = "\n".join(f"[{qid}] ({r['category']}) {r['question']}\n    Answer: {r['answer']}"
                      + (f" (period: {r['period']})" if r["period"] else "") for qid, r in ok.items())
    missing = "\n".join(f"[{r['qid']}] {r['question']}" for r in rows if r["qid"] not in ok)
    user = (f"Company: {co['name']} (ticker {ticker}).\n\n<checklist_answers>\n{facts}\n</checklist_answers>\n\n"
            f"<not_found_in_filings>\n{missing or '(none)'}\n</not_found_in_filings>")
    return llm.complete_json(model, answer.load_prompt("memo.md"), user, MEMO_SCHEMA, meter, effort=effort,
                             max_tokens=16000)


def check(memo: dict, rows: list[dict], meter: llm.CostMeter, model: str = CHECK_MODEL) -> dict:
    ok = usable(rows)
    sentences = [(s["heading"], x) for s in memo["sections"] for x in s["sentences"]]
    mechanical = []
    for n, (_, x) in enumerate(sentences):
        bad = [r for r in x["refs"] if r not in ok]
        if x["kind"] == "fact" and not x["refs"]:
            mechanical.append({"n": n, "problem": "fact sentence cites nothing"})
        elif bad:
            mechanical.append({"n": n, "problem": f"cites ids that aren't verified answers: {bad}"})
    cited = sorted({r for _, x in sentences for r in x["refs"] if r in ok})
    evidence = "\n\n".join(
        f"[{qid}] {ok[qid]['answer']}\n" + "\n".join(f"    quote: {c['quote']}" for c in ok[qid]["citations"]
                                                  if c["verified"]) for qid in cited)
    numbered = "\n".join(f"{n}. ({x['kind']}; cites {', '.join(x['refs']) or 'nothing'}) {x['text']}"
                         for n, (_, x) in enumerate(sentences))
    user = f"<answers>\n{evidence}\n</answers>\n\n<memo_sentences>\n{numbered}\n</memo_sentences>"
    verdicts = llm.complete_json(model, CHECK_SYSTEM, user, CHECK_SCHEMA, meter, effort="low")["verdicts"]
    by_n = {v["n"]: v for v in verdicts}
    facts_n = [n for n, (_, x) in enumerate(sentences) if x["kind"] == "fact"]
    mech_n = {m["n"] for m in mechanical}
    unsupported = sorted({n for n, v in by_n.items() if v["verdict"] == "unsupported"} | mech_n)
    return {
        "n_sentences": len(sentences), "n_fact_sentences": len(facts_n),
        "mechanical_violations": mechanical,
        "judged": [by_n.get(n, {"n": n, "verdict": "missing", "reason": "judge skipped"})
                   for n in range(len(sentences))],
        "unsupported": unsupported,
        "unsupported_rate": round(100 * len(unsupported) / max(len(sentences), 1), 1),
    }


def render_md(ticker: str, memo: dict, rows: list[dict], chk: dict | None, meta: dict) -> str:
    ok = usable(rows)
    order = []
    for s in memo["sections"]:
        for x in s["sentences"]:
            for r in x["refs"]:
                if r in ok and r not in order:
                    order.append(r)
    num = {qid: i + 1 for i, qid in enumerate(order)}
    flagged = set(chk["unsupported"]) if chk else set()
    lines = [f"# {memo['title']}", "",
             f"_Preliminary, from public SEC filings only. Generated {meta['timestamp']} · model `{meta['model']}`. "
             "Bracketed numbers point to the checklist answer and filing quote behind each statement._", ""]
    n = 0
    for s in memo["sections"]:
        lines += [f"## {s['heading']}", ""]
        para = []
        for x in s["sentences"]:
            refs = "".join(f"[{num[r]}]" for r in x["refs"] if r in num)
            flag = " ⚠️" if n in flagged else ""
            para.append(f"{x['text']}{refs}{flag}")
            n += 1
        lines += [" ".join(para), ""]
    if memo["open_questions"]:
        lines += ["## Open diligence questions", ""] + [f"- {q}" for q in memo["open_questions"]] + [""]
    if chk:
        lines += [f"_Claim check: {len(chk['unsupported'])} of {chk['n_sentences']} sentences flagged unsupported "
                  f"(⚠️). {chk['n_fact_sentences']} sentences state facts._", ""]
    lines += ["## Sources", ""]
    for qid in order:
        r = ok[qid]
        c = next(c for c in r["citations"] if c["verified"])
        lines.append(f"{num[qid]}. **{qid}**: {r['answer']}  \n   > “{c['quote']}” "
                     f"([{c['doc_id']} · {c['section'][:50]}]({c['url']}))")
    return "\n".join(lines) + "\n"


def run(ticker: str, run_path, model: str, effort: str | None, do_check: bool = True, note: str = "",
        log: bool = True, meter: llm.CostMeter | None = None) -> dict:
    data = json.loads(run_path.read_text())
    rows = data["answers"]
    meter = meter or llm.CostMeter()
    start = meter.cost()  # a shared meter (UI runs) already holds the answering cost
    memo = compose(ticker, rows, meter, model=model, effort=effort)
    chk = check(memo, rows, meter) if do_check else None
    stamp = run_path.stem.split("_", 1)[1]
    meta = {"timestamp": stamp, "model": model, "source_run": run_path.name, "cost_usd": round(meter.cost() - start, 4)}
    out = config.RUNS / f"{ticker}_{stamp}_memo"
    out.with_suffix(".json").write_text(json.dumps({"meta": meta, "memo": memo, "check": chk}, indent=1))
    out.with_suffix(".md").write_text(render_md(ticker, memo, rows, chk, meta))
    if chk and log:
        log_check(ticker, meta, chk, note)
    return {"meta": meta, "memo": memo, "check": chk, "path": out.with_suffix(".md")}


def log_check(ticker: str, meta: dict, chk: dict, note: str) -> None:
    """Memo claim checks go in results/ and get a row in CHANGELOG-evals.md (Unsupported % column)."""
    from datetime import datetime

    from .evaluate import CHANGELOG
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    config.RESULTS.mkdir(exist_ok=True)
    (config.RESULTS / f"{stamp}_memo_{ticker}.json").write_text(
        json.dumps({"meta": meta, "note": note, "check": chk}, indent=1))
    with open(CHANGELOG, "a") as f:
        f.write(f"| {stamp} memo | {ticker} | {note or '-'} ({meta['model']}) | – | – | "
                f"{chk['unsupported_rate']} ({len(chk['unsupported'])}/{chk['n_sentences']} sentences) | – | – | "
                f"{meta['cost_usd']} |\n")
