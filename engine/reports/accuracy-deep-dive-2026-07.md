# Accuracy Deep-Dive — 2026-07-07

(9-agent pipeline audit + error decomposition; all findings locally measured on the seed-42/43 harness data.)

# CMA Accuracy Improvement Plan — Consolidated Synthesis

**Protocol for every experiment below:** leave-one-out (MlsLoo), as-of frozen, prior-sale + AVM disabled unless the arm is testing them, within-seed paired deltas only (sign test + paired median |APE|), tune on seed-42, confirm on a held-out seed, report medAPE + signed bias + PPE10 + PPE20. Draw difficulty varies hugely across seeds — cross-seed absolute comparisons are invalid.

**Critical framing that reorders everything:** the current measurement harness is simultaneously *flattering* the engine (future-pending LOO leak, ~1pt) and *handicapping* it (subjects lack subdivision/high_school, so the subdivision branch that fires on 61% of production subjects has never been in any measured number, ~1pt) and *contaminating* the hygiene arms (cache-key collisions; 33/100 seed-43 subjects served seed-42 verdicts). No experiment result is trustworthy until the harness is rebuilt and all four headline arms are re-baselined. That is item 1, gate everything on it.

---

## Tier 0 — Bugs to fix now (correctness; fix regardless of gain)

### B1. Harness rebuild + full re-baseline (measurement correctness — blocks everything)
Bundle of five demonstrated measurement defects:
- **LOO future-pending leak**: any `close_date IS NULL` row passes any as-of (`mls_haiku_test.py:95`); touched 58/100 subjects' comp sets; leak-free rerun moved base 10.08→11.11. Blind packets are closed-only, so the engine-vs-blind comparison (7.7 ensemble vs 12.2 base) is tilted. Fix: require `status_changed_at < as_of` for non-closed rows in all three harnesses.
- **Subjects lack subdivision/high_school/property_subtype** (`mls_haiku_test.py:50-74`): subdivision-first branch (`cma_compset.py:786-822`) + both scoring bonuses dead in every measurement; restoring fields: 10.08→8.94 paired. Physical facts, leak-free; keep list_price OUT.
- **Non-reproducible draws**: `pick_subjects` window anchors on `current_date`; same seed reproduces only 22/100 subjects across days. Fix: literal date window + snapshot the parquet per experiment.
- **Subject arms-length screen**: seed-42 contained 2 auctions + 1 fixer (flagged medAPE 41.9% vs 8.5% unflagged; cleaning: sr 8.25→7.80). Auction "actuals" can exclude buyer's premium — unfixable, must exclude. Use the refined KW_STRONG patterns in `scratchpad/ground_truth_pollution.py`; report raw and screened.
- **Seed overlap**: seed-43 shares 24 parcels with seed-42 — draw seed-44+ disjoint for genuine holdouts.

Evidence: audit:compset-scoring, audit:hygiene-llm, audit:estimation-core, data:ground-truth-pollution (converging).
Gain: no production gain — makes every future number trustworthy; the hygiene finding below was invisible for exactly this reason. Cost: ~2-3h edits + one engine-only rerun (LLM-free, minutes) + one 4-arm rerun (small Haiku spend).
Validation: re-baseline base / SR-hygiene / blind / ensemble on rebuilt seed-42 and a fresh disjoint seed-44 with isolated per-arm caches.

### B2. Hygiene cache key + verdict-mapping rework (production + measurement correctness)
- Key is `listing_id|{sqft}-{subdivision[:20]}` with model NOT in key (`cma_hygiene.py:64-67, 35-41`); harness signatures degrade to sqft-only; **demonstrated**: 18/40 replay subjects served another subject's verdicts; 33/100 seed-43 subjects shared a signature with seed-42 — the 10.0% SR headline is partially contaminated. Live risk: after the Opus default flip, cache hits still return Haiku-era verdicts.
- Verdicts are mapped `zip(to_review, result)` with no length check and the model's returned address ignored (`cma_hygiene.py:199`) — one omitted item misassigns every subsequent verdict AND caches it permanently; truncation at max_tokens=2000 silently kills the batch.

Fix: key = sha256(listing_id | model | prompt_version | sqft | subdivision | subject-remarks-hash) + cache format version; validate result length, match by normalized address, skip-cache mismatches, one retry on parse failure, mismatch counter.
Gain: unblocks SR productionization; prevents permanent cache poisoning. Cost: ~2h.
Validation: rides B1's re-baseline (isolated caches per arm).

### B3. Prior-sale wrong-property anchors (LIVE production bug)
parcel_id-only matching + junk ids ('TBD'×19, '1/1', '0'; 101 pids map to >1 address): 2 of 27 simulated anchors were other properties' sales, one carrying ~74% of the blend weight ($803k "prior sale" on a $604k home). Prior-sale IS enabled in production. Fix: reject junk/short pids + require street-number+name agreement; treat sentinel pids as non-joinable in all parcel-keyed logic (dedup, LOO exclusion). Evidence: audit:priorsale-avm-trend; data:error-decomposition.
Gain: removes 30-180% errors on ~1-2% of live CMAs. Cost: 1-2h. Validation: unit cases + no backtest regression.

### B4. Dead deed-ratio comp guard (one line)
`_atypical_signals` reads `comp.get("deed_last_sale_price")` but `_CANDIDATE_COLUMNS` (`cma_compset.py:632-652`) never selects it — the engine's only deed-based non-arms-length comp check can never fire. Fix: add the column. Cost: minutes. Validation: paired engine arm, both seeds.

### B5. Hygiene drop rate leaves <6 comps, sometimes 0 — estimates silently destroyed
Pull n+4=10 vs 54% verdict drop rate, no backfill (`build_cma.py:1825-1844`; `cma_hygiene.py:245-249`): replay distribution {6:70 … 0:1}; 4/100 seed-42 estimates lost. Fix: backfill from the already-scored candidate remainder; hard floor: fall back to the deterministic set (hygiene as flags-only) rather than valuing off 1-2 comps. Gain: recovers ~4% of estimates, PPE20 protection. Cost: ~1h. Validation: rides any hygiene-arm rerun; count sets <6.

