# CLAUDE.md — filing-room

A first-look screening tool for US public companies, built for take-private deal teams and public-equity analysts. Add a company and it reads the company's recent SEC filings, answers 39 screening questions as labelled findings, each tied to a quote that code has checked against the filing, pulls five years of financials from SEC XBRL data, and drafts a screening memo. Every finding opens the filing passage behind it. Built by one person; runs locally.

The answering engine was built and measured as an experiment first (hypothesis, golden set, held-out company: see README "How accuracy was measured"). That measurement is why the engine is trusted, and it is also why its prompts and retrieval are frozen unless a change is re-measured.

## Constraints (non-negotiable)

- Public data only. SEC EDGAR filings and company-published IR documents. No paid data, no transcripts from third-party services, nothing behind a login.
- Personal machine, personal API keys, personal GitHub. Nothing from the author's employer: no templates, checklists, prompts, thesis language, or documents. The checklist is written from scratch here.
- Local and private: the server binds 127.0.0.1 only, checks the Host header, and requires an `X-Filing-Room: 1` header on every POST. Keep it that way. LangSmith tracing (a dependency of `langgraph`) is forced off in `filingroom/agent/graph.py` before langgraph loads, whatever the environment says; a test checks that an agent run opens no connection. Keep that too.
- **Budget.** Total API spend is about $19 (2026-11-15). Ask before any command expected to cost more than about $1. Paid paths: screening a company (about $1.25), asking a question (up to $0.05), `./fr ask|run|eval|memo`, and anything that calls `filingroom/llm.py`. Agent mode (`--mode agent`) costs about $0.03 per question; a graded 20-item agent subset about $0.80; a full 80-item agent eval about $2.90 with judging, above the $3 per-command cap (it needs `--full` and a raised `FILINGROOM_MAX_USD`, with the owner's approval). Prefer `--only` spot checks over full evals; a full tune-set eval is about $2.40. `FILINGROOM_MAX_USD` (default $3) hard-stops any single CLI command. In the app, screenings are capped at $3/day (`RUN_MAX_USD_PER_DAY`) and $2.50 per company; questions at $1/day (`UI_MAX_USD_PER_DAY`); evaluation runs at $3/day (`EVAL_MAX_USD_PER_DAY`), a full two-company run being about $2.45. The caller must confirm the estimated cost in the request (`confirm_usd`, `max_usd`); the server refuses otherwise. Claude Code's own work (coding, drafting) doesn't touch the API credits.
- Dependencies. Python: `anthropic` (locked at 1.8.0), `beautifulsoup4`, `lxml`, and `langgraph==1.2.24` (pinned; agent mode only, imported only by `filingroom/agent/graph.py`, and only when agent mode runs); ask before adding one. Frontend (`web/`): `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, Vite and TypeScript. No UI kit, no Tailwind, no chart library; ask before adding anything.

## Architecture

Engine (measured; keep model inputs unchanged unless the change is re-measured with the eval harness):

1. **Fetch** (`edgar.py`): filings by CIK from EDGAR, cached in `data/raw/`; never re-downloaded. Fiscal years are labelled by the calendar year they end in (BILL FY2026 ends 2026-06-30).
2. **Parse** (`parse.py`): iXBRL HTML to ordered text and table blocks per SEC item (`item7`, `partII-item1a`), tagged with a topic.
3. **Index** (`index.py`): section chunks of about 380 words; BM25 in plain Python; forms as a hard filter, topic and period as soft boosts.
4. **Answer** (`answer.py`, `prompts/answer.md`): top-k chunks plus neighbours, one schema-constrained call per question (`claude-sonnet-5`, effort medium). Every quote is string-verified against the chunk it names; an answer with no verified quote becomes `unsupported`. The verify-and-build-row step is `answer.build_row`, shared with agent mode and pinned by a characterisation test (`tests/test_answer_row.py`).
5. **Memo** (`memo.py`, `prompts/memo.md`): composed only from answered findings; each sentence cites finding ids; a claim check (`claude-opus-5`) flags unsupported sentences.

Agent mode (an alternative to step 4, CLI only, measured against it; design and findings in `PLAN_AGENT.md`):

- **What it is** (`filingroom/agent/`, `prompts/agent.md`, `prompts/agent_notes.md`): the model answers by calling three read-only tools bound to one company (`search_filings` over the same BM25 index, `get_chunk`, `list_filings`) in a LangGraph loop (`graph.py`: agent, tools, finalize, verify nodes), then the same `build_row` verifies its quotes. Claude is called through `llm.complete_tools` (spend caps, cache-aware cost), never through LangChain. Same model and effort as the pipeline; the checklist's `where`/`search` hints are withheld on purpose.
- **Rows**: every pipeline key with the same types, plus `mode: "agent"` and `agent` (calls, tool calls, tokens, cost, stop reason, repairs, the tool-call trace, verified quotes from never-shown chunks). Pipeline rows and run files gain nothing. `modes.answerer(mode)` picks the function; pipeline mode never imports langgraph (tested).
- **Budgets** (defaults in `filingroom/agent/__init__.py`): 6 model calls including the forced final answer, 8 tool calls, 100,000 tokens (input + cached input + output summed over calls; it grows roughly with the square of the turns). The token default was raised from 30,000 after a 6-call list question passed it; on all 80 items the maximum was 80,494. When a budget runs out, one last call answers with tools off; `recursion_limit` is only a backstop. The repair round (`--repair`) is off and unmeasured: its trigger never occurred.
- **Measured** (80 items, `results/agent/2026-11-21_1047_agent80*`): accuracy 94.9% against the pipeline's 93.6%, no detectable difference; recovers false not-founds, lower citation support, 1.23× the cost with caching (about 1.7× without), 1.8× the latency. `prompts/agent.md` and `agent_notes.md` are frozen like the engine prompts: change them only as a measured change.
- **Not in the app**: `server.py` calls the pipeline only. Agent mode in the app needs its own cost estimate, resume rules and copy.

App layer (presentation; free to change):

- **Presentation pass** (`present.py`, `prompts/present.md`): one `claude-haiku-5-5` call per finding. Answered findings get a gist of 12 words or fewer and 1–5 cited points; not-found findings get plain wording ("not found in the filings read") plus any related information from the model's note. Small problems are repaired (too many points, a stray cite, an over-long gist); a mechanical guard rejects any new number, any cite to a quote it wasn't given, and bad lengths, with one retry naming the broken rule; anything still rejected falls back to the answer's own text (or plain not-found wording). It never changes the answer. About $0.01 per company.
- **Findings** (`findings.py`): status is derived, never asked of the model. Verified = answered, every quote verified, confidence not low, no mismatch with SEC XBRL data. To review = anything else, or flagged by the user. Not disclosed = `not_found`. A user can mark a To review finding as reviewed (it then shows Verified, reasons kept); a flag always wins. Labels, groups and order come from additive fields in `checklist/checklist.json`; `na_projections` is `hidden` (a test probe).
- **Financials** (`financials.py`): up to five fiscal years from XBRL company facts, as reported in each year's own 10-K, matched by annual duration and an end date within 10 days of the fiscal year-end (52/53-week years).
- **Store** (`store.py`): the app's state, separate from the eval files. Root `$FILINGROOM_APP_DIR`, default `data/app/` (ships empty):
  `coverage.json`; `companies/<T>/{company,run,present,memo,annotations,job}.json`, `questions.jsonl`, `answers.partial.jsonl` (answers written as they complete, so an interrupted screening resumes without paying twice); `filings/{raw,parsed,index}/`, the app's own filing cache. Writes are atomic under one lock; ticker path segments are validated against a pattern and the coverage list.
- **Filing caches are separate.** The server switches fetch/parse/index to the app's cache (`config.use_filing_cache`), so adding or refreshing a company in the app never changes the corpus in `data/raw|parsed|index` that `./fr eval`, `./fr retrieval` and `./fr golden` read. Filings the CLI cache already holds are copied in, not downloaded again. The store root must sit inside the project folder. Only filings in a company's current manifest are indexed (`parse.load_parsed`); replaced filings stay on disk as cache. A finding citing a replaced filing shows its quotes, says the filing is no longer in the set, and is To review.
- **Server** (`server.py`): stdlib `http.server`. API: `/api/coverage`, `/api/sec/search|preview`, `/api/companies` (start), `/api/companies/<T>` plus `/financials`, `/findings[/<qid>[/note|flag|review]]`, `/passage?chunk=&source=finding:<qid>|memo:<n>|question:<id>`, `/memo`, `/questions`, `/filings`, `/export/findings.csv|memo.md`, `/retry`, `/remove`, `/api/usage`. One screening at a time, in a background thread. Spend ledgers stay in `data/ui_spend.json` and `data/run_spend.json` whatever the store.
- **Web app** (`web/`): Vite + React + TypeScript, hand-written CSS from `web/src/styles/tokens.css`. `./fr ui` serves `web/dist`.
- **Evaluation area** (developer tools; `devtools.py`, `evaljob.py`, `web/src/pages/evals/`): recorded eval runs with the pass bar and an accuracy trend, run detail with flipped items and graded items opening the source panel, the golden set (read-only), and a form to start a full run or a spot check plus a free retrieval check. One switch, `FILINGROOM_DEV_TOOLS` (default on): when off, the sidebar's Developer group is hidden and everything under `/api/dev/` returns 404. Runs execute in a child process (`python -m filingroom.evaljob`) on the CLI's corpus, because the app server's filing paths point at its own cache. Full runs go through `evaluate.run` unchanged (results file + changelog line); spot checks go to `data/evals/spot/` and never touch `results/` or `CHANGELOG-evals.md`. Passages for eval items come from `data/index`, never the app cache. Eval spend has its own ledger (`data/eval_spend.json`), daily cap `EVAL_MAX_USD_PER_DAY` (default $3) and per-run hard stop `EVAL_RUN_LIMIT_USD` (default $3); one paid job at a time across screenings and evals. Only this area may use eval vocabulary.
  - Every rate carries a 95% Wilson interval; run comparisons give the flips each way with an exact sign test (`evalstats.py`). The headline of each run is a trust metric from the app's own status function (`findings.derive_status`) on each graded row: Verified-but-wrong, wrong answers caught as To review, and false Not disclosed (the SEC number check is included only where the answer key is the SEC figure).
  - Answer-key review: the Golden set screen shows each hand-built item's quote highlighted in the eval corpus and can mark it checked (`"verified": "human"`) or as needing a fix (`"needs-fix"` plus `review_note`), editing only that line of `golden/manual.jsonl` in place. `golden/golden.jsonl` isn't rebuilt by the app (the screens read review state from `manual.jsonl`); `./fr golden` syncs it. These fields are never sent to a model.

## How to run

```
cp .env.example .env                       # ANTHROPIC_API_KEY and EDGAR_USER_AGENT (with an email)
npm --prefix web install && npm --prefix web run build
./fr ui                                    # http://127.0.0.1:8787, empty coverage on first run
```

Development:

```
FILINGROOM_APP_DIR=data/app-dev uv run python -m filingroom.dev_import BILL --run runs/BILL_2026-09-27_1558.json   # free, refuses the default store
FILINGROOM_APP_DIR=data/app-dev ./fr ui --no-open      # API on :8787
npm --prefix web run dev                               # :5173 with /api proxied to :8787
npm --prefix web run typecheck
uv run python -m unittest discover -s tests -t .       # stdlib tests for the pure functions
```

`./fr` wraps `uv run python -m filingroom`. The package isn't pip-installed on purpose: macOS flags uv's editable-install `.pth` as hidden and Python 3.12 skips hidden `.pth` files.

## Eval harness (regression tooling, not part of the app)

`evaluate.py`, `golden.py`, `golden/`, `results/`, `CHANGELOG-evals.md` and `config/companies.json` are how the engine's accuracy was measured. They stay working and out of the app: the app never reads them, and app screenings never write to `runs/` or `results/`.

- Run an eval only when a change touches what the model is sent (`prompts/answer.md`, `prompts/memo.md`, `prompts/judge.md`, retrieval in `index.py`/`answer.py`, the checklist's question/period/where/search fields). Ask first; a full tune-set eval is about $2.40. `./fr retrieval` is free.
- The app's Evaluation area can show every recorded run and start runs; a full run there is the same as `./fr eval --label ... --note ...`.
- `./fr eval --label <name> --note "<what changed>"` writes `results/<timestamp>_<label>.json|.md` and a `CHANGELOG-evals.md` line. Commit the results file with the change.
- BOX was the held-out company; the CLI still refuses it without `--final`. The app treats BOX like any other company. Agent mode has never been run on BOX, so one `--final` agent run would be a real held-out number; ask first.
- Agent-mode evals (`./fr eval --mode agent --ids <ids|@file>`, or `--full`) write to `results/agent/` and `CHANGELOG-agent-evals.md`, never to `results/*.json` or `CHANGELOG-evals.md`, so the pipeline's history and the Evaluation area are unaffected. `./fr compare <a.json> <b.json>` (free) pairs two results files by golden id: accuracy by grade, citation support, abstention, the app's trust metric, flips with a sign test, cost, latency, calls.
- Golden set: `./fr golden` rebuilds `golden/golden.jsonl` from XBRL plus `golden/manual.jsonl`.

## Working agreements for Claude Code sessions

- Don't change engine prompts or retrieval by feel: propose, measure with the eval harness, keep or revert.
- Keep prompts in `prompts/` as plain files with a one-line comment on what each is for and what eval it last moved.
- Never fabricate a citation. If a passage can't be found, the answer is `not_found`.
- UI copy: plain and precise; no eval, golden or holdout language in the app outside the Evaluation area. Every state designed (loading, empty, error with a recovery, in progress); cost shown before and after every paid action.
- UI design follows PRODUCT.md and DESIGN.md; the approved mockups are in `docs/mockups/`.
- Ask before adding a dependency or a service.
