"""Findings: checklist answers presented as labelled facts with a derived status, plus the filing passages behind them.

Status is derived from the answer, never asked of the model:
  not_disclosed  the filings don't answer it (`not_found`)
  verified       answered and every quote string-verified, confidence not low, no mismatch with SEC data
  review         anything else (unsupported, error, an unverified quote, low confidence, SEC mismatch)
A person can clear a `review` finding after checking it (`reviewed_at`); it then shows as verified with the machine
reasons still listed. A user flag always forces `review` and wins over reviewed.
"""

import csv
import io
import re

from . import present

FORM_LABELS = {"10-K": "Annual report (10-K)", "10-Q": "Quarterly report (10-Q)",
               "DEF 14A": "Proxy statement (DEF 14A)", "8-K": "Earnings release (8-K, Ex. 99.1)"}
NUMERIC_TYPES = {"currency", "percent", "count"}


# ---------------------------------------------------------------- status

def machine_reasons(row: dict | None, sec: dict | None) -> list[str]:
    if row is None:
        return ["Not answered yet"]
    st = row.get("status")
    if st == "error":
        return ["The question could not be answered (model error)"]
    if st == "not_found":
        return []
    cits = row.get("citations", [])
    n_ok = sum(bool(c.get("verified")) for c in cits)
    out = []
    if st == "unsupported" or (cits and n_ok == 0):
        out.append("No quote could be found in the filing")
    elif n_ok < len(cits):
        out.append(f"{len(cits) - n_ok} of {len(cits)} quotes not found in the filing")
    elif not cits:
        out.append("No quote given")
    if row.get("confidence") == "low":
        out.append("Low confidence")
    if sec and sec.get("match") is False:
        out.append("Differs from SEC structured data")
    return out


def derive_status(row: dict | None, sec: dict | None = None, ann: dict | None = None) -> dict:
    """{status, reasons, reviewed_at, flagged}."""
    ann = ann or {}
    reasons = machine_reasons(row, sec)
    flagged = bool(ann.get("flagged"))
    reviewed = ann.get("reviewed_at")
    if flagged:
        return {"status": "review", "reasons": ["Flagged for review"] + reasons, "reviewed_at": None, "flagged": True}
    if row is not None and row.get("status") == "not_found":
        return {"status": "not_disclosed", "reasons": [], "reviewed_at": None, "flagged": False}
    if not reasons:
        return {"status": "verified", "reasons": [], "reviewed_at": None, "flagged": False}
    if reviewed and row is not None:
        return {"status": "verified", "reasons": reasons, "reviewed_at": reviewed, "flagged": False}
    return {"status": "review", "reasons": reasons, "reviewed_at": None, "flagged": False}


# ---------------------------------------------------------------- display helpers

def doc_meta(manifest: list[dict]) -> dict[str, dict]:
    return {d["doc_id"]: d for d in manifest}


def short_period(form: str, period: str) -> str:
    return period.replace(" annual meeting", "") if form == "DEF 14A" else period


def source_label(row: dict, docs: dict[str, dict]) -> str:
    c = next((c for c in row.get("citations", []) if c.get("verified")), None)
    d = docs.get(c.get("doc_id")) if c else None
    return f"{d['form']} {short_period(d['form'], d['period'])}" if d else ""


def numeric_value(q: dict, row: dict | None) -> float | None:
    if not row or row.get("status") != "answered" or q.get("answer_type") not in NUMERIC_TYPES:
        return None
    v = row.get("parsed_value")
    return float(v) if isinstance(v, (int, float)) else None


def short_period_text(p: str) -> str:
    """'FY2026 (fiscal year ended 2026-06-30)' -> 'FY2026'; keeps phrases like 'as of 2026-06-30'."""
    p = (p or "").strip()
    return re.split(r"\s+\(", p, maxsplit=1)[0] if p else ""


def visible(qs: list[dict]) -> list[dict]:
    return sorted([q for q in qs if not q.get("hidden")], key=lambda q: q.get("order", 999))


GROUP_ORDER = ["Ownership and governance", "Capital structure and allocation", "Revenue and customers",
               "Profitability and cash flow", "People", "Competition and risk"]


# ---------------------------------------------------------------- list rows + detail

def finding_row(q: dict, row: dict | None, pres: dict | None, sec: dict | None, ann: dict | None,
                docs: dict[str, dict]) -> dict:
    st = derive_status(row, sec, ann)
    p = pres if pres and pres.get("presented") else (present.fallback(row) if row else None)
    nv = numeric_value(q, row)
    return {
        "qid": q["id"], "label": q.get("label", q["id"]), "group": q.get("group", ""), "order": q.get("order", 999),
        "answer_type": q.get("answer_type"), **st,
        "gist": (p or {}).get("gist", "") if st["status"] != "not_disclosed" else (
            present.first_sentence(row.get("answer", "")) if row else ""),
        "value": nv, "unit": (row or {}).get("unit") if nv is not None else None,
        "value_label": (p or {}).get("value_label", "") if nv is None else "",
        "source": source_label(row, docs) if row and st["status"] != "not_disclosed" else "",
        "has_note": bool((ann or {}).get("note")),
    }


