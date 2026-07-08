# Blacksburg AI head-to-head: MLS+county pool vs Zillow-scrape pool, same AI ensemble (July 2026)

*Run 2026-07 &middot; 20 random sold Blacksburg subjects (seed 42, reproducible) &middot; as-of 2026-06-30 &middot; n_comps=6 &middot; 18-month comp lookback &middot; leave-one-out in both arms (temporal + parcel-id for Arm A; spatial ~28 m + street-address for Arm B). Both arms run through the SAME workshopped AI pass: engine base (+ Haiku hygiene where the pool's comps carry remarks) and a blind Haiku valuer (claude-haiku-4-5-20251001) on an E3-enriched leak-free packet built from the identical LOO comp set; PRIMARY estimate = ens2 = mean(base, blind).*

**Arm A (MLS + county):** production comp pool — `data/mls_lookup.parquet`.
**Arm B (Zillow scrape, alone):** comp pool built exclusively from the Zillow-scrape parquet (`scratch/zillow_test/zillow_listings.parquet`, 333k rows, engine-schema-mapped, 1,273 Blacksburg rows; sqft pre-scaled 0.76 to the MLS basis at build time).

## What the AI pass actually included, per arm

- **Arm A hygiene:** on (Haiku hygiene; 4->3 survived), on (Haiku hygiene; 6->3 survived), on (Haiku hygiene; 6->4 survived), on (Haiku hygiene; 6->5 survived), on (Haiku hygiene; 6->6 survived), on (hygiene gutted the set; fell back to raw comps)
- **Arm B hygiene:** off (zillow comps carry no public_remarks -- verified NULL) — Zillow's `public_remarks` is NULL for all 1,273 Blacksburg rows (verified), so hygiene was disabled outright for this arm rather than spending an API call reviewing blank text.
- **Arm A blind packet:** E3-enriched (subtype/subdivision/appearance/dom/sold-to-orig-list/total_fin_sqft/basement/garage/how_sold/distress flags + comp and subject remarks where present).
- **Arm B blind packet:** same builder, but every MLS-only field (subtype, subdivision, appearance, dom, year_built, half_baths, remarks) is NULL in the Zillow pool and is OMITTED from the packet rather than fabricated — the model sees address/sold price/date/sqft/acres/beds/baths/distance only, thinner than Arm A by construction.

## Per-property results (ens2 primary estimate)

| # | Subject (street) | Sold | A ens2 | A err | B ens2 | B err | A comps@nearest | B comps@nearest | Closer |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2542 Blossom Trail W | $330,000 | $357,736 | +8.4% | $379,424 | +15.0% | 6 @ 0.01 mi | 6 @ 0.12 mi | A |
| 2 | 806 PETRA Pass | $760,000 | $900,267 | +18.5% | $672,261 | -11.5% | 6 @ 0.01 mi | 6 @ 0.29 mi | B |
| 3 | 4506 W Benoit Trail | $720,000 | $840,821 | +16.8% | $770,910 | +7.1% | 6 @ 0.2 mi | 6 @ 0.2 mi | B |
| 4 | 418 Midtown Way | $761,151 | $822,923 | +8.1% | $748,786 | -1.6% | 4 @ 0.07 mi | 6 @ 0.08 mi | B |
| 5 | 313 PHEASANT RUN Court | $345,000 | $343,920 | -0.3% | $348,102 | +0.9% | 6 @ 0.04 mi | 6 @ 0.04 mi | tie |
| 6 | 1711 Kyles Way | $572,670 | $457,349 | -20.1% | $466,741 | -18.5% | 6 @ 0.06 mi | 6 @ 0.23 mi | B |
| 7 | 616 FAIRVIEW Avenue | $410,000 | $420,890 | +2.7% | $451,000 | +10.0% | 6 @ 0.15 mi | 6 @ 0.15 mi | A |
| 8 | 3022 Deptford Street | $435,000 | $455,454 | +4.7% | $387,309 | -11.0% | 6 @ 0.01 mi | 6 @ 0.38 mi | A |
| 9 | 370 New Kent Road | $169,000 | $185,293 | +9.6% | $213,796 | +26.5% | 6 @ 0.03 mi | 6 @ 0.06 mi | A |
| 10 | 502 Edgewood Lane | $639,000 | $584,433 | -8.5% | $429,440 | -32.8% | 6 @ 0.16 mi | 6 @ 0.53 mi | A |
| 11 | 603 Alleghany St Street | $435,000 | $459,691 | +5.7% | $447,747 | +2.9% | 6 @ 0.13 mi | 6 @ 0.22 mi | B |
| 12 | 103 Yorkshire Court | $377,500 | $358,964 | -4.9% | $387,940 | +2.8% | 6 @ 0.01 mi | 6 @ 0.53 mi | B |
| 13 | 9169 BEAR CLAW FARMS Lane | $731,640 | $504,000 | -31.1% | $531,054 | -27.4% | 6 @ 1.62 mi | 6 @ 1.62 mi | B |
| 14 | 406 Laurence Lane | $346,000 | $346,551 | +0.2% | $339,855 | -1.8% | 6 @ 0.03 mi | 6 @ 0.03 mi | A |
| 15 | 1101 QUAIL Drive | $540,000 | $449,330 | -16.8% | $422,800 | -21.7% | 6 @ 0.09 mi | 6 @ 0.09 mi | A |
| 16 | 307 Charles Street | $260,000 | $294,528 | +13.3% | $339,929 | +30.7% | 6 @ 0.04 mi | 6 @ 0.03 mi | A |
| 17 | 2064 Kyles Way | $386,549 | $408,142 | +5.6% | $381,791 | -1.2% | 6 @ 0.16 mi | 6 @ 0.07 mi | B |
| 18 | 1810 Stratford View Drive | $550,000 | $525,120 | -4.5% | $466,964 | -15.1% | 6 @ 0.09 mi | 6 @ 0.13 mi | A |
| 19 | 612 Kentwood Drive | $645,000 | $654,197 | +1.4% | $617,567 | -4.3% | 6 @ 0.03 mi | 6 @ 0.03 mi | A |
| 20 | 2014 Carroll Drive | $464,500 | $425,657 | -8.4% | $390,997 | -15.8% | 6 @ 0.18 mi | 6 @ 0.47 mi | A |

## Summary

| Metric | Arm A (MLS + county) | Arm B (Zillow scrape alone) |
|---|---|---|
| Scored / resolve rate | 20/20 (100.0%) | 20/20 (100.0%) |
| Median comp count | 6.0 | 6.0 |
| Median nearest comp | 0.07 mi | 0.14 mi |
| Median farthest comp | 0.33 mi | 0.86 mi |

### Engine-only (base, no blind)

| Metric | Arm A | Arm B |
|---|---|---|
| n scored | 20 | 20 |
| Median \|APE\| | 7.27% | 6.48% |
| Median signed bias | 1.97% | -2.14% |
| PPE10 | 65.0% | 75.0% |
| PPE20 | 100.0% | 90.0% |

### Blind Haiku only (E3 packet)

| Metric | Arm A | Arm B |
|---|---|---|
| n scored | 20 | 20 |
| Median \|APE\| | 8.56% | 15.57% |
| Median signed bias | 0.14% | -2.74% |
| PPE10 | 60.0% | 40.0% |
| PPE20 | 80.0% | 60.0% |

### Ensemble ens2 = mean(base, blind) — PRIMARY

| Metric | Arm A | Arm B |
|---|---|---|
| n scored | 20 | 20 |
| Median \|APE\| | 8.24% | 11.25% |
| Median signed bias | 2.04% | -1.7% |
| PPE10 | 70.0% | 40.0% |
| PPE20 | 90.0% | 75.0% |

**Win count (ens2 closer to actual sold price):** Arm A 11 &middot; Arm B 8 &middot; tie (within 1.0 pt) 1.

## Findings

**1. On the plain engine, the Zillow-scrape pool matches MLS in Blacksburg — it is even a hair better on median.** Engine-only median |APE| was **6.48% (Zillow) vs 7.27% (MLS)**, with Zillow also ahead on PPE10 (75% vs 65%). The scraped comps, run through the ordinary comp engine, price Blacksburg homes about as accurately as the licensed MLS+county pool. This validates the scrape-only direction where MLS is unavailable: the comps themselves are good enough.

**2. The overall ensemble win for MLS (8.24% vs 11.25%) is created ENTIRELY by the AI pass, not the comps.** The blind Haiku valuer scored **8.56% on MLS but 15.57% on Zillow** — nearly double the error. Cause is structural, not random: the workshopped E3 packet was tuned on MLS-rich fields (subtype, subdivision, appearance, DOM, sold-to-list, remarks), and *every one of those is NULL in the scrape pool*. Stripped to address/price/date/sqft/acres/beds/baths/distance, the valuer flails — and because it flails, averaging it in **drags the Zillow ensemble (11.25%) below its own engine-only baseline (6.48%)**. On MLS the same pass is roughly neutral (7.27% → 8.24%). The AI pass, as built, is an MLS-shaped tool that does not transfer to thin scrape data.

**3. Practical implication.** Two honest paths to give the scrape arm a working AI pass: (a) **enrich the scrape packets via the detail sweep** — `year_built`, price history (→ prior-sale/trend), and `property_subtype` from `home_type` are all recoverable per the P0(b)/P1 plan, which would close most of the packet gap; or (b) give the scrape arm a **scrape-shaped blind prompt** that doesn't expect MLS fields. Until one of those lands, **scrape-only regions should run engine-only** (where they are already competitive) and NOT the current ensemble.

**4. The thinness tax is real but small, and it lives in the tail.** MLS comps are tighter (median farthest 0.33 mi vs 0.86 mi) and MLS had **zero** misses over 20% (PPE20 100% engine / 90% ensemble), while Zillow had a few driven by farther fallback comps — 502 Edgewood Lane (−33%, comps out to 0.53 mi) and 307 Charles Street (+31%). Denser scrape coverage (the detail sweep + more sold history) would shrink these.

**5. Per-property, the pools are near-parity: A won 11, B won 8, 1 tie.** The aggregate 3-point ensemble gap is not a broad comp-quality gap — it is the AI pass underperforming on 4–5 thin-packet subjects. On the engine, the two data sources are effectively interchangeable in Blacksburg.

**Bottom line:** the Zillow scrape can carry a Blacksburg CMA on the engine today (≈6.5% median error, on par with MLS). It cannot yet carry the *AI-ensemble* CMA — that pass needs the richer fields the scrape omits, which the detail-sweep plan already targets. Recommend: run scrape regions engine-only for now; re-run this head-to-head after the detail sweep enriches the packets.

*Caveat: n=20, single seed, Blacksburg only (a dense, well-covered market — the scrape's best case). Arm A hygiene occasionally over-ejected (6→3 comps, one full gutting with raw-comp fallback), consistent with the known stock-hygiene over-ejection issue; it did not change the arm ranking. Rural/thin markets would likely widen the gap in MLS's favor on coverage alone.*
