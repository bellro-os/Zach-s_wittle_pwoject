# Blacksburg head-to-head: standard pool vs supplemental public-records sales source (July 2026)

*Run 2026-07-02 · 20 random sold Blacksburg subjects (seed 42, reproducible) · as-of 2026-06-30 · n_comps=6 · 18-month comp lookback · leave-one-out in both arms (temporal + parcel-id for Arm A; spatial ~28 m + street-address for Arm B).*

**Arm A (standard):** production comp pool — MLS + county records.
**Arm B (supplemental-only):** comp pool built exclusively from the supplemental public-records sales source (sqft pre-scaled 0.76 to the MLS basis; list-side fields — list price, DOM — NULL by design).

Subjects are Closed residential (RE_1) sales in Blacksburg, Montgomery County, VA, closed in the 18 months before 2026-06-30 with plausible price/sqft; each has a known sold price as ground truth, and its own sale is excluded from its comp pool in both arms.

## Per-property results

| # | Subject (street) | Sold | Arm A est | A err | Arm B est | B err | A comps @ nearest | B comps @ nearest | Closer |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 380 New Kent Road | $183,000 | $205,000 | +12.0% | $245,000 | +33.9% | 6 @ 0.0 mi | 6 @ 0.03 mi | A |
| 2 | 806 PETRA Pass | $760,000 | $880,000 | +15.8% | $720,000 | -5.3% | 6 @ 0.01 mi | 6 @ 0.11 mi | B |
| 3 | 1060 Treetop Ridge Road | $980,000 | $755,000 | -23.0% | $770,000 | -21.4% | 6 @ 0.4 mi | 6 @ 0.96 mi | B |
| 4 | 1602 CARLSON Drive | $749,000 | $650,000 | -13.2% | $675,000 | -9.9% | 6 @ 0.09 mi | 6 @ 0.09 mi | B |
| 5 | 207 Craig Drive | $519,000 | $485,000 | -6.6% | $505,000 | -2.7% | 6 @ 0.06 mi | 6 @ 0.13 mi | B |
| 6 | 218 Mountain Breeze Drive | $445,000 | $440,000 | -1.1% | $380,000 | -14.6% | 6 @ 0.02 mi | 6 @ 0.38 mi | A |
| 7 | 1113 BROOK Circle | $460,000 | $455,000 | -1.1% | $485,000 | +5.4% | 6 @ 0.11 mi | 6 @ 0.32 mi | A |
| 8 | 411 PATRICK HENRY Drive | $525,000 | $410,000 | -21.9% | $425,000 | -19.0% | 6 @ 0.14 mi | 6 @ 0.14 mi | B |
| 9 | 416 VINYARD Avenue | $989,900 | $750,000 | -24.2% | $760,000 | -23.2% | 6 @ 0.05 mi | 6 @ 0.05 mi | B |
| 10 | 2277 SCENIC RIDGE Circle | $799,900 | $610,000 | -23.7% | $660,000 | -17.5% | 6 @ 0.12 mi | 6 @ 0.12 mi | B |
| 11 | 1404 University City Boulevard | $151,200 | $185,000 | +22.4% | $210,000 | +38.9% | 6 @ 0.0 mi | 6 @ 0.16 mi | A |
| 12 | 103 Yorkshire Court | $377,500 | $360,000 | -4.6% | $365,000 | -3.3% | 6 @ 0.01 mi | 6 @ 0.07 mi | B |
| 13 | 9169 BEAR CLAW FARMS Lane | $731,640 | $450,000 | -38.5% | $410,000 | -44.0% | 6 @ 1.62 mi | 6 @ 1.62 mi | A |
| 14 | 309 Dunton Drive | $640,000 | $470,000 | -26.6% | $405,000 | -36.7% | 6 @ 0.18 mi | 6 @ 0.41 mi | A |
| 15 | 4928 Mount Tabor Road | $596,000 | $770,000 | +29.2% | $830,000 | +39.3% | 6 @ 1.18 mi | 6 @ 3.17 mi | A |
| 16 | 206 Givens Lane | $395,000 | $335,000 | -15.2% | $315,000 | -20.3% | 6 @ 0.26 mi | 6 @ 0.34 mi | A |
| 17 | 602 FLOYD Street | $810,000 | $815,000 | +0.6% | $840,000 | +3.7% | 6 @ 0.13 mi | 5 @ 0.22 mi | A |
| 18 | 2101 HENRY EAVES Drive | $209,900 | $350,000 | +66.7% | $365,000 | +73.9% | 6 @ 0.5 mi | 6 @ 3.28 mi | A |
| 19 | 612 Kentwood Drive | $645,000 | $570,000 | -11.6% | $715,000 | +10.9% | 6 @ 0.03 mi | 6 @ 0.05 mi | tie |
| 20 | 907 Lora Lane | $324,000 | $360,000 | +11.1% | $380,000 | +17.3% | 6 @ 0.18 mi | 6 @ 0.18 mi | A |