def citation_view(i: int, c: dict, docs: dict[str, dict]) -> dict:
    d = docs.get(c.get("doc_id"), {})
    return {"n": i + 1, "chunk_id": c.get("chunk_id"), "quote": c.get("quote", ""), "verified": bool(c.get("verified")),
            "doc_id": c.get("doc_id"), "form": d.get("form"), "period": d.get("period"),
            "filing_date": d.get("filing_date"), "section": c.get("section", ""), "url": c.get("url") or d.get("url")}


def finding_detail(q: dict, row: dict | None, pres: dict | None, sec: dict | None, ann: dict | None,
                   docs: dict[str, dict]) -> dict:
    base = finding_row(q, row, pres, sec, ann, docs)
    p = pres if pres and pres.get("presented") else (present.fallback(row) if row else {"points": []})
    cits = [citation_view(i, c, docs) for i, c in enumerate((row or {}).get("citations", []))]
    n_ok = sum(c["verified"] for c in cits)
    ann = ann or {}
    return {
        **base, "question": q["question"], "answer": (row or {}).get("answer", ""),
        "presented": bool(pres and pres.get("presented")), "points": p.get("points", []),
        "citations": cits,
        "facts": {"quotes_found": f"{n_ok} of {len(cits)}" if cits else None,
                  "period": short_period_text((row or {}).get("period", "")),
                  "period_full": (row or {}).get("period", ""),
                  "confidence": (row or {}).get("confidence"),
                  "sec_check": sec and {"match": sec.get("match"), "expected": sec.get("expected", {}).get("value"),
                                        "period": sec.get("expected", {}).get("period"),
                                        "concepts": sec.get("source", {}).get("concepts")}},
        "note": {"text": ann["note"], "at": ann.get("note_at")} if ann.get("note") else None,
        "flagged_at": ann.get("flagged_at"),
    }


def group_rows(rows: list[dict]) -> list[dict]:
    groups = []
    for g in GROUP_ORDER + sorted({r["group"] for r in rows} - set(GROUP_ORDER)):
        items = [r for r in rows if r["group"] == g]
        if items:
            groups.append({"name": g, "items": items})
    return groups


def counts(rows: list[dict]) -> dict:
    c = {"total": len(rows), "verified": 0, "review": 0, "not_disclosed": 0}
    for r in rows:
        c[r["status"]] += 1
    return c


# ---------------------------------------------------------------- passages

_QUOTE_MAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _norm_index(text: str) -> tuple[str, list[int]]:
    """Lowercase, unify quotes/dashes, drop whitespace, '$' and '|'; keep a map back to original offsets."""
    chars, idx = [], []
    for i, ch in enumerate(text.translate(_QUOTE_MAP)):
        if ch.isspace() or ch in "$|":
            continue
        chars.append(ch.lower())
        idx.append(i)
    return "".join(chars), idx


def quote_spans(text: str, quote: str) -> list[tuple[int, int]]:
    """Where a (possibly '...'-elided) quote sits in the text, as original-offset spans; [] if not found."""
    norm, idx = _norm_index(text)
    spans, pos = [], 0
    for frag in re.split(r"\.\.\.|…", quote):
        f, _ = _norm_index(frag)
        if len(f) < 3:
            continue
        i = norm.find(f, pos)
        if i < 0:
            return []
        spans.append((idx[i], idx[i + len(f) - 1] + 1))
        pos = i + len(f)
    return spans


def _marks(start: int, end: int, spans: list[tuple[int, int, int]]) -> list[dict]:
    """Spans clipped to [start, end), relative to start."""
    out = []
    for s, e, n in spans:
        a, b = max(s, start), min(e, end)
        if a < b:
            out.append({"start": a - start, "end": b - start, "cite": n})
    return out


def passage(chunk: dict, quotes: list[tuple[int, str]]) -> dict:
    """The chunk as paragraphs and tables, with every given quote's position as marks. quotes: (cite number, text)."""
    text = chunk["text"]
    spans = [(s, e, n) for n, q in quotes for s, e in quote_spans(text, q)]
    blocks, pos, table = [], 0, None
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        if line == "[TABLE]":
            table = {"type": "table", "rows": []}
            blocks.append(table)
            continue
        if line == "[/TABLE]":
            table = None
            continue
        if not line.strip():
            continue
        if table is not None:
            cells, cpos = [], start
            for cell in line.split(" | "):
                cells.append({"text": cell, "marks": _marks(cpos, cpos + len(cell), spans)})
                cpos += len(cell) + 3
            table["rows"].append(cells)
        else:
            blocks.append({"type": "p", "text": line, "marks": _marks(start, start + len(line), spans)})
    return {"blocks": blocks, "found": sorted({n for _, _, n in spans})}


