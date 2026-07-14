"use client";

import { memo } from "react";

import { Pill } from "@/components/compbird/ui";
import { cn } from "@/lib/utils/cn";
import { usd, num, placeLabel } from "@/lib/compbird/format";
import {
  computePricingStrategy,
  type StrategyBand,
  type PricingStrategy as PricingStrategyModel,
} from "@/lib/compbird/pricing-strategy";
import type { Valuation, MarketContext } from "@/lib/compbird/types";

/**
 * ZONE 1 companion — replaces the old Street View tile (which was dead weight
 * without a Google Maps key). Where that showed nothing, this answers the
 * question an agent actually works at the listing table: what does each list
 * price likely COST in time on market?
 *
 * All figures are honest by construction (see lib/compbird/pricing-strategy.ts):
 * the three prices ARE the engine's own confidence interval, and the days are a
 * documented, labeled MODEL anchored on the neighborhood's median pace — never
 * a promise, and never fabricated when the pace data is missing.
 *
 * Renders on live Pro reports, the sample (its marketContext carries a
 * median_dom), AND locked reports — there marketContext is redacted to null, so
 * the price bands still render (valuation survives redaction) with a muted
 * "pace unavailable" fallback instead of invented days.
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

function PricingStrategyImpl({
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
      <p className="text-[0.7rem] leading-relaxed text-muted-foreground/80">
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

/** Memoized: valuation + marketContext are stable across comp-tuning re-renders. */
export const PricingStrategy = memo(PricingStrategyImpl);

export default PricingStrategy;
