---
version: 1
slug: "ui-index-html"
primary_target: "ui/index.html"
related_targets: []
---

# Surface: filing-room local app (ui/)

Mode: Operate. A presenter-driven research tool viewed on a laptop and over screen share.

Audience and job: the author demos to a mix of PE/finance people and technical interviewers; the viewer must see an answer, the exact filing passage behind it, and the measured accuracy within minutes. Secondary: the author's own golden-set review.

Proof on hand: real API data only (checklists, memos, evals, search, golden items). Paid action: Ask (all three companies), cost shown before and after, $1/day cap. Box's Checklist shows its single recorded test run, which Ask never changes.

Memorable moment: click an answer and the filing opens beside it with the quote highlighted in place.

Unresolved: none blocking. Quality bar: AlphaSense, Hebbia, S&P Capital IQ.

## Direction contract

THESIS: A research tool where every answer sits beside its source. It refuses the AI-dashboard default: no KPI tiles, no chat bubbles, no gradients.

OWN-WORLD: White document ground, graphite ink, hairline gray rules, one deep ocean-blue accent for interaction, yellow marker highlight reserved for quoted source text, status as small icon+word marks (verified, not found, unsupported). System UI sans for the app; a document serif (Charter) only inside the filing pane; tabular numerals everywhere.

STORY: The viewer understands that answers are extracted from SEC filings, believes them because the quote is right there, and sees the measured hit rate including failures.

FIRST VIEWPORT: Top bar: wordmark, company switcher, view tabs, spend meter. A slim result strip under it. Left 40%: the checklist grouped by category, the selected row active. Right 60%: the answer (question, answer at reading size, period, status, eval grade), then the filing pane open at the passage with the quote highlighted. Primary action: select a question; Ask sits in the top bar.

FORM: category standard (canon, safer register), executed against AlphaSense, Hebbia and S&P Capital IQ. Seed key 87195c45. Signature interaction: selecting an answer or citation scrolls the filing pane to the passage and the highlight sweeps across the quote once; hovering a citation marks its highlight. Motion grammar: 150-200ms ease-out for pane changes, one 400ms highlight sweep, nothing else moves; reduced motion shows the highlight instantly. Keyboard: up/down steps questions for presenting.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
