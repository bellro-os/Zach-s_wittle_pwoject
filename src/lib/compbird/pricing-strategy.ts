/**
 * Pricing-strategy model — the honest engine behind the studio's "Pricing
 * strategy" panel (src/components/compbird/studio/pricing-strategy.tsx).
 *
 * The panel replaced the dead Street View tile (which needed a Google Maps key
 * we don't ship). Where that tile showed nothing useful, this shows the one
 * thing an agent actually reasons about at the listing table: what each list
 * price is likely to COST in time on market.
 *
 * DESIGN CONSTRAINT — honest, not invented precision:
 *   - The three price BANDS are the engine's OWN confidence interval
 *     (valuation.low / .mid / .high). We do not synthesize prices; we label
 *     the numbers the CMA already stands behind.
 *   - The time-on-market figures are explicitly a MODEL, anchored on the
 *     neighborhood's median days-on-market at the market (mid) price and bent
 *     by a documented, monotonic elasticity curve. When median_dom is absent
 *     (thin market, or redacted on a locked report) we return dom = null and
 *     the UI says "pace data unavailable" — we never fabricate days.
 *
 * Pure + dependency-free so it unit-tests in plain Node.
 */

import type { Valuation, MarketContext } from "./types";

/* ── Public shape ──────────────────────────────────────────────────────────── */

/** Which market we're pricing into — drives the elasticity coefficient. */
export type MarketPace = "sellers" | "balanced" | "buyers";

export interface StrategyBand {
  /** Stable id for keys / test assertions. */
  key: "fast" | "market" | "maximize";
  /** Human label — "Sell fast" / "Market" / "Maximize". */
  label: string;
  /** One-line intent, e.g. "Priced to move" / "The estimate" / "Test the ceiling". */
  blurb: string;
  /** The list price — an engine confidence-interval endpoint, never invented. */
  price: number;
  /** price / mid − 1, i.e. how far this band sits above/below the anchor. */
  pctVsMid: number;
  /**
   * Modeled days on market at this price. null when median_dom is unavailable
   * (thin/redacted market) — the caller shows a muted fallback, not a number.
   */
  domMid: number | null;
  /** A modest ± band around domMid ([lo, hi]); null when domMid is null. */
  domRange: [number, number] | null;
  /** The anchor band (Market) — the UI accents it in ember. */
  isAnchor: boolean;
  /**
   * True when pricing above market carries real price-cut risk. Set on the
   * Maximize band whenever it sits above mid — surfaced as a text caveat, not
   * color alone.
   */
  cutRisk: boolean;
}

export interface PricingStrategy {
  bands: StrategyBand[];
  /** Market pace bucket derived from months_of_inventory. */
  pace: MarketPace;
  /** Human descriptor — "seller's market" / "balanced" / "buyer's market". */
  paceLabel: string;
  /** Elasticity coefficient actually used (documented below) — exposed for tests / disclosure. */
  sensitivity: number;
  /** Neighborhood median days-on-market the model is anchored on (null → modeled dom is null). */
  baseDom: number | null;
  /** $/sqft trend direction for context ("up" | "down" | "flat" | null). */
  trendDirection: string | null;
  /** months_of_inventory echoed for the disclosure line (null when unknown). */
  monthsOfInventory: number | null;
}

/* ── The curve ─────────────────────────────────────────────────────────────── */

/**
 * Days-on-market elasticity, by market pace. This is the single modeling
 * assumption and it is deliberately conservative and legible:
 *
 *     dom(price) = baseDom × clamp( exp(k · pctVsMid), FLOOR, CAP )
 *
 * where pctVsMid = price/mid − 1 and k is the coefficient below. Why this form:
 *
 *   • MONOTONIC + smooth: exp() is strictly increasing, so below mid → <1
 *     (faster) and above mid → >1 (slower), with no kink at the anchor.
 *   • ASYMMETRIC the right way: exp grows faster than it decays, so pricing
 *     +10% over market costs MORE time than pricing −10% under market saves —
 *     matching what listing agents observe (overpricing strands a listing;
 *     underpricing rarely sells THAT much faster once you're already quick).
 *   • Calibrated so k is readable as "each +1% over market ≈ +k% DOM" near the
 *     anchor (since exp(k·0.01) − 1 ≈ 0.01k for small moves):
 *       - seller's market  k = 1.3  → +1% over market ≈ +1.3% DOM. Demand soaks
 *         up modest overpricing; buyers compete, so the penalty is mild.
 *       - balanced         k = 2.0  → +1% over market ≈ +2% DOM. The textbook
 *         mid-case realtors quote.
 *       - buyer's market   k = 3.0  → +1% over market ≈ +3% DOM. Ample supply;
 *         an overpriced listing simply gets skipped, so time compounds fast.
 *
 * These are order-of-magnitude coefficients for a DIRECTIONAL model, not a
 * fitted regression — the panel presents outputs as ranges and labels itself a
 * model, never a promise. The clamp keeps a deep discount or an aggressive
 * ceiling from ever printing an absurd number.
 */
const SENSITIVITY: Record<MarketPace, number> = {
  sellers: 1.3,
  balanced: 2.0,
  buyers: 3.0,
};

/** Multiplier bounds: never faster than 0.4× nor slower than 3.0× the median. */
const MULT_FLOOR = 0.4;
const MULT_CAP = 3.0;

/** ± spread on the modeled dom, as a fraction of the estimate (a modeling band, not randomness). */
const DOM_RANGE_FRAC = 0.12;

