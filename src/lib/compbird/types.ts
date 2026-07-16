/**
 * compbird ↔ comp-engine contracts.
 *
 * These mirror the JSON returned by the public `/api/compbird/*` routes, which
 * in turn wrap the MLS Bot Python engine (see src/lib/cma/engine.ts). Kept in
 * one client-safe module so pages, sections, and the studio all share one shape.
 */

/* ── Address typeahead — /api/compbird/search ──────────────────────────────── */
export interface PropertyMatch {
  source: "mls" | "parcel";
  address: string;
  city: string;
  county: string;
  parcel_id: string;
  acres?: number | null;
  sqft?: number | null;
  year_built?: number | null;
  bedrooms?: number | null;
  full_baths?: number | null;
  half_baths?: number | null;
  owner?: string | null;
  subdivision?: string | null;
  last_sale_price?: number | null;
  last_sale_date?: string | null;
  status: string;
  list_price?: number | null;
  list_date?: string | null;
  listing_id?: string | null;
}

export interface SearchResponse {
  matches: PropertyMatch[];
  cached?: boolean;
  error?: string;
}

/* ── Comp-workshop similarity surface (CMA_COMP_SCORE_SURFACE=1) ───────────── */
/**
 * Per-comp match score + six-axis breakdown, emitted by the engine ONLY when
 * CMA_COMP_SCORE_SURFACE=1 (compbird's own engine instance — Ratifyly's leaves
 * it unset). Every field is OPTIONAL app-side: older engine responses and the
 * static SAMPLE_PROFILE lack them entirely, and the UI hides the Match column
 * when no comp carries a `similarity`. SOLO-only by construction — redact.ts
 * strips `comps → []` for FREE callers, so no client-side gating exists.
 */
export interface CompSubscore {
  /** The six axes the engine surfaces (price-band stays in the overall only). */
  key: "location" | "recency" | "size" | "lot" | "age" | "type";
  label: string;
  /** 0–100 int; null = not computable ("sqft not recorded" → em-dash, not 0). */
  score: number | null;
  /** This axis's share of the subject's achievable max, whole percent. */
  weight_pct: number;
  /** Engine-generated plain-English reason ("0.3 mi away · same subdivision"). */
  reason: string | null;
}

/** The optional similarity fields a preview OR profile comp may carry. */
export interface CompSimilarity {
  /**
   * Overall match, 0–100 int, raw-anchored against THIS subject (never
   * set-renormalized — pinning/excluding other comps can't move it). Includes
   * the price axis + atypical/pending discounts, so it is deliberately NOT
   * the average of the six subscores.
   */
  similarity?: number | null;
  subscores?: CompSubscore[];
  /** Top-3 plain-English drivers, ranked engine-side by weight × shortfall. */
  reasons?: string[];
  /** Set-relative honesty flags ($/sqft outlier, pending price) — never in the score. */
  atypical_flags?: string[];
  /** v1.1 — AI-hygiene annotation, e.g. "condition: renovated (+4% $/sqft)". */
  hygiene_note?: string | null;
  /** v1.1 — leave-one-out estimate impact in USD; null when the set is ≤ 3 comps. */
  impact_usd?: number | null;
}

/**
 * Subject-level aggregate of the per-comp scores. The engine attaches it to
 * the preview SUBJECT and the profile RESULT; avg/top feed the FREE teaser
 * (via CompsSummary), low is internal. Fields null when nothing was computable.
 */
export interface SimilaritySummary {
  avg: number | null;
  top: number | null;
  low: number | null;
}

/* ── Pricing surface (CMA_PRICING_SURFACE=1) ───────────────────────────────── */
/**
 * Engine-computed pricing-model surface. EVERY field here is OPTIONAL on the
 * wire: the engine emits them only when CMA_PRICING_SURFACE=1 is set on the
 * compbird worker, so older engines, the static sample, and un-flagged
 * deployments simply never send them and the UI stays a graceful no-op.
 */

/**
 * The dict the engine's confidence_signals() computes (build_cma.py:1597) —
 * previously reduced to the tier string, now serialized as-is. Key names match
 * the engine verbatim. Everything nullable/optional: render defensively from
 * whichever keys exist.
 */
export interface ConfidenceSignalsWire {
  tier?: "high" | "standard" | null;
  count?: number | null;
  nearest_mi?: number | null;
  farthest_mi?: number | null;
  /** Engine-vs-blind-AI arm agreement |engine − blind| / ensemble, percent. */
  agreement_pct?: number | null;
  /** Method spread (max − min) / mid, percent. */
  spread_pct?: number | null;
  /** True when the agreement gate (not the distance/spread gate) governed. */
  ensemble_arm?: boolean | null;
}

