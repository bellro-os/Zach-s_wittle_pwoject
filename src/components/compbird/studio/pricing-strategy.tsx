"use client";

import { memo } from "react";

import { Pill } from "@/components/compbird/ui";
import { cn } from "@/lib/utils/cn";
import { usd, usdCompact, num, placeLabel } from "@/lib/compbird/format";
import {
  computePricingStrategy,
  type StrategyBand,
  type PricingStrategy as PricingStrategyModel,
} from "@/lib/compbird/pricing-strategy";
import type {
  Valuation,
  MarketContext,
  PricingSurface,
  PricingBand,
  PricingTargetDom,
} from "@/lib/compbird/types";

/**
 * ZONE 1 companion — replaces the old Street View tile (which was dead weight
 * without a Google Maps key). Where that showed nothing, this answers the
 * question an agent actually works at the listing table: what does each list
 * price likely COST in time on market?
 *
 * TWO data postures, one panel:
 *
 *   ENGINE MODEL (CMA_PRICING_SURFACE=1 — `pricing.bands` on the wire): the
 *   three cards carry the engine's OWN dom_model quantiles (q25–q75 envelope,
 *   q50 emphasized) and price_cut_model cut-probability per band, plus the
 *   target-DOM "price to sell by a date" row and a derived overpricing-cost
 *   sentence. The synthetic client-side elasticity is fully REPLACED here.
 *
 *   SYNTHETIC FALLBACK (bands absent — older engines, the sample, locked
 *   reports where redact.ts strips `pricing`): exactly today's behavior — the
 *   documented client-side elasticity model, honest by construction (see
 *   lib/compbird/pricing-strategy.ts), degrading to "pace unavailable" when
 *   the neighborhood pace is missing/redacted.
 */

/** "~14–18 days" from a modeled range, or the muted no-data fallback. */
function domText(band: StrategyBand): string {
  if (!band.domRange) return "pace unavailable";
  const [lo, hi] = band.domRange;
  if (lo === hi) return `~${num(lo)} days`;
  return `~${num(lo)}–${num(hi)} days`;
}

/**
 * Horizontal position (0–1) of a band on the low→high rail, from its price.
 * The rail spans the outer bands; Market lands wherever mid sits between them
 * (rarely the exact center — the interval is usually asymmetric). Single-band
 * degradations pin to center.
 */
function railFraction(band: StrategyBand, bands: StrategyBand[]): number {
  const min = bands[0].price;
  const max = bands[bands.length - 1].price;
  if (max <= min) return 0.5;
  return (band.price - min) / (max - min);
}

/** Ember for the anchor, a cool tone for fast, a caution tone for the risky ceiling. */
function markerColor(band: StrategyBand): string {
  if (band.isAnchor) return "var(--cb-ember)";
  if (band.cutRisk) return "var(--negative)";
  return "var(--muted-foreground)";
}

