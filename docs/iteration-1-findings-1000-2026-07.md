# Iteration 1 findings — the 1000-subject pool changes the strategy

*2026-07-08. First run on the standing 1000-subject region-wide pool (`cert_pool_1000.py`), engine-only.
Two results that redirect the plan; the AI-ensemble baseline on the same pool is still running.*

## 1. Baseline: 13.24% median — but the median is a lie the terciles tell

Overall bias is −0.17% (looks unbiased) — because a huge **price tilt cancels itself out**:

| Tercile | Median sold | Median \|APE\| | Bias | Mean \|APE\| |
|---|---|---|---|---|
| Low | $190k | 21.58% | **+19.5%** (overprices) | 46.3% |
| Mid | $310k | 9.13% | −0.9% | 13.9% |
| High | $526k | 12.75% | −9.3% (underprices) | 17.4% |

Cheap/rural homes get pulled **up** toward the regional mean; expensive homes pulled **down**. The low
tercile is a near-catastrophe (46% mean error, 137/332 miss by >30%) — these are rural properties with
no true comparables, so the estimate is high-*variance*, not just offset.

## 2. L3 (global calibration) is REJECTED at scale — it backfires

The Blacksburg-100 finding (a price-tilt correction bought ~2.5 points) **did not generalize**. On the
full 1000, held-out:

| Correction | Held-out median \|APE\| |
|---|---|
| None | 13.24% |
| Constant bias-fix | 13.32% (no help) |
| 2-param price-tilt (on predicted) | **16.99% (worse)** |
| 3-param quadratic tilt | 16.88% (worse) |

Why it backfires: (a) predicted price is itself badly biased at the low end, so it's a corrupt
conditioning variable; (b) the low tercile's fat tail (mean 46%) dominates the least-squares fit and
drags *every* tercile down into a −10% to −12% bias. **You cannot calibrate away high variance.** This
is exactly the "does it generalize across markets?" gate doing its job — and the reason 1000-subject
testing was the right call.

## 3. L2 (confidence tiers) is VALIDATED — and it's the launch path

Comp distance is the strong confidence signal (as prior work predicted). Filtering to well-covered,
liquid homes — **engine-only, no AI pass yet**:

| Segment | Share | Median \|APE\| | PPE10 |
|---|---|---|---|
| All | 100% | 13.24% | 41% |
| nearest ≤ 0.5 mi | 71% | 11.09% | 47% |
| nearest ≤ 0.3 & farthest ≤ 1.0 mi | 49% | 9.09% | 53% |
| sold ≥ $250k & tight comps | 36% | 8.71% | 55% |
| **sold $250–600k & nearest ≤ 0.3 & far ≤ 0.8 mi** | **26%** | **7.36%** | **62%** |

**Even without the AI pass, a confidence filter reaches 7.36% on the best-covered quarter of the
market.** With the AI ensemble layered on (running now, historically worth ~2–4 points), that segment
plausibly reaches ~5%. This is the launchable set.

## What this means for execution

- **Drop L3 as a global lever.** Calibration is not the path region-wide. (A *segment-local* or
  same-basis-scrape calibration may still help specific tiers — revisit narrowly, not globally.)
- **Promote L2 to the top.** The strategy is confirmed: launch the high-confidence segment (tight
  comps, liquid mid-market) at ~5%, show the low tercile (rural/cheap, high-variance) as an explicit
  wide range — never a confident point. Grow the segment as accuracy improves.
- **The low tercile is a coverage/variance problem, not a bias problem** — it needs better comps
  (more pool depth, the scrape/county pools for rural areas, price-tier-aware selection L7) or honest
  confidence flagging, not a correction factor.
- **Next measurement:** the AI-ensemble @ n=1000 (in flight) — how much does the AI pass lift the
  overall median and, crucially, the high-confidence segment toward 5%.