/** MOI bucket boundaries — mirrors market-panel's inventoryTone thresholds. */
function paceFromMoi(moi: number | null | undefined): MarketPace {
  if (moi == null || !Number.isFinite(moi)) return "balanced"; // MOI null → MEDIUM default
  if (moi < 3) return "sellers";
  if (moi <= 6) return "balanced";
  return "buyers";
}

const PACE_LABEL: Record<MarketPace, string> = {
  sellers: "seller's market",
  balanced: "balanced market",
  buyers: "buyer's market",
};

/** clamp(exp(k·pct), floor, cap) — the pace-adjusted DOM multiplier. */
function paceMultiplier(pctVsMid: number, sensitivity: number): number {
  const raw = Math.exp(sensitivity * pctVsMid);
  return Math.min(MULT_CAP, Math.max(MULT_FLOOR, raw));
}

/**
 * Model days-on-market for a price relative to the anchor. Returns null (never
 * a fabricated number) when there's no median to anchor on.
 */
function modeledDom(
  price: number,
  mid: number,
  baseDom: number | null,
  sensitivity: number,
): number | null {
  if (baseDom == null || !Number.isFinite(baseDom) || baseDom <= 0) return null;
  const pctVsMid = price / mid - 1;
  const dom = baseDom * paceMultiplier(pctVsMid, sensitivity);
  // Round to the nearest day, floored at 1 — "0 days on market" would read as broken.
  return Math.max(1, Math.round(dom));
}

/** A modest ± window around a modeled dom, rounded to whole days (≥ 1 wide). */
function domRange(domMid: number | null): [number, number] | null {
  if (domMid == null) return null;
  const spread = Math.max(1, Math.round(domMid * DOM_RANGE_FRAC));
  const lo = Math.max(1, domMid - spread);
  const hi = domMid + spread;
  return [lo, hi];
}

/* ── Entry point ───────────────────────────────────────────────────────────── */

/**
 * Build the pricing-strategy view-model from the engine's valuation interval
 * and the neighborhood market context.
 *
 * Degradation ladder (honesty over completeness):
 *   - No usable mid → return null; the caller HIDES the whole panel (nothing to
 *     anchor bands on, so any "strategy" would be fiction).
 *   - mid present but low/high missing or collapsed onto mid → we still render
 *     the bands we can (at minimum the Market anchor). A band whose price would
 *     duplicate the anchor is dropped rather than shown as a distinct "strategy".
 *   - median_dom missing (thin market / locked report where marketContext is
 *     redacted to null) → bands render with domMid = null; the UI shows the
 *     prices and a muted "pace data unavailable", never invented days.
 */
export function computePricingStrategy(
  valuation: Valuation | null | undefined,
  marketContext: MarketContext | null | undefined,
): PricingStrategy | null {
  const mid = valuation?.mid;
  if (mid == null || !Number.isFinite(mid) || mid <= 0) return null;

  const low = valuation?.low;
  const high = valuation?.high;

  const moi = marketContext?.months_of_inventory ?? null;
  const pace = paceFromMoi(moi);
  const sensitivity = SENSITIVITY[pace];

  const baseDom =
    marketContext?.median_dom != null && Number.isFinite(marketContext.median_dom)
      ? marketContext.median_dom
      : null;

  const trendDirection = marketContext?.ppsf_trend_direction ?? null;

  // Build bands from the interval endpoints. A candidate is only distinct if its
  // price is meaningfully off the anchor (>0.5% away) AND finite — otherwise a
  // collapsed interval would show three identical "strategies".
  const distinct = (price: number | null | undefined): price is number =>
    price != null &&
    Number.isFinite(price) &&
    price > 0 &&
    Math.abs(price / mid - 1) > 0.005;

  const bands: StrategyBand[] = [];

  if (distinct(low)) {
    const dom = modeledDom(low, mid, baseDom, sensitivity);
    bands.push({
      key: "fast",
      label: "Sell fast",
      blurb: "Priced to move",
      price: low,
      pctVsMid: low / mid - 1,
      domMid: dom,
      domRange: domRange(dom),
      isAnchor: false,
      cutRisk: false,
    });
  }

  {
    // Market is always present — it IS the anchor, and mid is guaranteed above.
    const dom = modeledDom(mid, mid, baseDom, sensitivity);
    bands.push({
      key: "market",
      label: "Market",
      blurb: "The estimate",
      price: mid,
      pctVsMid: 0,
      domMid: dom,
      domRange: domRange(dom),
      isAnchor: true,
      cutRisk: false,
    });
  }

  if (distinct(high)) {
    const dom = modeledDom(high, mid, baseDom, sensitivity);
    bands.push({
      key: "maximize",
      label: "Maximize",
      blurb: "Test the ceiling",
      price: high,
      pctVsMid: high / mid - 1,
      domMid: dom,
      domRange: domRange(dom),
      isAnchor: false,
      // Above the anchor → real risk the listing sits and needs a price cut.
      cutRisk: high > mid,
    });
  }

  // Keep bands ordered fast → market → maximize by price (defensive: the engine
  // could in principle hand back low > mid on a degenerate interval).
  bands.sort((a, b) => a.price - b.price);

  return {
    bands,
    pace,
    paceLabel: PACE_LABEL[pace],
    sensitivity,
    baseDom,
    trendDirection,
    monthsOfInventory: moi,
  };
}