/** Tiny inline clock — the app ships no icon font, so glyphs are hand-drawn SVG. */
function ClockGlyph() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 shrink-0" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M8 5v3l2 1.3"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Caution triangle for the above-market price-cut risk. */
function RiskGlyph() {
  return (
    <svg viewBox="0 0 16 16" className="mt-px h-3.5 w-3.5 shrink-0" fill="none" aria-hidden>
      <path d="M8 2.5l5.6 9.7H2.4L8 2.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M8 6.4v2.6M8 10.9v.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

/* ── ENGINE-MODEL path (pricing.bands / pricing.target_dom on the wire) ────── */

/** One engine band, validated + mapped onto the panel's display vocabulary. */
interface ModelBand {
  key: "fast" | "market" | "maximize";
  label: string;
  blurb: string;
  price: number;
  isAnchor: boolean;
  domQ25: number | null;
  domQ50: number | null;
  domQ75: number | null;
  /** price_cut_model probability 0–1; null when the wire value was unusable. */
  cutProbability: number | null;
}

/** Wire key → display vocabulary (labels/blurbs match the synthetic cards). */
const MODEL_BAND_META: Record<
  PricingBand["key"],
  { key: ModelBand["key"]; label: string; blurb: string }
> = {
  sell_fast: { key: "fast", label: "Sell fast", blurb: "Priced to move" },
  market: { key: "market", label: "Market", blurb: "The estimate" },
  maximize: { key: "maximize", label: "Maximize", blurb: "Test the ceiling" },
};

function finiteOrNull(n: unknown): number | null {
  return typeof n === "number" && Number.isFinite(n) && n >= 0 ? n : null;
}

/**
 * Validate + map the wire bands. null unless at least one band survives — the
 * caller then keeps the synthetic path EXACTLY as before. Defensive per field:
 * a band with a bad price is dropped; bad quantiles/probability degrade to
 * null on an otherwise-good band (prices still render).
 */
export function buildModelBands(pricing: PricingSurface | null | undefined): ModelBand[] | null {
  const raw = pricing?.bands;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const out: ModelBand[] = [];
  for (const b of raw) {
    const meta = b && typeof b === "object" ? MODEL_BAND_META[b.key] : undefined;
    if (!meta) continue;
    if (typeof b.price !== "number" || !Number.isFinite(b.price) || b.price <= 0) continue;
    if (out.some((existing) => existing.key === meta.key)) continue; // one card per key
    const p = b.cut_probability;
    out.push({
      ...meta,
      price: Math.round(b.price),
      isAnchor: meta.key === "market",
      domQ25: finiteOrNull(b.dom_q25),
      domQ50: finiteOrNull(b.dom_q50),
      domQ75: finiteOrNull(b.dom_q75),
      cutProbability: typeof p === "number" && p >= 0 && p <= 1 ? p : null,
    });
  }
  if (!out.length) return null;
  out.sort((a, b) => a.price - b.price);
  return out;
}

/**
 * Validated target-DOM points ("price to sell by a date"), ascending by days.
 * SATURATION GUARDS (observed live on hot markets): the engine solver sweeps a
 * bounded price grid, and when even the grid ceiling clears every horizon it
 * returns the same max-grid price for 30/45/60d — a technically-correct but
 * useless "price to sell by any date: $1.02M" row. So: (a) drop points priced
 * >5% above the Maximize band (beyond the strategy rail = extrapolation, not
 * advice), (b) suppress the row entirely when every remaining point carries
 * one identical price (no information).
 */
export function buildTargetDom(
  pricing: PricingSurface | null | undefined,
  bands?: ModelBand[],
): PricingTargetDom[] {
  const raw = pricing?.target_dom;
  if (!Array.isArray(raw)) return [];
  let out = raw
    .filter(
      (t): t is PricingTargetDom =>
        t != null &&
        typeof t === "object" &&
        typeof t.days === "number" &&
        Number.isFinite(t.days) &&
        t.days > 0 &&
        typeof t.price === "number" &&
        Number.isFinite(t.price) &&
        t.price > 0,
    )
    .sort((a, b) => a.days - b.days);
  const ceiling = bands?.find((b) => b.key === "maximize")?.price;
  if (ceiling != null && ceiling > 0) {
    out = out.filter((t) => t.price <= ceiling * 1.05);
  }
  if (out.length > 1 && out.every((t) => t.price === out[0].price)) return [];
  return out;
}

/**
 * The overpricing-cost readout: what listing at the ceiling (Maximize) costs
 * vs Market, in days and cut risk — one derived sentence, null when either
 * side is missing or the ceiling isn't above market.
 */
export function overpricingSentence(bands: ModelBand[]): string | null {
  const market = bands.find((b) => b.key === "market");
  const maximize = bands.find((b) => b.key === "maximize");
  if (!market || !maximize) return null;
  const dPrice = maximize.price - market.price;
  if (dPrice <= 0) return null;
  const clauses: string[] = [];
  if (maximize.domQ50 != null && market.domQ50 != null && maximize.domQ50 > market.domQ50) {
    clauses.push(`costs ~${Math.round(maximize.domQ50 - market.domQ50)} extra days`);
  }
  // Cut model uses features beyond price, so its band curve can be
  // non-monotonic (observed live: maximize 41% < sell_fast 45%). Only voice the
  // clause when the ceiling genuinely raises the risk — "raises ... from 47% to
  // 41%" reads as a bug.
  if (
    maximize.cutProbability != null &&
    market.cutProbability != null &&
    maximize.cutProbability > market.cutProbability
  ) {
    clauses.push(
      `raises the chance of a price cut from ${Math.round(market.cutProbability * 100)}% to ${Math.round(maximize.cutProbability * 100)}%`,
    );
  }
  if (!clauses.length) return null;
  return `Listing +${usdCompact(dPrice)} above market ${clauses.join(" and ")}.`;
}

/** Rail position 0–1 for a price across the model bands' span. */
function modelRailFraction(price: number, bands: ModelBand[]): number {
  const min = bands[0].price;
  const max = bands[bands.length - 1].price;
  if (max <= min) return 0.5;
  return (price - min) / (max - min);
}

/** Marker color for a model band — ember anchor, caution ceiling at ≥50% cut odds. */
function modelMarkerColor(band: ModelBand): string {
  if (band.isAnchor) return "var(--cb-ember)";
  if (band.key === "maximize" && band.cutProbability != null && band.cutProbability >= 0.5)
    return "var(--negative)";
  return "var(--muted-foreground)";
}

/** "~19–34 days · typically 26" with q50 emphasized; degrades per known quantile. */
function ModelDomLine({ band }: { band: ModelBand }) {
  const { domQ25: q25, domQ50: q50, domQ75: q75 } = band;
  if (q25 == null && q50 == null && q75 == null) {
    return (
      <span className="flex items-center gap-1.5 font-data text-xs italic text-muted-foreground/70">
        <ClockGlyph />
        pace unavailable
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 font-data text-xs text-muted-foreground">
      <ClockGlyph />
      <span>
        {q25 != null && q75 != null ? (
          <>
            ~{num(q25)}–{num(q75)} days
            {q50 != null ? (
              <>
                {" "}
                · typically <span className="font-medium text-foreground">{num(q50)}</span>
              </>
            ) : null}
          </>
        ) : (
          <>~{num(q50 ?? q25 ?? q75)} days</>
        )}
      </span>
    </span>
  );
}

/** "24% chance of a price cut" + a subtle hairline gauge (instrument, not alarm). */
function CutRiskGauge({ probability }: { probability: number }) {
  const pct = Math.round(probability * 100);
  const risky = probability >= 0.5;
  return (
    <span className="flex flex-col gap-1">
      <span
        className={cn(
          "font-data text-xs",
          risky ? "text-[var(--negative-foreground)]" : "text-muted-foreground",
        )}
      >
        {pct}% chance of a price cut
      </span>
      <span className="block h-[3px] w-full overflow-hidden rounded-full bg-border/50" aria-hidden>
        <span
          className="block h-full rounded-full"
          style={{
            width: `${pct}%`,
            backgroundColor: risky ? "var(--negative)" : "var(--muted-foreground)",
          }}
        />
      </span>
    </span>
  );
}

/**
 * The model-backed panel: same header idiom, rail, and three-card layout as
 * the synthetic path, but every day/risk figure is the ENGINE's dom_model /
 * price_cut_model output — no client-side elasticity anywhere on this path.
 */
function ModelPricingStrategy({
  bands,
  targets,
  marketContext,
  areaName,
  areaCounty,
}: {
  bands: ModelBand[];
  targets: PricingTargetDom[];
  marketContext: MarketContext | null;
  areaName?: string | null;
  areaCounty?: string | null;
}) {
  const area = placeLabel(areaName, areaCounty) || "this area";
  const overpricing = overpricingSentence(bands);

  // Trend context pill — same derivation the synthetic header uses.
  const trendDirection = marketContext?.ppsf_trend_direction ?? null;
  const trendClause =
    trendDirection === "up"
      ? "prices trending up"
      : trendDirection === "down"
        ? "prices trending down"
        : trendDirection === "flat"
          ? "prices flat"
          : null;

  return (
    <div className="flex flex-col gap-4">
      {/* Header — eyebrow + subhead left, the data source named plainly right. */}
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex flex-col gap-1">
          <span className="cb-eyebrow text-muted-foreground">Pricing strategy</span>
          <p className="text-xs leading-snug text-muted-foreground">
            What each list price is likely to cost you in time on market.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone="ember">market model</Pill>
          {trendClause ? <Pill tone="neutral">{trendClause}</Pill> : null}
        </div>
      </div>

      {/* Price rail — same decorative idiom as the synthetic path. */}
      {bands.length > 1 ? (
        <div aria-hidden className="px-2 pb-1 pt-3">
          <div className="relative h-2 rounded-full border border-border bg-secondary">
            {bands.map((band) => (
              <span
                key={band.key}
                className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${modelRailFraction(band.price, bands) * 100}%` }}
              >
                <span
                  className={cn("block rounded-full", band.isAnchor ? "h-4 w-4" : "h-2.5 w-2.5")}
                  style={{
                    backgroundColor: modelMarkerColor(band),
                    boxShadow: band.isAnchor
                      ? "0 0 0 4px var(--cb-tint)"
                      : "0 0 0 2px var(--card)",
                  }}
                />
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {/* Strategy cards — label, price, the modeled DOM envelope (q50
          emphasized), and the per-band cut-probability gauge. */}
      <ul className={cn("grid gap-3", bands.length > 1 && "sm:grid-cols-3")}>
        {bands.map((band) => (
          <li
            key={band.key}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-3.5",
              band.isAnchor
                ? "border-2 border-[var(--cb-ember)]/50 bg-[var(--cb-tint)]/40"
                : "border-border bg-secondary/30",
            )}
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: modelMarkerColor(band) }}
              />
              <span
                className={cn(
                  "text-sm font-semibold",
                  band.isAnchor ? "text-[var(--cb-ember-text)]" : "text-foreground",
                )}
              >
                {band.label}
              </span>
              {band.isAnchor ? (
                <span className="cb-eyebrow ml-auto text-[var(--cb-ember-text)]">Market value</span>
              ) : null}
            </div>

            <span className="text-xs text-muted-foreground">{band.blurb}</span>

            <span
              className={cn(
                "font-data text-xl font-medium leading-none tracking-tight",
                band.isAnchor ? "text-[var(--cb-ember-text)]" : "text-foreground",
              )}
            >
              {usd(band.price)}
            </span>

            <ModelDomLine band={band} />

            {band.cutProbability != null ? (
              <CutRiskGauge probability={band.cutProbability} />
            ) : null}
          </li>
        ))}
      </ul>

      {/* Price-to-sell-by-date — dom_model.recommend_price_for_target_dom. */}
      {targets.length ? (
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
          <span className="font-medium text-foreground">Need to sell by a date?</span>
          {targets.map((t, i) => (
            <span key={t.days} className="inline-flex items-baseline gap-x-3 font-data text-muted-foreground">
              {i > 0 ? (
                <span aria-hidden className="text-border">
                  ·
                </span>
              ) : null}
              <span>
                {t.days}d: <span className="text-foreground">{usdCompact(t.price)}</span>
              </span>
            </span>
          ))}
        </p>
      ) : null}

      {/* Overpricing cost — Maximize vs Market, one derived sentence. */}
      {overpricing ? (
        <p className="flex items-start gap-1.5 text-xs leading-snug text-muted-foreground">
          <span className="text-[var(--negative-foreground)]/90">
            <RiskGlyph />
          </span>
          {overpricing}
        </p>
      ) : null}

      {/* Honest disclosure — names the model and its scope. */}
      <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
        Days on market and price-cut odds are modeled from {area}&rsquo;s recent sales,
        evaluated at each list price. A directional estimate, not a guarantee.
      </p>
    </div>
  );
}

/* ── SYNTHETIC fallback path (no pricing.bands on the wire) ────────────────── */

function SyntheticPricingStrategy({
  valuation,
  marketContext,
  areaName,
  areaCounty,
}: {
  valuation: Valuation | null;
  marketContext: MarketContext | null;
  /** Neighborhood/scope name for the disclosure line ("Walnut Creek"). */
  areaName?: string | null;
  /** County, so the disclosure can fall back to a place label. */
  areaCounty?: string | null;
}) {
  const model: PricingStrategyModel | null = computePricingStrategy(valuation, marketContext);

  // No usable mid → nothing honest to anchor bands on; hide the whole panel.
  if (!model || model.bands.length === 0) return null;

  const { bands, paceLabel, baseDom, trendDirection } = model;
  const hasPace = baseDom != null;
  const area = placeLabel(areaName, areaCounty) || "this area";

  // Trend clause for the pace context pill — only when the engine gave us one.
  const trendClause =
    trendDirection === "up"
      ? "prices trending up"
      : trendDirection === "down"
        ? "prices trending down"
        : trendDirection === "flat"
          ? "prices flat"
          : null;

  return (
    <div className="flex flex-col gap-4">
      {/* Header — eyebrow + subhead on the left, the model's headline pace
          assumption pinned right (stated plainly, never buried). */}
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex flex-col gap-1">
          <span className="cb-eyebrow text-muted-foreground">Pricing strategy</span>
          <p className="text-xs leading-snug text-muted-foreground">
            What each list price is likely to cost you in time on market.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={hasPace ? "ember" : "neutral"}>{paceLabel}</Pill>
          {trendClause ? <Pill tone="neutral">{trendClause}</Pill> : null}
        </div>
      </div>

      {/* ── PRICE SPECTRUM (decorative) ────────────────────────────────────────
          A low→high rail with a marker per band, positioned by real price. The
          anchor wears an ember halo so the eye lands on market value first. Pure
          decoration — aria-hidden — the same numbers read out in the cards. */}
      {bands.length > 1 ? (
        <div aria-hidden className="px-2 pb-1 pt-3">
          <div className="relative h-2 rounded-full border border-border bg-secondary">
            {bands.map((band) => {
              const frac = railFraction(band, bands);
              return (
                <span
                  key={band.key}
                  className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                  style={{ left: `${frac * 100}%` }}
                >
                  <span
                    className={cn("block rounded-full", band.isAnchor ? "h-4 w-4" : "h-2.5 w-2.5")}
                    style={{
                      backgroundColor: markerColor(band),
                      boxShadow: band.isAnchor
                        ? "0 0 0 4px var(--cb-tint)"
                        : "0 0 0 2px var(--card)",
                    }}
                  />
                </span>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* ── STRATEGY CARDS (the accessible source of truth) ────────────────────
          One card per band — label, $ price, modeled pace. The anchor carries an
          ember frame + tag; the ceiling spells out its price-cut risk in text
          (never color alone). Three-up on wide, stacked on mobile. */}
      <ul className={cn("grid gap-3", bands.length > 1 && "sm:grid-cols-3")}>
        {bands.map((band) => (
          <li
            key={band.key}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-3.5",
              band.isAnchor
                ? "border-2 border-[var(--cb-ember)]/50 bg-[var(--cb-tint)]/40"
                : "border-border bg-secondary/30",
            )}
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: markerColor(band) }}
              />
              <span
                className={cn(
                  "text-sm font-semibold",
                  band.isAnchor ? "text-[var(--cb-ember-text)]" : "text-foreground",
                )}
              >
                {band.label}
              </span>
              {band.isAnchor ? (
                <span className="cb-eyebrow ml-auto text-[var(--cb-ember-text)]">Market value</span>
              ) : null}
            </div>

            <span className="text-xs text-muted-foreground">{band.blurb}</span>

            <span
              className={cn(
                "font-data text-xl font-medium leading-none tracking-tight",
                band.isAnchor ? "text-[var(--cb-ember-text)]" : "text-foreground",
              )}
            >
              {usd(band.price)}
            </span>

            <span
              className={cn(
                "flex items-center gap-1.5 font-data text-xs",
                hasPace ? "text-muted-foreground" : "italic text-muted-foreground/70",
              )}
            >
              <ClockGlyph />
              {domText(band)}
            </span>

            {/* Price-cut caveat — spelled out in text so it survives color-blind
                and screen-reader use; only on the above-market ceiling. */}
            {band.cutRisk ? (
              <span className="flex items-start gap-1.5 text-xs leading-snug text-[var(--negative)]">
                <RiskGlyph />
                Above market — higher chance of a price cut.
              </span>
            ) : null}
          </li>
        ))}
      </ul>

      {/* ── HONEST DISCLOSURE ──────────────────────────────────────────────────
          Names it a model, never a promise. Two forms: with a median to anchor
          on, and the muted fallback when the pace data is missing/redacted. */}
      <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
        {hasPace ? (
          <>
            Time on market modeled from {area}&rsquo;s median pace of {num(baseDom)} days at
            market price; pricing above market typically extends time and raises the chance
            of a price reduction. A directional estimate, not a guarantee.
          </>
        ) : (
          <>Pace data unavailable for {area} — prices shown without a time-on-market model.</>
        )}
      </p>
    </div>
  );
}

/* ── Dispatcher ────────────────────────────────────────────────────────────── */

function PricingStrategyImpl({
  valuation,
  marketContext,
  pricing = null,
  areaName,
  areaCounty,
}: {
  valuation: Valuation | null;
  marketContext: MarketContext | null;
  /**
   * Engine pricing-model surface (CMA_PRICING_SURFACE=1). Absent/invalid ⇒
   * the synthetic path renders EXACTLY as before — the model UI is a
   * graceful no-op until the engine flag ships.
   */
  pricing?: PricingSurface | null;
  /** Neighborhood/scope name for the disclosure line ("Walnut Creek"). */
  areaName?: string | null;
  /** County, so the disclosure can fall back to a place label. */
  areaCounty?: string | null;
}) {
  const bands = buildModelBands(pricing);
  if (bands) {
    return (
      <ModelPricingStrategy
        bands={bands}
        targets={buildTargetDom(pricing, bands)}
        marketContext={marketContext}
        areaName={areaName}
        areaCounty={areaCounty}
      />
    );
  }
  return (
    <SyntheticPricingStrategy
      valuation={valuation}
      marketContext={marketContext}
      areaName={areaName}
      areaCounty={areaCounty}
    />
  );
}

/** Memoized: valuation + marketContext + pricing are stable across comp-tuning re-renders. */
export const PricingStrategy = memo(PricingStrategyImpl);

export default PricingStrategy;
