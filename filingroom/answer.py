"""Answer checklist questions: retrieve -> ask the model for cited JSON -> verify every quote against its chunk."""

import re
import time
import unicodedata

from . import checklist, config, llm
from .index import Hit, Index

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_EFFORT = "medium"
DEFAULT_K = 8
DEFAULT_EXPAND = 2  # add the neighbors of the top-N hits (answers often sit just across a chunk boundary)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "not_found"]},
        "answer": {"type": "string"},
        "value": {"type": "string"},
        "unit": {"type": "string", "enum": ["USD", "percent", "count", ""]},
        "period": {"type": "string"},
        "citations": {"type": "array", "items": {
            "type": "object",
            "properties": {"chunk_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["chunk_id", "quote"], "additionalProperties": False}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["status", "answer", "value", "unit", "period", "citations", "confidence"],
    "additionalProperties": False,
}


def load_prompt(name: str) -> str:
    lines = (config.PROMPTS / name).read_text().splitlines()
    return "\n".join(l for l in lines if not l.startswith("<!--")).strip()


# ---------------------------------------------------------------- citation verification

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}))
    s = s.replace("$", "")  # currency symbols are formatting; tables often print them in some rows only
    s = re.sub(r"\s*\|\s*", " | ", s)
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote: str, chunk_text: str) -> bool:
    """True if the quote (allowing '...' elisions) appears in order in the chunk, whitespace/case-insensitive."""
    text = _norm(chunk_text)
    pos = 0
    for frag in re.split(r"\.\.\.|…", quote):
        frag = _norm(frag).strip(" |")
        if not frag:
            continue
        i = text.find(frag, pos)
        if i < 0:
            return False
        pos = i + len(frag)
    return pos > 0


def parse_value(v: str) -> float | None:
    if not v:
        return None
    s = v.replace(",", "").replace("$", "").replace("%", "").strip()
    if re.fullmatch(r"\(\s*[\d.]+\s*\)", s):
        s = "-" + s.strip("() ")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- answering

def _excerpt(c: dict) -> str:
    return (f'<excerpt chunk_id="{c["chunk_id"]}" filing="{c["ticker"]} {c["form"]} {c["period"]} '
            f'(filed {c["filing_date"]})" section="{c["heading"][:90]}" subsection="{c["subheading"][:90]}">\n'
            f'{c["text"]}\n</excerpt>')


def retrieve(ix: Index, q: dict, P: dict, k: int, expand: int = DEFAULT_EXPAND) -> list:
    query = f"{q['question']} {q.get('search', '')}"
    where = q.get("where", {})
    forms = where.get("forms")
    if forms and q.get("period") == "current":
        forms = sorted(set(forms) | {"10-Q", "8-K"})  # the latest fact can be in any recent filing
    hits = ix.search(query, k=k, forms=forms, topics=where.get("topics"),
                     periods=checklist.target_periods(q, P))
    if not expand:
        return hits
    out, seen = [], set()
    for i, h in enumerate(hits):
        group = [h]
        if i < expand:  # prev, hit, next: keeps the neighbors in reading order
            prev_next = ix.neighbors(h.chunk["chunk_id"])
            group = [Hit(0.0, c) for c in prev_next if c["chunk_id"] < h.chunk["chunk_id"]] + [h] + \
                    [Hit(0.0, c) for c in prev_next if c["chunk_id"] > h.chunk["chunk_id"]]
        for g in group:
            if g.chunk["chunk_id"] not in seen:
                seen.add(g.chunk["chunk_id"])
                out.append(g)
    return out


def answer_question(ticker: str, q: dict, ix: Index, meter: llm.CostMeter, model: str = DEFAULT_MODEL,
                    effort: str | None = DEFAULT_EFFORT, k: int = DEFAULT_K,
                    expand: int = DEFAULT_EXPAND) -> dict:
    co = config.company(ticker)
    P = checklist.periods(ticker)
    hits = retrieve(ix, q, P, k, expand)
    fye = co["fiscal_year_end"]
    user = (f"<question id=\"{q['id']}\">\n"
            f"Company: {co['name']} (ticker {ticker}); fiscal year ends {fye[:2]}/{fye[2:]}.\n"
            f"Question: {q['question']}\n"
            f"Answer type: {q['answer_type']}\n"
            f"Target period: {checklist.describe_period(q, P)}\n"
            f"</question>\n\n<excerpts>\n" + "\n\n".join(_excerpt(h.chunk) for h in hits) + "\n</excerpts>")
    t0 = time.time()
    try:
        out = llm.complete_json(model, load_prompt("answer.md"), user, ANSWER_SCHEMA, meter, effort=effort)
        error = None
    except llm.LLMError as e:
        out = {"status": "error", "answer": "", "value": "", "unit": "", "period": "", "citations": [],
               "confidence": "low"}
        error = str(e)

    # Mechanical citation check: a quote counts only if it appears in the chunk it names.
    for c in out["citations"]:
        chunk = ix.by_id.get(c["chunk_id"])
        c["verified"] = bool(chunk) and verify_quote(c["quote"], chunk["text"])
        if chunk:
            c["url"] = chunk["url"]
            c["doc_id"] = chunk["doc_id"]
            c["section"] = chunk["heading"][:90]
    n_ok = sum(c["verified"] for c in out["citations"])
    status = out["status"]
    if status == "answered" and n_ok == 0:
        status = "unsupported"  # answered, but no quote checks out: treat as an unsupported claim
    return {
        "qid": q["id"], "ticker": ticker, "question": q["question"], "category": q["category"],
        "status": status, "model_status": out["status"], "answer": out["answer"],
        "value": out["value"], "parsed_value": parse_value(out["value"]), "unit": out["unit"],
        "period": out["period"], "confidence": out["confidence"], "citations": out["citations"],
        "citations_verified": n_ok, "retrieved": [h.chunk["chunk_id"] for h in hits],
        "model": model, "effort": effort, "k": k, "expand": expand, "seconds": round(time.time() - t0, 1), "error": error,
    }
