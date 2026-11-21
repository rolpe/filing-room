# Comparison on 40 paired items

Base: 2026-09-27_1635 HOLDOUT-box (pipeline) · Other: 2026-11-21_1100 HOLDOUT-box (agent)

| Metric | Base | Other |
|---|---|---|
| Accuracy | 89.7% (35/39; 76.4–95.9) | 97.4% (38/39; 86.8–99.5) |
| Accuracy: numeric | 92.3% (12/13; 66.7–98.6) | 100.0% (13/13; 77.2–100.0) |
| Accuracy: judged | 86.4% (19/22; 66.7–95.3) | 95.5% (21/22; 78.2–99.2) |
| Accuracy: abstain | 100.0% (4/4; 51.0–100.0) | 100.0% (4/4; 51.0–100.0) |
| Citation support (judge: yes, of answered) | 100.0% (33/33; 89.6–100.0) | 97.1% (33/34; 85.1–99.5) |
| Unsupported claims (of answered) | 0.0% (0/33; 0.0–10.4) | 0.0% (0/34; 0.0–10.2) |
| Abstention precision | 57.1% (4/7; 25.0–84.2) | 66.7% (4/6; 30.0–90.3) |
| Abstention recall | 100.0% (4/4; 51.0–100.0) | 100.0% (4/4; 51.0–100.0) |
| Verified but wrong (app status) | 3.1% (1/32; 0.6–15.7) | 0.0% (0/33; 0.0–10.4) |
| Wrong answers caught as To review | 0.0% (0/4; 0.0–49.0) | 0.0% (0/1; 0.0–79.3) |
| False not found | 8.3% (3/36; 2.9–21.8) | 5.6% (2/36; 1.5–18.1) |
| Answer cost per question ($) | 0.0248 (run average over its 40 items) | 0.0294 (sum over these items) |
| Latency mean / median / p90 (s) | 4.3 / 3.6 / 7.0 | 7.2 / 6.0 / 12.0 |
| Model calls / tool calls per question | 1 / 0 | 2.98 / 2.27 |
| Questions that hit a limit | 0 | 1 |

Flips: 3 items changed (3 better, 0 worse); too few to tell from noise (sign test p = 0.25).
- Right only in other: BOX:bs_cash, BOX:gov_structure, BOX:rev_customers
- Only partly supported by their quotes (other): BOX:risk_key

Rates show the count and a 95% Wilson interval. Judge cost is not included in answer cost.
