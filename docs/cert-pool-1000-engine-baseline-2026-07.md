# 1000-subject engine-only baseline — region-wide (July 2026)

*Run 2026-07-08 · 1000 random NRV subjects (seed 20260708, reproducible) across all covered cities/counties · as-of 2026-06-30 · leave-one-out · n_comps=6 · 18-mo lookback · **engine only, no AI pass, no AVM**. The standing certification pool — every iteration re-runs this exact 1000-subject draw so gains are trustworthy at scale.*

| Metric | Value |
|---|---|
| Scored / resolve | 998/1000 (99.8%) |
| **Median \|APE\|** | **13.24%** |
| Mean \|APE\| | 25.85% |
| Median signed bias | -0.17% |
| PPE5 / PPE10 / PPE20 | 23.9% / 41.0% / 65.6% |
| Misses >20% / >30% | 343 / 222 |

## By price tercile (where the tail lives)

| Tercile | Median sold | Median \|APE\| | Bias | PPE10 |
|---|---|---|---|---|
| low | $190,000 | 21.58% | +19.53% | 29.5% |
| mid | $310,000 | 9.13% | -0.92% | 53.0% |
| high | $525,800 | 12.75% | -9.3% | 40.4% |

This engine-only, no-AI, no-AVM number is the **floor** — the reproducible backbone for the iteration loop (see `accuracy-to-5pct-plan-2026-07.md`). L1 (productionize the ensemble) and the AI-pass certification run on the SAME 1000 subjects via `get_subjects()`.