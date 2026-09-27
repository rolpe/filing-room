# filing-room

A diligence agent that answers a 40-question private-equity diligence checklist from a company's public SEC filings, cites a verifiable passage for every answer, drafts an IC-style memo from those answers, and is measured against a hand-built golden set, including a company held out until the end.

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

## How it works

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
- **Ground truth:** 120 golden items (40 questions × 3 companies). Numbers come from EDGAR's XBRL financial data, generated automatically; text answers were drafted from the filings with the exact supporting quote, and are checked in `golden/REVIEW.md`.
- **No vector database:** filings use consistent vocabulary and the checklist says where each answer should live, so plain-Python keyword search (BM25) was enough: the right number was in the retrieved passages for 100% of tuning-set numeric questions and 91% on the held-out company.

## What broke and how it was fixed

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

## Results by run

| Run | Companies | Items | Accuracy | Citation support | Abstention P / R | Cost (answer) |
|---|---|---|---|---|---|---|
| baseline | BILL, RPD | 38 | 94.7% | 93.8% | 83% / 100% | $0.75 |
| + citation `$` fix | BILL, RPD | 38 | 97.4% | 96.9% | 83% / 100% | $0.75 |
| + neighbor passages | BILL, RPD | 38 | 100% | 97.0% | 100% / 100% | $0.90 |
| full-checklist golden set | BILL, RPD | 80 | 91.0% | 92.5% | 62% / 100% | $1.93 |
| + recency fix | BILL, RPD | 80 | 93.6% | 94.0% | 62% / 100% | $1.91 |
| **held-out, frozen system** | **BOX** | **40** | **89.7%** | **100%** | 57% / 100% | **$0.99** |

Abstention P / R: of the times the agent said "not found", how often that was right / of the questions the filings don't answer, how many it caught. Models: Claude Sonnet 5 answers and writes memos; Claude Opus 5 grades. Total API spend for the whole project, including dead ends, was about $18.

## What I'd do next

1. **Second-chance retrieval on "not found"**: when the model abstains, let it write its own search query and try again. Targets the one real weakness (3 of 4 held-out misses).
2. **Answer prompt v2**: cite a quote for every fact in the answer (4 tuning answers were only partly supported), don't add unrequested comparisons, and answer "none/$0" when the filings show it instead of "not found".
3. **Grade the prose, not just the number**, so "right value, wrong direction" errors fail the checklist eval rather than surfacing only in the memo.
4. **Batch API for evals** (50% cheaper; evals don't need instant answers).
5. **Embeddings** only if keyword search stops being enough, e.g. on filings with less standard vocabulary.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and an Anthropic API key. Fetching, parsing and indexing are free; only `ask`, `run`, `eval` and `memo` call the API (`FILINGROOM_MAX_USD` caps any single command, default $3).

```
cp .env.example .env         # add ANTHROPIC_API_KEY and your email for EDGAR's User-Agent
./fr build BILL              # fetch + parse + index
./fr ask BILL gov_activist   # one question (~$0.02)
./fr run BILL                # full checklist -> runs/BILL_<time>.md (~$1)
./fr memo BILL               # IC memo from the latest run, with claim check (~$0.15)
./fr eval --label my-change  # score the tuning set (~$2.40)
./fr retrieval               # free: is the right number in the retrieved passages?
```

## Layout

```
checklist/checklist.json   40 questions, written from scratch
golden/manual.jsonl        hand-built golden items with source quotes; golden/REVIEW.md to check them
golden/golden.jsonl        generated: XBRL items + manual items
prompts/                   answer, memo and judge prompts
filingroom/                edgar, parse, index, answer, memo, evaluate, cli
results/                   one file per eval run (committed)
CHANGELOG-evals.md         one line per run: what changed, what moved
```
