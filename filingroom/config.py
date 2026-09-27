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
USER_COMPANIES = DATA / "companies_user.json"  # added from the UI or `./fr add`; never part of evals


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
    cos = {c["ticker"]: c for c in json.loads(COMPANIES.read_text())}
    if USER_COMPANIES.exists():
        for c in json.loads(USER_COMPANIES.read_text()):
            cos.setdefault(c["ticker"], c)
    return cos


def add_user_company(entry: dict) -> None:
    rows = json.loads(USER_COMPANIES.read_text()) if USER_COMPANIES.exists() else []
    if not any(r["ticker"] == entry["ticker"] for r in rows):
        rows.append(entry)
        USER_COMPANIES.parent.mkdir(parents=True, exist_ok=True)
        USER_COMPANIES.write_text(json.dumps(rows, indent=2))


def company(ticker: str) -> dict:
    all_ = companies()
    if ticker.upper() not in all_:
        raise SystemExit(f"Unknown ticker {ticker}. Known: {', '.join(all_)}")
    return all_[ticker.upper()]
