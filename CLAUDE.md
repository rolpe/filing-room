# CLAUDE.md — filing-room

A personal learning project: a diligence agent that answers a standard PE diligence checklist over a target company's public SEC filings, with citations, and drafts an IC-style memo from the answers. Built by one person on weekends. The point is to learn how grounded agents behave on real financial documents and to produce a measured result, not to ship a product.

## Hypothesis

> An agent grounded in a company's public filings can answer a standard diligence checklist with cited, verifiable answers accurately enough to replace the first pass of diligence prep.

**Proves it:** on a held-out golden set, ≥85% of answers correct, ≥90% of citations point to text that actually supports the answer, and the agent correctly says "not in the filings" for questions the filings don't answer.

**Kills it:** accuracy plateaus below ~70% after two iterations on retrieval and prompting, or the unsupported-claim rate (answers with no supporting passage) stays above 10%. If killed, the write-up says why — that is still a result.

## Constraints (non-negotiable)

- Public data only. SEC EDGAR filings and company-published IR documents. No paid data, no transcripts from third-party services, nothing behind a login.
- Personal machine, personal API keys, personal GitHub. Nothing from the author's employer: no templates, checklists, prompts, thesis language, or documents. The diligence checklist is written from scratch here.
- Log API cost per run. Prefer cheaper models for bulk extraction; use the strongest model only where quality is measured to need it.
- **Budget: this is a learning project, not a product.** Total API spend so far is ~$16.50 (2026-09-27). Ask before any command expected to cost more than ~$1. Prefer `--only` spot checks over full evals; a full tune-set eval is ~$2.40. `FILINGROOM_MAX_USD` (default $3) hard-stops any single command. Claude Code's own work (coding, drafting golden items) doesn't touch the API credits; only `./fr ask|run|eval|memo` do.
- No framework sprawl. Plain Python, a local index, prompts in files, one CLI. Add a dependency only when a measured problem needs it. Current deps: `anthropic`, `beautifulsoup4`, `lxml`.

## Scope for v1

- **Targets** (`config/companies.json`): **BILL** (June FY; Starboard cooperation agreement Oct 2025) and **RPD** / Rapid7 (Dec FY; Jana ~10% stake pushing for a sale) are the tuning set. **BOX** (Jan FY) is held out — fetched, but not parsed, inspected, or evaluated until the final run. The CLI refuses BOX without `--final`.
- **Corpus per company:** last two 10-Ks, last four 10-Qs, latest DEF 14A (proxy), latest earnings-release 8-K (its EX-99.1). All from EDGAR. User-Agent with contact email lives in `.env` (`EDGAR_USER_AGENT`).
- **Checklist** (`checklist/checklist.json`): 40 questions across revenue, margins, cash flow, balance sheet/debt, customers, competition, risk, management/comp, governance, litigation, M&A, capital allocation, people, and 3 abstention questions the filings shouldn't answer. Each records answer type, target period (`latest_fy`, `prior_fy`, `latest_fy_end`, `latest_release`, `latest_proxy`, `current`), where it should be found (forms + section topics), and how it's graded.
- **Outputs:** (1) answered checklist as JSON and Markdown with a citation per answer (`./fr run`); (2) an IC-style memo (not built yet); (3) an eval report (`./fr eval`).
- **Interface:** CLI only (`./fr`). No web UI in v1.

## Architecture (keep it boring)

1. **Fetch** (`edgar.py`) — download filings by CIK from EDGAR; cache raw files in `data/raw/`; never re-download. Fiscal periods are labeled by the calendar year the fiscal year ends in (BILL FY2026 ends 2026-06-30; BOX FY2027 ends 2027-01-31).
2. **Parse** (`parse.py`) — iXBRL HTML → ordered text/table blocks; tables keep rows as `cell | cell | cell`. Sections are SEC items (10-K `item7`, 10-Q `partII-item1a`) tagged with a topic (`mdna`, `risk_factors`, ...). Headings are picked in canonical item order; the first uses the longest-span candidate to skip the table of contents. A `.txt` dump per filing sits next to the JSON for reading by eye.
3. **Index** (`index.py`) — chunk by section (~380 words, short trailing context carried over); **BM25 in plain Python**, forms as a hard filter, topic and period as soft boosts. No vector store in v1: embeddings are an experiment to run only if evals show retrieval misses BM25 can't fix.
4. **Answer** (`answer.py`, `prompts/answer.md`) — retrieve top-k chunks, one schema-constrained JSON call per question (answer, value in base units, period, quotes with chunk ids). **Every quote is string-verified against the chunk it names**; an answer with no verified quote is downgraded to `unsupported`. `not_found` when the excerpts don't support an answer.
5. **Memo** — compose sections from answered questions only; no new claims; every sentence that states a fact references a checklist answer ID. (Weekend 4.)
6. **Eval** (`evaluate.py`, `prompts/judge.md`) — one command; writes `results/<timestamp>_<label>.json|.md`, compares to the previous run, lists items that flipped, appends a line to `CHANGELOG-evals.md`.

