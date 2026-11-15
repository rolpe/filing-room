"""Development only: copy an existing CLI run (and its memo) into an app store, with no API calls.

    FILINGROOM_APP_DIR=data/app-dev uv run python -m filingroom.dev_import BILL --run runs/BILL_2026-09-27_1558.json

Refuses to write to the default store (data/app), which ships empty. Copies the company's CLI corpus (filings,
manifest) into the store's own filing cache and parses and indexes it there. Runs from before the SEC number check get it
computed here (free: XBRL company facts). Imported runs have no presentation pass, so they show the fallback text.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import config, edgar, index, parse, pipeline, store


def main() -> None:
    ap = argparse.ArgumentParser(prog="dev_import")
    ap.add_argument("ticker")
    ap.add_argument("--run", required=True, help="runs/<TICKER>_<stamp>.json")
    ap.add_argument("--memo", help="default: the run's _memo.json if it exists")
    a = ap.parse_args()
    if store.is_default_root():
        sys.exit("Refusing to import into the default app store (data/app). Set FILINGROOM_APP_DIR, e.g. data/app-dev.")
    t = a.ticker.upper()
    co = config.company(t)
    store.use_filing_cache()
    store.copy_corpus(t)  # the CLI's corpus for this company, into the app's own filing cache (free)
    parse.parse_company(t)
    index.build_index(t)
    run_path = Path(a.run)
    data = json.loads(run_path.read_text())
    if "number_check" not in data["meta"]:
        data["meta"]["number_check"] = pipeline.number_check(t, data["answers"])
    memo_path = Path(a.memo) if a.memo else run_path.with_name(run_path.stem + "_memo.json")
    sub = edgar.submissions(co)
    store.add(t)
    store.put(t, "company.json", {"ticker": t, "name": pipeline.nice_name(sub.get("name") or co["name"]),
                                  "cik": co["cik"], "fiscal_year_end": co["fiscal_year_end"],
                                  "sic": sub.get("sicDescription", ""), "added": date.today().isoformat(),
                                  "updated": data["meta"]["timestamp"][:10], "imported_from": run_path.name})
    store.put(t, "run.json", data)
    if memo_path.exists():
        m = json.loads(memo_path.read_text())
        store.put(t, "memo.json", {"meta": m["meta"], "memo": m["memo"], "check": m["check"]})
    nc = data["meta"]["number_check"]
    print(f"Imported {t} into {store.root()}: {len(data['answers'])} answers, number check {nc['matched']}/{nc['checked']}, "
          f"memo {'yes' if memo_path.exists() else 'no'}.")


if __name__ == "__main__":
    main()
