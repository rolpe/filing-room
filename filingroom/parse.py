"""Filing HTML (inline XBRL) -> ordered text/table blocks, grouped into sections.

Output per filing: data/parsed/<TICKER>/<doc_id>.json (+ a .txt dump for reading by eye).
Each section carries the SEC item key (e.g. "item7", "partII-item1a") and a topic tag
("mdna", "risk_factors", ...) that the checklist uses to say where an answer should live.
"""

import json
import re
import warnings

from bs4 import BeautifulSoup, Comment, NavigableString, XMLParsedAsHTMLWarning

from . import config, edgar

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BLOCK_TAGS = {"div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table",
              "section", "article", "body", "html", "center", "blockquote", "pre", "dl",
              "dt", "dd", "hr", "tr", "td", "th", "tbody", "thead"}

TENK_ITEMS = ["1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8", "9", "9A", "9B",
              "9C", "10", "11", "12", "13", "14", "15", "16"]
TENQ_ITEMS = [("I", "1"), ("I", "2"), ("I", "3"), ("I", "4"), ("II", "1"), ("II", "1A"),
              ("II", "2"), ("II", "3"), ("II", "4"), ("II", "5"), ("II", "6")]

TENK_TOPICS = {"1": "business", "1A": "risk_factors", "1B": "other", "1C": "cybersecurity",
               "2": "properties", "3": "legal", "4": "other", "5": "equity", "6": "other",
               "7": "mdna", "7A": "market_risk", "8": "financials", "9": "other",
               "9A": "controls", "9B": "other", "9C": "other", "10": "governance",
               "11": "exec_comp", "12": "ownership", "13": "governance", "14": "auditor",
               "15": "exhibits", "16": "other"}
TENQ_TOPICS = {("I", "1"): "financials", ("I", "2"): "mdna", ("I", "3"): "market_risk",
               ("I", "4"): "controls", ("II", "1"): "legal", ("II", "1A"): "risk_factors",
               ("II", "2"): "equity", ("II", "3"): "other", ("II", "4"): "other",
               ("II", "5"): "other", ("II", "6"): "exhibits"}

ITEM_RE = re.compile(r"^item\s*(\d{1,2}[a-c]?)\b\s*[\.:\-–—]?", re.I)
PAGE_NOISE_RE = re.compile(r"^(\d{1,3}|[ivx]{1,5}|table of contents|index)$", re.I)


def _clean(s: str) -> str:
    s = s.replace("\xa0", " ").replace("​", "")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\(\s+(?=[\d$.])", "(", re.sub(r"(?<=[\d%])\s+\)", ")", s))  # "( 73,447 )" -> "(73,447)"


# ---------------------------------------------------------------- html -> blocks

def _table_rows(table) -> list[str]:
    rows = []
    for tr in table.find_all("tr"):
        cells = [_clean(td.get_text(" ")) for td in tr.find_all(["td", "th"])]
        merged: list[str] = []
        pending_prefix = ""
        for c in cells:
            if not c:
                continue
            if c in ("$", "(", "$(", "($"):
                pending_prefix += c
                continue
            if c in (")", "%", ")%", "%)", "pts", "bps") and merged:
                merged[-1] += c
                continue
            merged.append(pending_prefix + c)
            pending_prefix = ""
        if merged and (not rows or rows[-1] != " | ".join(merged)):
            rows.append(" | ".join(merged))
    return rows


def _has_block(el) -> bool:
    return el.find(BLOCK_TAGS) is not None


def _walk(el, out: list[dict]) -> None:
    buf: list[str] = []

    def flush():
        text = _clean("".join(buf))
        buf.clear()
        if text:
            out.append({"kind": "text", "text": text})

    for child in el.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            buf.append(str(child))
        elif child.name == "br":
            buf.append(" ")
        elif child.name == "table":
            flush()
            rows = _table_rows(child)
            if len(rows) == 1 and len(rows[0]) < 200:
                out.append({"kind": "text", "text": rows[0].replace(" | ", " ")})
            elif rows:
                out.append({"kind": "table", "text": "\n".join(rows)})
        elif child.name in BLOCK_TAGS or _has_block(child):
            flush()
            _walk(child, out)
        else:
            buf.append(child.get_text(" "))
    flush()


