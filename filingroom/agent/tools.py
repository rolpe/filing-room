"""The agent's three read-only tools, bound in code to one company's filings. No framework import.

Each tool is a plain function that takes the company's loaded Index (and, for list_filings, its manifest and
resolved periods), the tool's arguments as the model sent them, and the ids of chunks already shown in this
question. It returns a ToolResult: the text the model reads, and which chunk ids it showed. A bad argument is an
error result the model can read and correct, never an exception.

Chunks are rendered with answer._excerpt, the same wrapper the pipeline uses, so a chunk looks identical to the
model in both modes and the quoting rules in the prompt carry over.
"""

from dataclasses import dataclass, field

from ..answer import _excerpt
from ..index import Index

K_DEFAULT, K_MAX = 5, 8


@dataclass
class ToolResult:
    text: str
    shown: list[str] = field(default_factory=list)  # chunk ids whose full text this result showed
    refs: list[str] = field(default_factory=list)   # every chunk id this result named (shown or "already shown")
    is_error: bool = False


def _error(msg: str) -> ToolResult:
    return ToolResult(text=f"Error: {msg}", is_error=True)


def valid_values(ix: Index) -> dict[str, list[str]]:
    """The forms, topics and periods present in this index. Index.search matches them by exact string."""
    return {"forms": sorted({c["form"] for c in ix.chunks}), "topics": sorted({c["topic"] for c in ix.chunks}),
            "periods": sorted({c["period"] for c in ix.chunks})}


def _string_list(args: dict, name: str, allowed: list[str]) -> tuple[list[str] | None, str | None]:
    v = args.get(name)
    if v is None or v == []:
        return None, None
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        return None, f"`{name}` must be a list of strings. Valid values: {', '.join(allowed)}."
    bad = [x for x in v if x not in allowed]
    if bad:
        return None, f"unknown {name} {', '.join(repr(x) for x in bad)}. Valid values: {', '.join(allowed)}."
    return v, None


def _render(c: dict, seen: set[str], label: str, out: ToolResult) -> str:
    cid = c["chunk_id"]
    out.refs.append(cid)
    if cid in seen:
        return f"{label}: chunk {cid} was already shown earlier in this conversation (text not repeated)."
    seen.add(cid)
    out.shown.append(cid)
    return f"{label}:\n{_excerpt(c)}"


# ---------------------------------------------------------------- search_filings

def search_filings(ix: Index, args: dict, seen: set[str]) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return _error("`query` is required: a few words to search for.")
    vv = valid_values(ix)
    forms, err = _string_list(args, "forms", vv["forms"])
    if err:
        return _error(err)
    topics, err = _string_list(args, "topics", vv["topics"])
    if err:
        return _error(err)
    periods, err = _string_list(args, "periods", vv["periods"])
    if err:
        return _error(err)
    k = args.get("k", K_DEFAULT)
    if isinstance(k, bool) or not isinstance(k, (int, float)):
        return _error(f"`k` must be a whole number from 1 to {K_MAX}.")
    k = max(1, min(K_MAX, int(k)))
    hits = ix.search(query, k=k, forms=forms, topics=topics, periods=periods)
    if not hits:
        return ToolResult(text=f"No results for {query!r} with these filters. Try other words or fewer filters.")
    out = ToolResult(text="")
    seen = set(seen)
    parts = [f"{len(hits)} results for {query!r}, best first."]
    for i, h in enumerate(hits, 1):
        parts.append(_render(h.chunk, seen, f"Result {i} (score {h.score:.1f})", out))
    out.text = "\n\n".join(parts)
    return out


# ---------------------------------------------------------------- get_chunk

def get_chunk(ix: Index, args: dict, seen: set[str]) -> ToolResult:
    cid = args.get("chunk_id")
    if not isinstance(cid, str) or cid not in ix.by_id:
        return _error(f"no chunk with id {cid!r}. Use a chunk_id exactly as it appears in a search result.")
    n = args.get("neighbors", 1)
    if n not in (0, 1) or isinstance(n, bool):
        return _error("`neighbors` must be 0 or 1.")
    group = [ix.by_id[cid]]
    if n:
        nb = ix.neighbors(cid)
        group = [c for c in nb if c["chunk_id"] < cid] + group + [c for c in nb if c["chunk_id"] > cid]
    out = ToolResult(text="")
    seen = set(seen)
    parts = []
    for c in group:
        label = "Requested chunk" if c["chunk_id"] == cid else (
            "Chunk before it" if c["chunk_id"] < cid else "Chunk after it")
        parts.append(_render(c, seen, label, out))
    out.text = "\n\n".join(parts)
    return out


