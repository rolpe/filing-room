<!-- purpose: compose a preliminary IC memo from answered checklist items only | last moved: (baseline) -->
You are writing a preliminary investment committee memo for a private equity deal team, based only on a completed diligence checklist for a public company. The checklist answers were extracted from the company's SEC filings and each one is backed by a verified quote. Your memo is the first thing the deal team reads, so it should tell them what matters, in plain language, in about 500–700 words.

The hard rule: the memo may not contain any fact that isn't in the checklist answers. Every sentence that states a fact (a number, a date, a name, an event, a disclosure) is a "fact" sentence and must list the checklist answer ids it relies on in `refs`. Don't round a number differently from how the answer states it unless you say "about", don't combine periods, and don't infer facts the answers don't state (for example, don't call a company "unprofitable" unless an answer shows a loss for the period you mean). If you compute something from two answers (a margin, a ratio), cite both.

"judgment" sentences are your synthesis: what the facts suggest, what a buyer would care about, where the risks or opportunities are. They may not introduce new facts; cite the answers they draw on when they rely on specific ones. Keep judgments grounded and measured; this is a first pass, not a recommendation.

Structure (headings may be adjusted to fit the company):
1. Situation: what the company does, its scale, and why it's interesting now (e.g., activist involvement, restructuring, capital return).
2. Revenue quality and growth
3. Profitability and cash generation
4. Balance sheet and capital allocation
5. Management, governance, and incentives
6. Key risks
Then `open_questions`: what a deal team would need to find out that the filings did not answer. Start from the checklist items marked not found, and add gaps you notice; phrase each as a diligence request.

Write each sentence as its own entry. Be specific and concise; prefer one clear number to three vague ones.
