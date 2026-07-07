/**
 * Confidence tiers + thin-comp labeling — turns silent thin-comp misses into
 * labeled output.
 *
 * TWO tiers only, by design: "high" (the evidence genuinely supports the
 * number) and "standard" (the honest default). There is deliberately no scary
 * red "low" tier — thin evidence is communicated through the reasons list and
 * the `caution` flag ("Limited comparable data in this area"), not a downgrade
 * badge that reads like an indictment of the estimate.
 *
 * The honest confidence drivers (measured, see docs/regional-accuracy-2026-07.md):
 *   - comp proximity: nearest comp <0.5 mi ≈ 7–8% median error; >1.5 mi much worse
 *   - comp count: more nearby closed sales = better anchored
 *   - method agreement: tight spread across independent methods = meaningfully
 *     more accurate
 *
 * Works on BOTH the unlocked and the redacted (locked) payload shapes:
 * redact.ts strips comps → [] and methods → [] but keeps `compsSummary`
 * {count, nearest_mi, farthest_mi} and `valuation.divergence_pct`, so a FREE
 * viewer still gets an honest tier (confidence is a selling point for the
 * unlock, not gated content). What degrades when locked: the method spread is
 * taken from the engine's `divergence_pct` instead of being recomputed from
 * the per-method values, and single-method runs (which report divergence 0)
 * can't be told apart from genuine agreement — bounded, because the ≥5-comps
 * and ≤0.5-mi gates still apply before "high" is possible.
 */

export type ConfidenceTier = "high" | "standard";

export interface ConfidenceResult {
  tier: ConfidenceTier;
  /** Human-readable drivers — positives for "high", honest caveats first for "standard". */
  reasons: string[];
  compCount: number | null;
  nearestMi: number | null;
  /** Method spread (max−min)/mid as a PERCENTAGE (e.g. 6.5); null when unknowable. */
  methodSpreadPct: number | null;
  /** Thin-comp evidence: <4 comps or nearest >1.5 mi — the UI adds explicit caution copy. */
  caution: boolean;
}

/* ── Tier gates (all must hold for "high") ─────────────────────────────────── */
export const HIGH_MIN_COMPS = 5;
export const HIGH_MAX_NEAREST_MI = 0.5;
export const HIGH_MAX_SPREAD_PCT = 10;

/* ── Thin-comp caution gates (either trips it) ─────────────────────────────── */
export const CAUTION_MIN_COMPS = 4;
export const CAUTION_MAX_NEAREST_MI = 1.5;

/**
 * The granular signal set the tier is computed from. `computeConfidence`
 * extracts these from a Profile/Preview body; UI callers that already hold the
 * pieces (e.g. the valuation panel, which receives scalars so React.memo stays
 * effective) can call `computeConfidenceFromSignals` directly.
 */
export interface ConfidenceSignals {
  /** Comparable-sale count; null = unknown (blocks "high", never fakes a number). */
  compCount: number | null;
  /** Distance (mi) of the closest comp; null = unknown. */
  nearestMi: number | null;
  /**
   * Mid value of every method that produced a value (unlocked payloads).
   * Pass null when methods[] was REDACTED (locked) — the spread then falls
   * back to `divergencePct`. An empty array means "genuinely no method values"
   * and reads as limited evidence, NOT as redaction.
   */
  methodValues?: number[] | null;
  /** Engine divergence stat — survives redaction; the locked-payload spread fallback. */
  divergencePct?: number | null;
  /** Headline estimate — the spread denominator. */
  mid?: number | null;
  /** Share (0–1) of comps from the public-records pool — >50% caps the tier at standard. */
  supplementalShare?: number | null;
}

/** "0.3", clamped so a 400-ft comp never prints as "0.0 mi". */
function fmtMi(d: number): string {
  return Math.max(0.1, Math.round(d * 10) / 10).toFixed(1);
}

