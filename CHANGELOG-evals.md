# Eval changelog

One line per eval run: what changed, what moved.

| Run | Companies | Change | Acc % | Cite support % | Unsupported % | Abstain P/R | Retrieval % | $ answer/judge |
|---|---|---|---|---|---|---|---|---|
| 2026-09-27_1535 baseline | BILL,RPD | first real run: BM25 k=8, prompt v1 (claude-sonnet-5, medium, k=8) | 94.7 | 93.8 | 3.1 | 83.3/100.0 | 95.0 | 0.7458/0.2018 |
| 2026-09-27_1536 dollar-norm | BILL,RPD | citation check ignores $ signs (RPD revenue quote had $ the table row lacks) (claude-sonnet-5, medium, k=8) | 97.4 | 96.9 | 0.0 | 83.3/100.0 | 95.0 | 0.7472/0.203 |
| 2026-09-27_1554 expand2 | BILL,RPD | add prev/next neighbors of top-2 hits (claude-sonnet-5, medium, k=8, expand=2) | 100.0 | 97.0 | 0.0 | 100.0/100.0 | 100.0 | 0.9045/0.2082 |