/** One pricing-strategy point: price + modeled DOM quantiles + cut odds. */
export interface PricingBand {
  key: "sell_fast" | "market" | "maximize";
  price: number;
  /** DOM quantiles from the engine's dom_model predicted AT this price. */
  dom_q25: number;
  dom_q50: number;
  dom_q75: number;
  /** price_cut_model probability of a price cut at this price, 0–1. */
  cut_probability: number;
}

/** dom_model.recommend_price_for_target_dom — "price to sell by a date". */
export interface PricingTargetDom {
  days: number;
  price: number;
}

/** The `pricing` object a profile/preview response may carry. */
export interface PricingSurface {
  /** Exactly three bands (sell_fast/market/maximize) when present. */
  bands?: PricingBand[];
  /** 30/45/60-day price recommendations. */
  target_dom?: PricingTargetDom[];
}

/**
 * Active-listing model read — ONLY when the subject is an active listing with
 * a list_price (both models evaluated AT that list price).
 */
export interface ActiveListingModel {
  expected_dom_q50: number;
  cut_probability: number;
}

/* ── Evidence-paywall teaser (survives redaction) ──────────────────────────── */
/**
 * Comp teaser computed server-side BEFORE comps are stripped for a non-Pro
 * caller (src/lib/compbird/redact.ts). These fields deliberately SURVIVE
 * redaction: the confidence tier (src/lib/compbird/confidence.ts) and the
 * locked UI's "N comps within X mi" line are built from them.
 */
export interface CompsSummary {
  count: number;
  nearest_mi: number | null;
  farthest_mi: number | null;
  /**
   * Average/top per-comp match (0–100 ints), computed from the UNREDACTED
   * comps before the strip — the "average match 78" clause of the locked
   * teaser. Absent when no comp carried a similarity score.
   */
  avg_similarity?: number;
  top_similarity?: number;
}

/* ── Full dossier — /api/compbird/profile ──────────────────────────────────── */
export interface ProfileFacts {
  address: string;
  city: string;
  county: string;
  parcel_id: string;
  subdivision: string | null;
  property_type: string | null;
  status: string | null;
  sqft: number | null;
  acres: number | null;
  beds: number | null;
  full_baths: number | null;
  half_baths: number | null;
  year_built: number | null;
  assessed_value: number | null;
  lat: number | null;
  lng: number | null;
  list_price: number | null;
  /** Days on market for an ACTIVE subject, when the feed carries it. */
  feed_dom?: number | null;
  /** Active-listing model read — some engine builds attach it to the facts. */
  active_model?: ActiveListingModel | null;
}

export interface ValuationMethod {
  name: string;
  value: number | null;
  rationale: string;
}

export interface Valuation {
  mid: number | null;
  low: number | null;
  high: number | null;
  comp_ppsf: number | null;
  implied_subject_ppsf: number | null;
  divergence_pct: number | null;
  methods: ValuationMethod[];
  /**
   * Blind-AI arm of the fast ensemble (engine flag CMA_AI_ENSEMBLE) — the
   * independent "AI comparable read" estimate, BEFORE averaging. OPTIONAL:
   * older engine responses and the static sample lack it, and the confidence
   * tier degrades gracefully to the distance/spread gate when absent. Survives
   * redaction (redact.ts spreads the valuation object).
   */
  ai_blind?: number | null;
  /** True when `mid` IS the ensemble mean(engine, ai_blind), not engine-only. */
  ai_ensemble?: boolean;
  /**
   * ENGINE-computed measured confidence tier (CMA_BLIND_ENSEMBLE engines) —
   * AUTHORITATIVE over the client-side computation when present, so the studio
   * and the generated report tell the same story. Optional: older engine
   * responses and the static sample omit it (confidence.ts then falls back to
   * the client-side gates). Survives redaction (redact.ts spreads valuation).
   */
  confidence_tier?: "high" | "standard" | null;
  /**
   * The full signals dict the tier was computed from (CMA_PRICING_SURFACE=1
   * engines) — drives the one-line confidence evidence sentence. Optional:
   * older engines send only the tier string.
   */
  confidence_signals?: ConfidenceSignalsWire | null;
}