Models: answering `claude-sonnet-5` at effort `medium` (bulk extraction); judge `claude-opus-5` at effort `low` with server-side refusal fallbacks. Both are CLI flags — model/effort comparisons are eval runs like any other.

## Evals — build these before the agent is good

- **Golden set:** `./fr golden` writes `golden/golden.jsonl` = XBRL-derived numeric items (from EDGAR company facts, plus derived growth/margin) + hand-built items from `golden/manual.jsonl`. Manual items carry the source quote; `"verified": "claude-draft"` means drafted from that quote and still needs a human check → flip to `"human"` once checked. Target: 40 questions × 3 companies.
- **Grading:** `numeric` (within tolerance: 0.5% relative, 0.6pp for percentages; the answer must also have a verified citation), `judged` (LLM judge vs golden text), `abstain` (correct iff `not_found`), `support_only` (judgment questions: only citation support scored).
- **Metrics:** accuracy (overall and by grade), citations verified (mechanical), citation support (judged, verified quotes only), unsupported-claim rate, abstention precision/recall, retrieval recall (LLM-free: is the golden number in the top-k chunks?), cost, wall time. `./fr retrieval` runs the retrieval check with no API calls.
- **Discipline:** run the full eval on every meaningful change; commit the results file with the change; `CHANGELOG-evals.md` gets one line per run automatically — pass `--note "what changed"`.
- Hold out one company entirely until the end. Tune on two, report on three.

## Build order (weekends)

1. ✅ Fetch + parse (all three fetched; BILL + RPD parsed/indexed). Checklist v1. Golden set (38 items for BILL + RPD). CLI that answers with citations. First real runs 2026-09-27: baseline 94.7% accuracy, 97.4% after the `$` citation-normalization fix (see CHANGELOG-evals.md).
2. Eval runner (built). First real numbers (done). Neighbor chunks (+expand 2): 97.4 → 100 on the 38-item set.
3. Golden set expanded to the full checklist (80 items for BILL + RPD): honest baseline 91.0%; recency fix for 'current' questions → 93.6%; CEO fix spot-checked.
4. Memo generation + claim check (done): prompt v2 cut unsupported memo sentences 4.0% → 1.9%.
5. System frozen (git tag `frozen-for-holdout`); BOX parsed for the first time after the freeze. Tuning is over; remaining ideas go in the README's 'what's next'.

Original plan:

2. Eval runner. Fix the two worst failure modes. Known first candidate: neighbor-chunk misses (BILL employee count sits in chunk #021; retrieval returns #022/#023).
3. Expand golden set to the full checklist for both tuning companies. Expect table parsing and fiscal-period confusion to dominate the errors. Known parse issue: proxy Summary Compensation Tables stack three years in one cell.
4. Memo generation + unsupported-claim check.
5. Abstention behavior, cost/latency pass, held-out run (`--final`). Write-up and a 3-minute demo recording.
6. Buffer. If ahead: thesis-fit scoring — score each company against a short written investment thesis using the same grounded answers.

## How to run

```
./fr build BILL            # fetch + parse + index (cached)
./fr golden                # rebuild golden set
./fr retrieval             # LLM-free retrieval recall
./fr ask BILL rev_total    # one question (id or free text)
./fr run BILL              # full checklist -> runs/
./fr eval --label baseline --note "first run"
./fr search BILL "net dollar-based retention" --full
```

`./fr` wraps `uv run python -m filingroom`. The package isn't pip-installed on purpose: macOS flags uv's editable-install `.pth` as hidden and Python 3.12 skips hidden `.pth` files.

## Working agreements for Claude Code sessions

- Start each session by reading `CHANGELOG-evals.md` and the latest results file.
- Prefer the smallest change that moves a metric. One hypothesis per branch. Kill it if it doesn't move the number.
- Don't optimize prompts by feel. Propose the change, run the eval, keep or revert.
- Ask before adding a dependency, a service, or a UI.
- Keep prompts in `prompts/` as plain files with a one-line comment on what each is for and what eval it last moved.
- Never fabricate a citation. If a passage can't be found, the answer is `not_found`.
- Never parse, inspect, or tune on BOX before the final run.

## Deliverables

- Public repo with README: hypothesis, architecture, eval results table, what broke and how it was fixed, cost per company, what would come next.
- 3-minute screen recording of a run.
- One-page write-up suitable for a LinkedIn post, in the author's own voice.
