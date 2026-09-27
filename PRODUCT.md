# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated: plain HTML, CSS and JavaScript (ES modules) with no build step, served by the existing zero-dependency Python server (`./fr ui`, `filingroom/server.py`). The user is "fine with additional components as long as you don't go too crazy": a small vendored library is acceptable where it clearly earns its place; no frontend framework or npm toolchain.

## Users

Primary: the project's author, who presents it in interviews. The UI's main job is **interview demos**: screen-sharing or a ~3-minute recording that walks someone through what the system does and why its answers can be trusted.

Audience watching those demos: a mix of finance / PE professionals (who care about the diligence content and whether they can trust it) and technical interviewers (who care about how it works and how it's measured).

Secondary: the author's own review work (verifying golden answers, browsing results, asking the occasional question).

## Product Purpose

filing-room answers a 40-question private-equity diligence checklist for a public company using only its SEC filings, backs every answer with a verbatim quote that code has verified against the filing, drafts an IC-style memo from those answers, and measures itself against a golden answer set that includes a company held out until the end. The UI makes that visible. Success: within a few minutes a viewer has seen an answer, the exact filing passage behind it, and the measured accuracy, including where it fails.

## Positioning

The claim is verifiability and honest measurement, not model cleverness: every answer traces to a machine-verified quote with a link to sec.gov; "not found in the filings" is a first-class answer; and accuracy is measured, including a held-out company (Box: 89.7%) run once on a frozen system (git tag `frozen-for-holdout`).

## Operating Context

Runs only on the author's Mac at `http://127.0.0.1:8787` (`./fr ui`), in a desktop browser, typically on a laptop screen and often screen-shared or recorded, so legibility at shared-screen resolution matters.

Companies: BILL (June fiscal year; Starboard cooperation agreement), Rapid7 / RPD (December FY; JANA activist stake; CEO change June 1, 2026), Box (January FY; held-out company). Documents per company: two 10-Ks, four 10-Qs, the latest proxy (DEF 14A), the latest earnings-release 8-K, all from SEC EDGAR with links back to sec.gov.

## Capabilities and Constraints

Surfaces backed by the existing API (`filingroom/server.py`):
- Companies overview: situation, fiscal year-end, filings loaded, eval score, tune vs. holdout.
- Checklist per company: 40 questions by category; answer, status (answered / not_found / unsupported), value, period, confidence; verified quotes with filing links; the eval's grade against the golden answer.
- IC memo: sections of sentences, each citing checklist answers; sentences flagged by the claim check; open diligence questions.
- Eval history: metrics across runs (accuracy, citation support, abstention, retrieval, cost), failures per run, memo claim checks.
- Passage search (BM25, free): what retrieval returns for a query.
- Golden-set review: each hand-drafted golden item with its quote; a verify toggle writes `"verified": "human"` to `golden/manual.jsonl`.
- Ask: a live question to BILL or RPD (paid, ~$0.02–0.05).

Constraints:
- Local only: loopback bind, Host-header check, custom header required on POSTs.
- Ask is the only paid action, capped server-side at $1/day (`UI_MAX_USD_PER_DAY`); the UI must make cost explicit before and after. No UI path may trigger full checklist runs or evals.
- Box is read-only (held out); Ask is disabled for it.
- Terminology to keep: checklist, golden set, quote / citation, verified, not found, unsupported, held-out company, eval run, fiscal period labels like FY2026 and Q2 FY2027.

## Brand Commitments

Name: filing-room (lowercase). Voice: plain, precise, and honest about limits: failures and flagged sentences are shown, not hidden. No logo or other brand assets exist.

Standing preference (user, direction round 2026-09-27): substance and clearly laid-out information over clever visual design; nothing "cute". The UI follows the conventional grammar of front-office research tools and should sit credibly alongside AlphaSense, Hebbia and S&P Capital IQ, whose craft level is the quality bar.

## Evidence on Hand

Real outputs in the repo: `results/*.json` (six eval runs and memo claim checks), `runs/` (checklists and memos for BILL and RPD; Box answers come from its holdout eval), `golden/manual.jsonl` (84 hand-drafted items, mostly unverified "claude-draft"), `CHANGELOG-evals.md`, and the README results tables. Everything the UI shows must come from these files through the API. There are no users, testimonials, or benchmarks beyond them, and none may be invented.

## Product Principles

1. Every claim is one click from its source passage.
2. Show the measurement, including failures and weaknesses.
3. Explain as you go: part of the audience doesn't know what a 10-K or an eval is.
4. Spending money is always explicit.
5. Local and private by construction.