### B6. $5k rounding applied inside `_estimate_value` (`build_cma.py:358-359, 1117-1119`)
Every consumer — ensemble, backtests, disclosures — inherits quantization (up to +2.3pp APE on sub-$150k homes, the known statewide over-valuation cohort). Fix: unrounded in ValuationResult, round at render. Cost: ~1h, zero risk.

### B7. Recency weight decays from `date.today()` not the as-of date (`cma_compset.py:365-368`)
Backtest comp ranking anchored to run date. Thread as-of through. Cost: 15 min.

---

## Tier 1 — Quick experiments (this week, cheap, all post-B1 re-baseline)

Ranked by (expected gain ÷ cost). All deterministic arms are $0/~4 min each.

### Q1. property_subtype gate — strongest consensus finding (4 independent auditors)
Selected at `cma_compset.py:651`, used nowhere. 26% of Montgomery RE_1 solds are Townhouse/Condo (Condo $273-275/sqft vs Detached $226-229); 58/100 final compsets mixed subtypes; the townhouse tail case (pid 100059, comped to $525k vs $330k actual) is subtype-explainable; ~2/3 of the hygiene LLM's drop work is type-filtering the SQL should do. Measured: hard filter (fallback when <10 rows) 9.10 vs 10.08 (−0.50 paired).
Fix: hard filter in `_pull_candidates` with thin-pool fallback, else 0.85× mismatch multiplier; also pass subtype to blind packets and hygiene prompt.
Gain: 0.3-1.0pt + large tail reduction, plus it shrinks the hygiene drop rate (helps B5). Cost: ~20 LOC.
Validation: paired arm, seeds 42 + held-out; check post-fix hygiene drop rate falls <15%.

### Q2. Candidate pool starvation: min_count 30→80-100
Pool stops at 30 rows (`cma_compset.py:703, 879-881`), cohorts recency-truncated at LIMIT 200 before similarity scoring. Measured: min_count=80 → 8.95 vs 10.08 (−0.60 paired). Also explains the far-comp selection artifact (all 9 >1.5mi-nearest-comp subjects had eligible candidates ≤1.0mi that never reached the scorer).
Fix: raise default; optionally similarity pre-rank inside cohorts. Gain: 0.3-1.1pt. Cost: 1 line. Validation: paired, both seeds; check min-chosen-distance distribution shifts nearer.

