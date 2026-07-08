# Blacksburg engine-only, paired: MLS+county vs Zillow-scrape (n=100, July 2026)

*Run 2026-07-08 · SAME 100 random sold Blacksburg subjects (seed 42) comped through BOTH pools · as-of 2026-06-30 · n_comps=6 · 18-mo lookback · leave-one-out · **engine only, no AI pass**. Same subjects as `blacksburg-zillow-engine-100-2026-07.md` (Arm B here == that run). Isolates whether the Zillow error is scrape-specific or a Blacksburg/harness effect.*

| Metric | Arm A — MLS + county | Arm B — Zillow scrape |
|---|---|---|
| Scored / resolve | 100/100 (100.0%) | 100/100 (100.0%) |
| **Median \|APE\|** | **13.5%** | **15.92%** |
| Mean \|APE\| | 17.81% | 20.42% |
| Median signed bias | -3.09% | -7.82% |
| PPE5 | 21.0% | 16.0% |
| PPE10 | 41.0% | 32.0% |
| PPE20 | 66.0% | 62.0% |
| Misses >20% / >30% | 34 / 17 | 38 / 23 |
| Median nearest / farthest comp | 0.08 / 0.37 mi | 0.17 / 0.88 mi |

**Win count (closer to actual sold price):** MLS 58 · Zillow 27 · tie (within 1.0 pt) 15.

## Read

**1. The n=20 head-to-head was optimistic for BOTH pools — small samples lied.** At n=20, MLS engine-only looked like 7.27% and Zillow 6.48%. At n=100 the same harness gives **MLS 13.5% and Zillow 15.92%**. Both nearly doubled. The takeaway is not "Zillow got worse" — it's that the 20-property draw happened to hit easy, well-covered subjects for both pools. n=100 is the trustworthy read.

**2. MLS is genuinely better than the scrape, but only modestly — ~2.4 points of median error.** 13.5% vs 15.92% median, and MLS wins the paired head-to-head **58–27 (15 ties)**. So the scrape data is a real step down, not a catastrophe: same ballpark, MLS clearly ahead.

**3. The scrape's specific taxes are visible and physical:** worse bias (**−7.82% vs −3.09%** — the scrape systematically underprices ~2× harder), farther comps (median farthest **0.88 vs 0.37 mi** — thinner local coverage forces reaches), and a heavier tail (**23 vs 17** misses over 30%). These three — bias, distance, tail — are the entire ~2–4pt gap, and all three are exactly what the detail-sweep enrichment + per-region recalibration target.

**4. The most important finding is about the BASELINE, not the pools.** Bare engine-only is **~13–16% median in Blacksburg regardless of data source.** That is the raw comp generator with *no AI pass* (no hygiene, no blind Haiku) — the floor, not the product. The single-digit accuracy the stack is known for (≈7.9% certified) comes from the AI ensemble layered on top. So "how accurate is the comp generator on Zillow data" has two honest answers: **engine-only ~16%** (this run), and the AI-pass number is unknown for the scrape until its packets are enriched (the prior head-to-head showed the current MLS-shaped AI pass *hurts* thin scrape packets).

**Bottom line:** roughly 85% of the scrape's error is just "engine-only is mediocre in Blacksburg" (MLS has the same problem); only ~2.4 points is scrape-specific, concentrated in a low bias, farther comps, and a fatter tail. The scrape pool is a viable *starting* pool for a region the engine can't otherwise reach — but it needs the detail-sweep enrichment (to fix coverage/bias) AND the AI pass to become competitive, same as MLS does.

*Caveat: this "engine-only" path is barer than the certified production base (no hygiene, and the comp-comparison harness does not run the AVM), so absolute numbers here sit above the ~10% production base / ~7.9% ensemble measured on Montgomery MLS. The MLS-vs-Zillow DELTA is clean — identical config on identical subjects.*