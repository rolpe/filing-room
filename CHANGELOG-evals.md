# Eval changelog

One line per eval run: what changed, what moved.

| Run | Companies | Change | Acc % | Cite support % | Unsupported % | Abstain P/R | Retrieval % | $ answer/judge |
|---|---|---|---|---|---|---|---|---|
| 2026-09-27_1535 baseline | BILL,RPD | first real run: BM25 k=8, prompt v1 (claude-sonnet-5, medium, k=8) | 94.7 | 93.8 | 3.1 | 83.3/100.0 | 95.0 | 0.7458/0.2018 |
| 2026-09-27_1536 dollar-norm | BILL,RPD | citation check ignores $ signs (RPD revenue quote had $ the table row lacks) (claude-sonnet-5, medium, k=8) | 97.4 | 96.9 | 0.0 | 83.3/100.0 | 95.0 | 0.7472/0.203 |
| 2026-09-27_1554 expand2 | BILL,RPD | add prev/next neighbors of top-2 hits (claude-sonnet-5, medium, k=8, expand=2) | 100.0 | 97.0 | 0.0 | 100.0/100.0 | 100.0 | 0.9045/0.2082 |
| 2026-09-27_1600 memo | BILL | memo prompt v1 (sample 1) (claude-sonnet-5) | – | – | 0.0 (0/36 sentences) | – | – | 0.1471 |
| 2026-09-27_1601 memo | BILL | memo prompt v1 (sample 2) (claude-sonnet-5) | – | – | 5.9 (2/34 sentences) | – | – | 0.1547 |
| 2026-09-27_1602 memo | RPD | memo prompt v1 (sample 1) (claude-sonnet-5) | – | – | 5.0 (2/40 sentences) | – | – | 0.1477 |
| 2026-09-27_1602 memo | RPD | memo prompt v1 (sample 2) (claude-sonnet-5) | – | – | 5.1 (2/39 sentences) | – | – | 0.14 |
| 2026-09-27_1604 memo | BILL | memo prompt v2: citation discipline (sample 1) (claude-sonnet-5) | – | – | 2.8 (1/36 sentences) | – | – | 0.1525 |
| 2026-09-27_1604 memo | BILL | memo prompt v2: citation discipline (sample 2) (claude-sonnet-5) | – | – | 0.0 (0/39 sentences) | – | – | 0.1509 |
| 2026-09-27_1605 memo | RPD | memo prompt v2: citation discipline (sample 1) (claude-sonnet-5) | – | – | 2.3 (1/43 sentences) | – | – | 0.1415 |
| 2026-09-27_1606 memo | RPD | memo prompt v2: citation discipline (sample 2) (claude-sonnet-5) | – | – | 2.3 (1/43 sentences) | – | – | 0.1502 |
| 2026-09-27_1614 golden-v2 | BILL,RPD | golden set expanded to full checklist (38 -> 80 items); new baseline (claude-sonnet-5, medium, k=8, expand=2) | 91.0 | 92.5 | 0.0 | 61.5/100.0 | 100.0 | 1.9287/0.5246 |
| 2026-09-27_1616 recency | BILL,RPD | current-period questions: boost newest 10-Q/10-K + 8-K, always search 10-Q/8-K, tell model newest filings win (claude-sonnet-5, medium, k=8, expand=2) | 93.6 | 94.0 | 0.0 | 61.5/100.0 | 100.0 | 1.9122/0.5083 |
| 2026-09-27 spot-check | RPD | CEO question also searches MD&A/8-K: RPD:mgmt_ceo ✗→✓ (Wael Mohamed, CEO since 2026-06-01); BILL:mgmt_ceo still ✓. 2-item spot check, not a full eval | – | – | – | – | – | 0.05 |
| 2026-09-27_1635 HOLDOUT-box | BOX | held-out company, first and only run on system frozen at tag frozen-for-holdout (claude-sonnet-5, medium, k=8, expand=2) | 89.7 | 100.0 | 0.0 | 57.1/100.0 | 90.9 | 0.9933/0.2428 |
