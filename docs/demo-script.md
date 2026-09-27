# 3-minute demo script

Total API cost to record this: about $0.05. Everything else is reading files that already exist.

1. **(20s) The problem.** Open `checklist/checklist.json` and scroll: 40 questions a deal team asks early, answered here only from SEC filings.
2. **(40s) One live answer.** Run `./fr ask RPD mgmt_ceo`. Point out: it answers Wael Mohamed (CEO since June 1, 2026), cites the 10-Q, and explains that the newer filing supersedes the April proxy. Mention that this exact question was a bug found and fixed through the evals.
3. **(40s) The full checklist.** Open the latest `runs/BILL_*.md`: every answer has a quote and a link to the filing. Show one "not found in the filings" answer and say why that's the right behavior.
4. **(30s) The memo.** Open the latest `runs/BILL_*_memo.md`: bracketed numbers on every factual sentence link to the Sources list. Mention the claim check.
5. **(50s) How you know it works.** Open `CHANGELOG-evals.md` and the README results tables: the progression from 94.7% on an easy test, to 91.0% on the honest one, to 93.6% after fixes, then the held-out company at 89.7%. Close on "what I'd do next".