export interface ProfileComp extends CompSimilarity {
  address: string;
  city: string | null;
  subdivision: string | null;
  sold_price: number | null;
  /** Original list price when the wire carries it — the sold-vs-ask chip. */
  original_list_price?: number | null;
  ppsf: number | null;
  sqft: number | null;
  acres: number | null;
  beds: number | null;
  baths: number | null;
  year_built: number | null;
  close_date: string | null;
  dom: number | null;
  distance_mi: number | null;
  lat: number | null;
  lng: number | null;
  pending: boolean;
  atypical: boolean;
  /** Comp provenance: "mls" | "supplemental" (public records). */
  source?: string | null;
  /** Engine reasoning, when the wire carries it. */
  cohort?: string | null;
  atypical_reason?: string | null;
  appearance_tier?: number | null;
}

export interface MarketContext {
  ppsf_median: number | null;
  ppsf_trend: number | null;
  median_dom: number | null;
  active_count: number | null;
  sold_count: number | null;
  months_of_inventory: number | null;
  scope: string | null;
  /**
   * Aliases the LIVE engine emits. The studio historically read the sample-only
   * names above; these mirror the field names the real `/api/compbird` engine
   * returns so both sources resolve against one interface.
   */
  median_ppsf?: number | null;
  ppsf_trend_pct?: number | null;
  ppsf_trend_direction?: string | null;
  scope_value?: string | null;
  median_sold_price?: number | null;
}

export interface ProfileResult {
  ok: boolean;
  facts: ProfileFacts | null;
  valuation: Valuation | null;
  comps: ProfileComp[];
  saleHistory: Array<{ price: number | null; date: string | null }>;
  marketContext: MarketContext | null;
  meta: {
    generated: string | null;
    as_of: string | null;
    flags: Record<string, unknown> | string[] | null;
  } | null;
  /**
   * Record→adjusted disclosure carried from a LIVE preview when the agent applied
   * subject overrides (engine-authoritative `_override_diff`). Drives the on-screen
   * non-suppressible disclosure so the screen carries the same honesty as the PDF.
   */
  overrideDiff?: Record<string, { from: unknown; to: unknown }> | null;
  /** Record-basis vs agent-adjusted value — shown in the on-screen disclosure. */
  overrideValue?: { record: number | null; adjusted: number | null } | null;
  /**
   * Subject-level similarity aggregate — engine attaches it TOP-LEVEL on the
   * profile payload (property_profile.py), unlike the preview where it rides
   * on the subject. Only present under CMA_COMP_SCORE_SURFACE=1.
   */
  similarity_summary?: SimilaritySummary | null;
  /**
   * Pricing-model surface (CMA_PRICING_SURFACE=1) — strategy bands + target-DOM
   * points. Stripped by redact.ts for non-Pro callers (model outputs are
   * evidence), so its absence keeps the pricing panel on today's exact path.
   */
  pricing?: PricingSurface | null;
  /**
   * Active-listing model read. The wire contract names it `subject.active_model`;
   * the app also accepts it top-level (the tuned-recompute merge writes it
   * here) or on `facts` — report-view reads all three defensively.
   */
  active_model?: ActiveListingModel | null;
  subject?: { active_model?: ActiveListingModel | null } | null;
  /**
   * Evidence paywall (server-side redaction — src/lib/compbird/redact.ts).
   * `locked: true` means comps/marketContext/saleHistory/methods were stripped
   * for a non-Pro caller; `compsSummary` is the teaser computed before the strip.
   */
  locked?: boolean;
  compsSummary?: CompsSummary;
  error?: string;
}

/* ── PDF render — /api/compbird/generate ───────────────────────────────────── */
export interface GenerateResult {
  ok: boolean;
  subject?: string;
  valueLow?: number;
  valueMid?: number;
  valueHigh?: number;
  compCount?: number;
  pages?: number;
  elapsedSeconds?: number;
  autofitAttempts?: number;
  pdfName?: string;
  htmlName?: string;
  error?: string;
}

/* ── Live preview — /api/compbird/preview ──────────────────────────────────── */
/**
 * One comparable as the live engine emits it (see PREVIEW_RUNNER in
 * src/lib/cma/engine.ts → `_comp_dict`). Mostly nullable: the feed is uneven.
 */
