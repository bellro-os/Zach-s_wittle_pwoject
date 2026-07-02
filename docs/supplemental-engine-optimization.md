# Optimizing the engine for supplemental-only comps (2026-07-02)

Grounded in: the 12-region test (supplemental +8% hot statewide, wins MLS-thin, loses
MLS-dense), the Blacksburg 20-home head-to-head (18.3% vs 15.5% median error, +3.2pt
hot per home), and a field inventory of the raw source (351k rows: beds 90.7%,
baths 91.2%, sfla 91.6%, lot 86.1%, home_type ~100%; list_price 0% — schema-only,
never captured; NO year_built column).

Every lever is backtest-gated: the paired-arm harness runs 40 engine calls in ~15s,
so nothing promotes without beating the current baseline on held-out sold subjects,
statewide — not just Montgomery.

## Ranked levers

1. **Regional sqft-basis calibration (kills the known bias).** The single 0.76
   scalar was fit on Montgomery (bias there ≈ 0) and runs +8% hot statewide, +19%
   in Craig. Fit per-county factors — or better, a small regression on homes present
   in BOTH pools (same address ⇒ MLS finished-area vs assessor-basis sfla) by
   county × size-band × home_type. Supervised, cheap, directly attacks the
   largest measured error component.

2. **home_type-aware comping (~75k rows currently flattened).** TOWNHOUSE (54k),
   CONDO (16.5k), MANUFACTURED (4.7k) all map into the same class as single-family
   today, so condos price against SFH comps and vice versa. Carry home_type into
   the pool as property_subtype + add a same-type similarity term. The worst
   Blacksburg misses (+34%, +39% on the two cheapest homes) fit this failure shape.

3. **year_built + attribute enrichment via the parcel join.** The source has no
   year-built, but the pipeline already owns statewide assessor records that do.
   Join scraped rows → parcels by address/lat-lng (both geocoded), fill year_built
   (0% → high), enabling age adjustment + sharper comp ranking. Flagged as the
   cheapest data lever by the regional report.

4. **Pool-aware scoring profile.** When source=supplemental: treat missing fields
   (year_built, condition) as NEUTRAL in similarity, not mismatches; tighten the
   distance budget (median nearest comp is 0.17 mi — the engine shouldn't reach
   0.92 mi when closer sales exist); raise recency weight since no DOM/pending
   leading signals exist.

5. **Public-records outlier guards.** Deed data includes non-arm's-length transfers
   (family sales, partial interests) the MLS-based atypical detector can't see.
   Flag comps that deviate hard from their own micro-area $/sqft distribution
   before they enter a slate.

6. **AVM behavior on the supplemental pool.** The sklearn AVM trained on MLS
   features sees nulls here. Verify its contribution on supplemental-only runs;
   either retrain a reduced-feature variant on the 333k scraped sales or drop the
   AVM method and reweight comp methods for this pool.

7. **Explicit time-index adjustment.** 36 months of sales support a county price
   index; adjust older comps to as-of value rather than relying on recency
   weighting alone.

8. **(Scraper-side, future sweep):** the listing pages show list price; capturing it
   would populate the dead list_price column and unlock sold-to-list downstream.

## Expected shape of the win

Levers 1–3 together plausibly close most of the ~3pt dense-area gap and widen the
existing rural lead (where the pool already beats MLS by 10+ points). The end state
feeding production stays the blend rule: MLS pool when a close MLS comp exists,
supplemental beyond — with a supplemental arm strong enough to stand alone where
it must.
