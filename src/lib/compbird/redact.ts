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
 *
 * CONTRACT the confidence tier depends on (src/lib/compbird/confidence.ts):
 * `compsSummary` {count, nearest_mi, farthest_mi} and `valuation.divergence_pct`
 * must SURVIVE redaction — the locked UI computes its confidence badge and
 * "Based on N comparable sales · nearest X mi" line from exactly these fields.
 */

import type { CompsSummary } from "./types";

export type { CompsSummary };

/** The evidence-bearing fields a Profile/Preview body may carry. */
interface EvidenceFields {
  comps?: Array<{ distance_mi?: number | null; similarity?: number | null }> | null;
  saleHistory?: unknown;
  marketContext?: unknown;
  valuation?: Record<string, unknown> | null;
  overrideDiff?: unknown;
  overrideValue?: unknown;
  pricing?: unknown;
  active_model?: unknown;
  subject?: Record<string, unknown> | null;
  facts?: Record<string, unknown> | null;
}

/**
 * Strip Pro-only evidence from an engine response, keeping the headline
 * estimate (valuation mid/low/high/divergence) live as the free teaser:
 *
 *   - comps → [] (a `compsSummary` teaser — count + nearest/farthest mi +
 *     avg/top match when the engine scored the set — is computed FIRST so the
 *     locked UI can still say "6 comps within 1.2 mi · average match 78")
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

  // Match teaser — avg/top of the per-comp similarity scores (comp-workshop
  // surface, present only when the engine ran with CMA_COMP_SCORE_SURFACE=1).
  // OMITTED entirely when no comp carries a score, so older engine responses
  // keep today's exact CompsSummary shape. Only these two aggregate ints leak
  // past the paywall — never the per-comp scores, subscores, or reasons.
  const sims = comps
    .map((c) => (c && typeof c === "object" ? c.similarity : null))
    .filter((s): s is number => typeof s === "number" && Number.isFinite(s));
  if (sims.length) {
    compsSummary.avg_similarity = Math.round(sims.reduce((a, b) => a + b, 0) / sims.length);
    compsSummary.top_similarity = Math.round(Math.max(...sims));
  }

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

  // Pricing-model surface (DOM/cut bands + target-DOM points) and the
  // active-listing model read are Pro evidence (CMA_PRICING_SURFACE=1):
  // a locked viewer keeps today's exact pricing panel (interval prices +
  // "pace unavailable") and only the FREE list-vs-estimate delta line —
  // never the model outputs. The subject/facts copies below strip only the
  // model key, leaving every other subject field intact.
  delete out.pricing;
  delete out.active_model;
  if (src.subject && typeof src.subject === "object") {
    const subject = { ...src.subject };
    delete subject.active_model;
    out.subject = subject;
  }
  if (src.facts && typeof src.facts === "object" && "active_model" in src.facts) {
    const facts = { ...src.facts };
    delete facts.active_model;
    out.facts = facts;
  }

  out.locked = true;
  out.compsSummary = compsSummary;

  return out as T & { locked: true; compsSummary?: CompsSummary };
}