# ---------------------------------------------------------------- memo

def memo_view(m: dict, rows: list[dict], qs_by_id: dict[str, dict]) -> dict:
    """Memo with footnote numbers: each distinct cited finding gets a number in order of first use."""
    by_qid = {r["qid"]: r for r in rows}
    usable = {r["qid"] for r in rows if r["status"] == "answered" and r.get("citations_verified", 0) > 0}
    order: list[str] = []
    for s in m["memo"]["sections"]:
        for x in s["sentences"]:
            for r in x["refs"]:
                if r in usable and r not in order:
                    order.append(r)
    num = {qid: i + 1 for i, qid in enumerate(order)}
    chk = m.get("check") or {}
    flagged = set(chk.get("unsupported", []))
    reasons = {v["n"]: v.get("reason", "") for v in chk.get("judged", []) if v.get("verdict") == "unsupported"}
    for mv in chk.get("mechanical_violations", []):
        reasons.setdefault(mv["n"], mv["problem"])
    n, sections = 0, []
    for s in m["memo"]["sections"]:
        sents = []
        for x in s["sentences"]:
            sents.append({"n": n, "text": x["text"], "kind": x["kind"],
                          "notes": [num[r] for r in x["refs"] if r in num],
                          "flagged": n in flagged, "reason": reasons.get(n, "") if n in flagged else ""})
            n += 1
        sections.append({"heading": s["heading"], "sentences": sents})
    title = re.sub(r"\s+[—-]\s+Preliminary Diligence Memo$", "", m["memo"]["title"])
    return {"title": title, "generated": m["meta"].get("timestamp"), "model": m["meta"].get("model"),
            "sections": sections, "open_questions": m["memo"].get("open_questions", []),
            "notes": [_memo_note(num[q], q, qs_by_id, by_qid) for q in order],
            "check": {"sentences": chk.get("n_sentences"), "flagged": len(flagged)} if chk else None}


def _memo_note(n: int, qid: str, qs_by_id: dict, by_qid: dict) -> dict:
    """A footnote: the finding it points to and its first verified quote (for print and export)."""
    r = by_qid.get(qid, {})
    c = next((c for c in r.get("citations", []) if c.get("verified")), {})
    return {"n": n, "qid": qid, "label": qs_by_id.get(qid, {}).get("label", qid), "quote": c.get("quote", ""),
            "doc_id": c.get("doc_id", ""), "url": c.get("url", ""),
            "section": "" if c.get("section") in ("proxy", "press_release") else c.get("section", "")}


def memo_markdown(name: str, ticker: str, mv: dict, rows: list[dict]) -> str:
    by = {r["qid"]: r for r in rows}
    lines = [f"# {mv['title']}", "", f"Screening memo · {name} ({ticker}) · from public SEC filings only", ""]
    for s in mv["sections"]:
        lines += [f"## {s['heading']}", ""]
        para = []
        for x in s["sentences"]:
            refs = "".join(f"[^{k}]" for k in x["notes"])
            para.append(x["text"] + refs + (" (flagged: not fully supported)" if x["flagged"] else ""))
        lines += [" ".join(para), ""]
    if mv["open_questions"]:
        lines += ["## Open questions", ""] + [f"- {q}" for q in mv["open_questions"]] + [""]
    for note in mv["notes"]:
        r = by.get(note["qid"], {})
        c = next((c for c in r.get("citations", []) if c.get("verified")), {})
        lines.append(f"[^{note['n']}]: {note['label']}. \"{c.get('quote', '')}\" {c.get('doc_id', '')}, "
                     f"{c.get('section', '')}. {c.get('url', '')}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- CSV export

def findings_csv(ticker: str, details: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ticker", "group", "finding", "status", "value", "unit", "period", "summary", "answer", "reasons",
                "note", "quote", "quote_found_in_filing", "filing", "section", "source_url"])
    status_label = {"verified": "Verified", "review": "To review", "not_disclosed": "Not disclosed"}
    for d in details:
        base = [ticker, d["group"], d["label"], status_label[d["status"]],
                "" if d["value"] is None else f"{d['value']:g}" if d["unit"] != "USD" else f"{d['value']:.0f}",
                d["unit"] or "", d["facts"]["period_full"], d["gist"], d["answer"], "; ".join(d["reasons"]),
                (d["note"] or {}).get("text", "")]
        cits = d["citations"] or [None]
        for c in cits:
            w.writerow(base + ([c["quote"], "yes" if c["verified"] else "no", c["doc_id"] or "", c["section"],
                                c["url"] or ""] if c else ["", "", "", "", ""]))
    return buf.getvalue()
