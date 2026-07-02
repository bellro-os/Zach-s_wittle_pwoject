# compbird — Market Report Tool + Feature Roadmap (2026-07-02)

Grounded in the stress-tested market-tools design (workflow wgmd16dxw), the regional
accuracy test (docs/regional-accuracy-2026-07.md), and the live FREE/Pro-$20 paywall.

## 1. The Market Report tool (the Pro carrot)

**Shape:** a scoped market engine + an in-studio "Market" view first; the downloadable
Market Report PDF is a fast-follow (it needs the report-template registry).

- **M0 — engine:** `computeMarketReport(scope)` behind `GET /api/compbird/markets/[scope]`
  (scope = county/city, subdivision where MLS-dense). Extends the proven DuckDB runner.
- **Metrics (verified computable):** sold-to-list ratio + % over/under list (MLS rows ONLY —
  supplemental list_price is NULL by design), price & $/sqft distribution (IQR + histogram),
  price/$psf trend with **sample-size gating** (monthly → quarterly → "insufficient data";
  subdivision monthly medians are noise), seasonality (median by calendar month), hottest-
  subdivisions ranking, current months-of-inventory as a POINT-IN-TIME scalar.
  **Never ship:** absorption/inventory *trends* — history isn't in the data; only a
  forward-collected snapshot job can ever chart those.
- **Coverage-aware:** every response carries provenance (`mls | mls+supplemental`);
  supplemental extends sold-side metrics to the VA+DC 130-county map, county scope only.
- **M1 — studio Market view:** a tab beside the report — KPIs, distribution chart,
  gated trend, seasonality. Free = view on screen; Pro = part of the download.
- **M2 — Market Report PDF** (needs template decomposition) → **M3 — recurring client
  digest** (retention lever; needs saved-sphere + deliverability domain — last).

## 2. Other features, ranked by leverage

1. **Provenance panel on every report** — "6 comps: 4 MLS · 2 public records · nearest
   0.3 mi" + the published spread. Trust is the RPR-beating differentiator; we already
   have the data. (S)
2. **My reports shelf** — accounts exist; persist each generated dossier (subject, tuned
   comp set, PDF token) and re-run in one click. Foundation for compare + digest. (M)
3. **Shareable read-only report links** — tokenized like the PDF names; agent texts a
   client a live link. FREE shares carry the compbird mark = the viral loop. (M)
4. **Coverage explorer** — an honest interactive county map from the regional-test
   coverage table ("where compbird works, and how deep"). Marketing that's also a
   disclosure. (M)
5. **Compare view** — 2–3 saved properties side by side (listing pitch tool). (M)
6. **What-if pricing slider** — reuse the override engine: drag sqft/condition, watch the
   estimate move; the record→adjusted disclosure already exists. (S–M)
7. **Blend rule in the engine** — MLS pool when nearest MLS comp ≤ ~2 mi, supplemental
   beyond; direct evidence from the regional test. Engine-side, backtest-gated. (M)

**Sequence:** P1 = Market M0–M1 + provenance panel · P2 = shelf + share links ·
P3 = Market PDF + compare + coverage explorer · P4 = digest.

## 3. Anti-slop design rules (bake into every new surface)

The site's identity is "precision instrument": Bricolage display type, one blue accent,
mono figures, real data. New features must keep it:

- **Real numbers or nothing.** Every figure on a marketing or product surface comes from
  an actual engine run (the landing already does this). No invented stats, no lorem.
- **Data IS the layout.** Lead with the chart/table/figure; prose annotates it. No
  three-icon-card rows explaining what a histogram would show better.
- **Asymmetry + editorial rhythm.** Alternate dense data panels with quiet full-width
  statements; avoid uniform card grids and centered-hero + gradient-blob clichés.
- **One accent, no emoji, no glassmorphism soup.** Muted ink surfaces, hairline rules,
  the existing tick/contour motifs.
- **Concrete copy.** "Six closed comps within 1.1 mi" — never "unlock powerful insights."
  Publish the spread and the provenance; hedge where the data is thin (gating labels).
- **Charts:** shared scales, labeled axes, no decorative 3-D or sparkline confetti;
  IQR bands + histograms over donut charts.
