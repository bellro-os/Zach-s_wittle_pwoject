# Road to 5% median |APE| — iterative testing plan (nationwide-flexible)

*Draft 2026-07-08. Target: drive median absolute percentage error as close to 5% as possible before
launch, with a method that generalizes to any US market. Grounded in the July accuracy program
(certified 7.9% MLS ensemble on held-out seed-45; Zillow-only 13–16%; price-tilt + calibration
findings). This is a testing/iteration plan, not a feature spec.*

---

## 0. Honest framing — what "5%" means, and the unlock

- **Best certified today:** 7.9% median |APE| (MLS + AI ensemble `ens3`, held-out seed-45, Montgomery).
- **Measured ceiling with current methods:** ~6.5–7% median. Getting *every* property below 5% would
  require signal we don't model yet (interior condition, richer comps). Treat blanket-5% as the
  north star, not a day-one gate.
- **The unlock that makes "5% at launch" real — confidence tiers.** We already measured that the
  subset where the 3 valuation methods agree within 10% hits **4.7% median |APE| / PPE20 92.5% on
  ~41% of subjects** (P=.999). So we do not need every home at 5%; we need to *know which homes are
  already at 5%* and launch those with confidence, then grow that set every iteration.

**The plan therefore optimizes two things at once:** (a) push the overall median down toward 5%, and
(b) grow the share of properties that provably sit ≤5% (the launchable set). Success = "at launch,
the properties we show a confident number for are ≈5%, and that set keeps expanding."

---

## 1. The measurement backbone (build this first — everything gates on it)

Nothing promotes without a trustworthy, nationwide-representative test rig. Harden what the July runs
already used (`cert_seed45.py`, `blacksburg_head_to_head.py`, the paired-arm harness):

1. **Certification protocol (frozen, reused every iteration):** leave-one-out, as-of frozen,
   held-out seeds disjoint from all tuning, paired bootstrap (P-improve + 95% CI), report median &
   mean |APE|, signed bias, PPE5/10/20, resolve rate — **plus per-segment breakdowns** (price tier,
   property type, rural/urban, market density, data tier). The median hides the tail; segments expose
   where the next point lives.
2. **National stratified test set — not just Blacksburg.** Sample subjects across a fixed panel of
   market archetypes: dense metro (e.g. NoVA/Richmond), suburban, small-town, rural; and across data
   tiers (below). ≥100 subjects/market, multiple seeds. A lever must generalize across the panel to
   promote — this is what makes the tech nationwide-flexible instead of Blacksburg-tuned.
3. **Data tiers (a market belongs to exactly one; each has its own baseline + gate):**
   - **T1 — MLS-covered:** full MLS+county pool + AI pass. Baseline ~7.9%.
   - **T2 — scrape + county:** Zillow scrape ∪ public deed records, no MLS. Baseline ~14.5% (Blacksburg).
   - **T3 — scrape-only:** Zillow alone. Baseline ~13–16% engine, ~13.5% w/ calibration.
4. **Automated scoreboard** (extend `cma_dial_all.py`): one command runs the full arm suite per market
   in the panel and appends median |APE| + PPE20 + launchable-share to a tracked table, so every
   iteration's effect is visible and regressions are caught.

**Gate to leave Phase 0:** the scoreboard reproduces the known numbers (7.9% T1, ~14.5% T2, ~13.5% T3)
and runs end-to-end on ≥6 markets across all 3 tiers.

---

## 2. The iteration loop (the method, repeated until diminishing returns)

Each cycle (the loop already used all July):

1. **Pick** the highest expected-gain lever from the backlog (§3).
2. **Implement env-gated** — default OFF, so Ratifyly/production stays byte-identical until promoted.
3. **Paired test** on the national panel + held-out seeds.
4. **Promotion gate (all must hold):** median |APE| improves by a pre-registered margin **AND** PPE20
   does not regress **AND** it generalizes (wins on ≥2 market archetypes and ≥2 seeds, not one lucky
   draw — the July n=20→n=100 reversal is the cautionary tale). Adversarial check: does it help the
   *segment* it targets without hurting others?
5. **Promote or reject**, re-baseline, update the scoreboard + the launchable-share number.
6. Repeat.

Cadence: aim for one promoted lever per iteration; expect ~1 in 2 candidates to fail the gate (that
is the process working, not failing).

---

## 3. Prioritized lever backlog (sequenced by expected gain × confidence × reach)

