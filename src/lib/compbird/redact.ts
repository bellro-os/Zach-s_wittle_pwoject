/**
 * Server-side evidence redaction — the paywall's DATA boundary.
 *
 * FREE (and anonymous) callers get the ESTIMATED VALUE of a property; the
 * EVIDENCE — comps, market analytics, sale history, the method breakdown — is
 * Pro-only ("cma.evidence"). The redaction happens HERE, on the server, before
 * the response ships: a non-Pro client never receives the evidence at all, so
 * no amount of CSS/devtools poking can un-blur it.
 *
 * Works on both ProfileResult- and PreviewResult-shaped bodies (they share the
 * evidence fields this strips). Pure function — never mutates its input.
 */

export interface CompsSummary {
  count: number;
  nearest_mi: number | null;
  farthest_mi: number | null;
}

/** The evidence-bearing fields a Profile/Preview body may carry. */
interface EvidenceFields {
  comps?: Array<{ distance_mi?: number | null }> | null;
  saleHistory?: unknown;
  marketContext?: unknown;
  valuation?: Record<string, unknown> | null;
  overrideDiff?: unknown;
  overrideValue?: unknown;
}

/**
 * Strip Pro-only evidence from an engine response, keeping the headline
 * estimate (valuation mid/low/high/divergence) live as the free teaser:
 *
 *   - comps → [] (a `compsSummary` teaser — count + nearest/farthest mi — is
 *     computed FIRST so the locked UI can still say "6 comps within 1.2 mi")
 *   - marketContext → null, saleHistory → []
 *   - valuation keeps mid/low/high/divergence_pct; methods → [] and every
 *     comp-derived ppsf (comp_ppsf / implied_subject_ppsf / preview `ppsf`)
 *     is nulled
 *   - overrideDiff / overrideValue are dropped (override editors are Pro)
 *   - `locked: true` marks the body so the UI renders the paywall state
 */
export function redactEvidence<T extends object>(
  body: T,
): T & { locked: true; compsSummary?: CompsSummary } {
  const src = body as T & EvidenceFields;

  // Teaser stats — computed from the real comps BEFORE they are stripped.
  const comps = Array.isArray(src.comps) ? src.comps : [];
  const distances = comps
    .map((c) => (c && typeof c === "object" ? c.distance_mi : null))
    .filter((d): d is number => typeof d === "number" && Number.isFinite(d));
  const compsSummary: CompsSummary = {
    count: comps.length,
    nearest_mi: distances.length ? Math.min(...distances) : null,
    farthest_mi: distances.length ? Math.max(...distances) : null,
  };

  const out: Record<string, unknown> = { ...(body as Record<string, unknown>) };

  out.comps = [];
  out.marketContext = null;
  out.saleHistory = [];

  if (src.valuation && typeof src.valuation === "object") {
    const valuation: Record<string, unknown> = { ...src.valuation, methods: [] };
    if ("comp_ppsf" in valuation) valuation.comp_ppsf = null;
    if ("implied_subject_ppsf" in valuation) valuation.implied_subject_ppsf = null;
    if ("ppsf" in valuation) valuation.ppsf = null; // preview's comp-derived ppsf
    out.valuation = valuation;
  }

  delete out.overrideDiff;
  delete out.overrideValue;

  out.locked = true;
  out.compsSummary = compsSummary;

  return out as T & { locked: true; compsSummary?: CompsSummary };
}
