# Regional CMA Accuracy — Supplemental Public-Records Sales Source (2026-07-02)

**What this is.** A regional accuracy test of the compbird CMA engine with its comp pool
swapped to the **supplemental public-records sales source** (`data/supplemental_listings.parquet`,
333,598 sold rows, `source='supplemental'`), head-to-head against the production MLS pool on
the **same ground-truth subjects** (recently sold properties whose actual sold price is known).
It reuses the engine's isolated dual-pool backtest harness (`accuracy_backtest.py`, under the
engine's scratch area) verbatim: as-of date freezing, temporal leave-one-out, and — for the
supplemental arm —
spatial (~28 m) plus street-address self-exclusion so the subject's own sale never appears in
its comp pool. No production file was modified; every run was read-only with in-process
patches only.

---

## 1. Coverage map of the supplemental pool

**Verdict: effectively Virginia + Washington DC.** State inferred from address tails:

| State | Rows |
|---|---:|
| VA | 318,999 (95.6%) |
| DC | 14,521 (4.4%) |
| MD/NC/TN/WV/other | 51 total (border noise) |

- **Date range:** 2023-06-15 → 2026-06-26 (~3 years of closed sales).
- **130 distinct counties/cities.** **129 have ≥ 50** sold rows in the last 24 months; **111 have ≥ 200.**
  Full per-county table was generated during the run (counts, 24-mo counts, first/last sale, median price).
- **Regional rollup** (rows total / last 24 mo):

| Region | Rows | Last 24 mo |
|---|---:|---:|
| NoVA (Fairfax, Pr. William, Loudoun, Arlington, Alexandria, Stafford, Fauquier…) | 87,118 | 58,130 |
| Tidewater (VA Beach, Chesapeake, Norfolk, Newport News, Hampton, Suffolk…) | 65,824 | 24,927 |
| Richmond metro (Henrico, Chesterfield, Richmond, Hanover…) | 42,842 | 28,593 |
| Shenandoah Valley (Winchester, Rockingham, Frederick, Augusta…) | 21,358 | 14,308 |
| Fredericksburg area | 14,682 | 9,807 |
| Washington DC | 14,523 | 9,910 |
| Charlottesville area (Albemarle+) | 12,506 | 8,263 |
| SW VA beyond NRV (Wythe, Carroll, Grayson, Patrick, Bland, Craig…) | 12,405 | 8,088 |
| Roanoke metro (Roanoke, Salem, Botetourt) | 11,114 | 7,520 |
| Lynchburg area | 11,044 | 7,440 |
| New River Valley (Montgomery, Pulaski, Radford, Giles, Floyd) | 5,828 | 4,082 |

**Field quality:** sold_price and lat/lng 100% populated; sqft 96.7% (pre-scaled to the
calibrated basis at build time); acres 85.6%; **year_built 0%**; list_price and DOM are NULL
**by design** (not collected for this source). The missing year_built/list-side fields limit
the engine's condition/age/negotiation adjustments when running on this pool.

---

## 2. Regional accuracy test — supplemental pool vs MLS pool

**Method.** 12 regions, 15 sold subjects each (180 subjects total, 179 paired). Subjects are
drawn from the engine's own subject lookup (production MLS parquet, Closed RE_1, sold ≥ $80k,
geocoded, plausible $/sqft, closed in the 18 months before 2026-06-30, spread evenly across
the window) — i.e., only subjects the engine can actually resolve. Each subject is valued
twice with its own sale held out of the pool both times: once against the supplemental pool,
once against the MLS pool. Comp settings: n=6 comps, 18-month lookback, typical_dom=21.
Ground truth = the subject's actual sold price. Total runtime: 94 s.

**Important scope note:** the engine's subject lookup only contains sold subjects in its
SW VA / New River Valley MLS footprint, so the 12 testable regions are all in that footprint.
The supplemental pool's biggest coverage (NoVA, Richmond, Tidewater, DC) **could not be
accuracy-tested** — see Limits.

### Per-region results (paired subjects; SUP = supplemental pool, MLS = production pool)

| Region | n | Resolve SUP/MLS | Median \|APE\| SUP | Median \|APE\| MLS | Signed bias SUP | Signed bias MLS | Med comps SUP | Nearest comp SUP/MLS (mi) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Montgomery (NRV core) | 15 | 100% / 100% | 14.1% | **9.9%** | +1.6% | −3.1% | 6 | 0.35 / 0.19 |
| Pulaski (NRV) | 15 | 100% / 100% | 17.5% | **7.9%** | +4.2% | +4.5% | 6 | 0.34 / 0.13 |
| Radford City (NRV) | 15 | 100% / 100% | 6.1% | **5.0%** | +4.0% | −2.1% | 6 | 0.19 / 0.10 |
| Giles (NRV) | 15 | 100% / 100% | 22.4% | **20.0%** | +9.1% | 0.0% | 6 | 0.40 / 0.24 |
| Floyd (Blue Ridge plateau) | 15 | 100% / 100% | 25.0% | **15.5%** | +13.6% | +6.0% | 6 | 0.99 / 1.28 |
| Wythe (I-81 SW) | 15 | 100% / 100% | 17.9% | **11.9%** | +7.2% | +3.6% | 6 | 0.34 / 0.57 |
| Carroll (SW Blue Ridge) | 15 | 100% / 100% | **20.0%** | 25.6% | +7.9% | +6.4% | 6 | 0.85 / 2.88 |
| Roanoke metro | 15 | 100% / 100% | 18.1% | **16.2%** | +10.4% | +0.1% | 6 | 0.16 / 0.42 |
| Grayson + Galax (far SW) | 14 | 93% / 100% | **22.2%** | 37.4% | +17.5% | +37.4% | 6 | 0.66 / 1.30 |
| Patrick | 15 | 100% / 100% | **13.7%** | 23.5% | +5.7% | +21.7% | 6 | 1.10 / 3.52 |
| Bland | 15 | 100% / 100% | **20.5%** | 30.9% | 0.0% | +30.9% | 5 | 1.75 / 9.26 |
| Craig | 15 | 100% / 100% | 22.5% | **21.6%** | +19.2% | −9.2% | 5 | 1.72 / 5.28 |

