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
}

export interface ProfileComp {
  address: string;
  city: string | null;
  subdivision: string | null;
  sold_price: number | null;
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
  /** Engine reasoning, when the wire carries it (preview always; profile may not). */
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
export interface PreviewComp {
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
}

export interface PreviewResult {
  ok: boolean;
  subject?: PreviewSubject;
  comps?: PreviewComp[];
  valuation?: PreviewValuation;
  elapsed_seconds?: number;
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
}

export interface MarketsResponse {
  markets: NeighborhoodMarket[];
  error?: string;
}
