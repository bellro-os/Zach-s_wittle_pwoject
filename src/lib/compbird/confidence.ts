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
 * The honest confidence drivers (measured — thresholds derived from the
 * 1000-subject regional certification pool, see the gate constants below):
 *   - comp proximity: nearest AND farthest comp distance — a tight, local comp
 *     set is the strongest single signal
 *   - comp count: more nearby closed sales = better anchored
 *   - arm agreement: when the engine ships the blind-AI ensemble arm
 *     (valuation.ai_blind), |engine − blind| / ensemble is the sharpest gate
 *   - method agreement: tight spread across independent methods — the fallback
 *     evidence gate when no blind arm is present
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
  /** Distance (mi) of the farthest comp; null when unknown. */
  farthestMi: number | null;
  /** Method spread (max−min)/mid as a PERCENTAGE (e.g. 6.5); null when unknowable. */
  methodSpreadPct: number | null;
  /**
   * Blind-AI arm agreement |engine − blind| / ensemble as a PERCENTAGE;
   * null when the engine didn't ship `valuation.ai_blind`.
   */
  agreementPct: number | null;
  /** Thin-comp evidence: <4 comps or nearest >1.5 mi — the UI adds explicit caution copy. */
  caution: boolean;
}

/* ── Tier gates (all must hold for "high") ───────────────────────────────────
 *
 * MEASURED thresholds, derived 2026-07-13 from the 1000-subject regional
 * certification pool (scratchpad cert_pool_1000_ens_fast_detail.jsonl —
 * fields sold / engine_only / blind / ens / ape / near / far; derivation
 * script: derive_confidence_gates.mjs alongside it). Pool-wide ensemble
 * median APE is 11.54%; the gates below carve out the slice where the number
 * is genuinely trustworthy.
 *
 * ENSEMBLE ARM — valuation.ai_blind present AND ai_ensemble (the shown mid is
 * the ensemble). Chosen gate:
 *   nearest ≤ 0.3 mi & farthest ≤ 1.0 mi & agreement ≤ 10%
 *     → median APE 6.13% @ 31.0% coverage (n=310)
 *   runners-up (all ~equivalent within half-split noise):
 *     nearest ≤ 0.2 & farthest ≤ 1.0 & agree ≤ 12% → 6.17% @ 32.7%
 *     nearest ≤ 0.4 & farthest ≤ 1.0 & agree ≤ 10% → 6.24% @ 31.7%
 *     nearest ≤ 0.2 & farthest ≤ 1.5 & agree ≤ 12% → 6.24% @ 32.9%
 *       (raw coverage argmax — rejected: a 0.2-mi nearest cut is knife-edge
 *       against the engine's rounded distances and region density)
 *   STANDARD complement measures 14.95% median APE @ 69.0% — the honest gap
 *   the range-hero presentation exists for.
 *
 * FALLBACK ARM — no blind arm (the shown mid is engine-only). Keeps today's
 * nearest/spread gate, plus the farthest bound now that it's computed:
 *   nearest ≤ 0.5 & farthest ≤ 0.8 → engine-only median APE 9.21% @ 42.9%
 *   (vs 11.13% without the farthest bound — the bound is what keeps "high"
 *   honest on this arm; engine-only never reaches ≤6.5% at any distance gate).
 */
