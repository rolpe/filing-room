"""Chunk parsed filings by section and search them with BM25.

No vector store in v1: filings use consistent vocabulary, and the checklist tells us which
form/section to look in. Embeddings are a later experiment, adopted only if evals show
retrieval misses that BM25 can't fix.
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass

from . import config, parse

TARGET_WORDS = 380
MAX_WORDS = 650
OVERLAP_WORDS = 60

STOPWORDS = set("""a an and are as at be by for from has have in is it its of on or that the this
to was were will with what which who how does did do our we their they than any all each
per were been being into over under about there these those such""".split())


# ---------------------------------------------------------------- chunking

def _split_big(block: dict) -> list[dict]:
    words = len(block["text"].split())
    if words <= MAX_WORDS:
        return [block]
    if block["kind"] == "table":
        rows = block["text"].split("\n")
        header, body = rows[:2], rows[2:]
        pieces, cur = [], []
        for row in body:
            cur.append(row)
            if len(" ".join(cur).split()) > TARGET_WORDS:
                pieces.append(cur)
                cur = []
        if cur:
            pieces.append(cur)
        return [{**block, "text": "\n".join(header + p)} for p in pieces]
    sentences = re.split(r"(?<=[.!?])\s+", block["text"])
    pieces, cur = [], []
    for s in sentences:
        cur.append(s)
        if len(" ".join(cur).split()) > TARGET_WORDS:
            pieces.append(" ".join(cur))
            cur = []
    if cur:
        pieces.append(" ".join(cur))
    return [{**block, "text": p} for p in pieces]


def chunk_doc(doc: dict) -> list[dict]:
    chunks = []
    for sec in doc["sections"]:
        blocks = [p for b in sec["blocks"] for p in _split_big(b)]
        cur: list[dict] = []
        n = 0

        def emit():
            nonlocal n
            if not cur:
                return
            body = "\n".join(("[TABLE]\n" + b["text"] + "\n[/TABLE]") if b["kind"] == "table" else b["text"]
                             for b in cur)
            chunks.append({
                "chunk_id": f"{doc['doc_id']}#{sec['key']}#{n:03d}",
                "doc_id": doc["doc_id"], "ticker": doc["ticker"], "form": doc["form"],
                "period": doc["period"], "filing_date": doc["filing_date"],
                "section": sec["key"], "topic": sec["topic"], "heading": sec["heading"],
                "subheading": cur[0].get("subheading", ""), "url": doc["url"], "text": body,
            })
            n += 1

        for b in blocks:
            size = len(" ".join(x["text"] for x in cur).split())
            if cur and size + len(b["text"].split()) > TARGET_WORDS:
                emit()
                # Carry short trailing context (e.g. "(In thousands)" or a table's lead-in sentence).
                carry, words = [], 0
                for prev in reversed(cur):
                    w = len(prev["text"].split())
                    if prev["kind"] == "table" or words + w > OVERLAP_WORDS:
                        break
                    carry.insert(0, prev)
                    words += w
                cur = carry
            cur.append(b)
        emit()
    return chunks


def build_index(ticker: str) -> list[dict]:
    chunks = [c for doc in parse.load_parsed(ticker) for c in chunk_doc(doc)]
    out = config.INDEX / f"{ticker}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    sizes = sorted(len(c["text"].split()) for c in chunks)
    print(f"  {ticker}: {len(chunks)} chunks, median {sizes[len(sizes) // 2]} words, max {sizes[-1]}")
    return chunks


# ---------------------------------------------------------------- BM25

def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)*", text.lower())
    out = []
    for t in toks:
        t = t.replace(",", "")
        if t in STOPWORDS or len(t) < 2:
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss") and not t[-2].isdigit():
            t = t[:-1]
        out.append(t)
    return out


@dataclass
class Hit:
    score: float
    chunk: dict


class Index:
    def __init__(self, ticker: str, k1: float = 1.4, b: float = 0.75):
        path = config.INDEX / f"{ticker}.jsonl"
        if not path.exists():
            raise SystemExit(f"No index for {ticker}. Run: filing-room index {ticker}")
        self.chunks = [json.loads(line) for line in path.read_text().splitlines()]
        self.by_id = {c["chunk_id"]: c for c in self.chunks}
        self.k1, self.b = k1, b
        self.tfs = []
        df: Counter = Counter()
        for c in self.chunks:
            toks = tokenize(f"{c['heading']} {c['subheading']} {c['text']}")
            tf = Counter(toks)
            self.tfs.append((tf, len(toks)))
            df.update(tf.keys())
        n = len(self.chunks)
        self.avgdl = sum(l for _, l in self.tfs) / max(n, 1)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def neighbors(self, chunk_id: str) -> list[dict]:
        """The chunks immediately before and after this one in the same section."""
        base, _, n = chunk_id.rpartition("#")
        return [self.by_id[i] for i in (f"{base}#{int(n) - 1:03d}", f"{base}#{int(n) + 1:03d}") if i in self.by_id]

    def search(self, query: str, k: int = 8, forms: list[str] | None = None,
               topics: list[str] | None = None, periods: list[str] | None = None,
               topic_boost: float = 1.5, period_boost: float = 1.3) -> list[Hit]:
        q = Counter(tokenize(query))
        hits = []
        for c, (tf, dl) in zip(self.chunks, self.tfs):
            if forms and c["form"] not in forms:
                continue
            s = 0.0
            for term, qn in q.items():
                f = tf.get(term)
                if f:
                    s += qn * self.idf[term] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s <= 0:
                continue
            if topics and c["topic"] in topics:
                s *= topic_boost
            if periods and c["period"] in periods:
                s *= period_boost
            hits.append(Hit(s, c))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