export interface PreviewComp extends CompSimilarity {
  address: string | null;
  city: string | null;
  county: string | null;
  subdivision: string | null;
  parcel_id: string | null;
  sold_price: number | null;
  original_list_price: number | null;
  sqft: number | null;
  acres: number | null;
  year_built: number | null;
  bedrooms: number | null;
  full_baths: number | null;
  half_baths: number | null;
  dom: number | null;
  close_date: string | null;
  score: number | null;
  distance_mi: number | null;
  cohort: string | null;
  atypical_sale: boolean;
  atypical_reason: string | null;
  appearance_tier: number | null;
  /** Comp provenance: which pool the sale came from ("mls" | "supplemental"). */
  source?: string | null;
  pending: boolean;
  status: string;
  forced: boolean;
  /** Coordinates so tuned/added comps keep their map pin (PREVIEW_RUNNER → `_comp_dict`). */
  latitude: number | null;
  longitude: number | null;
}

/** The resolved subject the preview echoes back (PREVIEW_RUNNER → `out_subject`). */
export interface PreviewSubject {
  address: string | null;
  city: string | null;
  county: string | null;
  subdivision: string | null;
  parcel_id: string | null;
  status: string | null;
  list_price: number | null;
  sqft: number | null;
  acres: number | null;
  year_built: number | null;
  bedrooms: number | null;
  full_baths: number | null;
  half_baths: number | null;
  assessed_total: number | null;
  feed_dom: number | null;
  /** True when an agent subject override was applied (engine flag). */
  _overridden?: boolean;
  /** Record→adjusted diff per changed field — engine-authoritative, drives the disclosure. */
  _override_diff?: Record<string, { from: unknown; to: unknown }> | null;
  /** Value at the un-overridden (record) subject — the honest baseline for the disclosure. */
  _record_mid?: number | null;
  /** Value at the agent-adjusted subject (== valuation.mid). */
  _adjusted_mid?: number | null;
  /**
   * Subject-level similarity aggregate — the preview engine attaches it to the
   * SUBJECT dict (build_cma.py). Only present under CMA_COMP_SCORE_SURFACE=1.
   */
  similarity_summary?: SimilaritySummary | null;
  /**
   * Active-listing model read (CMA_PRICING_SURFACE=1) — ONLY when the subject
   * is an active listing with a list_price, evaluated AT that price.
   */
  active_model?: ActiveListingModel | null;
}

/** One reconciliation method in the preview valuation (PREVIEW_RUNNER → `out_valuation`). */
export interface PreviewValuationMethod {
  name: string;
  value: number | null;
  low: number | null;
  high: number | null;
  rationale: string;
}

export interface PreviewValuation {
  low: number | null;
  mid: number | null;
  high: number | null;
  ppsf: number | null;
  divergence_pct: number | null;
  methods: PreviewValuationMethod[];
  /** Blind-AI ensemble arm — same optional contract as `Valuation.ai_blind`. */
  ai_blind?: number | null;
  /** True when `mid` IS the ensemble mean(engine, ai_blind), not engine-only. */
  ai_ensemble?: boolean;
  /** Engine-computed measured tier — same authoritative contract as `Valuation.confidence_tier`. */
  confidence_tier?: "high" | "standard" | null;
  /** Full confidence-signals dict — same optional contract as `Valuation.confidence_signals`. */
  confidence_signals?: ConfidenceSignalsWire | null;
}

export interface PreviewResult {
  ok: boolean;
  subject?: PreviewSubject;
  comps?: PreviewComp[];
  valuation?: PreviewValuation;
  /** Pricing-model surface — same optional contract as `ProfileResult.pricing`. */
  pricing?: PricingSurface | null;
  elapsed_seconds?: number;
  /** Evidence paywall — same server-side redaction contract as ProfileResult. */
  locked?: boolean;
  compsSummary?: CompsSummary;
  error?: string;
}

/* ── Neighborhood market report (landing showcase + markets) ───────────────── */
export interface NeighborhoodMarket {
  name: string;
  area: string;
  medianPrice: number;
  ppsf: number;
  ppsfTrendPct: number;
  medianDom: number;
  monthsOfInventory: number;
  soldCount: number;
  activeCount: number;
  /** 12-point median-price trend, oldest → newest. */
  trend: number[];
  /** Headline takeaway for the card. */
  note: string;
  /* ── Heat additions (compbird-only /markets fields; no engine flag) ──
     All optional: older engines omit them and the card's heat row hides. */
  /** Median sold/list ratio (e.g. 0.984). */
  sold_to_list?: number;
  /** Share of solds closing at-or-above ask, 0–1. */
  pct_over_ask?: number;
  /** Share of solds that had a price cut before closing, 0–1. */
  cut_share?: number;
  /** Composite market-heat score, 0–100 (formula documented engine-side). */
  heat?: number;
}

export interface MarketsResponse {
  markets: NeighborhoodMarket[];
  error?: string;
}