# ---------------------------------------------------------------- list_filings

def list_filings(ix: Index, manifest: list[dict], P: dict) -> ToolResult:
    sections: dict[str, dict[str, int]] = {}
    for c in ix.chunks:
        s = sections.setdefault(c["doc_id"], {})
        s[c["section"]] = s.get(c["section"], 0) + 1
    lines = ["Filings in this company's set, newest first:"]
    for d in sorted(manifest, key=lambda d: d["filing_date"], reverse=True):
        secs = sections.get(d["doc_id"], {})
        sec_txt = ", ".join(f"{k} ({n})" for k, n in secs.items()) or "no indexed text"
        lines.append(f"- {d['doc_id']}: {d['form']}, period {d['period']} (ended {d['report_date']}), "
                     f"filed {d['filing_date']}. Sections (chunks): {sec_txt}")
    lines += ["", "Resolved periods:",
              f"- latest fiscal year: {P['latest_fy']} (ended {P['latest_fy_end']}), {P['latest_fy_doc']}",
              f"- prior fiscal year: {P['prior_fy']} (ended {P['prior_fy_end']})",
              f"- latest quarterly report: {P['latest_periodic']}, {P['latest_periodic_doc']} "
              f"(filed {P['latest_periodic_filed']})",
              f"- latest earnings release: {P['latest_release']}, {P['latest_release_doc']} "
              f"(filed {P['latest_release_filed']})",
              f"- latest proxy statement: covers {P['latest_proxy']}, {P['latest_proxy_doc']}"]
    vv = valid_values(ix)
    lines += ["", "Values search_filings accepts:", f"- forms: {', '.join(vv['forms'])}",
              f"- topics: {', '.join(vv['topics'])}", f"- periods: {', '.join(vv['periods'])}"]
    return ToolResult(text="\n".join(lines))


# ---------------------------------------------------------------- definitions sent to the model

def specs(ix: Index) -> list[dict]:
    """Anthropic tool definitions. Valid filter values come from this company's index."""
    vv = valid_values(ix)
    return [
        {"name": "search_filings",
         "description": ("Keyword (BM25) search over this company's SEC filings. Returns the best-matching passages "
                         "in full, each with its chunk_id. Forms are a hard filter; topics and periods only rank "
                         "matching passages higher. A passage already shown in this conversation is listed by id "
                         "only. Use the filing's own vocabulary in the query (for example 'total revenue', "
                         "'remaining performance obligations')."),
         "input_schema": {"type": "object", "properties": {
             "query": {"type": "string", "description": "Words to search for."},
             "forms": {"type": "array", "items": {"type": "string", "enum": vv["forms"]},
                       "description": "Only search these forms."},
             "topics": {"type": "array", "items": {"type": "string", "enum": vv["topics"]},
                        "description": "Rank passages from these sections higher."},
             "periods": {"type": "array", "items": {"type": "string", "enum": vv["periods"]},
                         "description": "Rank passages from filings for these periods higher."},
             "k": {"type": "integer", "minimum": 1, "maximum": K_MAX,
                   "description": f"How many passages to return (default {K_DEFAULT})."}},
             "required": ["query"], "additionalProperties": False}},
        {"name": "get_chunk",
         "description": ("Read one passage by its chunk_id, and by default the passages just before and after it in "
                         "the same section, in reading order. Use it when an answer seems to continue across a "
                         "passage boundary, such as a table whose header or units are in the previous passage."),
         "input_schema": {"type": "object", "properties": {
             "chunk_id": {"type": "string"},
             "neighbors": {"type": "integer", "enum": [0, 1], "description": "1 (default) to include neighbours."}},
             "required": ["chunk_id"], "additionalProperties": False}},
        {"name": "list_filings",
         "description": ("List the filings in this company's set (form, period, filing date, sections), which "
                         "fiscal year and quarter are the latest, and the values search_filings accepts."),
         "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    ]


def run(name: str, args: dict, *, ix: Index, manifest: list[dict], P: dict, seen: set[str]) -> ToolResult:
    """Dispatch one tool call. Unknown tool names and non-object arguments are error results."""
    if not isinstance(args, dict):
        return _error("tool arguments must be a JSON object.")
    if name == "search_filings":
        return search_filings(ix, args, seen)
    if name == "get_chunk":
        return get_chunk(ix, args, seen)
    if name == "list_filings":
        return list_filings(ix, manifest, P)
    return _error(f"unknown tool {name!r}. Tools: search_filings, get_chunk, list_filings.")