| # | Lever | Tier | Expected gain | Effort | Evidence |
|---|---|---|---|---|---|
| **L1** | **Productionize the `ens3` ensemble** (E3 blind + AVM-debias mean) — it's harness-only today; production still serves ~10% base | T1 | **~10% → 7.9%** | Low (wiring) | Certified seed-45 |
| **L2** | **Confidence tiers live** — compute the method-agreement tier, gate the launchable set, show it | all | Unlocks the **4.7%** segment for launch | Low–Med | 4.7%/PPE20 92.5% on 41% (P=.999) |
| **L3** | **2-param regional calibration** (level + price-slope) in the dial-in loop | all | ~2.5pt on scrape; helps T1 up-market tail | Med | Held-out 15.9%→13.5% |
| **L4** | **Detail-sweep enrichment** (year_built, price_history→prior-sale, subtype from home_type) | T2/T3 | Root-cause fix for scrape thinness; unlocks the AI pass | Med–High | Head-to-head packet gap |
| **L5** | **Scrape-shaped AI pass** — retune the blind packet to available fields | T2/T3 | Recover the ~2–4pt AI gain on scrape | Med | Current pass *hurts* thin packets |
| **L6** | **Wave-3 tail fixes** — S1 prior-sale index trending, S2 rural/acreage model, S3 finished-basement effective-sqft, prior-sale age cap | all | ~0.3–1pt each, kills tail segments | Med | Replicated segment failures (rural 19.8%, basement −7% bias) |
| **L7** | **Price-tier-aware comp selection** — stop cheap comps dragging high-end estimates | all | Attacks the up-market tilt at the source | Med | Bias −2.6/−9.2/−15.0% by tercile |
| **L8** | **Interior-condition signal** (photo upload → condition) | all | The likely key to breaking ~6.5% toward 5% | High | Condition is the top unmodeled variance driver |
| **L9** | **Model expansion** — per-region retrained AVM, more/fresher comps, better similarity model, more ensemble members | all | Diminishing, but where the last points live | High | — |

Rationale for the order: L1–L2 are near-free and get T1 to a launchable 5% *segment* almost immediately.
L3–L5 lift the scrape tiers so nationwide coverage isn't stuck at 14%. L6–L7 grind the tail. L8–L9 are
the research bets required to move the *whole* distribution under 6%.

---

## 4. Market-tier launch gates (what "ready" means per market)

A market goes **live** only when its held-out panel run clears its tier gate:

- **T1 (MLS):** overall median ≤ 6%, **high-confidence segment ≤ 5%**; launch high-confidence homes
  first, show a wider range on the rest.
- **T2 (scrape+county):** overall ≤ 9–10% after calibration; launch high-confidence segment only,
  with an explicit coverage/confidence disclosure.
- **T3 (scrape-only):** engine + calibration; launch with prominent confidence framing; expand as
  enrichment (L4) lands.

This is the crux: **launch is gated on the confident segment, not the blanket median.** Every market
ships the ≤5% homes on day one and widens coverage as the loop improves it.

---

## 5. Nationwide flexibility (the architecture that makes it scale)

Already partly built — the plan leans on it so no market is bespoke:

- **Region calibration store** (`cma_regions.json`, fips5 → CBSA → state → global precedence) — now
  extended to the 2-param calibration (L3).
- **Coverage/status registry** per region (`building | calibrating | live`) — the app serves only
  `live` regions, each with its measured accuracy + confidence disclosure.
- **Cron-able dial-in loop** — refresh data → rebuild pool → recalibrate → re-certify → auto-promote
  through the gate → flip to `live`. New markets onboard by *running the loop*, not writing code.
- **Tier routing** — each region maps to a data tier (T1/T2/T3), which selects the pool + calibration.

The same tech serves a NoVA MLS market and a rural scrape-only county; only the tier + region
calibration differ, and both are data, not code.

---

## 6. Milestones

- **M1 (launch-ready core):** Phase-0 backbone + L1 + L2. Outcome: T1 markets ship a
  high-confidence set at ≈5%; we can name the launchable share per market.
- **M2 (broaden T1, lift the median):** L3 + L6 + L7. Outcome: T1 overall toward ~6%, launchable
  share grows.
- **M3 (nationwide scrape):** L3 + L4 + L5 on T2/T3. Outcome: scrape markets to ~8–10%, launchable
  segments open nationwide.
- **M4 (break the ceiling):** L8 (condition) + L9. Outcome: attempt to move the *whole* distribution
  under 6% toward 5%.

---

## 7. Risks & the honest ceiling

- **5% blanket may be unreachable with current signal.** The measured ceiling is ~6.5–7%. If L1–L7
  plateau there, hitting 5% *everywhere* needs L8 (condition) and/or L9 (better comps/models) — treat
  those as the research track, and lean on confidence tiers to launch at 5% on the ready segment
  meanwhile. Say this plainly to stakeholders.
- **Small-sample mirages.** The n=20→n=100 reversal (6.5%→16%) proves single draws lie. The multi-
  seed, multi-market gate is non-negotiable.
- **Overfitting the panel.** Keep a truly-held-out national seed set touched only at certification.
- **Scrape legal/ToS exposure** at national scale — a standing decision flagged in the scrape-only
  plan; unchanged here.
- **Basis consistency** — scrape accuracy is basis-sensitive (Zillow-basis subjects + Zillow comps +
  calibration, not cross-basis). The test rig must match production basis per tier.

---

## First concrete step

Stand up Phase-0 (§1) and run L1 + L2 to establish the launchable-5% segment on T1 markets — that is
the fastest path to a truthful "we're at 5% for the homes we're confident about, on N markets" before
launch. Everything after is the loop in §2 grinding the median and growing that segment.