def html_to_blocks(html: bytes) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["ix:header", "script", "style", "head"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
        tag.decompose()
    blocks: list[dict] = []
    _walk(soup.body or soup, blocks)
    # Drop page numbers / running headers: bare numerals, and short lines repeated many times.
    counts: dict[str, int] = {}
    for b in blocks:
        if b["kind"] == "text" and len(b["text"]) < 100:
            counts[b["text"]] = counts.get(b["text"], 0) + 1
    return [b for b in blocks
            if not (b["kind"] == "text" and (PAGE_NOISE_RE.match(b["text"])
                                             or (counts.get(b["text"], 0) >= 8 and len(b["text"]) < 100)))]


# ---------------------------------------------------------------- sections

def _item_candidates(blocks: list[dict]) -> list[tuple[int, str]]:
    cands = []
    for i, b in enumerate(blocks):
        if b["kind"] != "text" or len(b["text"]) > 250:
            continue
        m = ITEM_RE.match(b["text"])
        if m:
            cands.append((i, m.group(1).upper()))
    return cands


def _span_words(blocks, start: int, end: int) -> int:
    return sum(len(b["text"].split()) for b in blocks[start:end])


def _pick_sections(blocks, sequence: list[str]) -> list[tuple[int, int]]:
    """Choose one heading per item in canonical order.

    The first item found takes the candidate that starts the longest run of text (this skips
    the table of contents); each later item takes the first matching candidate after the
    previous pick. Returns [(sequence_index, block_index)].
    """
    cands = _item_candidates(blocks)
    positions = [c[0] for c in cands]
    picks: list[tuple[int, int]] = []
    prev = -1
    for si, key in enumerate(sequence):
        matches = [c[0] for c in cands if c[1] == key and c[0] > prev]
        if not matches:
            continue
        if not picks:
            def span(pos):
                nxt = [p for p in positions if p > pos]
                return _span_words(blocks, pos, nxt[0] if nxt else len(blocks))
            chosen = max(matches, key=span)
        else:
            chosen = matches[0]
        picks.append((si, chosen))
        prev = chosen
    return picks


def _is_subheading(text: str) -> bool:
    return (len(text) <= 120 and not text.endswith((".", ",", ";")) and any(ch.isalpha() for ch in text)
            and (text[0].isupper() or text[0].isdigit()) and len(text.split()) <= 16)


def sectionize(blocks: list[dict], form: str) -> list[dict]:
    if form == "10-K":
        seq = TENK_ITEMS
        picks = _pick_sections(blocks, seq)
        keyed = [(f"item{seq[si].lower()}", TENK_TOPICS[seq[si]], bi) for si, bi in picks]
    elif form == "10-Q":
        seq_keys = [item for _, item in TENQ_ITEMS]
        picks = _pick_sections(blocks, seq_keys)
        keyed = [(f"part{TENQ_ITEMS[si][0]}-item{TENQ_ITEMS[si][1].lower()}", TENQ_TOPICS[TENQ_ITEMS[si]], bi)
                 for si, bi in picks]
    else:
        topic = {"DEF 14A": "proxy", "8-K": "press_release"}.get(form, "other")
        keyed = [(topic, topic, 0)]

    sections = []
    if keyed and keyed[0][2] > 0:
        keyed = [("cover", "cover", 0)] + keyed
    for n, (key, topic, start) in enumerate(keyed):
        end = keyed[n + 1][2] if n + 1 < len(keyed) else len(blocks)
        heading = blocks[start]["text"][:120] if key not in ("cover", "proxy", "press_release") else key
        sub = ""
        out_blocks = []
        for b in blocks[start:end]:
            if b["kind"] == "text" and _is_subheading(b["text"]):
                sub = b["text"]
            out_blocks.append({**b, "subheading": sub})
        sections.append({"key": key, "topic": topic, "heading": heading, "blocks": out_blocks})
    return sections


# ---------------------------------------------------------------- driver

def parse_company(ticker: str) -> list[dict]:
    out_dir = config.PARSED / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = []
    for entry in edgar.manifest(ticker):
        blocks = html_to_blocks((config.ROOT / entry["path"]).read_bytes())
        sections = sectionize(blocks, entry["form"])
        doc = {**entry, "sections": sections}
        (out_dir / f"{entry['doc_id']}.json").write_text(json.dumps(doc))
        with open(out_dir / f"{entry['doc_id']}.txt", "w") as f:
            for s in sections:
                f.write(f"\n\n######## [{s['key']} | {s['topic']}] {s['heading']}\n\n")
                for b in s["blocks"]:
                    f.write(("[TABLE]\n" + b["text"] + "\n[/TABLE]" if b["kind"] == "table" else b["text"]) + "\n")
        words = sum(len(b["text"].split()) for s in sections for b in s["blocks"])
        print(f"  {entry['doc_id']:<22} {len(sections):>2} sections  {words:>7,} words  "
              + " ".join(s["key"] for s in sections))
        docs.append(doc)
    return docs


def load_parsed(ticker: str) -> list[dict]:
    """Parsed filings in the company's current manifest. Filings a corpus refresh replaced stay on disk as cache
    but are not loaded (so they don't get indexed); without a manifest, every parsed file is loaded."""
    out_dir = config.PARSED / ticker
    try:
        current = {d["doc_id"] for d in edgar.manifest(ticker)}
    except SystemExit:
        current = None
    return [json.loads(p.read_text()) for p in sorted(out_dir.glob("*.json")) if current is None or p.stem in current]
