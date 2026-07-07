# Comp Workshop + Similarity Score
Build plan · Compbird · 2026-07-06 · Status: approved design, ready to sequence

---

## 1. Chosen UX concept

**Concept A — "the table IS the workshop"**: a Match column (0–100) with a per-axis breakdown popover added to the existing comps table, a live estimate-delta ticker + ghost baseline tick in the valuation panel, and a reset-to-engine chip — plus one graft from Concept B (a collapsed "Next-best candidates" bench strip) and one from Concept C (engine-generated plain-English reason strings).

Why: the exclude/pin/recompute loop is already shipped and the engine already computes the score with a per-axis breakdown, so Concept A ships the category's only transparent per-comp similarity score with zero new surfaces, zero learning curve, and one click per correction — which is exactly the simplicity moat. Concepts B and C add interaction physics (drag/drop, forced wizard steps) that tax the 90%-the-engine-was-right case to serve the 10% case, inverting the "near-instant" promise.

---

## 2. v1 CUT — smallest shippable version that preserves the wow

**IN (v1):**
- **Match column** in comps-table: integer 0–100 + tier word (85+ Excellent · 70–84 Strong · 55–69 Fair · <55 Weak) + hairline ember bar. Renders on first paint (profile) and every recompute (preview).
- **Breakdown popover** on the Match figure: six subscore bars (Location / Recency / Size / Lot / Age / Type) with one reason string each ("0.3 mi away · same subdivision"), plus atypical/pending discounts and the "overall also reflects sale-price alignment" footnote. Mobile: bottom sheet.
- **Pinned-comp honesty**: pinned rows wear their real score ("Pinned · Match 34") with the two dragging subscores named; pin-rejection toast carries the concrete reason (closes ui-review #23).
- **Realized estimate delta**: after any toggle/pin recompute, ticker under the mid — "Engine set $455,000 → yours $462,000 (+1.5%)" — with a ghost tick at the original engine estimate, and a **Reset to engine picks** chip whenever excluded ∪ forced ≠ ∅.
- **Non-suppressible disclosure**: tuned sets print "Comp set adjusted by agent: 2 removed, 1 added" in the PDF; weak pins keep their Weak label in the report.
- **FREE teaser**: one aggregate line added to the redaction-surviving CompsSummary — "6 comparable sales · nearest 0.3 mi · average match 78 — unlock the comp set to see why."

**Deliberately OUT (v1):**
- **Per-comp impact_usd chips** (leave-one-out "−$12k if removed") — spec is final (see §3) but it's v1.1; the realized-delta ticker delivers 80% of the feeling for zero engine work.
- **Bench strip** (next-best candidates) — v1.1; needs the runner-up pool on the wire.
- **Hygiene_note surfacing**, `/profile` forced/excluded params (saved tuned workspaces), parcel_id-keyed pin protocol (address substrings ship v1 with known limits), nComps UI (pin-truncation warning is a toast, not a control), confidence-tier hookup for weak pins, weight-visibility "lot matters more here" hints, first-run coach mark, photo/condition AI, weight sliders (never — display must not fork from engine truth).

---

## 3. Similarity-score spec (final)

### Mapping (raw → 0–100)
```
similarity = round(100 × clamp01(final_score / achievable_max(subject)))
achievable_max = Σ _weights_for_subject(subject).values()
              + (50 if subject has normalized subdivision else 0)
              + (15 if subject has high_school else 0)
```
- **Raw-anchored, never set-renormalized**: a comp's number is f(subject, comp) only — pinning/excluding other comps cannot move any badge. 100 = "best possible comp for THIS subject."
- Atypical ×0.80 / pending ×0.90 multipliers fold in **before** normalization (the discount shows in the number, matching what the selector actually used).
- Set-relative signals ($/sqft outlier flag, quality floor) go in `atypical_flags[]`, **never** in the score.
- Missing-data comps land ~mid-40s from 0.5-neutral axes → tooltip says "limited data," not "poor match."
- Known drift (recency decays daily; pending imputed price wobbles with pool median): documented, disclosed, not fixed.

### Six subscores (1:1 onto existing `_score_breakdown`; engine generates reason strings)
| Key | Derivation | Reason example |
|---|---|---|
| location | (w_DIST·dist + earned bonuses) / (w_DIST + possible bonuses) | "0.3 mi away · same subdivision" |
| recency | rec_score | "sold 2 months ago" |
| size | sf_score | "18% larger — 2,940 vs 2,480 sqft" |
| lot | ac_score | "0.45 ac vs 0.30 ac" |
| age | yr_score | "built 1998 — 6 yrs older" |
| type | (w_BEDS·bd + w_BATHS·fb) / (w_BEDS + w_BATHS) | "3 bd / 2 ba vs 4 bd / 2.5 ba" |

Missing input → subscore `null` + reason "sqft not recorded" → UI renders em-dash. The price-band axis is deliberately not a shown subscore (reads circular) but stays in the overall; when price_score < 0.4, append reasons[] entry "sold well outside the subject's price band." Invariant: overall ≠ average of the six (price axis + multipliers live only in the overall) — stated in tooltip. Each subscore carries `weight_pct` (share of achievable_max).

### API contract (additive per-comp fields on preview + profile `comps[]`)
```json
{
  "similarity": 78,
  "subscores": [
    {"key":"location","label":"Location","score":91,"weight_pct":34,"reason":"0.3 mi away · same subdivision"},
    {"key":"recency","label":"Recency","score":72,"weight_pct":15,"reason":"sold 2 months ago"}
  ],
  "reasons": ["0.3 mi away","sold 2 months ago","18% larger"],
  "atypical_flags": ["Sold ~12% below list — possibly distressed."],
  "hygiene_note": "condition: renovated (+4% $/sqft)",
  "impact_usd": -12000
}
```
Plus subject-level `"similarity_summary": {"avg":74,"top":91,"low":52}` (avg/top feed the FREE teaser; low is internal). All fields optional app-side → older engine responses stay valid. Scores are 0–100 ints; `null` = not computable. `reasons[]` = top-3 by weight_pct × |score−100|. Reason strings generated **engine-side** (one canonical phrasing for studio, PDF, future share links); provenance vocabulary is only "MLS" / "public records" — never vendor names.

**impact_usd (v1.1)**: engine-side leave-one-out inside build_preview after the final set exists — `round_to_$1k(mid_all − _estimate_value(subject, comps_without_i).mid)`, diffing **unrounded** mids. AVM computed once (subject-only); total ≤ ~50ms warm. Null when set ≤ 3 comps. Tooltip caveat: "if removed (before a replacement backfills)." Client-side recompute is rejected — it re-creates the preview≠PDF divergence build_preview exists to kill.

### Env gate
`CMA_COMP_SCORE_SURFACE=1`, set **only** in Compbird's own engine-instance environment (same isolation pattern as `CMA_LISTINGS_PARQUET`). Unset → serialization byte-identical to today → Ratifyly untouched. New pure helper `similarity_surface(subject_record, comp)` lives in cma_compset.py (owns weights/subdivision semantics), called from the serialization loop inside one `if`; reads `_score_breakdown` outputs only — never re-runs or alters score_comp, selection, or floors.

### Paywall placement
Server redaction already strips `comps → []` for FREE, so **every per-comp field is SOLO-only by construction** — zero new gating code. The single decision: add `avg_similarity` + `top_similarity` ints to CompsSummary (computed before the strip, like the existing distance teaser). Rejected: FREE "best comp" scorecard (leaks strongest evidence), address-hidden scored rows (scraping-by-elimination). No settings, no sliders.

---

## 4. Implementation checklist (dependency order)

**⚠ Files owned by the currently-running Compbird workflow — sequence all edits to them AFTER it finishes: `comps-table.tsx`, `add-comp-search.tsx`, `valuation-panel` component.** Engine + types + redact work has no collision and can start now.

### Phase A — Engine (MLS Bot repo, no app dependency)
1. **[S]** `similarity_surface()` helper: normalization, six subscores, reason strings, atypical_flags, similarity_summary. → `src/mls_bot/analytics/cma_compset.py` (beside score_comp :439-550, weights :184-200)
2. **[S]** Emit fields in serialization behind `CMA_COMP_SCORE_SURFACE=1`; no key reordering when unset. → `scripts/build_cma.py` `_preview_comp_dict` :2140-2160, response assembly :2261-2288
3. **[S]** Add `similarity` + subscores to the **profile** payload (first paint currently has no score). → `scripts/property_profile.py` `_build_comps` :188-229, same gate
4. **[S]** Set the env var in Compbird's engine service env. → `compbird_engine_setup.ps1` / service environment
5. **[M]** *(v1.1)* Leave-one-out `impact_usd` in build_preview post-hygiene/trim on the final set; unrounded-mid diffs. → `build_cma.py` near :2261, reusing `_estimate_value` :1220-1355
6. **[M]** *(v1.1)* Runner-up pool: return top ~12 scored non-selected candidates (already scored in pick_comps — expose, don't recompute). → `cma_compset.py` pick_comps :1113-1287, `build_cma.py`, `worker/cma_worker.py` /preview :151-168

### Phase B — Worker/wire (depends on A)
7. **[S]** Verify /preview and /profile pass the new fields through untouched (worker returns build_preview dict verbatim — likely no change; confirm spawn-runner parity too). → `worker/cma_worker.py`, `Compbird src/lib/cma/engine.ts` :237-316

### Phase C — App types + server (Compbird repo; no collision with running workflow)
8. **[S]** Extend `PreviewComp`/`ProfileComp` with optional `similarity/subscores/reasons/atypical_flags/hygiene_note/impact_usd`; extend `CompsSummary` with `avg_similarity/top_similarity`. → `src/lib/compbird/types.ts` :45-49, :88-112, :185-215
9. **[S]** Fix the drop: `previewCompToProfile` must carry the new fields (it currently drops `score` on the floor). → `src/components/compbird/studio/comp-studio.tsx` :64-93
10. **[S]** Teaser aggregates computed before the strip; locked-panel copy line. → `src/lib/compbird/redact.ts` :46-83, locked report view

### Phase D — App UI (⚠ SEQUENCE AFTER the running workflow releases these files)
11. **[M]** Match column + tier + bar; null-subscore em-dashes; pinned rows show honest score. → `comps-table.tsx` (columns :45-55) ⚠
12. **[M]** Breakdown popover / mobile bottom sheet with six bars + reasons + multiplier lines + invariant footnote (also closes ui-review #10). → `comps-table.tsx` + new `match-popover.tsx` ⚠
13. **[S]** Delta ticker + ghost baseline tick + "Reset to engine picks" chip. → valuation-panel component ⚠ + `comp-studio.tsx` (diff consecutive unrounded mids)
14. **[S]** Pin-rejection toast upgraded to carry concrete reason; pin-truncation-past-nComps warning toast. → `comp-studio.tsx` :328-350
15. **[S]** PDF disclosure line "Comp set adjusted by agent: N removed, M added" + Weak labels in report comp table (reuses reportConfig/audit rails). → report template path + `generate/route.ts` audit :136-144
16. **[M]** *(v1.1)* Bench strip: collapsed "Next-best candidates (12)" disclosure row, Match + one-line why-not + one-click Add. → `comps-table.tsx` footer region ⚠, depends on item 6
17. **[S]** *(v1.1)* impact_usd chips per row with the backfill caveat tooltip. → `comps-table.tsx` ⚠, depends on item 5
18. **[M]** *(fast-follow)* parcel_id-keyed pin/exclude protocol (kills the MAIN-ST-substring collision class); feed min(pinned similarity) into confidence tier. → `cma_compset.py` :1194-1237, `comp-studio.tsx`, `add-comp-search.tsx` ⚠

Each phase is additive and reversible by unsetting the flag. v1 = items 1–4, 7–15.

---

## 5. Ranked next-features menu (post-workshop)

1. **Aggregate provenance strip** — "6 comps: 4 MLS · 2 public records · nearest 0.3 mi · avg match 78" on report + FREE locked state; roadmap's own #1 trust play. [S]
2. **Bench strip** (next-best candidates, one-click add) — the only power feature costing zero new learning. [S–M]
3. **Per-comp impact chips** (impact_usd) — "removing this moves the estimate −$4,200"; no competitor surfaces it. [M]
4. **My Reports shelf** — persist {subject, tuned comp set, PDF token}, one-click re-run; needs /profile forced/excluded params; foundation for compare + digest. [M]
5. **Shareable client link** — read-only, tokenized like PDFs; reason strings make it homeowner-legible; the viral loop. [M]
6. **Market snapshot panel** (M0–M2) — the SOLO carrot, one panel not a dashboard, sample-size gated. [M]
7. **What-if pricing slider** (sqft + condition) — plumbing shipped (subject overrides + disclosure); demo gold. [S–M]
8. **On-market / seller mode** — active/pending subjects get list-price band + DOM + sold-to-list framing; a toggle, not a product. [M]

---

## 6. Competitive positioning

Every agent CMA tool lets you add and remove comps; none of them will tell you whether you just made your valuation better or worse. RPR buries the answer under a five-step wizard and an adjustments grid it warns you to ask your broker about; Cloud CMA is a beautiful report template over manual MLS-number entry; dashCMA proved agents want simplicity but sells persuasion, not measurement; HouseCanary has the only similarity score in the market and ships it as an unexplained black box aimed at lenders. Compbird is the only tool where a solo agent types an address, gets a measured ~8%-median-error valuation on one screen, and can tune the comp set with one-click excludes and pins while every comp — including the one they just added — wears a live 0–100 match score with the reasons in plain English and the estimate's drift from the engine baseline always visible. The honest sentence: **Compbird is the only CMA tool that grades your comps and shows its work — RPR makes you do the appraiser math, Cloud CMA makes you format it, and Compbird just does it, for a flat $20.** The number is copyable in a quarter; the reasons layer welded to a measured engine, honest thin-market labeling, and a non-suppressible adjusted-by-agent disclosure is the moat.
