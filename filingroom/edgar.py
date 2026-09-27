"""Fetch filings from SEC EDGAR by CIK. Everything is cached under data/raw; filings are never re-downloaded.

EDGAR rules: descriptive User-Agent with a contact email, and at most 10 requests/second.
"""

import calendar
import json
import time
import urllib.error
import urllib.request
from datetime import date

from bs4 import BeautifulSoup

from . import config

_last_request = 0.0


def _get(url: str) -> bytes:
    global _last_request
    for attempt in range(5):
        wait = 0.15 - (time.time() - _last_request)  # stay well under 10 req/s
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": config.edgar_user_agent(),
                                                   "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"unreachable: {url}")


def _cached(path, url: str, refresh: bool = False) -> bytes:
    if path.exists() and not refresh:
        return path.read_bytes()
    body = _get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def _raw_dir(ticker: str):
    return config.RAW / ticker


def submissions(co: dict, refresh: bool = False) -> dict:
    cik = f"{co['cik']:010d}"
    body = _cached(_raw_dir(co["ticker"]) / "submissions.json",
                   f"https://data.sec.gov/submissions/CIK{cik}.json", refresh)
    return json.loads(body)


def company_facts(co: dict, refresh: bool = False) -> dict:
    cik = f"{co['cik']:010d}"
    body = _cached(_raw_dir(co["ticker"]) / "companyfacts.json",
                   f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", refresh)
    return json.loads(body)


# ---------------------------------------------------------------- fiscal periods

def _quarter_ends(fye: str, year: int) -> list[date]:
    """The four fiscal quarter-end dates whose fiscal year ends in `year`."""
    fye_month = int(fye[:2])
    ends = []
    for back in (9, 6, 3, 0):
        m = fye_month - back
        y = year
        if m <= 0:
            m += 12
            y -= 1
        ends.append(date(y, m, calendar.monthrange(y, m)[1]))
    return ends


def fiscal_year_of(d: date, fye: str) -> int:
    """Fiscal years are named by the calendar year they end in (BILL FY2026 ends 2026-06-30)."""
    return d.year if d.month <= int(fye[:2]) else d.year + 1


def fiscal_quarter_of(d: date, fye: str) -> tuple[int, int]:
    fy = fiscal_year_of(d, fye)
    q = ((d.month - int(fye[:2])) % 12) // 3
    return (4 if q == 0 else q), fy


def latest_quarter_end_before(d: date, fye: str) -> date:
    candidates = [e for y in (d.year - 1, d.year, d.year + 1) for e in _quarter_ends(fye, y) if e < d]
    return max(candidates)


def period_label(form: str, report_date: str, filing_date: str, fye: str) -> str:
    rd = date.fromisoformat(report_date) if report_date else None
    if form == "10-K":
        return f"FY{fiscal_year_of(rd, fye)}"
    if form == "10-Q":
        q, fy = fiscal_quarter_of(rd, fye)
        return f"Q{q} FY{fy}"
    if form == "8-K":  # earnings release covers the quarter that ended just before filing
        q, fy = fiscal_quarter_of(latest_quarter_end_before(date.fromisoformat(filing_date), fye), fye)
        return f"Q{q} FY{fy}"
    if form == "DEF 14A":  # reportDate is the annual meeting date
        return f"{rd.year} annual meeting"
    return report_date


# ---------------------------------------------------------------- corpus selection

def select_corpus(sub: dict) -> list[dict]:
    """Last two 10-Ks, last four 10-Qs, latest DEF 14A, latest earnings-release 8-K (Item 2.02)."""
    r = sub["filings"]["recent"]
    rows = [{k: r[k][i] for k in ("accessionNumber", "filingDate", "reportDate", "form",
                                  "primaryDocument", "items")}
            for i in range(len(r["form"]))]
    rows.sort(key=lambda x: x["filingDate"], reverse=True)
    want = {"10-K": 2, "10-Q": 4, "DEF 14A": 1, "8-K": 1}
    picked = []
    for row in rows:
        form = row["form"]
        if form not in want or want[form] == 0:
            continue
        if form == "8-K" and "2.02" not in row["items"].split(","):
            continue
        want[form] -= 1
        picked.append(row)
    return picked


def _exhibit_991(co: dict, acc_nodash: str, acc: str) -> str:
    """Find the EX-99.1 (the press release) in an 8-K's filing index."""
    url = f"https://www.sec.gov/Archives/edgar/data/{co['cik']}/{acc_nodash}/{acc}-index.htm"
    html = _cached(_raw_dir(co["ticker"]) / acc / "index.htm", url)
    soup = BeautifulSoup(html, "lxml")
    for tr in soup.select("table.tableFile tr"):
        tds = tr.find_all("td")
        if len(tds) >= 4 and tds[3].get_text(strip=True).upper().startswith("EX-99.1"):
            return tds[2].find("a").get_text(strip=True)
    raise RuntimeError(f"No EX-99.1 in {acc}")


def doc_id(ticker: str, form: str, period: str) -> str:
    slug = {"10-K": "10K", "10-Q": "10Q", "8-K": "8K", "DEF 14A": "DEF14A"}[form]
    return f"{ticker}_{slug}_{period.replace(' annual meeting', '').replace(' ', '')}"


def fetch_company(ticker: str, refresh_index: bool = False) -> list[dict]:
    co = config.company(ticker)
    sub = submissions(co, refresh=refresh_index)
    manifest = []
    for f in select_corpus(sub):
        acc = f["accessionNumber"]
        acc_nodash = acc.replace("-", "")
        doc = _exhibit_991(co, acc_nodash, acc) if f["form"] == "8-K" else f["primaryDocument"]
        url = f"https://www.sec.gov/Archives/edgar/data/{co['cik']}/{acc_nodash}/{doc}"
        path = _raw_dir(ticker) / acc / doc
        cached = path.exists()
        _cached(path, url)
        period = period_label(f["form"], f["reportDate"], f["filingDate"], co["fiscal_year_end"])
        entry = {
            "doc_id": doc_id(ticker, f["form"], period),
            "ticker": ticker,
            "form": f["form"],
            "period": period,
            "report_date": f["reportDate"],
            "filing_date": f["filingDate"],
            "accession": acc,
            "url": url,
            "path": str(path.relative_to(config.ROOT)),
        }
        manifest.append(entry)
        print(f"  {'cached ' if cached else 'fetched'} {entry['doc_id']:<22} {f['filingDate']}  {doc}")
    company_facts(co, refresh=refresh_index)
    (_raw_dir(ticker) / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def manifest(ticker: str) -> list[dict]:
    path = _raw_dir(ticker) / "manifest.json"
    if not path.exists():
        raise SystemExit(f"No filings for {ticker}. Run: filing-room fetch {ticker}")
    return json.loads(path.read_text())