## Summary

| Metric | Arm A (standard) | Arm B (supplemental-only) |
|---|---|---|
| Scored / resolve rate | 20/20 (100.0%) | 20/20 (100.0%) |
| Median \|APE\| | **15.49%** | **18.27%** |
| Median signed bias | -5.59% | -4.29% |
| Median comp count | 6.0 | 6.0 |
| Median nearest comp | 0.11 mi | 0.17 mi |
| Median farthest comp | 0.56 mi | 0.92 mi |

**Win count (closer to actual sold price):** Arm A 11 · Arm B 8 · tie (within 1 pt) 1.

## Findings

1. **The supplemental pool alone CAN carry Blacksburg comp coverage — but not Blacksburg accuracy.** Arm B resolved all 20 subjects with a full comp slate (6 comps on 19 of 20) and a median nearest comp of 0.17 mi (vs 0.11 mi for Arm A), so coverage and comp locality are genuinely there. Accuracy, however, trails the standard pool by about 3 points at the median (18.3% vs 15.5% |APE|), and Arm A was the closer arm on 11 of 20 subjects vs 8 for Arm B. In a town this MLS-dense, the supplemental pool is a viable fallback, not a replacement.

2. **Where Arm B falls short is the fields it lacks, not the sales it lacks.** The supplemental pool carries no list price or days-on-market (NULL by design), no year_built, and no condition/remodel signal — so the engine loses its list-side anchors and age adjustment, and its comps run wider (median farthest comp 0.92 mi vs 0.56 mi). The worst B-only degradations were small/atypical homes where like-kind matching matters most (e.g., New Kent Rd +33.9% vs A's +12.0%; University City Blvd +38.9% vs +22.4%).

3. **The Montgomery-calibrated 0.76 sqft factor shows up as a mild positive skew.** Per subject, Arm B's estimate ran a median +3.2 points above Arm A's (positive shift on 15 of 20 subjects), and Arm B's overall bias is less negative than Arm A's (−4.3% vs −5.6%). Because the factor was calibrated on Montgomery County itself the skew stays mild here; expect it to be larger where local sqft conventions differ from the calibration county.

4. **The big misses are shared, not pool-specific.** On 7 of 20 subjects BOTH arms missed by more than 20% (e.g., Bear Claw Farms Ln −38.5%/−44.0%, Treetop Ridge Rd −23.0%/−21.4%, Henry Eaves Dr +66.7%/+73.9%). These are high-end custom, rural-acreage, or otherwise unusual properties — a subject-modeling limitation, not a comp-pool one, and this random sample drew several of them (which is why both medians sit above the county-wide figures).

5. **Consistent with the earlier 12-region test.** That run found Montgomery County MLS-dense with the standard arm ahead (median |APE| 9.9% vs 14.1% county-wide), so Arm A was expected to win here — and this 20-subject Blacksburg sample agrees on every axis: A wins the head-to-head count (11–8–1), the median |APE|, and comp tightness, while B remains a credible, fully-resolving second source.