export const HIGH_MIN_COMPS = 5;
/* ensemble arm (ai_blind + ai_ensemble) */
export const HIGH_ENS_MAX_NEAREST_MI = 0.3;
export const HIGH_ENS_MAX_FARTHEST_MI = 1.0;
export const HIGH_ENS_MAX_AGREEMENT_PCT = 10;
/* fallback arm (no blind arm — today's degradation path) */
export const HIGH_MAX_NEAREST_MI = 0.5;
export const HIGH_MAX_FARTHEST_MI = 0.8;
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
   * Distance (mi) of the farthest comp; null/undefined = unknown. Unknown does
   * NOT block "high" on its own (nearest + the evidence gate still hold) — it
   * only exists as a defensive path for scalar callers not yet passing it;
   * every payload shape carries it (comps array or compsSummary.farthest_mi).
   */
  farthestMi?: number | null;
  /**
   * Blind-AI ensemble arm (valuation.ai_blind) — the independent AI estimate.
   * Absent/null → the evidence gate falls back to the method spread.
   */
  aiBlind?: number | null;
  /** valuation.ai_ensemble — true when `mid` IS the ensemble mean. */
  aiEnsemble?: boolean | null;
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
  /**
   * ENGINE-computed tier (`valuation.confidence_tier`, CMA_BLIND_ENSEMBLE
   * engines) — AUTHORITATIVE when defined: the engine owns every raw input
   * (unrounded mid, exact comp distances, the blind anchor it fetched) and
   * computes the tier server-side (build_cma.confidence_signals in the MLS Bot
   * repo — same gates as this file), so it cannot be spoofed by request inputs
   * and always matches the generated report's hero treatment. The client-side
   * gates below remain the fallback for locked/legacy/sample payloads that
   * don't carry it. Reasons/caution are still computed from the local signals
   * either way (the tier decides ordering, not content).
   */
  engineTier?: ConfidenceTier | null;
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
  const farthestMi = isFiniteNum(s.farthestMi) && s.farthestMi >= 0 ? s.farthestMi : null;
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

  // Arm agreement |engine − blind| / ensemble, reconstructed from what the
  // wire carries. When the shown mid IS the ensemble (ai_ensemble), the engine
  // arm is 2·mid − blind and the denominator is mid itself; when the mid is
  // engine-only, the ensemble midpoint is (mid + blind) / 2. Identical to the
  // derivation pool's `|engine_only - blind| / ens` in both cases.
  const aiBlind = isFiniteNum(s.aiBlind) && s.aiBlind > 0 ? s.aiBlind : null;
  let agreementPct: number | null = null;
  if (aiBlind != null && mid != null) {
    const engineOnly = s.aiEnsemble === true ? 2 * mid - aiBlind : mid;
    const ens = s.aiEnsemble === true ? mid : (mid + aiBlind) / 2;
    if (ens > 0) agreementPct = (Math.abs(engineOnly - aiBlind) / ens) * 100;
  }
  // The measured ensemble gate only describes the ENSEMBLE value — when
  // ai_blind arrives without ai_ensemble the shown mid is engine-only, so the
  // fallback (distance/spread) gate governs and agreement is a reason only.
  const ensembleArm = s.aiEnsemble === true && agreementPct != null;

  // "high" needs ≥5 comps (null count = UNKNOWN — doesn't block on its own,
  // any caller that KNOWS a thin count passes the number and gets blocked),
  // a local comp set, and the arm-appropriate evidence gate:
  //   ensemble arm: nearest ≤0.3, farthest ≤1.0, agreement ≤10%  (6.13% APE)
  //   fallback arm: nearest ≤0.5, farthest ≤0.8, spread ≤10%     (9.21% APE)
  // Unknown farthest degrades gracefully (nearest + evidence still gate).
  const countOk = compCount == null || compCount >= HIGH_MIN_COMPS;
  const distanceOk = ensembleArm
    ? nearestMi != null &&
      nearestMi <= HIGH_ENS_MAX_NEAREST_MI &&
      (farthestMi == null || farthestMi <= HIGH_ENS_MAX_FARTHEST_MI)
    : nearestMi != null &&
      nearestMi <= HIGH_MAX_NEAREST_MI &&
      (farthestMi == null || farthestMi <= HIGH_MAX_FARTHEST_MI);
  const evidenceOk = ensembleArm
    ? (agreementPct as number) <= HIGH_ENS_MAX_AGREEMENT_PCT
    : methodSpreadPct != null && methodSpreadPct <= HIGH_MAX_SPREAD_PCT;

  const computedTier: ConfidenceTier =
    mid != null && countOk && distanceOk && evidenceOk && supplementalShare <= 0.5
      ? "high"
      : "standard";
  // Engine tier is authoritative when the payload carries one (see the
  // ConfidenceSignals docs) — the client computation is the fallback.
  const tier: ConfidenceTier =
    s.engineTier === "high" || s.engineTier === "standard" ? s.engineTier : computedTier;

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

  // Farthest: bound by the ARM's gate — a set that stretches past it reads as
  // a caveat even when the nearest comp is on the doorstep.
  const farBound = ensembleArm ? HIGH_ENS_MAX_FARTHEST_MI : HIGH_MAX_FARTHEST_MI;
  if (farthestMi != null && compCount !== 0) {
    if (farthestMi <= farBound) positives.push(`all comps within ${fmtMi(farthestMi)} mi`);
    else caveats.push(`comp set stretches to ${fmtMi(farthestMi)} mi out`);
  }

  if (agreementPct != null) {
    if (agreementPct <= HIGH_ENS_MAX_AGREEMENT_PCT)
      positives.push(
        `independent AI read agrees within ${Math.max(1, Math.ceil(agreementPct))}%`,
      );
    else caveats.push(`independent AI read differs by ${Math.round(agreementPct)}%`);
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

  return {
    tier,
    reasons,
    compCount,
    nearestMi,
    farthestMi,
    methodSpreadPct,
    agreementPct,
    caution,
  };
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
    /** Blind-AI ensemble arm — optional, survives redaction (see types.ts). */
    ai_blind?: number | null;
    ai_ensemble?: boolean;
    /** Engine-computed tier — authoritative when present (see ConfidenceSignals.engineTier). */
    confidence_tier?: string | null;
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
  let farthestMi: number | null = null;
  if (useSummary) {
    nearestMi = isFiniteNum(summary.nearest_mi) ? summary.nearest_mi : null;
    farthestMi = isFiniteNum(summary.farthest_mi) ? summary.farthest_mi : null;
  } else {
    for (const c of comps) {
      const d = c?.distance_mi;
      if (!isFiniteNum(d)) continue;
      if (nearestMi == null || d < nearestMi) nearestMi = d;
      if (farthestMi == null || d > farthestMi) farthestMi = d;
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

  const engineTier = valuation?.confidence_tier;

  return computeConfidenceFromSignals({
    compCount,
    nearestMi,
    farthestMi,
    methodValues,
    divergencePct: valuation?.divergence_pct ?? null,
    mid: valuation?.mid ?? null,
    aiBlind: valuation?.ai_blind ?? null,
    aiEnsemble: valuation?.ai_ensemble ?? null,
    supplementalShare,
    engineTier: engineTier === "high" || engineTier === "standard" ? engineTier : null,
  });
}
