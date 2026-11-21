# Agent mode eval changelog

One line per agent-mode eval run (results in results/agent/). The pipeline's runs are in CHANGELOG-evals.md.

| Run | Companies | Items | Change | Acc % | Unsupported % | Abstain P/R | Calls/tools per q | Hit limit | $ per q | $ answer/judge |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-21_1040 agent20 | BILL,RPD | 20 (subset) | first 20-item stratified subset (seed 20261121), default budgets (claude-sonnet-5, medium, {"max_model_calls": 6, "max_tool_calls": 8, "max_tokens": 100000, "repair": false}) | 95.0 | 0.0 | 100.0/100.0 | 3.0/2.4 | 1 | 0.0323 | 0.6458/0.1364 |
| 2026-11-21_1047 agent80 | BILL,RPD | 80 | first full agent-mode eval, default budgets (claude-sonnet-5, medium, {"max_model_calls": 6, "max_tool_calls": 8, "max_tokens": 100000, "repair": false}) | 94.9 | 0.0 | 80.0/100.0 | 2.92/2.24 | 1 | 0.0295 | 2.3628/0.5524 |
| 2026-11-21_1100 HOLDOUT-box | BOX | 40 | held-out company, first and only agent-mode run; prompts/agent.md and budgets unchanged since the 80-item tune-set run (claude-sonnet-5, medium, {"max_model_calls": 6, "max_tool_calls": 8, "max_tokens": 100000, "repair": false}) | 97.4 | 0.0 | 66.7/100.0 | 2.98/2.27 | 1 | 0.0294 | 1.1768/0.2496 |
