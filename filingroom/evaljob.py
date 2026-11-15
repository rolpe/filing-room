"""Child process for the app's evaluation area. Runs exactly what the CLI runs, against the CLI's corpus.

The app server points fetch/parse/index at its own filing cache, so evals run in a separate process where
config keeps its defaults (data/raw|parsed|index). Two entry points:

    python -m filingroom.evaljob run <job_dir>        # spec.json in, status.json out (polled by the server)
    python -m filingroom.evaljob retrieval BILL,RPD   # free retrieval check; prints one JSON line

A full run goes through evaluate.run unchanged (results/ file + CHANGELOG-evals.md line). A spot check goes
through evaluate.run with `only` and writes to the spot-check folder, never to results/ or the changelog.
"""

import contextlib
import io
import json
import os
import sys
import traceback
from pathlib import Path

from . import answer, config, evaluate, llm

SPOT_DIR = config.DATA / "evals" / "spot"


def _write(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)


def run_job(job_dir: Path) -> int:
    spec = json.loads((job_dir / "spec.json").read_text())
    status_path = job_dir / "status.json"
    status = {"state": "running", "done": 0, "total": spec["total"], "cost_usd": 0.0, "pid": os.getpid(),
              "result": None, "error": None}
    _write(status_path, status)
    llm.MAX_USD_PER_COMMAND = float(spec["limit_usd"])  # hard stop for this run

    def progress(done, total):
        status.update(done=done, total=total, cost_usd=round(llm._command_spend, 4))
        _write(status_path, status)

    spot = spec["kind"] == "spot"
    try:
        with open(job_dir / "output.log", "w") as log, contextlib.redirect_stdout(log):
            r = evaluate.run(spec["tickers"], answer.DEFAULT_MODEL, answer.DEFAULT_EFFORT, answer.DEFAULT_K,
                             answer.DEFAULT_EXPAND, label=spec.get("label", ""), note=spec.get("note", ""),
                             only=set(spec["ids"]) if spot else None, progress=progress,
                             out_dir=SPOT_DIR if spot else None, changelog=not spot)
        m = r["metrics"]["cost_usd"]
        status.update(state="done", cost_usd=round(m["answer"] + m["judge"], 4),
                      result={"kind": "spot" if spot else "results", "name": r["name"]})
    except BaseException as e:  # SystemExit from the hard stop, API errors: report, don't hide
        status.update(state="failed", cost_usd=round(llm._command_spend, 4),
                      error=str(e) or e.__class__.__name__)
        with open(job_dir / "output.log", "a") as log:
            traceback.print_exc(file=log)
    _write(status_path, status)
    return 0 if status["state"] == "done" else 1


def retrieval(tickers: list[str]) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        return evaluate.retrieval_check(tickers, answer.DEFAULT_K, answer.DEFAULT_EXPAND)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        sys.exit(run_job(Path(sys.argv[2])))
    if len(sys.argv) == 3 and sys.argv[1] == "retrieval":
        print(json.dumps(retrieval(sys.argv[2].split(","))))
        sys.exit(0)
    sys.exit("usage: python -m filingroom.evaljob run <job_dir> | retrieval BILL,RPD")
