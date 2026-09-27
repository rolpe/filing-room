"""Paths, settings, and company config. Everything reads from here."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"          # untouched EDGAR downloads (cache; never re-downloaded)
PARSED = DATA / "parsed"    # one JSON per filing: sections + text
INDEX = DATA / "index"      # chunks per company
RUNS = ROOT / "runs"        # answered checklists
RESULTS = ROOT / "results"  # eval results (committed)
PROMPTS = ROOT / "prompts"
CHECKLIST = ROOT / "checklist" / "checklist.json"
GOLDEN = ROOT / "golden" / "golden.jsonl"
COMPANIES = ROOT / "config" / "companies.json"


def load_env() -> None:
    """Minimal .env loader so we don't need python-dotenv. Real env vars win."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value and key.strip() not in os.environ:
            os.environ[key.strip()] = value


load_env()


def edgar_user_agent() -> str:
    ua = os.environ.get("EDGAR_USER_AGENT", "")
    if "@" not in ua:
        raise SystemExit("Set EDGAR_USER_AGENT in .env (SEC requires a contact email).")
    return ua


def companies() -> dict[str, dict]:
    return {c["ticker"]: c for c in json.loads(COMPANIES.read_text())}


def company(ticker: str) -> dict:
    all_ = companies()
    if ticker.upper() not in all_:
        raise SystemExit(f"Unknown ticker {ticker}. Known: {', '.join(all_)}")
    return all_[ticker.upper()]