(Bold = better arm on median |APE|. Grayson resolve <100% because one supplemental run
returned a zero estimate.)

### Pooled (all 179 paired subjects)

| Metric | Supplemental pool | MLS pool |
|---|---:|---:|
| Median \|APE\| | 17.4% | 15.7% |
| Median signed error | +7.9% | +5.0% |
| PPE10 / PPE20 | 32% / 58% | 34% / 54% |
| Median nearest comp | 0.53 mi | 1.00 mi |

### The split that matters: MLS-dense vs MLS-thin

| Subset | n | Median \|APE\| SUP | Median \|APE\| MLS | Signed SUP | Signed MLS |
|---|---:|---:|---:|---:|---:|
| MLS-dense (nearest MLS comp ≤ 2 mi) | 116 | 16.7% | **13.6%** | +8.1% | +2.7% |
| MLS-thin (nearest MLS comp > 2 mi) | 61 | **20.5%** | 23.3% | +8.7% | **+17.4%** |

---

## 3. Findings (plain English)

1. **The supplemental pool wins exactly where the MLS feed is thin — the rural fringe.**
   In Carroll, Grayson+Galax, Patrick, and Bland it beats the MLS pool outright (e.g. Bland
   20.5% vs 30.9%, Patrick 13.7% vs 23.5%), because its comps are physically much closer
   (nearest comp 0.7–1.8 mi vs 1.3–9.3 mi for MLS). On the MLS-thin subset overall it cuts
   median |APE| by ~3 points and, more importantly, cuts the MLS arm's runaway +17.4%
   over-valuation bias in half.
2. **Where the MLS feed is dense (Montgomery, Pulaski, Radford, Roanoke metro), MLS still
   wins by 2–10 points.** The supplemental pool is a fallback/gap-filler, not a replacement:
   richer MLS fields (year_built, list-side data, DOM) and cleaner records beat raw breadth
   when both have nearby comps.
3. **The supplemental arm runs consistently hot: about +8% median over-valuation pooled,
   and +10% to +19% in Roanoke metro, Floyd, Grayson+Galax, and Craig.** The sqft basis
   factor baked into the pool (0.76) was calibrated on Montgomery, where the bias is now
   near zero (+1.6%) — it does not transfer cleanly to other counties. Craig is the one
   region where the supplemental pool is both hot (+19%) and no more accurate than MLS.
4. **Comp availability is excellent inside its footprint:** 179/180 subjects (99.4%) produced
   a valuation off the supplemental pool alone, with a median nearest comp of 0.53 mi —
   closer than the MLS pool's 1.00 mi.

## 4. Limits — be aware before quoting these numbers

- **This is not a multi-state test and cannot be one yet.** The supplemental pool is
  VA + DC only, and — the harder constraint — the engine can only resolve ground-truth
  subjects that exist in its VA parcel/MLS subject lookup, which today covers the
  SW VA / NRV footprint. The pool's largest markets (NoVA 87k rows, Tidewater 66k,
  Richmond 43k, DC 15k) are untested for accuracy; testing them needs either subject
  ground truth from those markets or a leave-one-out design that draws subjects from the
  supplemental pool itself.
- 15 subjects per region: medians are stable enough for ranking arms, but single-region
  point estimates carry roughly ±5-point noise.
- Supplemental rows lack year_built, list price, and DOM, so engine adjustments relying on
  those fields are degraded on this pool by construction.
- Thin-region MLS numbers (Bland, Craig, Patrick, Grayson) describe an arm forced to reach
  5–9 mi for comps; they are a feature of feed coverage, not of the valuation model.

## 5. What to fix next

1. **Recalibrate the supplemental sqft basis statewide, not on Montgomery alone** — sweep the
   factor against a multi-county subject set (the +8% pooled over-valuation suggests the
   effective factor should be a bit lower, or region-dependent).
2. **Blend rule:** prefer the MLS pool when the nearest MLS comp is within ~2 mi; fall back to
   (or union in) the supplemental pool beyond that. The dense/thin split above is the direct
   evidence for this policy.
3. **Unlock the big markets:** add subject-resolution ground truth outside SW VA (statewide
   parcel join or a supplemental-pool leave-one-out subject design) so NoVA / Richmond /
   Tidewater / DC accuracy can actually be measured before shipping coverage claims.
4. **Enrich year_built** on supplemental rows from parcel data (currently 0% populated) —
   likely the cheapest accuracy lever inside the pool itself.
5. Investigate the single `zero_estimate` failure (Grayson subject) in the harness's
   supplemental arm.

---
*Method artifacts: runner script `regional_accuracy.py`, per-subject detail
`regional_results_detail.jsonl`, and summary `regional_results_summary.json` in the session
scratchpad; harness = the engine's isolated `accuracy_backtest.py` (read-only reuse).*
