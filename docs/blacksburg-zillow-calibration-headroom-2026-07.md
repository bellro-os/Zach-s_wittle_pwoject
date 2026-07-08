# Improving Zillow-only median |APE| — calibration headroom (Blacksburg, July 2026)

*Analysis on the n=100 Blacksburg Zillow-only engine run (`blacksburg-zillow-engine-100-2026-07.md`,
median |APE| 15.92%, bias −7.82%). Post-hoc corrections cross-validated 5-fold (held-out), Zillow
data only — no MLS, no county, no new sources.*

## The question
Going off Zillow data alone, is there any way to improve the 15.92% median |APE|? **Yes — the error
is dominated by a correctable price-tilt bias, not by comp noise.**

## The diagnosis: the engine underprices progressively harder as homes get more expensive

Bias by **predicted-value** tercile (what you can see at inference — no ground-truth leak):

| Predicted band | Median bias | Median \|APE\| |
|---|---|---|
| Low (~$310k) | −2.6% | 9.6% |
| Mid (~$394k) | −9.2% | 14.8% |
| High (~$606k) | −15.0% | 19.4% |

This is classic **regression-to-the-mean from thin high-end comp coverage**: expensive homes get
pulled down by cheaper comps the scrape pool over-supplies, so the top of the market is
systematically underpriced. It is a *shape* problem (a price tilt), which is exactly what
calibration fixes.

## The headroom (held-out, deployable)

| Correction | Held-out median \|APE\| | Δ |
|---|---|---|
| None (current) | 15.92% | — |
| Constant bias-fix (bias-zeroing multiplier) | 14.46% | −1.5 |
| **Price-tilt on predicted value** (regress bias on log-predicted, apply) | **13.47%** | **−2.5** |

A single global multiplier only buys ~1.5 points because the bias isn't uniform. Correcting the
*tilt* — a two-parameter per-region calibration (level + price-slope) learnable from held-out
scraped sales — buys ~2.5 points, taking Zillow-only from **15.9% → ~13.5%**, deployable, no new data.

## Beyond post-hoc calibration (compounding, still Zillow-only)
1. **Detail-sweep enrichment** — `year_built`, `price_history` (→ prior-sale anchor), and
   `property_subtype` from `home_type` are all Zillow detail-page fields. They attack the tilt at its
   *root* (better high-end comp matching) rather than papering over it, and they also unlock the AI
   ensemble pass, which on thin packets currently hurts.
2. **Price-tier-aware comp selection** — for a high-value subject, weight toward same-price-band comps
   so the pool stops dragging the estimate down.
3. **The AI ensemble pass** — worth ~2–4 points on MLS; only becomes usable once (1) enriches the packets.

## Context
The prior Montgomery same-basis dial-in already reached **9.86% median** on scrape-only with a
properly calibrated sqft factor — that run used Zillow-*basis* subjects (consistent basis). This
Blacksburg test uses MLS-basis subjects (ground truth = MLS sold price), which is what surfaces the
cross-basis price tilt. So a true Zillow-alone product (Zillow subjects + Zillow comps + this tilt
calibration) should land **below** the 13.5% shown here.

**Recommendation:** extend the dial-in loop (`cma_dial_region.py` / `cma_regions.json`) from a single
sqft-factor knob to a two-parameter **level + price-slope** regional calibration, fit on held-out
scraped sales, and re-measure with Zillow-basis subjects. That is the concrete path from ~16% toward
the ~10–13% range on Zillow alone.
