# filing-room

A diligence agent that answers a private-equity diligence checklist from a company's public SEC filings, cites a verifiable passage for every answer, and is measured against a golden set.

**Hypothesis:** an agent grounded in a company's public filings can answer a standard diligence checklist with cited, verifiable answers accurately enough to replace the first pass of diligence prep. It passes if, on a held-out company, ≥85% of answers are correct, ≥90% of citations support their answer, and the agent says "not in the filings" when that's the truth.

**Status:** end-to-end pipeline running on the two tuning companies (38 golden items). Held-out company not yet run.

## How it works

```
EDGAR ──fetch──> raw HTML ──parse──> sections (Item 1A, Item 7, ...) ──chunk──> BM25 index
                                                                                   │
checklist question ──> retrieve top-k (form filter, section/period boost) ─────────┘
                   ──> Claude: JSON answer + verbatim quotes w/ chunk ids
                   ──> every quote string-matched against its source chunk
                   ──> answered | not_found | unsupported
```

- **Targets:** BILL (Starboard settlement), Rapid7 (Jana stake) for tuning; Box held out until the final run. Three different fiscal year-ends, on purpose.
- **Ground truth:** numeric answers come from EDGAR's XBRL company-facts API, so most of the golden set is built automatically. Text answers are hand-verified against a quoted passage.
- **No vector store (yet):** filings use consistent vocabulary and the checklist says where each answer should live, so v1 uses plain-Python BM25. Embeddings get added only if the eval shows retrieval misses BM25 can't fix.
- **Citations can't be invented:** the model returns quotes; code checks each one appears in the chunk it names. An answer with no verified quote is flagged `unsupported` and scored as wrong.

## Results

| Run | Companies | Accuracy | Citation support | Unsupported | Abstention P/R | Retrieval recall | Cost / company |
|---|---|---|---|---|---|---|---|
| baseline (Sonnet 5, BM25 k=8) | BILL, RPD | 94.7% | 93.8% | 3.1% | 83% / 100% | 95% | $0.37 |
| citation check ignores `$` | BILL, RPD | 97.4% | 96.9% | 0.0% | 83% / 100% | 95% | $0.37 |

Tuning-set numbers only (not the held-out company). Retrieval recall = the golden number appears in the retrieved chunks (19/20 numeric items). Cost / company is answering cost; judging adds ~$0.10.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and an Anthropic API key.

```
cp .env.example .env        # add ANTHROPIC_API_KEY and your email for EDGAR's User-Agent
./fr build BILL             # fetch + parse + index
./fr run BILL               # answered checklist -> runs/BILL_<time>.md
./fr eval --label baseline  # score against the golden set -> results/
```

## Layout

```
checklist/checklist.json   40 questions, written from scratch
golden/manual.jsonl        hand-built golden items (with source quotes)
golden/golden.jsonl        generated: XBRL items + manual items
prompts/                   answer and judge prompts
filingroom/                edgar, parse, index, answer, evaluate, cli
results/                   one file per eval run (committed)
CHANGELOG-evals.md         one line per run: what changed, what moved
```