### Q3. Hygiene repair suite (cache-replay = free) + SR productionization
Stock hygiene is a measured **net negative and the dominant seed-43 bias source**: engine-only 10.7%/−2.3 bias vs 12.2%/−6.1 with stock hygiene on the exact held-out subjects; cause = prompt hard-codes "average-to-updated subject" (`cma_hygiene.py:158-159`) → adjustments 5:1 negative (mean −3.0%), 54% ejection rate; hygiene clamp ±30 is 2× the deterministic ±15. The SR variant (subject's actual masked remarks) beats stock on both seeds and is the only hygiene config worth keeping.
Experiments (post-hoc on cached verdicts — zero API cost): (a) zero-center adjustments per comp set; (b) clamp ±15 at ingest; (c) drops→advisory 0.5× penalty unless corroborated by deed-ratio/subtype, floor at n_comps. Then port `review_comps_sr` into production (**requires B2**), stock-assumption fallback for off-market subjects.
Gain: 1.0-1.5pt standalone; 0.3-0.8pt on the ensemble if bias correction preserves decorrelation (note: ens(SR)+blind 7.7 beat ens(no-AI)+blind 8.4 — hygiene diversity has ensemble value, don't just delete it). Cost: ~1 day; validation on clean seed-44, ~$3-6 Haiku.

### Q4. Symmetric atypical penalty (bias mechanism)
sold/list >1.05 gets 0.80× (`cma_compset.py:543-545`); above-list sales concentrate in the top price tercile → downward bias. Measured: symmetric arm 9.55 vs 10.08, bias +1.70→+1.28. Fix: display-only for 1.05-1.15, penalize >1.15. Gain: 0.2-0.5pt, mainly bias. Cost: 3 LOC. Validation: gate on mean signed error, both seeds.

### Q5. Combined compset arm confirmation
Q1+Q2+Q4+fields stacked to 8.94 (−1.17 paired, 43W/39L, p≈0.23 — directional only). Run on the rebuilt harness, n=200 for power, held-out seed as gate. Bake only if held-out paired delta negative and bias not worse. Gain: 0.8-1.2pt if it replicates. Cost: ~15 min/seed.

### Q6. Blind-packet enrichment ladder (upgrades the best single arm, 8.2%)
Packet is starved: subject omits year_built/half_baths/subdivision/subtype; query has no `_class` filter or parcel dedup (`mls_haiku_test.py:135-165`). Ladder (identical comp selection across arms, only content varies): E0 fix subject fields + RE_1 filter + dedup → E1 structured comp fields (subtype, subdivision, DOM, sold/orig-list, appearance — appearance shows a monotonic $144→$275/sqft spread and never reaches any LLM) → E2 comp remarks[:250] (price/status regex-stripped) → E3 subject remarks (stripped) → E4 post-D1 fields (total-fin sqft, garage, distress flags, how_sold). Also test tax-assessed + prior-deed anchors in the packet (ensemble-confidence's recommendation for the mid-disagreement band).
Gain: E0 0.1-0.4, E1 0.3-1.0, E2 0.5-1.5; compounding plausibly takes the ensemble toward ~7%. Cost: ~$0.2-0.6 per 100-subject arm. Validation: paired ladder on seed-42, winners confirmed on held-out seed, ensemble rebuilt after each winner.

### Q7. AVM index-debias + re-add as 4th ensemble signal (biggest tail lever found)
Frozen HGBR (train cutoff 2025-09-30, no calendar feature) carries −7 to −8% staleness bias; leak-free index debias: solo 11.0→8.5 (seed-43); added at w=0.5 to the ensemble: PPE20 84→89 / PPE10 58→63 (seed-43), PPE20 68→83 (seed-42), medAPE roughly neutral. Also removes ~−2.4% systematic bias from every current production suburban CMA.
Fix: multiply prediction by index(as-of)/index(training center) inside `_method_avm` (debias factor scripts exist in scratchpad); keep envelope gate; tune w∈{0.3, 0.5} on non-final seeds. Gain: +5-15pt PPE20, +0.3pt production median. Cost: ~2h.

### Q8. Prior-sale re-enable, leak-free, with guards
As-of-aware query routed through the LOO connection factory (fixes the harness leak that forced disabling it), plus B3 identity guard, plus flip guard (fresh resales are adversely selected — both freshest simulated anchors were flips) and divergence gate (|anchor/blend−1| < 0.25 → subset medAPE 9.2→7.8). Fires on ~14% of subjects at 3.3-4.0% anchor medAPE; coverage grows as history deepens.
Gain: 0.1-0.3pt now, growing. Cost: ~1 day. Validation: paired on 2 seeds + confirm on a third; anchored subsets are n≈16-27, so use sign test + mean|APE| alongside median.

### Q9. Ship confidence tiers (product, zero accuracy risk)
Two independently-derived, mutually consistent signals: (a) 3-arm spread ≤10% → 4.7% medAPE / PPE20 92.5 on 41% of subjects (bootstrap P=0.999; Medium/Low indistinguishable — ship TWO tiers only); (b) nearest-chosen-comp distance <0.5mi/0.5-1.5/>1.5 → 7.7/14.4/33.1 medAPE + local density. Combine: spread3 + distance/density drive the tier and interval width; ppsf spread only as a tail flag (partial ρ 0.057 vs 0.291 for distance).
Gain: 0pt medAPE; converts the worst 10-15% of CMAs from silent misses into labeled low-confidence output. Cost: hours. Validation: threshold check on one fresh seed (High tier must stay <~7% medAPE at 35-55% coverage).

### Q10. Small scorer knobs (ride the same sweep harness)
- **Relative sqft scale**: flat 600-sqft e-fold (`cma_compset.py:431`) → 20.3% medAPE cliff at >25% mismatch; test scale = max(400, 0.25×subject_sqft) + hard-drop >30% mismatch when enough closer comps survive.
- **half_baths**: score baths as full + 0.5×half (currently full-only at `:435,939-948`).
- **Land-heaviness-morphed distance decay**: distance is the dominant error driver (min_dist ρ=0.415, p<0.001; age ρ=−0.03 — time adjustment compensates for staleness, nothing compensates for location) BUT flat 1.5mi tightening was REFUTED (16W/33L). Test only the morphed version (scale 1.5mi suburban → 5mi at lh=1.0) + DIST weight 80→110 / RECENCY 70→50 grid.
- **Appearance tier-proximity scoring axis** (65% filled, absent from scoring).
- **Price-axis circularity quantification**: `_subject_reference_ppsf` anchors 12% of the score to the subject's list/deed price — dead in every harness run, never measured. Add a list_price-supplied arm and a weight-0 arm.

Gain each: 0-0.5pt; all $0 and minutes each. Validation: one-knob-at-a-time paired arms.

---

## Tier 2 — Structural improvements

### S1. County monthly $/sqft index (`data/market_index.parquet`) — infrastructure, not a direct win
The raw appr-rate swap tested **neutral** (8.8→9.0 — do not ship alone), and the seed-43 −6.1% bias is draw composition, not time-lag (flat across as-of months; sign-runs z=+2.94 against clustering). Build it anyway because it enables Q7 (AVM debias), Q8 (anchor trending), falling markets (`_APPR_MIN=0` cannot represent decline; 72% of subjects sit on a clamp boundary), and non-Montgomery regions running ≠4%/yr. Blend (0.5/0.5) with the pool estimate, allow −0.05 floor; test on mean-comp-age >9mo subjects (subdivision 48-month-window cases). Cost: ~1 day.

### S2. Rural / acreage overvaluation — biggest replicated segment failure
no-subdivision: 19.8/33.1% medAPE both seeds; 2+ acres: 15.9/14.4; subjects out-acring their top-3 comps: +13.0% bias. The refuted-$306k subject (see ceiling section) is this failure mode: 4 acres, 0 comps within 1mi, base +124%. Mechanism: land double-count (gap×$/ac ON TOP of ppsf embedding land, `build_cma.py:736-739`), one-sided `max(0, gap)`, residual method's full-ppsf improvement basis + positive-residual truncation (`:819,828,838`).
Fix: symmetric gap; one-iteration residual decomposition (land_rate → improvement_ppsf → land_rate); comp-density-gated land-premium cap; rural marker + acres in the blind packet (the blind arm anthem-prices lyrical rural listings). Test fixes on the **ensemble**, not single arms (blind partially rescues thin areas).
Gain: ~0.4-0.6pt median, transforms the tail. Cost: ~half-day to 2 days. Validation: both-seed paired + the existing 500-home high-acreage backtest (Montgomery only exposes 8%).

### S3. Finished-basement effective sqft — two independent convergent findings
Engine prices above-grade only (LM_Dec_52); total-finished sqft is 100%-populated upstream and ≥1.2× above-grade for 25.8% of solds; error decomposition independently found a replicated −7% bias on finished-basement remarks and 3 of the 10 worst seed-43 misses quoting finished-basement sqft against half-sized sqft fields. A blanket +7% bump fails cross-seed — the fix must be sqft-basis-level.
Fix: land `total_fin_sqft`/`bsmt_fin_sqft` (D1), backtest eff_sqft = above_grade + k×bsmt_fin, k∈{0.3,0.5,0.7}, both sides; add both figures to packets; hygiene schema extracts {finished_basement, stated_total_finished_sqft} for subjects lacking the field.
Gain: 0.5-2pt engine + major tail. Cost: ~1h landing + backtests. Validation: paired both seeds, gate on the finished-basement segment bias closing.

### S4. Contract-date price-strike trending
`L_ContractDate` 100%-populated (or list_date+feed_dom); prices strike median 36d before close; engine trends from close_date. Cancels in LOO by construction — this is a **production bias correction** (~−0.35% Montgomery, ~−1% hot markets), verify backtest-neutrality only. Build the S1 index on contract month (de-lags ~1.2mo). Cost: 2-3h.

### S5. Winsorize the raw-ppsf outlier drop (confirmed non-monotonic)
Demonstrated: raising a comp's price DROPPED the estimate $405k→$395k at the 2.2× boundary (`cma_compset.py:990,1004`); test uses raw ppsf + upper-median while valuation uses adjusted ppsf + `statistics.median`; all-or-nothing min_keep revert is a second cliff. Fix: clamp adjusted ppsf into [med/2.2, med×2.2] instead of ejecting; standardize on `statistics.median`. Gain: ~0-0.2pt Montgomery; agent-facing stability + statewide thin-pool protection. Cost: ~2h.

### S6. Deterministic arms-length pre-filter (comps + packets + subjects, one shared predicate)
6.8% of the Montgomery pool trips a strong flag; blind packets filter on nothing but price>25k (~1.7 flagged sales per packet) and the blind arm is 50% of the ensemble; the public surface runs hygiene-OFF. Hard-drop refined-strong keywords + sold/list<0.85 (with new-construction guard — the >1.15 side is dominated by pre-sold builds and must stay down-weight-only) + escalate the B4 deed-ratio signal to drop. Precision hazards documented (bare "estate"/"family" unusable). Gain: 0.1-0.4 engine, plausibly larger on the blind arm. Cost: ~60 LOC + 2 reruns.

### S7. High-disagreement escalation (arbiter)
The >10%-disagreement half sits at 13.5% medAPE with a shared −9.4% bias in the 10-20% band — both arms miss low together (information gap, not arbitration); only 7/31 tail rows were arbitration-recoverable, oracle best-of-2 caps upside at ~2pt. Run only AFTER the data fixes (S2/S3) shrink the shared-miss population: second differently-composed blind packet (nearest-40 / same-subdivision) averaged in for spread3>10% subjects (~48% of volume). Gain: 0.3-0.9pt realistic. Cost: ~1 day + ~50 calls/run.

### S8. Score-weighted median + AVM monthly retrain (detrended target)
Comp scores never weight any valuation aggregate; a 0.6×-floor comp votes equally with a same-subdivision twin. Cheap deterministic experiment. AVM: scheduled retrain + fit on sold_price/index(close_month) so the tree stops extrapolating. Gain: 0.1-0.4 / durability. Cost: ~2h + half-day.

### S9. Product: on-market mode + spread-scaled intervals
Final list price is a 1.8% oracle — **circular for pre-listing CMAs, never use there** — but mean(ensemble, orig_list) = 5.14% on both seeds for buyer-side/portfolio/active-listing use. Separate product flag. Interval width scaled by comp spread + distance tier before the ±15% cap (fixes the coverage patch principledly).

---

## Tier 3 — Data acquisition (all already upstream; one projection edit + `mls-rebuild-parquet`)

**D1. Batch parquet landing** (`build_parcel_lookup.py:80-119`): total_fin_sqft, bsmt_fin_sqft, contract_date, distress bits (Estate 5.4%/Manufactured 5.8%/Modular 3.4%/Auction 2.1%/REO 0.8%/Short-sale/Duplicate), how_sold (Cash 28%), garage, basement, levels, fireplaces, taxes+tax_year, school district, waterfront (4.2%), # rooms. Consumption priority: blind packets (zero engine code) → AVM features → scorer terms only where a backtest earns them. Also use distress bits to clean future test draws. Cost: ~1-2h total. **Do early — gates S3, S4, S6, E4.**

**D2. Cleanup**: agent_remarks is 100%-NULL (feed never populates LR_remarks11) — drop from parquet + hygiene prompt ("AGENT REMARKS: (none)" on every call, ~10% tokens). Seller concessions confirmed 0% upstream — add a concessions question to the hygiene JSON schema instead (rides E2).

---

## Refuted / do-not-do (measured negatives — spending here is waste)

| Idea | Evidence |
|---|---|
| Global de-bias shift | c=0 exactly optimal on the ensemble; +2.77% bump → 7.71→8.63 |
| Flat distance tightening (1.5mi e-fold) | 10.48 vs 10.08, 16W/33L |
| Raw county-index swap for appr_rate | 8.8→9.0, bias worse |
| Photo-based condition adjustment | already dead (magnitude prompt-anchored) |
| 3-arm combiners / base in the ensemble | mean3 8.81, median3 10.13, trimmed 11.05 — correlated base+sr outvote the independent blind arm; keep 50/50 mean(sr, blind) |
| Base-trust regime selector | strictly-closest base 14/98, χ² p≈0.13, edge 1.3pt |
| Year-built / city fixed effects, price-conditional bias corrections | flagged in one seed only, sign-flips across seeds |
| Fitted ensemble weights | grid flat 0.4-0.6; anything tuned is in-sample |

---

## Measured ceiling & honest current accuracy

**Ground truth is mostly clean.** Seed-43's 7.71% is NOT pollution-inflated (excluding flagged subjects → 7.92); seed-42 carried ~0.4pt of real pollution (sr 8.25→7.80 clean). The **$306k case is REFUTED as non-arms-length** by two independent analysts (sold at 94% of its $324.9k list after 30 DOM — a genuine rural-acreage model miss; base +124%). One analyst's "confirmed non-arms-length" is overruled by the deed/list evidence. All six seed-43 >30% tail misses are market-corroborated real sales the models overestimate. Keep 016278 in all backtests — it is the engine's worst real failure mode. The comp-quality analyst's "~9.5% suspect actuals" flag (both arms >30% same direction) largely re-detects these real rural/segment failures, not bad labels; the dedicated pollution audit's 1-6% strong-flag rate stands.

**Information ceilings measured:** final list price 1.8-1.9% medAPE (full-information benchmark, circular); oracle best-of-2 arm selection 5.7%; counterfactual parity on the 3 replicated bad segments (no-subdivision, 2+ acres, price Q2) → 7.71→6.98 / 8.25→6.84, but meanAPE 11.5→8.2 and PPE20 83.7→96.9.

**Realistic best-achievable measured medAPE: ~6.5-7.0%**, via segment/data fixes (S2, S3, Q1) + packet enrichment (Q6) + AVM 4th signal (Q7). The median is robust — the sellable win is the tail: PPE20 from ~84 into the mid-90s (almost no >20% blowups), which matters more for CMA credibility than the last 0.5pt of median. Below ~6% requires information the pipeline does not have (verified interior condition/renovation state — the shared-miss band's gap).

**Honest current true accuracy: ~7.5-8.5%, not precisely known.** The 7.7% headline nets out three roughly offsetting measurement defects: pending-leak flattery of engine arms (~+1pt worse when fixed), the missing-subdivision handicap (~−1pt when fixed), and seed-43 SR cache contamination (direction unknown). Production additionally carries live defects the backtest never sees: wrong-property prior-sale anchors (B3), raw-AVM −2.4% blend drag (Q7), unmeasured list-price circularity (Q10), and ~−0.35% contract-lag bias (S4). The clean re-baseline (step 1) is the only way to state the real number.

---

## Recommended execution order (with gates)

1. **B1 + B2: harness + cache rebuild, then re-baseline all four arms** on rebuilt seed-42 and a fresh disjoint seed-44 with isolated caches. *Gate: numbers reproduce across days; per-arm caches clean; this becomes the new baseline for everything.*
2. **B3-B7 production bug batch** (prior-sale identity guard, deed-ratio column, hygiene backfill+floor, rounding to render, recency as-of). *Gate: no paired regression on the new baseline.*
3. **D1 parquet landing + D2 cleanup.** *Gate: column fill rates verified; rebuild clean.*
4. **Q1+Q2+Q4 deterministic compset batch → Q5 combined-arm confirmation** (n=200, held-out seed). *Gate: held-out paired median delta negative AND bias not worse → bake; else bake only individually-winning knobs.*
5. **Q3 hygiene repair (cache-replay variants, free) → productionize SR** on a clean seed. *Gate: SR beats no-hygiene arm standalone AND ensemble(SR-fixed, blind) beats ensemble baseline.*
6. **Q6 packet ladder E0→E4 + Q7 AVM debias + Q8 prior-sale re-enable**, rebuilding the ensemble after each winner. *Gate per arm: paired win on tuning seed, confirmed on held-out seed, PPE20 must not regress.*
7. **S1 index + S2 rural/land fix + S3 basement sqft + S4 contract date.** *Gates: S2 on the high-acreage backtest + ensemble; S3 on the finished-basement segment bias; S4 backtest-neutral (production-only correction).*
8. **Q9 confidence tiers ship** (after step 6 settles arm identities) + **S9 on-market mode**. *Gate: High tier <7% medAPE at 35-55% coverage on one fresh seed.*
9. **S5-S8 + Q10 knobs + S6 pre-filter + S7 arbiter**, opportunistically, each one-knob paired-arm gated; run S7 only after S2/S3 land.
10. **Final certification:** one never-touched seed (45+, disjoint parcels, arms-length-screened, per-criterion pollution counts reported), full arm suite, report medAPE/bias/PPE10/PPE20 raw and screened. This number is the new headline.

---

# Appendix — Investigator summaries

## audit:compset-scoring (11 findings)
Audited the comp candidate SQL, scoring formula, and shortlist-to-final flow in cma_compset.py/build_cma.py, then ran 8 paired deterministic LOO arms (100 seed-42 Montgomery subjects, hygiene off, frozen as-of, no LLM calls). Two harness-validity problems dominate: (a) backtest subjects omit subdivision/high_school, so the subdivision-first branch — which fires on 61/100 production-like subjects — and both scoring bonuses have never been in any measured number (adding the fields: median |APE| 10.08→8.94 paired); (b) the LOO view leaks future pendings (close_date NULL passes any as-of), touching 58/100 subjects' comp sets and flattering the engine arms by ~1pt median |APE| (leak-free rerun: 11.11) while the blind-Haiku packets are closed-sales-only — the engine-vs-blind comparison is tilted in the engine's favor. Real engine leaks measured: property_subtype is pulled but never used (58/100 final compsets mix Detached/Townhouse/Condo; hard-filter arm 9.10 median), the 30-row candidate-pool early stop starves the scorer (min_count=80 arm 8.95), and the atypical penalty asymmetrically punishes above-list sales which concentrate in the top price tercile. A combined arm reached 8.94 median (paired mean delta −1.17pt, 43W/39L, Wilcoxon p≈0.23 — directional, needs seed-43 confirmation). Distance-decay tightening (5mi→1.5mi e-fold) was tested and REFUTED (16W/33L). Note: this run's base (10.08) is not comparable to the remembered 8.8 because adding SELECT columns changed the pre-shuffle row order and hence the subject draw; only within-run paired deltas are valid.

## audit:estimation-core (9 findings)
Audited the full estimation chain in scripts/build_cma.py + cma_compset.py and ran three deterministic experiments (no LLM calls) on the seed-43 protocol: a 100-subject leak audit, a paired county-index time-trend probe, and an engine-only rerun on the exact 98 held-out subjects from final_validation_seed43.json. Headline: the single biggest measured leak is the stock hygiene layer itself — on the held-out draw the engine WITHOUT hygiene scores 10.7% medAPE / −2.3 bias vs 12.2% / −6.1 with stock hygiene, and the cache shows why: Haiku's ppsf adjustments are 5:1 negative (mean −3.0%) because the prompt asserts the subject is "average-to-updated", and 54% of verdicts eject the comp. The known non-monotonicity was confirmed mechanically: the $/sqft outlier drop tests RAW ppsf against the upper-median of the current set (cma_compset.py:990,1004), so pushing one comp across the 2.2× boundary ejects it and moved a real subject's mid from $405k DOWN to $395k as the comp got MORE expensive; hygiene keep-drops churn membership the same way through the trim at build_cma.py:1844 and the clamp caps at 1076-1088. Other measured leaks: subjects with more acreage than their top-3 comps carry +13.0% median signed bias (land double-count + the max(0,gap) asymmetry at build_cma.py:736,819,838), comp-spread strongly predicts error (medAPE 5.6% low-spread tercile vs 12.4% high-spread; Spearman 0.22) but neither the interval nor the ensemble uses it, and the appreciation estimator saturates its clamps on 72% of subjects — though a county-index replacement tested neutral (8.8→9.0), bounding that leak. $5k rounding is aggregate-neutral (−0.05pp median) but costs up to +2.3pp APE on sub-$150k homes.

## audit:hygiene-llm (8 findings)
Audited the LLM comp-hygiene layer (cma_hygiene.py, llm.py, prepare_comps/apply_hygiene in build_cma.py) plus a zero-LLM cache-replay experiment on 100 seed-42 subjects (scratchpad/hygiene_audit_rerun.py/.json). Headlines: (1) the stock hygiene pass measured ~zero net lift in the original runs (8.9% no-AI vs 8.8% hygiene) while flagging 54% of reviewed comps for removal and silently destroying 4/100 estimates — because most drops are property-type mismatches the SQL could filter deterministically (property_subtype is SELECTed but never used; _class RE_1 is 26% townhouse/condo); (2) the model-blind cache key is worse than documented — the experiment harness omits subdivision from subjects so the signature degrades to sqft-only, and I demonstrated live that 18/40 fully-covered subjects in the replay were served verdicts computed for a different subject, and 33/100 "held-out" seed-43 subjects shared a cache signature with seed-42, partially contaminating the 10.0% SR headline; (3) verdict mapping is zip-by-index (the model's returned "address" is ignored) so any omission/reorder misassigns verdicts and poisons the cache, and truncation kills the whole batch silently; (4) the effective ±30 adjustment clamp is 2x the deterministic path's ±15 with no parse-time clamp (cached max |adj|=70), and the replay decomposition shows adjustments-only ≈ base while drops-only hurts; (5) the prompt omits DOM, list-price trajectory, prior deed sale, and property_subtype — all in the parquet — and presents pending comps' synthetic prices as real sales. Biggest accuracy lever: move type-filtering to SQL + backfill after drops + productionize the subject-remarks variant on a fixed (remarks+model-hashed, versioned) cache.

## audit:priorsale-avm-trend (7 findings)
Audited the two test-disabled signals (prior-sale anchor, AVM) and the time machinery in C:/Users/zach/Desktop/MLS Bot/scripts/build_cma.py, then measured everything locally on the exact seed-42/43 held-out subjects (no LLM calls). Mechanics: the prior-sale anchor trends the subject's last MLS sale forward at the comp-pool appreciation rate and enters the blend with weight 3.0*exp(-months/13) — but it reads the full parquet directly (the backtest leak) and matches on parcel_id alone, which the data shows collides across different properties for ~2% of closed rows (junk ids like 'TBD'); 2 of 27 simulated anchors were wrong-property hits. The AVM is a HistGradientBoostingRegressor frozen 2026-05-06 with training cutoff 2025-09-30 and no calendar-level feature: measured on the 2026 held-out subjects it carries a -7 to -8% staleness bias, and a leak-free county-index debias cuts its solo medAPE 11.0->8.5 (seed43) and, added to the 7.7% ensemble at w=0.5, lifts PPE20 84->89 / PPE10 58->63 on seed-43 and PPE20 68->83 on seed-42. Time adjustment is a per-CMA split-half estimate from the final ~6 comps clamped to [0,+12%]/yr with default +4% — Montgomery's actual index runs +3-4%/yr, so trend error explains under ~1pt of seed-43's -6.1% bias (which is spread across all as-of months, i.e., mostly draw difficulty); the index's real value is enabling prior-sale trending, AVM debiasing, and falling-market correctness. A leak-free prior-sale re-enable (as-of-aware query + identity/flip guards) is designed and simulated: anchors fire on ~14% of subjects (data-history-capped) with anchor-alone medAPE 3.3-4.0%, worth ~0.1-0.3pt overall today and more as history accumulates. Contract-vs-close: prices are set at contract, ~36 days (median) before close; this cancels in the LOO backtest but makes production ~0.3-0.4% low in Montgomery today.

## audit:data-enrichment (10 findings)
Audited every column the CMA read-path actually consumes (cma_compset.py candidate SELECT + scorer, build_cma.py estimator, cma_hygiene.py, and the blind-valuer packet builder) against the 30-column parquet, the 225MB listings JSONL, and the RETS metadata export. Three headline conclusions: (1) the parquet itself hides several unused-or-broken fields — property_subtype is selected but never used (26% of Montgomery RE_1 solds are Townhouse/Condo, and Condo runs $273/sqft vs Detached $226), the comp-side non-arms-length deed check is provably dead code, and half_baths is never scored; (2) the ingest JSONL already carries — fully populated, no re-pull needed — total-finished sqft (25.8% of solds have ≥1.2x the above-grade sqft the engine prices on), contract date (median 36-day close lag), explicit REO/short-sale/estate/auction/manufactured flags (~11% of comps), financing type, garage/basement/levels/fireplaces, taxes, and school district; landing them is a one-file projection edit in build_parcel_lookup.py plus `tasks.py mls-rebuild-parquet`; (3) the strongest arm (blind Haiku, 8.2%) is fed a starved packet — the subject prompt even omits year_built while comps show theirs — and five cheap packet-enrichment experiments (~$0.30-0.60 per 100-subject arm) directly upgrade it. Seller concessions are the one hoped-for field that is genuinely absent upstream (0% populated); they remain reachable only through remarks.

## data:error-decomposition (8 findings)
Decomposed the held-out seed-43 ensemble (mean(sr_raw, blind), n=98, 7.71% median |APE|, median bias -2.77%) by joining every subject back to data/mls_lookup.parquet (0 unmatched in both seeds) and cross-checked every segment against seed-42 (sr arm, n=95, 8.25%). The replicated weaknesses are property-information gaps, not model/arbitration failures: no-subdivision rural homes (19.8%/33.1% medAPE), 2+ acre parcels (15.9%/14.4%), the lower-middle price quartile (13.5%/11.2%), workshop/outbuilding remarks (18.9%/20.3%), and a systematic -7% underestimate of finished-basement homes whose below-grade area is missing from the MLS sqft field (3 of the 10 worst misses quote "finished basement"/"2,650 finished square feet" against sqft=1325). Fixing the 3 worst replicated segments to overall-median accuracy moves medAPE only 7.71->6.98 (seed-43) / 8.25->6.84 (seed-42) because the median is robust, but transforms the tail: meanAPE 11.5->8.2, PPE20 83.7->96.9. Two bonus levers: sr-vs-blind disagreement is a strong shippable confidence gate (bottom-2/3 disagreement = 6.25% medAPE vs 14.34% for the top third), and the suspected non-arm's-length $306k actual is actually clean (sold at 94% of its $324.9k list after 30 DOM) — the models, not the actual, are wrong on rural acreage (base arm +124% on that row). A flat de-bias bump HURTS (7.71->8.63), so the -2.8% bias is concentrated in segments, not global.

## data:ground-truth-pollution (6 findings)
Audited ground-truth pollution across both backtest draws (seed-42 and seed-43 reproduced exactly: 95/95 and 98/98 JSON pids) plus the full Montgomery comp pool (444 sales/6mo, 1382/18mo), using deterministic flags: strong remarks keywords, sold/list ratio outside [0.85,1.15], and same-city ppsf |z|>2.5. Headline: the test is mostly honest — pollution explains at most ~0.3-0.5pt of median APE and only in some draws. Seed-43's 7.7% ensemble medAPE is already clean (excluding flagged subjects moves it to 7.9, i.e., no inflation), and all six seed-43 tail misses (>30% APE) are market-corroborated real sales (sold/list 0.92-1.03, normal DOM) that the models overestimate — real model error, not bad actuals. Seed-42 DID contain real pollution (2 auctions + 1 fixer at 0.82x list, median APE of flagged subjects 41.9% vs 8.5% unflagged; cleaning improves sr arm 8.25->7.80). The famous $306k case is refuted as non-arm's-length: it listed at $324.9k and closed at 0.94x list after 30 DOM — a model overestimate (1969 ranch, appearance=Average, acreage/view over-credit), not test pollution. Comp-pool pollution is real but modest: 6.8% of Montgomery sales trip a strong flag (1.7% keywords, 3.3% ratio, 3.0% z, nearly disjoint); 100% have remarks, and spot-checks show the Haiku hygiene pass would plausibly catch ~7-8/10 — but hygiene is OFF on the public surface and the blind-arm nearest-25 packets are completely unfiltered, so a deterministic pre-filter still has a job.

## data:ensemble-confidence (6 findings)
Audited the seed-43 held-out rows (n=98, final_validation_seed43.json) plus seed-42 (remarks_subject_results.json) with pure local analysis (scripts ensemble_analysis.py/2/3 in the scratchpad; attributes joined from data/mls_lookup.parquet). Headlines: (1) the shipped 50/50 mean(sr_cap, blind) is already at the empirical optimum — the weight grid is flat 0.4–0.6 and every base-including or robust combiner is worse because base and sr are correlated arms that outvote the independent blind arm; (2) arm disagreement is a genuinely strong confidence signal — a 3-arm spread <=10% tier delivers 4.7% medAPE / 77.5 PPE10 / 92.5 PPE20 on 41% of subjects (bootstrap P=0.999) vs ~13.5% medAPE below the cut, and Medium/Low are indistinguishable so ship two tiers, not three; (3) no bias correction is defensible — the ensemble's medAPE-optimal global shift is exactly 0 on seed-43 despite -2.8 median bias, and price-conditional biases flip sign between seeds; (4) there is no detectable regime where the stock engine should be trusted more (strict base wins 14/98, chi-square p≈0.13, median winning edge 1.3pt). The remaining accuracy ceiling is arm quality on the 48% high-disagreement subjects (13.5% medAPE, shared -9.4% bias in the 10-20% band), plus dirty actuals (pid 016278 confirmed non-arm's-length), not combination math.

## data:comp-quality-vs-error (7 findings)
Joined the 95 seed-42 subjects (remarks_subject_results.json) to their hygiene-selected comp sets (vision_compsets.json) via the MLS parquet and computed per-subject comp-quality metrics, then tested each against |e_sr|. Headline: comp DISTANCE is the dominant and only strongly significant comp-quality error driver (min chosen-comp distance spearman rho=0.415, p<0.001; still 0.319/p=0.003 after excluding suspect sales), while comp AGE has zero correlation with error (rho=-0.03) — the $/sqft time-adjustment already compensates for stale comps but nothing compensates for far comps. Subjects whose nearest chosen comp is <0.5mi run 7.7% medAPE vs 14.4% at 0.5-1.5mi and 33.1% beyond 1.5mi; critically, all 9 far-comp subjects HAD eligible candidates within 1.0mi that the scorer's flat exp(-d/5) decay passed over, and a naive nearest-6 estimator beats the engine 8/13 in the 0.5-1.5mi band (14.4→10.2) while losing badly in the bulk — so the fix is steepening decay inside the existing scorer, not distance-first selection. Comp ppsf spread does NOT beat distance (partial rho 0.057 vs 0.291 for distance) and only predicts tail risk. Separately, ~9.5% of backtest "actuals" look non-arm's-length (all arms miss >30% in the same direction, e.g. $83k actual / +117% base error), which inflates measured medAPE and explains much of the cross-seed draw variance.



---

# ADDENDUM — 2026-07-07 wave-1 execution + clean re-baseline

Tier-0 (B1-B7) + D1 all landed and verified (6-agent workflow + follow-ups; engine tests 36/36).
Gates run on the REBUILT harness (leak-free LOO, subdivision-restored subjects, v2 hygiene cache,
backfill+floor, +/-15 clamp, arm-private caches, disjoint draws):

| Arm (raw medAPE) | seed-42 | seed-43 disjoint |
|---|---|---|
| engine-only | 9.5 | 9.7 |
| + stock hygiene (repaired) | 9.2 | 11.3 |
| + subject-remarks hygiene | 10.0 | 11.0 |
| blind Haiku | — | 9.5 |
| **ens(hygiene + blind)** | — | **8.9 raw / 8.7 screened (PPE10 55, PPE20 82)** |
| ens(SR + blind) | — | 9.5 |
| ens(engine-only + blind) | — | 9.7 |

Verdicts vs the pre-fix era:
- **SR's big median wins do NOT replicate on the repaired system** (they were partly compensating for
  the broken machinery: contaminated cache, unclamped adjustments, no backfill). SR's consistent residual
  benefits: bias (-3.1->-1.7 s42; -1.1->-0.6 s43) and PPE20 (+3/+1). Keep the production hook (it is the
  off-market/user-upload mechanism) but it is NOT the default arm.
- **Stock hygiene standalone is draw-inconsistent** (+0.3 s42, -1.6 s43) — BUT the ensemble built on the
  hygiene arm beats the engine-only ensemble (8.87 vs 9.69, P=0.73): hygiene's errors decorrelate with
  blind's. Hygiene earns its keep through the ensemble, not solo. (Replicates the pre-fix finding.)
- **Q1 subtype filter: NOT promoted** (seed-44 gate: 10.6 vs 10.6, 9W/13L). Q2 pool-floor-80 and Q4
  symmetric penalty: refuted on the clean harness. All three stay env-gated off.
- **New honest baseline: ens(engine+hygiene, blind) ~ 8.7-8.9 medAPE** on a clean disjoint holdout —
  the old 7.7% headline was harness-inflated, as predicted (honest range was estimated 7.5-8.5).

Next (wave 2, in plan order): Q6 blind-packet enrichment ladder (blind is the anchor arm — feeding it the
D1 fields + remarks is the highest-leverage remaining experiment), Q7 AVM index-debias as 4th signal,
Q8 leak-free prior-sale re-enable, S2 rural/acreage fix, S3 finished-basement effective sqft, Q9 confidence
tiers (clean-harness split: spread<=10% -> 8.4 vs 10.9 — weaker than pre-fix but real).


---

# ADDENDUM 2 — 2026-07-07 wave-2 results (Q6/S1/Q7/Q8)

**Q6 packet ladder: PROMOTED (E3, all-or-nothing).** Enriched blind packet (fixed subject fields + RE_1/dedup/addr-guard
SQL + structured comp fields incl. D1 columns + price-stripped comp remarks + $-masked subject remarks): blind arm
9.5->8.5 on seed-43-disjoint (49W/26L p=.011, PPE20 +3); **new best ensemble ens(hygiene, E3-blind) = 8.1 raw / 7.8
screened, bias -2.4->-0.3, PPE10 58, PPE20 83** (paired vs 8.9 baseline: 48W/28L p=.029). E2 (comp remarks w/o subject
remarks) REJECTED as a stopping point. Follow-up worth $2: E1+subject-remarks-only variant (comp remarks may be dead
weight). Artifacts: packet_ladder.py / packet_ladder_results.json / mls_snapshot_q6.parquet (pin!).

**S1 county index: PROMOTED (infrastructure).** build_market_index.py -> data/market_index.parquet + market_index.py
loader (index_ratio production / index_ratio_asof leak-free; n>=8 floor; 15/15 checks). Montgomery +4.4%/yr implied.
Coverage honest: only ~7 NRV counties clear the floor — fallbacks stay load-bearing. tasks.py: mls-rebuild-market-index.

**Q7 AVM de-bias: PROMOTED (set CMA_AVM_INDEX_DEBIAS=1 in prod).** Corrects the frozen model's -7..-8% staleness to ~0;
beats AVM-off paired on BOTH seeds (W62/33, W63/31) with PPE10+PPE20 improving both; vs raw AVM it is a bias fix (medians
~neutral). Also: CMA_SKIP_AVM=1 harness convention understates production ~0.4-0.7pt. 4th-signal ens3 on seed-43 =
7.7 raw (W65/31) but PPE20 82->80 + no disjoint confirm yet -> NEEDS-MORE-DATA.

**Q8 prior-sale: seam+as-of routing PROMOTED (bug-fix class; production parity 63/63); CMA_PRIOR_SALE_GUARDS=1 PROMOTED
for prod** (flip guard 2/2 catastrophic-flip catches, saves 18/40pp, zero false trips; guards-vs-unguarded passes both
draws, no PPE regressions). Prior-sale-vs-OFF accuracy claim NEEDS-MORE-DATA (anchor-alone 7.3/13.9 not the audit's
3.3-4.0; stale-anchor clamp-saturated trending is the residual failure -> wire S1 index into anchor trending + ~24-30mo
age cap, then re-run prior_sale_arm.py). Keep prior-sale disabled in headline harness baselines for comparability.

**Combined stack (post-hoc, seed-43, needs fresh-seed confirm before promotion):** ens(base, E3-blind) + de-biased AVM:
mean3 = 7.61 raw / 7.46 screened (W64/32 vs ens2_new); w=0.3 = 7.35 raw, PPE10 62 (w fitted in-sample — treat as ceiling
estimate). PPE20 slips 83->82 by ~1 subject.

**Production gap:** the ensemble/blind arm exists only in the harness. Production today = engine + hygiene + raw AVM +
unguarded prior-sale. Shipping list: set CMA_AVM_INDEX_DEBIAS=1 + CMA_PRIOR_SALE_GUARDS=1 (engine flags, ready);
productionize the E3 blind arm + 50/50 mean in the worker/service (new build); then the certification run (fresh seed-45,
full stack).
