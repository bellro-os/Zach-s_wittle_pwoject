# Production-posture certification — blind ensemble flag-on vs flag-off (July 2026)

*Run 2026-07-13 · standing 1000-subject NRV pool (seed 20260708) · engine @ `6f11c2d` · production posture in BOTH arms: AVM ON + `CMA_AVM_INDEX_DEBIAS=1` (leak-free as-of index), prior-sale ON + `CMA_PRIOR_SALE_GUARDS=1`, hygiene OFF (anon posture) · arms differ ONLY in `CMA_BLIND_ENSEMBLE` · leave-one-out on the pinned snapshot, per-subject frozen as-of, **as-of-routed prior-sale** (anchor can only see sales strictly before the subject's sale — the quasi-oracle confound of the 15-subject spot check is dead) · blind = `claude-haiku-4-5-20251001` on the LOO comp packets, scratch cache, production 8s timeout, fold = the shipped `_apply_blind_ensemble`.*

Scored 1000/1000; blind anchors 987; anchor folded on 987 (rest engine-only fallback = production behavior). Prior-sale anchors found on 58 subjects, 0 as-of violations.

## Paired arms (common support)

| Arm | n | Median \|APE\| | Mean \|APE\| | Signed bias | PPE5 | PPE10 | PPE20 | >20% | >30% |
|---|---|---|---|---|---|---|---|---|---|
| flag-off (engine, production knobs) | 1000 | 11.78% | 24.71% | +2.24% | 24.0% | 44.4% | 67.3% | 327 | 208 |
| **flag-on (+ blind ensemble)** | 1000 | 11.21% | 23.61% | +1.56% | 26.9% | 45.5% | 68.5% | 315 | 197 |

**Paired bootstrap** (4000 resamples): delta medAPE (on − off) = **-0.57 pp**, 95% CI [-1.21, +0.29], P(improve) = 88.7%.

## Price terciles (both arms)

| Tercile | Median sold | n | off med\|APE\| | on med\|APE\| | off bias | on bias | off PPE20 | on PPE20 |
|---|---|---|---|---|---|---|---|---|
| low | $190,000 | 333 | 19.3% | 19.03% | +17.7% | +15.61% | 50.5% | 50.8% |
| mid | $310,000 | 333 | 8.93% | 8.68% | +1.19% | -0.17% | 77.5% | 81.1% |
| high | $525,800 | 334 | 10.69% | 9.77% | -5.02% | -5.54% | 74.0% | 73.7% |

## Launch-gate segment (flag-on arm, production posture)

Gate = nearest selected comp ≤ 0.3 mi AND farthest ≤ 1.0 mi AND engine-vs-blind agreement |engine−blind|/ens within the threshold.

| Segment | n | Coverage | on med\|APE\| | on mean | on PPE10 | on PPE20 | off med\|APE\| (same subjects) |
|---|---|---|---|---|---|---|---|
| agreement ≤ 8% | 343 | 34.3% | 7.24% | 14.7% | 62.1% | 84.0% | 7.02% |
| **agreement ≤ 10% (the gate)** | 383 | 38.3% | 7.24% | 14.61% | 61.9% | 83.3% | 7.29% |
| agreement ≤ 12% | 417 | 41.7% | 7.15% | 14.25% | 62.1% | 83.2% | 7.37% |
| distance only (no agreement) | 503 | 50.3% | 7.46% | 14.37% | 60.8% | 82.1% | 8.12% |

## Secondary: hygiene-ON (authed posture), first 200 subjects

| Arm | n | Median \|APE\| | Mean | Bias | PPE10 | PPE20 | >20% |
|---|---|---|---|---|---|---|---|
| flag-off (hygiene on) | 200 | 11.78% | 24.21% | +0.79% | 45.5% | 68.0% | 64 |
| flag-on (hygiene on) | 200 | 11.33% | 24.08% | +1.78% | 46.5% | 68.0% | 64 |

Paired bootstrap: delta medAPE -0.45 pp, 95% CI [-2.25, +1.55], P(improve) 63.2%.

## Verdict

**flag-on improves the production posture** — see the tables above; the detail per subject is in `prod_posture_cert_detail.jsonl`.

{VERDICT_NOTES}