function isFiniteNum(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

export function computeConfidenceFromSignals(s: ConfidenceSignals): ConfidenceResult {
  const compCount = isFiniteNum(s.compCount) && s.compCount >= 0 ? s.compCount : null;
  const nearestMi = isFiniteNum(s.nearestMi) && s.nearestMi >= 0 ? s.nearestMi : null;
  const mid = isFiniteNum(s.mid) && s.mid > 0 ? s.mid : null;
  const supplementalShare = isFiniteNum(s.supplementalShare) ? s.supplementalShare : 0;

  // Method spread: recompute from per-method values when we have ≥2; fall back
  // to the engine's divergence stat only when methods are UNKNOWN (redacted).
  // A known single-method run gets NO spread — its divergence of 0 is a lie.
  const values = Array.isArray(s.methodValues)
    ? s.methodValues.filter((v) => isFiniteNum(v) && v > 0)
    : null;
  let methodSpreadPct: number | null = null;
  if (values && values.length >= 2 && mid != null) {
    methodSpreadPct = ((Math.max(...values) - Math.min(...values)) / mid) * 100;
  } else if (values == null && isFiniteNum(s.divergencePct) && s.divergencePct >= 0) {
    methodSpreadPct = s.divergencePct;
  }

  // "high" requires ≥5 comps, nearest ≤0.5 mi, AND spread ≤10%. A count of
  // null means UNKNOWN (a caller that can't see the comps array yet) — that
  // does not block "high" on its own, because any caller that KNOWS a thin
  // count passes the number and gets blocked; but nearest + spread must still
  // both pass, so the strongest two signals always gate the tier.
  const tier: ConfidenceTier =
    mid != null &&
    (compCount == null || compCount >= HIGH_MIN_COMPS) &&
    nearestMi != null &&
    nearestMi <= HIGH_MAX_NEAREST_MI &&
    methodSpreadPct != null &&
    methodSpreadPct <= HIGH_MAX_SPREAD_PCT &&
    supplementalShare <= 0.5
      ? "high"
      : "standard";

  const caution =
    (compCount != null && compCount < CAUTION_MIN_COMPS) ||
    (nearestMi != null && nearestMi > CAUTION_MAX_NEAREST_MI);

  // Reasons — each known signal yields either a positive or an honest caveat.
  // Unknown signals are simply omitted (never advertise a plumbing gap).
  const positives: string[] = [];
  const caveats: string[] = [];

  if (compCount != null) {
    if (compCount >= HIGH_MIN_COMPS) positives.push(`${compCount} comparable sales`);
    else if (compCount === 0) caveats.push("no comparable sales found nearby");
    else
      caveats.push(
        `only ${compCount} comparable ${compCount === 1 ? "sale" : "sales"} nearby`,
      );
  }

  if (nearestMi != null) {
    if (nearestMi <= HIGH_MAX_NEAREST_MI) positives.push(`nearest ${fmtMi(nearestMi)} mi`);
    else if (nearestMi <= CAUTION_MAX_NEAREST_MI)
      caveats.push(`nearest comparable ${fmtMi(nearestMi)} mi away`);
    else caveats.push(`nearest comparable is ${fmtMi(nearestMi)} mi away`);
  }

  if (methodSpreadPct != null) {
    if (methodSpreadPct <= HIGH_MAX_SPREAD_PCT)
      positives.push(`methods agree within ${Math.max(1, Math.ceil(methodSpreadPct))}%`);
    else caveats.push(`valuation methods differ by ${Math.round(methodSpreadPct)}%`);
  } else if (values != null && values.length <= 1) {
    caveats.push(values.length === 1 ? "single valuation method" : "limited method evidence");
  }

  if (supplementalShare > 0.5) caveats.push("mostly public-records sales data");

  // High: lead with the positives. Standard: honest caveats first, then
  // whatever held up — the popover reads as "here is what's thin, and here is
  // what's still solid".
  const reasons = tier === "high" ? [...positives, ...caveats] : [...caveats, ...positives];
  if (!reasons.length) reasons.push("limited data for this property");

  return { tier, reasons, compCount, nearestMi, methodSpreadPct, caution };
}

/**
 * The evidence-bearing slices of a Profile/Preview body this reads. Structural
 * on purpose: both ProfileResult and PreviewResult (locked or not) satisfy it.
 */
export interface ConfidenceInput {
  locked?: boolean;
  comps?: Array<{ distance_mi?: number | null; source?: string | null }> | null;
  compsSummary?: { count: number; nearest_mi: number | null; farthest_mi?: number | null } | null;
  valuation?: {
    mid?: number | null;
    divergence_pct?: number | null;
    methods?: Array<{ value?: number | null }> | null;
  } | null;
}

/**
 * Compute the tier straight from a Profile- or Preview-shaped body (locked or
 * not). Comp count/nearest come from the comps array when present, else from
 * the redaction-surviving `compsSummary` teaser.
 */
export function computeConfidence(profile: ConfidenceInput): ConfidenceResult {
  const comps = Array.isArray(profile.comps) ? profile.comps : [];
  const summary = profile.compsSummary ?? null;

  // A locked body ships comps: [] — the summary is the truth there. An
  // unlocked body with zero comps is genuinely comp-less (count 0, not null).
  const useSummary = comps.length === 0 && summary != null;
  const compCount = useSummary ? summary.count : comps.length;

  let nearestMi: number | null = null;
  if (useSummary) {
    nearestMi = isFiniteNum(summary.nearest_mi) ? summary.nearest_mi : null;
  } else {
    for (const c of comps) {
      const d = c?.distance_mi;
      if (isFiniteNum(d) && (nearestMi == null || d < nearestMi)) nearestMi = d;
    }
  }

  const valuation = profile.valuation ?? null;
  const methods = valuation?.methods;
  // Redacted payloads carry methods: [] — treat as UNKNOWN (null) so the
  // spread falls back to divergence_pct, which survives redaction.
  const methodValues = profile.locked
    ? null
    : Array.isArray(methods)
      ? methods.map((m) => m?.value).filter((v): v is number => isFiniteNum(v) && v > 0)
      : null;

  const supplementalShare = comps.length
    ? comps.filter((c) => c?.source === "supplemental").length / comps.length
    : 0;

  return computeConfidenceFromSignals({
    compCount,
    nearestMi,
    methodValues,
    divergencePct: valuation?.divergence_pct ?? null,
    mid: valuation?.mid ?? null,
    supplementalShare,
  });
}
