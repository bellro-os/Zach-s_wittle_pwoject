# Blacksburg engine-only, 3-way: MLS+county vs Zillow vs Zillow+county (n=100, July 2026)

*Run 2026-07-08 · SAME 100 random sold Blacksburg subjects (seed 42) · as-of 2026-06-30 · n_comps=6 · 18-mo lookback · leave-one-out · **engine only, no AI pass**. Arm C pool = the pure-Zillow scrape UNION county-deed recorded sales (23,893 new residential sales added, deduped vs Zillow), NO MLS.*

| Metric | A — MLS+county | B — Zillow only | C — Zillow+county |
|---|---|---|---|
| **Median \|APE\|** | **13.5%** | **15.92%** | **14.52%** |
| Mean \|APE\| | 17.81% | 20.42% | 19.75% |
| Median signed bias | -3.09% | -7.82% | -8.13% |
| PPE10 | 41.0% | 32.0% | 31.0% |
| PPE20 | 66.0% | 62.0% | 66.0% |
| Misses >20% / >30% | 34/17 | 38/23 | 34/21 |
| Median nearest / farthest comp | 0.08/0.37 mi | 0.17/0.88 mi | 0.15/0.75 mi |

**Does county help on top of Zillow? (C vs B):** C wins 34 · B wins 24 · tie 42.
**MLS vs Zillow+county (A vs C):** A wins 57 · C wins 33 · tie 10.

## Read

**1. County deed records help — Zillow+county beats Zillow-only, closing more than half the gap to MLS.** Median |APE| drops **15.92% → 14.52%** (−1.4pt), PPE20 rises 62% → 66%, and the tail thins (>30% misses 23 → 21, median farthest comp 0.88 → 0.75 mi). Head-to-head, C beats B **34–24** (42 ties). The Zillow→MLS gap was 2.4 points (15.92 vs 13.5); adding county closes ~1.4 of it, landing ~1 point short of MLS.

**2. The gain is COVERAGE, and it reaches a minority of subjects.** 42 of 100 were ties — for most homes Zillow already had a tight top-6 comp set, so the 23,893 added county sales didn't crack it. Where county *did* help (~a third of subjects), it was by supplying a closer recorded sale that trimmed a big miss. That is exactly the mechanism you'd want: county fills the spatial holes Zillow leaves, shrinking the tail rather than shifting the median much.

**3. County does NOT fix the systematic low bias — it slightly worsened it (−7.82% → −8.13%).** This is the key diagnostic: the ~8% underestimate is *not* a coverage problem (more comps didn't move it). It is a level/basis problem — most likely the 0.76 sqft-prescale interacting with MLS-basis subjects, and/or scraped+deed sold prices sitting below the MLS-basis truth. **That gap needs per-region recalibration (the dial-in loop), not more data.** MLS's bias is only −3.09% because its sqft basis matches the subjects.

**4. MLS still wins (A vs C: 57–33), but Zillow+county is now the best license-free floor.** For a region the engine can't otherwise reach, Zillow+county at **14.5% engine-only** beats pure scrape and needs no MLS license (the deed file is already public-records data). It's a legitimate cold-start pool.

**Bottom line:** county deed data is a cheap, license-free coverage booster that gets scrape-only most of the way to MLS *on the bare engine* — but two things still stand between it and a shippable number: (a) **per-region recalibration** to kill the −8% bias (a modeling fix, not a data fix), and (b) the **AI ensemble pass** to reach single digits, which first needs the scrape/deed packets enriched (year-built and price-history are already in the deed rows — a head start). Recommended next: run the dial-in recalibration on this Zillow+county pool for Blacksburg and re-measure the bias.

*Caveat: engine-only, no AI, no AVM — a floor, not the product. County deed rows carry NULL bed/bath and no remarks, so they help the $/sqft and comp-distance signals but not the hygiene/subtype ones. Deduped vs Zillow by normalized-address + sale month, so county contributes only sales Zillow missed.*