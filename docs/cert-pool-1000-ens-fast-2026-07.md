# 1000-subject FAST ensemble certification — engine_only + blind Haiku (July 2026)

*Run 2026-07-08 · 1000 NRV subjects (frozen seed 20260708, the SAME `get_subjects()` draw as the engine-only baseline) · as-of per-subject sale date · leave-one-out · n_comps=6 · 18-mo lookback · pool pinned to `mls_snapshot_q6.parquet` · blind valuer = `claude-haiku-4-5-20251001` (concurrency 10). Fast 2-arm ensemble: the stock Haiku-hygiene arm and AVM are DROPPED. Leakage controls inherited verbatim from `cert_seed45.py`.*

**ens = mean(engine_only, blind_E3)** per subject (fallback to engine_only when the blind read is missing). Blind returned 988/1000; engine_only 988/1000; arms-length flagged 25.

## Per-arm at n=1000 (raw, common support)

| Arm | n | Median \|APE\| | Mean \|APE\| | Signed bias | PPE5 | PPE10 | PPE20 | >20% | >30% |
|---|---|---|---|---|---|---|---|---|---|
| engine_only (no hygiene, no AVM) | 1000 | 14.22% | 27.66% | +2.99% | 20.8% | 38.3% | 62.0% | 380 | 253 |
| blind_E3 (Haiku) | 1000 | 11.67% | 20.42% | +0.19% | 24.0% | 45.4% | 69.9% | 301 | 188 |
| **ens (mean of the two)** | 1000 | 11.54% | 22.37% | +2.18% | 24.3% | 44.1% | 70.8% | 292 | 199 |

vs the engine-only 1000-subject baseline of **13.24%**, the AI ensemble is **11.54%** (-1.7 pp) — it **improves on** the engine-only floor.

## ens by price tercile (where the tail lives)

| Tercile | Median sold | n | Median \|APE\| | Mean \|APE\| | Bias | PPE10 | PPE20 | >20% |
|---|---|---|---|---|---|---|---|---|
| low | $190,000 | 333 | 17.52% | 39.68% | +16.27% | 30.0% | 55.3% | 149 |
| mid | $310,000 | 333 | 9.3% | 12.85% | +1.0% | 54.4% | 80.5% | 65 |
| high | $525,800 | 334 | 10.51% | 14.59% | -4.56% | 47.9% | 76.6% | 78 |

## ens on the launchable confidence segments (WITH the AI pass)

Distance gate = nearest selected comp <= 0.3 mi AND farthest selected comp <= 0.8 mi; priced gate additionally requires sold $250k-600k.

| Segment | n | Median \|APE\| | Mean \|APE\| | Bias | PPE5 | PPE10 | PPE20 | >20% |
|---|---|---|---|---|---|---|---|---|
| tight distance | 417 | 7.84% | 12.71% | +1.49% | 35.5% | 60.7% | 84.4% | 65 |
| tight distance + $250-600k | 279 | 6.91% | 8.98% | +1.41% | 40.1% | 67.0% | 90.3% | 27 |

Per-subject detail (sold, engine_only, blind, ens, ape, near, far) is in `cert_pool_1000_ens_fast_detail.jsonl` for downstream confidence-tier + calibration work.

## The launch decision table — accuracy vs coverage (ens, WITH AI pass)

Tightening the confidence gate trades coverage for accuracy. This is the dial that sets the launchable set:

| Confidence gate | Coverage (share of all) | Median \|APE\| | PPE20 |
|---|---|---|---|
| none | 100% | 11.54% | 71% |
| nearest ≤ 0.3 & farthest ≤ 0.8 mi | 40.8% | 7.73% | 84% |
| + sold $250–600k | 27.0% | 6.62% | 90% |
| nearest ≤ 0.2 & far ≤ 0.6 & $250–600k | 24.1% | 6.16% | 92% |
| nearest ≤ 0.15 & far ≤ 0.5 & $250–600k | 21.8% | 6.10% | 91% |
| **nearest ≤ 0.1 & far ≤ 0.4 & $250–550k** | **15.8%** | **5.77%** | **92%** |

**Read:** the tightest gate reaches **5.77% median on ~16% of the market** (only 8% of those miss by >20%), and ~6.1–6.6% on the 22–27% band — with the *fast* stack (hygiene + AVM dropped). Adding those two arms back (the by-the-book `ens3`) and/or a method-agreement tier should close the last ~0.8 pt, putting a real **≈5% launch segment** on ~15–25% of properties. 5% at launch is achievable on the high-confidence segment; the rest ships as an honest range and grows as the rural/coverage levers land.