# Product

<!-- impeccable:product-schema 1 -->

## Platform

web (desktop; local only)

## Stack

React + TypeScript + Vite in `web/`, with React Router and TanStack Query; hand-written CSS from one tokens file. No UI kit, no Tailwind, no chart library. Served as a static build by the project's stdlib Python server (`./fr ui`, `filingroom/server.py`), which also provides the JSON API.

## Users

Primary: deal-team associates and VPs on take-private teams, and public-equity analysts, doing a first look at a US-listed company: is there something here, and what would we need to diligence first?

They read SEC filings for a living, know what a 10-K, a proxy and a convertible note are, and don't trust a number until they've seen where it came from. They work on a laptop or a desktop monitor, often with a filing open in another window.

## Product Purpose

filing-room is a screening tool. Add a company and, in a few minutes and for about $1.25 of model usage, it reads the latest two 10-Ks, four 10-Qs, proxy statement and earnings release from SEC EDGAR, and produces:

- 39 findings in six groups (ownership and governance; capital structure and allocation; revenue and customers; profitability and cash flow; people; competition and risk), each a labelled fact with a value, a period and the filing quotes behind it;
- five years of financials from the SEC's structured XBRL data;
- a screening memo whose factual sentences cite findings;
- a per-company Q&A thread for follow-up questions, answered only from the filings.

Success: a user can go from "never looked at this company" to a defensible first view, and can check any statement in one click.

## Positioning

A first look you can check. Every finding is tied to quotes that code has string-matched against the filing, and the passage is one click away with the quote highlighted. What the filings don't disclose is said plainly. Findings that need a human look are marked To review, with the reason. It is a screening tool, not a diligence report or an investment recommendation.

## Operating Context

Runs on the user's own machine at `http://127.0.0.1:8787`. Coverage starts empty. Companies are any SEC registrant that files 10-Ks; foreign filers (20-F/40-F) and companies missing the needed filings are refused at the add step with the reason.

## Capabilities and Constraints

Screens: Coverage (home) with find-or-add; company workspace with Overview, Findings, Screening memo, Q&A and Filings tabs; Usage; and, under a Developer group in the sidebar, Evaluation (Runs, Golden set, Run an eval).

- Findings have three statuses: Verified, To review, Not disclosed. Users can add notes, flag a finding for review, and mark a To review finding as reviewed after checking it.
- Exports: findings as CSV with source URLs; memo as Markdown; memo print stylesheet.
- Paid actions: screening a company (about $1.25; $2.50 hard stop per company; $3/day cap) and asking a question (up to $0.05; $1/day cap). The cost is shown before the action and confirmed in the request; the actual cost is shown after. One screening runs at a time; an interrupted one resumes without paying again for answers already produced.
- Local only: loopback bind, Host-header check, custom header on POSTs.
- Evaluation area (developer tools; `FILINGROOM_DEV_TOOLS`, default on): shows how the answering engine is measured: recorded eval runs against the pass bar set before building (accuracy at least 85%, citation support at least 90%, unsupported claims at most 10%), the held-out company's single run, each graded item with its expected answer, the judge's verdict and the filing passage, and the golden set. It can start a full run or a spot check (cost shown and confirmed, $3/day cap) and a free retrieval check. Each run leads with whether the app's own statuses can be trusted (answers it would mark Verified that were wrong; wrong answers it would flag To review; false Not disclosed), every rate shows a 95% interval, and run-to-run changes say whether they can be told from noise. The owner reviews the hand-built answer key here: each item beside its highlighted source passage, marked checked or needing a fix. This is the only place eval vocabulary (golden set, held-out company, judge) appears, each defined in a line where it first shows. It must read well on a shared screen.

## Brand Commitments

Name: filing-room (lowercase). Voice: plain, precise, unhedged; say what the filings show and what they don't. No tutorial paragraphs, no marketing tone, no jargon about how the tool was evaluated.

Standing preference: substance and clearly laid-out information over clever design; nothing cute. The quality bar is AlphaSense, Hebbia and S&P Capital IQ.

## Evidence on Hand

Everything shown comes from SEC EDGAR filings, SEC XBRL company facts, and the model's answers to the checklist with their verified quotes. There are no testimonials, ratings or benchmarks to show in the app; none may be invented.

## Product Principles

1. Every claim is one click from its source passage.
2. Say what's not disclosed, and what needs review, as plainly as what's verified.
3. Spending money is always explicit: cost before, cost after, capped per day.
4. Dense and calm: tables, tabular numerals, one accent for highlighted filing text.
5. Local and private by construction.
