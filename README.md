# filing-room

A first-look screening tool for US public companies, for take-private deal teams and public-equity analysts. Add a company and filing-room reads its recent SEC filings and gives you:

- **39 findings** across ownership and governance, capital structure and allocation, revenue and customers, profitability and cash flow, people, and competition and risk. Each one is a labelled fact with a value, a period and the filing quotes behind it. Code checks every quote word for word against the filing; a finding is **Verified**, **To review** (with the reason), or **Not disclosed**.
- **The source, one click away.** Open any finding, memo footnote or answer and the filing passage appears beside it with every quote highlighted, plus a link to the document on sec.gov.
- **Five years of financials** from the SEC's structured XBRL data, as reported in each year's 10-K.
- **A screening memo** whose factual sentences cite findings, with sentences an automatic claim check can't support marked. Exports to Markdown and prints cleanly.
- **Q&A** per company: follow-up questions answered only from the filings, with the same citations.
- **Notes, flags and review marks** on findings, and a CSV export of everything with source URLs.
- **Evaluation** (developer tools, for demos): every recorded eval run against the pass bar with 95% intervals and a trust headline (how often the app's own Verified status was wrong), each graded item with its expected answer and the filing passage, a review screen for checking the hand-built answer key against its source, and a form to start a run or a free retrieval check. One switch hides it: `FILINGROOM_DEV_TOOLS=0`.

Sources: the last two 10-Ks, last four 10-Qs, latest proxy statement and latest earnings release, from SEC EDGAR. Nothing else.

## Run it

Needs [uv](https://docs.astral.sh/uv/), Node 22, and an Anthropic API key.

```
cp .env.example .env                                   # ANTHROPIC_API_KEY, and an email for EDGAR's User-Agent
npm --prefix web install && npm --prefix web run build
./fr ui                                                # http://127.0.0.1:8787
```

Coverage starts empty: find a company by name or ticker and confirm the cost to add it.

**Cost and limits.** Screening a company costs about $1.25 in model usage and takes a few minutes; each screening stops at $2.50 and screenings are capped at $3/day (`RUN_MAX_USD_PER_DAY`). A question costs up to $0.05, capped at $1/day (`UI_MAX_USD_PER_DAY`). The cost is shown before every paid action and confirmed in the request; the actual cost is shown after, and the Usage screen keeps the totals. If the app is closed mid-screening, resuming keeps the answers already paid for.

**Private by construction.** The server listens on 127.0.0.1 only, rejects requests whose Host isn't the app itself (blocks DNS rebinding), and requires a custom header on every POST (blocks cross-site requests).

## How it works

```
EDGAR ──fetch──> filings ──parse──> SEC items ──chunk──> BM25 index
                                                             │
39 screening questions ──> retrieve passages ────────────────┘
                       ──> Claude Sonnet 5: answer + value + period + verbatim quotes
                       ──> code checks every quote appears in the passage it names
                       ──> Claude Haiku 5.5: one-line gist and cited points (no new facts; guarded)
answered findings      ──> Claude Sonnet 5: screening memo; Claude Opus 5: claim check
SEC XBRL company facts ──> five-year financials, and a cross-check of numeric findings
```

- **Backend:** plain Python (`filingroom/`), stdlib HTTP server, three dependencies (`anthropic`, `beautifulsoup4`, `lxml`), plus `langgraph` (pinned) for the optional agent mode, which only the CLI uses and which is never imported otherwise. App state lives in `data/app/` (`FILINGROOM_APP_DIR` to move it); downloaded filings are cached in `data/raw/`.
- **Frontend:** React + TypeScript + Vite in `web/`, hand-written CSS. Design notes in DESIGN.md; the approved mockups are in `docs/mockups/`.
- **Development:** `FILINGROOM_APP_DIR=data/app-dev uv run python -m filingroom.dev_import BILL --run runs/<run>.json` imports an existing CLI run with no API call; `npm --prefix web run dev` serves the frontend on :5173 against `./fr ui` on :8787; `uv run python -m unittest discover -s tests -t .` runs the tests.

## How accuracy was measured

The answering engine was built as a measured experiment before it became a tool: a written hypothesis, a golden answer set, two companies to tune on and one held out until the system was frozen. The eval harness (`./fr eval`, `golden/`, `results/`, `CHANGELOG-evals.md`) is kept as regression tooling: any change to what the model is sent is re-measured with it. The app's Evaluation area shows the same results and can start the same runs (a full run there writes exactly what `./fr eval` writes; spot checks are kept apart). Eval runs are capped at $3/day (`EVAL_MAX_USD_PER_DAY`).

**Hypothesis:** an agent grounded in a company's public filings can answer a standard diligence checklist with cited, verifiable answers accurately enough to replace the first pass of diligence prep.
**Pass bar (set before building):** on a held-out company, ≥85% of answers correct, ≥90% of citations support their answer, and the agent says "not in the filings" when that's the truth.

**Result:** passed on the held-out company, with one clear weakness.

| Held-out company (Box, 40 questions) | Result | Bar |
|---|---|---|
| Answers correct | **89.7%** (35/39 graded) | ≥85% |
| Citations that support their answer | **100%** | ≥90% |
| Answers with no supporting passage | **0%** | ≤10% |
| Says "not in filings" when the filings don't answer | **4/4** | all |
| Says "not in filings" when they *do* answer (false abstention) | 3 | — |
| Cost to answer the full checklist | **$0.99** (+$0.24 to grade) | — |

The weakness: when retrieval misses the right passage, the agent says "not found" rather than guessing. That's the safe failure mode (no invented answers), but it cost 3 of the 4 held-out misses.

### How the engine works

```
EDGAR ──fetch──> filings (HTML) ──parse──> sections (Item 1A, Item 7, ...) ──chunk──> keyword index (BM25)
                                                                                         │
checklist question ──> retrieve 8 passages (+ neighbors of the top 2) ───────────────────┘
                   ──> Claude: answer + value + period + verbatim quotes with passage ids   (JSON)
                   ──> code checks every quote appears in the passage it names
                   ──> answered | not_found | unsupported
answered checklist ──> Claude: IC memo, every factual sentence tagged with the answers it uses
                   ──> claim check: judge reads each sentence against only the answers it cites
```

- **Companies:** BILL (June fiscal year; Starboard activist settlement) and Rapid7 (December FY; Jana activist stake, CEO change June 2026) for building and tuning. **Box** (January FY) was held out: not parsed or looked at until the system was frozen (git tag `frozen-for-holdout`), then run once.
- **Corpus per company:** last two 10-Ks, last four 10-Qs, latest proxy (DEF 14A), latest earnings release (8-K exhibit 99.1).
- **Citations can't be invented:** the model returns quotes; code checks each one appears word-for-word in the passage it cites. An answer with no verified quote is flagged `unsupported` and scored wrong.
- **Ground truth:** 120 golden items (40 questions × 3 companies). Numbers come from EDGAR's XBRL financial data, generated automatically; text answers were drafted from the filings with the exact supporting quote and still need checking by hand (`golden/REVIEW.md`, or the Golden set screen in the app's Evaluation area).
- **No vector database:** filings use consistent vocabulary and the checklist says where each answer should live, so plain-Python keyword search (BM25) was enough: the right number was in the retrieved passages for 100% of tuning-set numeric questions and 91% on the held-out company.

### What broke and how it was fixed

Every change was one hypothesis, measured with the full eval, and kept only if the number moved (`CHANGELOG-evals.md`).

| # | Problem found | Fix | Effect |
|---|---|---|---|
| 1 | A correct quote was rejected because the model added `$` signs the table didn't have | Citation check ignores `$` | 94.7% → 97.4% (38-item set) |
| 2 | BILL's headcount sat in the passage just *before* the best search hit | Also send the neighbors of the top 2 hits | 97.4% → 100%; retrieval 95% → 100%; +21% cost |
| 3 | 100% meant the test was too easy (mostly numbers read off tables) | Expanded golden set from 38 to 80 items covering all 40 questions | Honest baseline **91.0%** |
| 4 | "Most recent" questions answered from an older 10-Q (Rapid7 ARR, customer count) | Boost the newest filings and tell the model newest wins | 91.0% → **93.6%** |
| 5 | Missed Rapid7's CEO change: the checklist only looked in the proxy and 10-K | "Current" questions always search the latest 10-Q/8-K | Spot-checked: now answers Wael Mohamed (CEO since June 1, 2026) |
| 6 | Memo said "roughly evenly" about a 700/700/89 split; wrote "does not disclose" for things merely not found | Memo prompt v2: cite every source, check direction words, not-found ≠ not-disclosed | Unsupported memo sentences 4.0% → 1.9% |
| 7 | XBRL "ground truth" for Box capex missed Box's separately tagged capitalized software ($6.1M vs $41.2M) | Caught by cross-checking XBRL against the filing text; overridden | Golden set correct before the holdout run |

Two lessons worth more than the numbers:
- **Right number, wrong sentence.** The answer for Rapid7 operating income had the correct value but said "up from $35.0M" when it had *fallen*. The numeric grader passed it; the memo's claim check caught it. Grading only the extracted value misses errors in the prose around it.
- **Structured data isn't automatically ground truth.** Companies tag the same line item differently in XBRL; the auto-built answer key needed checking against the documents too.

### Results by run

| Run | Companies | Items | Accuracy | Citation support | Abstention P / R | Cost (answer) |
|---|---|---|---|---|---|---|
| baseline | BILL, RPD | 38 | 94.7% | 93.8% | 83% / 100% | $0.75 |
| + citation `$` fix | BILL, RPD | 38 | 97.4% | 96.9% | 83% / 100% | $0.75 |
| + neighbor passages | BILL, RPD | 38 | 100% | 97.0% | 100% / 100% | $0.90 |
| full-checklist golden set | BILL, RPD | 80 | 91.0% | 92.5% | 62% / 100% | $1.93 |
| + recency fix | BILL, RPD | 80 | 93.6% | 94.0% | 62% / 100% | $1.91 |
| **held-out, frozen system** | **BOX** | **40** | **89.7%** | **100%** | 57% / 100% | **$0.99** |

Abstention P / R: of the times the agent said "not found", how often that was right / of the questions the filings don't answer, how many it caught. Models: Claude Sonnet 5 answers and writes memos; Claude Opus 5 grades. Total API spend for the whole project, including dead ends, was about $18.

### Agent mode: letting the model choose the searches

A second way to answer a question, built alongside the pipeline above and measured against it on the same answer key. In the pipeline, code picks the passages and the model answers once. In agent mode the model gets three read-only tools, scoped in code to the one company, and calls them in a loop until it decides it has enough:

```
question ──> agent ──(asks for tools, budget left)──> tools ──> agent ...
                   ──(tool-call or token budget spent)──> finalize (one call, tools off) ──┐
                   ──(answers)───────────────────────────────────────────────────────────┴──> verify ──> row
tools: search_filings (BM25 with form/topic/period filters) · get_chunk (a passage and its neighbours) · list_filings
```

- **Same trust rule.** The final answer goes through the same quote check as the pipeline (`answer.build_row`): no verified quote, no answer. Rows have the same shape plus `mode` and `agent` (calls, tokens, cost, why it stopped, and every tool call it made), so the memo, the app's statuses and the grader read them unchanged.
- **Same instructions, no hints.** The answering rules are the pipeline's, copied word for word (`prompts/agent.md`); the checklist's hand-tuned search words and form filters are withheld. Whether the model finds the passages without them is the experiment.
- **Hard budgets in the graph's routing**: at most 6 model calls and 8 tool calls per question, and 100,000 tokens (input, cached input and output summed over calls), after which one last call answers with tools switched off. LangGraph's own recursion limit is only a backstop.
- **Built with LangGraph**, using only its graph runtime; Claude is called through the project's own `llm.py`, so the spend caps apply. LangSmith tracing is forced off (a test checks no connection is made even when the environment turns it on). The framework is here to make the loop an explicit, testable state machine, not because the problem needs one: the Anthropic SDK alone could run this loop.

**Result: the same direction on the held-out company, with a larger gap, but still no detectable difference in accuracy; agent mode costs more and is slower.** Each mode against the recorded pipeline run (`./fr compare`; 95% intervals). The tuning set is the two companies the pipeline was tuned on (80 items); Box is the held-out company (40 items), run once in each mode with the system frozen.

| | Tuning set: pipeline | Tuning set: agent | Box (held out): pipeline | Box (held out): agent |
|---|---|---|---|---|
| Answers correct | 93.6% (73/78; 85.9–97.2) | 94.9% (74/78; 87.5–98.0) | 89.7% (35/39; 76.4–95.9) | 97.4% (38/39; 86.8–99.5) |
| Citations that fully support their answer (judge) | 94.0% (63/67) | 88.6% (62/70) | 100% (33/33) | 97.1% (33/34) |
| Says "not found" when the filings do answer | 5 of 72 | 2 of 72 | 3 of 36 | 2 of 36 |
| Says "not found" when that's the truth | 8/8 | 8/8 | 4/4 | 4/4 |
| Verified by the app but wrong | 2 of 65 | 3 of 68 | 1 of 32 | 0 of 33 |
| Cost per question | $0.024 | $0.030 | $0.025 | $0.029 |
| Time per question (mean / 90th percentile) | 4.5 / 7.3 s | 7.9 / 14.3 s | 4.3 / 7.0 s | 7.2 / 12.0 s |
| Model calls per question | 1 | 2.9 (2.2 tool calls) | 1 | 3.0 (2.3 tool calls) |

Items that changed grade: 3 better and 2 worse on the tuning set, 3 better and 0 worse on Box. Together that is 112/117 against 108/117, 6 better and 2 worse, sign test p = 0.29: the same direction twice, but too few changes to tell from noise.

What agent mode changed, item by item:
- **Most gains come from questions where the pipeline's one search missed.** On the tuning set it recovered three of the pipeline's five false "not found" answers (BILL's share of revenue outside the US, Rapid7's say-on-pay vote, Rapid7's cooperation agreement with Jana) by searching again with its own words. On Box it recovered two of three (cash at year end, and the customer count, found on its sixth and last call) and fixed one wrong answer (board structure). This is the pipeline's known weakness, and the fix the next-steps list below proposed. Box's acquisition of Alphamoon was missed by both modes.
- **On the tuning set it added one premature stop and one reading error; on Box, none.** For BILL's customer count it ran two searches with weak words, never saw any of the six passages holding the 479,300 total, took a 21,400 figure from a passage it did see, and answered with high confidence. That is the cost of withholding the hand-tuned search words and of telling the model to stop once a passage answers. For Rapid7's board it miscounted the directors. Both quotes were real, so the app would have shown both as Verified.
- **Citation support differs between the two sets.** On the tuning set more of its answers were only partly backed by their quotes (8 of 70, against 4 of 67): there it read more passages and wrote more than it quoted. On Box this did not show (1 of 34, against 0 of 33). Both are too few items to call significant.
- **Cost depends on caching.** On the tuning set it read 2.1 times the pipeline's input tokens but cost 1.23 times as much, because almost all of it was served from the prompt cache. Without caching the same run would have cost about 2.1 times the pipeline ($3.99 against $1.91 for answering), in line with the 2.1 times the tokens. Box reproduces the cost and latency picture (1.19 times the cost, 1.7 times the mean time).

Caveats: each pipeline run is from September and each agent run from November, so the latency ratios are indicative, and one item in 20 changed grade between two agent runs minutes apart. The tuning-set numbers are on the companies the pipeline's retrieval was tuned on, with an agent prompt written once and not tuned on them. The Box numbers are held out: Box was not looked at while either mode was built, and each mode ran on it once (agent mode with the prompt and budgets frozen at the tuning-set run). Box has now been used for agent mode, so a later change to the agent prompt can't be checked on it as a held-out company again. The judge is a model, and most items that flipped are judged ones. A one-retry "repair" step for answers whose quotes fail the check is built but unmeasured: in 140 agent answers its trigger never occurred.

**When each mode is the better tool.** The pipeline is cheaper, faster, and best when the question is known in advance and someone has written down where its answer lives, which is the 39-question screen. Agent mode earns its cost when the first search misses: across both sets it turned five of the pipeline's eight false "not found" answers into correct ones. My hypothesis, not measured here, is that it helps most on ad hoc questions, which have no hand-tuned search hints. The app still uses the pipeline; agent mode is CLI-only. The experiment cost $5.41 in API usage, including tests of the loop and the held-out run. The design, every decision and what each step found are in `PLAN_AGENT.md`.

**Hybrid mode: the pipeline first, agent mode only when it comes back empty.** `--mode hybrid` (CLI only) answers with the pipeline and, only when that answer is "not found" or has no verified quote, asks the same question again in agent mode; the agent's answer replaces it unless the agent fails. Simulated from the four recorded runs above, not run live: 112 of 117 right, the same as agent mode, against the pipeline's 108 (4 better, 0 worse, sign test p = 0.125), at 1.30 times the pipeline's cost per question and 1.37 times its mean time, against 1.22 and 1.74 for agent mode. 20 of 120 questions escalated, and on the 12 questions the filings don't answer the agent also said "not found" every time. It can't fix a wrong answer the pipeline gives as answered, which is why it misses two items agent mode got right. The rule was chosen after seeing both modes' results, Box included, so this is an in-sample estimate, not a held-out one. Its evals are written to `results/agent/` and `CHANGELOG-agent-evals.md`, like agent mode's.

### What I'd do next

1. **Second-chance retrieval on "not found"**: when the model abstains, let it write its own search query and try again. Targets the one real weakness (3 of 4 held-out misses). Agent mode, above, tested a general version of this: it recovered 5 of the pipeline's 8 false "not found" answers across the tuning set and Box, at higher cost and with one new premature-stop failure. A narrower version, used only after the pipeline says "not found", would keep the pipeline's cost on the other answers. That version is now built as hybrid mode (above), simulated but not yet run live.
2. **Answer prompt v2**: cite a quote for every fact in the answer (4 tuning answers were only partly supported), don't add unrequested comparisons, and answer "none/$0" when the filings show it instead of "not found".
3. **Grade the prose, not just the number**, so "right value, wrong direction" errors fail the checklist eval rather than surfacing only in the memo.
4. **Batch API for evals** (50% cheaper; evals don't need instant answers).
5. **Embeddings** only if keyword search stops being enough, e.g. on filings with less standard vocabulary.

### CLI

Fetching, parsing and indexing are free; `ask`, `run`, `eval` and `memo` call the API (`FILINGROOM_MAX_USD` caps any single command, default $3).

```
./fr build BILL              # fetch + parse + index
./fr ask BILL gov_activist   # one question (~$0.02)
./fr run BILL                # full checklist -> runs/BILL_<time>.md (~$1)
./fr memo BILL               # memo from the latest run, with claim check (~$0.15)
./fr eval --label my-change  # score the tuning set (~$2.40)
./fr retrieval               # free: is the right number in the retrieved passages?

# agent mode (CLI only): the model searches with tools; same flags on ask, run and eval
./fr ask BILL rev_total --mode agent          # one question, prints every tool call (~$0.03)
./fr eval --mode agent --ids @golden/agent-subset-20.txt --label x   # graded subset -> results/agent/ (~$0.80)
./fr compare results/<pipeline run>.json results/agent/<agent run>.json   # free: side by side, with intervals

# hybrid mode (CLI only): the pipeline first, agent mode only on "not found" or no verified quote
./fr ask BILL rev_international --mode hybrid   # ~$0.02, or ~$0.07 when it escalates
./fr eval --mode hybrid --ids @golden/agent-subset-20.txt --label x  # graded subset -> results/agent/ (~$0.70)
```

Agent-mode budgets: `--max-steps` (model calls, default 6), `--max-tool-calls` (8), `--max-tokens-per-question` (100,000), `--repair` (one retry when no quote verifies; off). The same flags set hybrid mode's agent step. A full 80-item agent eval costs about $2.90 with grading and needs `--full` and a `FILINGROOM_MAX_USD` above $3; a full hybrid eval also needs `--full`.

## Layout

```
web/                       the app (React + TypeScript); ./fr ui serves web/dist
filingroom/                edgar, parse, index, answer, memo (engine); present, findings, financials, store, server (app)
filingroom/agent/          agent mode: tools.py (three read-only tools), graph.py (the LangGraph loop), prompts.py
filingroom/hybrid.py       hybrid mode: the pipeline, then agent mode on its non-answers
checklist/checklist.json   the 40 questions (39 shown in the app), with labels and groups
prompts/                   answer, memo, judge and presentation prompts; agent.md and agent_notes.md for agent mode
tests/                     stdlib unit tests for the app's pure functions
golden/, results/          eval harness: golden answers and one file per eval run
CHANGELOG-evals.md         one line per eval run: what changed, what moved
results/agent/             agent- and hybrid-mode eval runs and comparisons, with CHANGELOG-agent-evals.md (kept apart from the pipeline's history)
PLAN_AGENT.md              agent mode's design, decisions, and what each build step found
docs/mockups/              approved visual mockups
```
