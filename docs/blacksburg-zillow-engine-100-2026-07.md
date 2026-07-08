# Blacksburg engine-only accuracy on Zillow-scrape data (n=100, July 2026)

*Run 2026-07-08 · 100 random sold Blacksburg subjects (seed 42, reproducible) · as-of 2026-06-30 · n_comps=6 · 18-month lookback · leave-one-out (spatial ~28 m + street-address self-exclusion, temporal as-of freeze). **Engine only — no AI pass** (no hygiene, no blind Haiku). Comp pool = the Zillow-scrape parquet ALONE (`scratch/zillow_test/zillow_listings.parquet`).*

## Result

| Metric | Value |
|---|---|
| Scored / resolve rate | 100/100 (100.0%) |
| **Median \|APE\|** | **15.92%** |
| Mean \|APE\| | 20.42% |
| Median signed bias | -7.82% |
| PPE5 (within 5%) | 16.0% |
| PPE10 (within 10%) | 32.0% |
| PPE20 (within 20%) | 62.0% |
| Misses > 20% / > 30% | 38 / 23 |
| 90th-percentile \|APE\| | 44.33% |
| Median comp count | 6.0 |
| Median nearest / farthest comp | 0.17 mi / 0.88 mi |

## Worst 8 misses

| Subject | Sold | Estimate | Error | Comps @ nearest |
|---|---|---|---|---|
| 646 Jennelle Road | $129,900 | $271,907 | +109.3% | 6 @ 1.4 mi |
| 1231 Huff Lane | $227,000 | $394,270 | +73.7% | 6 @ 0.45 mi |
| 4489 Preston Forest Drive | $325,000 | $560,111 | +72.3% | 6 @ 0.39 mi |
| 5236 MT. TABOR Road | $158,000 | $244,301 | +54.6% | 6 @ 9.02 mi |
| 1865 PLANK Drive | $1,040,000 | $505,855 | -51.4% | 6 @ 2.28 mi |
| 9169 BEAR CLAW FARMS Lane | $731,640 | $361,884 | -50.5% | 6 @ 1.62 mi |
| 3473 Natalies Way | $994,332 | $502,303 | -49.5% | 6 @ 0.14 mi |
| 602 JEFFERSON Street | $1,350,000 | $684,325 | -49.3% | 6 @ 0.07 mi |

## Context

This isolates the bare comp engine on scraped data (no AI ensemble). It is the n=100 scale-up of Arm B engine-only from the head-to-head (`blacksburg-scrape-vs-mls-ai-2026-07.md`, which was n=20 at 6.48% median |APE|). The Zillow pool carries NULL list_price/DOM and sparse subtype/year_built by design; sqft is pre-scaled 0.76 to the MLS basis at build time.