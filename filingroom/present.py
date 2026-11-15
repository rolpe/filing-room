"""Presentation pass (app only): one cheap call per answered finding that turns the answer text and its verified
quotes into a short gist and 1-5 cited points. It never changes the answer and adds no facts:

  - the model sees only the answer and the quotes already verified against the filing;
  - a mechanical guard rejects any output with a new number, a cite to a quote it wasn't given, or bad lengths;
  - anything rejected or failed falls back to plain text built from the answer (`fallback`).

The answering prompt and pipeline are untouched; this runs after them, on their output.
"""

import re
from concurrent.futures import ThreadPoolExecutor

from . import answer, llm

MODEL = "claude-haiku-5-5"
EFFORT = "low"
NUMERIC_TYPES = {"currency", "percent", "count"}
MAX_GIST_WORDS = 12
MAX_POINTS = 5
MAX_LABEL_WORDS = 3


def _schema(with_label: bool) -> dict:
    props = {
        "gist": {"type": "string"},
        "points": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "cites": {"type": "array", "items": {"type": "integer"}}},
            "required": ["text", "cites"], "additionalProperties": False}},
    }
    if with_label:
        props["value_label"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def verified_quotes(row: dict) -> list[tuple[int, str]]:
    """(citation number, quote) for every verified quote; numbers are 1-based positions in the citation list."""
    return [(i + 1, c["quote"]) for i, c in enumerate(row.get("citations", [])) if c.get("verified")]


def eligible(row: dict) -> bool:
    return row.get("status") == "answered" and bool(verified_quotes(row))


def build_user(q: dict, row: dict) -> str:
    quotes = "\n".join(f"[{n}] {quote}" for n, quote in verified_quotes(row))
    want_label = q.get("answer_type") not in NUMERIC_TYPES
    return (f"<finding>\nLabel: {q.get('label', q['id'])}\nQuestion: {q['question']}\n"
            f"Answer: {row['answer']}\n" + (f"Period: {row['period']}\n" if row.get("period") else "") +
            f"</finding>\n\n<quotes>\n{quotes}\n</quotes>\n\n"
            + ("Include value_label." if want_label else "This is a numeric finding: no value_label."))


# ---------------------------------------------------------------- guard + fallback

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUM.finditer(text)}


def _haystack(row: dict) -> str:
    parts = [row.get("answer", ""), row.get("period", "")] + [q for _, q in verified_quotes(row)]
    return " ".join(parts).replace(",", "")


def guard(out: dict, row: dict, want_label: bool) -> str | None:
    """Why this output can't be shown, or None if it passes."""
    gist = (out.get("gist") or "").strip()
    points = out.get("points") or []
    label = (out.get("value_label") or "").strip() if want_label else ""
    if not gist or len(gist.split()) > MAX_GIST_WORDS:
        return "gist missing or too long"
    if not 1 <= len(points) <= MAX_POINTS:
        return "wrong number of points"
    allowed = {n for n, _ in verified_quotes(row)}
    for p in points:
        if not p.get("text", "").strip():
            return "empty point"
        if not p.get("cites") or any(c not in allowed for c in p["cites"]):
            return "point cites a quote it was not given"
    if label and len(label.split()) > MAX_LABEL_WORDS:
        return "value label too long"
    hay = _haystack(row)
    for text in [gist, label] + [p["text"] for p in points]:
        for num in _numbers(text):
            if num not in hay:
                return f"number {num} is not in the answer or its quotes"
    return None


_SENTENCE_END = re.compile(r"(?<=[A-Za-z0-9%)\]]{2}[.!?])\s+(?=[A-Z(\"“])")  # "U.S. Bank" stays whole


def first_sentence(text: str) -> str:
    """The answer's first sentence; a bare "Yes." or "No." takes the next sentence along so the gist says something."""
    text = (text or "").strip()
    if not text:
        return ""
    parts = _SENTENCE_END.split(text, maxsplit=2)
    if len(parts) > 1 and len(parts[0].split()) <= 3:
        return f"{parts[0]} {parts[1]}"
    return parts[0]


def fallback(row: dict) -> dict:
    """Shown when there is no presentation output: the answer's first sentence and the answer as one cited point."""
    cites = [n for n, _ in verified_quotes(row)]
    answer_text = (row.get("answer") or "").strip()
    return {"gist": first_sentence(answer_text), "points": [{"text": answer_text, "cites": cites}] if answer_text else [],
            "value_label": "", "presented": False}


def clean(out: dict, want_label: bool) -> dict:
    return {"gist": out["gist"].strip().rstrip("."),
            "points": [{"text": p["text"].strip(), "cites": sorted(set(p["cites"]))} for p in out["points"]],
            "value_label": (out.get("value_label") or "").strip() if want_label else "", "presented": True}


# ---------------------------------------------------------------- calls

def present_one(q: dict, row: dict, meter: llm.CostMeter, complete=llm.complete_json) -> dict:
    """Presentation for one finding; {"presented": False, ...} with a reason when it fell back."""
    if not eligible(row):
        return {**fallback(row), "reason": "not answered with a verified quote"}
    want_label = q.get("answer_type") not in NUMERIC_TYPES
    try:
        out = complete(MODEL, answer.load_prompt("present.md"), build_user(q, row), _schema(want_label), meter,
                       effort=EFFORT, max_tokens=4000)
    except llm.LLMError as e:
        return {**fallback(row), "reason": str(e)}
    except SystemExit:
        raise  # spend limits stop the whole job
    except Exception as e:  # network or API errors: show the plain answer instead
        return {**fallback(row), "reason": f"{e.__class__.__name__}: {e}"[:200]}
    why = guard(out, row, want_label)
    return {**fallback(row), "reason": why} if why else clean(out, want_label)


def present_all(qs: list[dict], rows: list[dict], meter: llm.CostMeter, workers: int = 6,
                complete=llm.complete_json) -> dict:
    """Run the pass over every eligible answer. Result is stored as the company's present.json."""
    by_id = {q["id"]: q for q in qs}
    todo = [r for r in rows if r["qid"] in by_id and eligible(r)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outs = list(pool.map(lambda r: present_one(by_id[r["qid"]], r, meter, complete), todo))
    items = {r["qid"]: o for r, o in zip(todo, outs)}
    return {"model": MODEL, "items": items, "attempted": len(todo),
            "fallbacks": sum(not o["presented"] for o in outs)}
