"""The app's own state: which companies are in coverage, and each company's screening results, notes and questions.

Layout (root = $FILINGROOM_APP_DIR, default data/app/):
  coverage.json                      ["BILL", ...] in coverage order
  companies/<T>/company.json         {ticker, name, cik, fiscal_year_end, sic, added, updated}
               run.json              the checklist run as the pipeline wrote it ({meta, answers})
               answers.partial.jsonl answers written as they complete (lets an interrupted run resume)
               present.json          presentation pass ({model, items: {qid: ...}, fallbacks})
               memo.json             the screening memo ({meta, memo, check})
               annotations.json      {qid: {note, note_at, flagged, flagged_at, reviewed_at}}
               questions.jsonl       one asked question per line
               job.json              processing state

Separate from the evaluation harness: nothing here is read by evals, and nothing in runs/ or results/ is read here.
Every write is atomic (temp file + rename) under one lock, because the job thread and request threads both write.
"""

import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

from . import config

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
lock = threading.RLock()


def root() -> Path:
    p = Path(os.environ.get("FILINGROOM_APP_DIR") or (config.DATA / "app"))
    return p if p.is_absolute() else config.ROOT / p


def is_default_root() -> bool:
    return root().resolve() == (config.DATA / "app").resolve()


# ---------------------------------------------------------------- atomic file helpers

def write_json(path: Path, obj) -> None:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(obj, f, indent=1)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def append_jsonl(path: Path, obj) -> None:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(obj) + "\n")


def read_jsonl(path: Path) -> list:
    out = []
    try:
        for line in path.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass
    return out


# ---------------------------------------------------------------- coverage

def valid_ticker(t: str) -> bool:
    return bool(TICKER_RE.fullmatch(t or ""))


def coverage() -> list[str]:
    return [t for t in read_json(root() / "coverage.json", []) if valid_ticker(t)]


def in_coverage(t: str) -> bool:
    return valid_ticker(t) and t in coverage()


def add(t: str) -> None:
    if not valid_ticker(t):
        raise ValueError(f"Not a valid ticker: {t!r}")
    with lock:
        cov = coverage()
        if t not in cov:
            write_json(root() / "coverage.json", cov + [t])


def remove(t: str) -> None:
    with lock:
        d = company_dir(t)  # validates
        write_json(root() / "coverage.json", [x for x in coverage() if x != t])
        shutil.rmtree(d, ignore_errors=True)


def company_dir(t: str) -> Path:
    """The folder for a ticker in coverage. Raises KeyError for anything else (bad pattern or not in coverage)."""
    if not in_coverage(t):
        raise KeyError(t)
    d = (root() / "companies" / t).resolve()
    if d.parent != (root() / "companies").resolve():
        raise KeyError(t)
    return d


# ---------------------------------------------------------------- per-company files

def path(t: str, name: str) -> Path:
    return company_dir(t) / name


def get(t: str, name: str, default=None):
    return read_json(path(t, name), default)


def put(t: str, name: str, obj) -> None:
    write_json(path(t, name), obj)


def annotate(t: str, qid: str, **fields) -> dict:
    """Merge fields into one finding's annotation (None removes a field)."""
    with lock:
        ann = get(t, "annotations.json", {})
        cur = {**ann.get(qid, {}), **fields}
        cur = {k: v for k, v in cur.items() if v not in (None, "")}
        if cur:
            ann[qid] = cur
        else:
            ann.pop(qid, None)
        put(t, "annotations.json", ann)
        return cur
