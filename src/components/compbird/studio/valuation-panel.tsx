"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";

import { Pill } from "@/components/compbird/ui";
import { CountUp } from "@/components/compbird/motion";
import { usd, ppsf, stripTags } from "@/lib/compbird/format";
import { cn } from "@/lib/utils/cn";
import {
  computeConfidenceFromSignals,
  HIGH_MIN_COMPS,
  HIGH_ENS_MAX_NEAREST_MI,
  HIGH_ENS_MAX_FARTHEST_MI,
  HIGH_ENS_MAX_AGREEMENT_PCT,
  HIGH_MAX_SPREAD_PCT,
  type ConfidenceResult,
} from "@/lib/compbird/confidence";
import { ConfidenceBadge, ConfidenceFactsLine } from "./confidence-badge";
import type { Valuation } from "@/lib/compbird/types";

/**
 * The headline figure — presented by TIER (src/lib/compbird/confidence.ts):
 *
 *   HIGH — the measured gate says the number is trustworthy: the mid reads
 *   LARGE with an animated count-up, the low–high range sits beneath as
 *   support, and the badge reads as certainty.
 *
 *   STANDARD — the honest default: the RANGE is the hero at the size the mid
 *   holds on high-tier reports, the mid demotes to "midpoint $X" in the
 *   support row, and one plain line says why ("comparables are farther/fewer —
 *   treat this as a range"). Same idiom, no scare colors — the shape of the
 *   layout carries the honesty. On LIVE unlocked reports the explainer is
 *   followed by up to two ACTION chips ("Pin a closer comparable" / "Review
 *   the comp set") that jump to the evidence section they name — the range
 *   hero explains AND offers the next step.
 *
 * Both tiers keep the comp $/sqft, the always-visible comp-evidence facts
 * line, and the itemized method rows (which render whatever methods the engine
 * ships by name — including the ensemble's "AI comparable read" row — with no
 * name special-casing). When a tuning recompute settles (exclude/pin/what-if),
 * each method row whose value moved briefly shows the old value ghosted with
 * an arrow to the new plus a signed % chip, fading back to the plain row after
 * ~6s; new/dropped methods get a subtle chip instead of a delta (see the
 * method-delta helpers below).
 *
 * Confidence renders for LOCKED viewers too — it is computed from fields that
 * survive redaction (compsSummary count/nearest/farthest + divergence_pct +
 * the optional ai_blind arm), so it works as a selling point for the unlock
 * without moving any gated data client-side.
 */

/* ── STANDARD-tier thin-comp predicates (shared by explainer + action chips) ── */

/** The two measured thin-comp drivers, evaluated exactly as the tier gates do. */
function thinCompSignals(conf: ConfidenceResult): { fewer: boolean; farther: boolean } {
  const fewer = conf.compCount != null && conf.compCount < HIGH_MIN_COMPS;
  const farther =
    (conf.nearestMi != null && conf.nearestMi > HIGH_ENS_MAX_NEAREST_MI) ||
    (conf.farthestMi != null && conf.farthestMi > HIGH_ENS_MAX_FARTHEST_MI);
  return { fewer, farther };
}

/**
 * The one honest line under a STANDARD-tier range hero — names the dominant
 * measured driver (distance, then count), falling back to method disagreement.
 */
function rangeExplainer(conf: ConfidenceResult): string {
  const { fewer, farther } = thinCompSignals(conf);
  if (farther && fewer)
    return "Comparables here are farther away and fewer — treat this as a range, not a point estimate.";
  if (farther)
    return "Comparables here are farther away — treat this as a range, not a point estimate.";
  if (fewer)
    return "Fewer comparable sales here — treat this as a range, not a point estimate.";
  return "The valuation methods don't settle on a single number — treat this as a range, not a point estimate.";
}

/* ── PART B: actionable STANDARD tier ────────────────────────────────────────
 *
 * The range hero explains WHY the answer is a range; these chips offer the
 * next step, chosen from the same measured drivers the explainer reads:
 *
 *   far/few comps   → "Pin a closer comparable"  → jumps to + focuses the
 *                     add-a-comparable search in the evidence zone
 *   methods diverge → "Review the comp set"      → jumps to the comps table
 *
 * LIVE unlocked STANDARD reports only — the caller (report-view) passes
 * `canPinComp` / `canReviewComps` false on sample/locked reports, where the
 * targets don't exist; HIGH never shows a range hero, so chips never render
 * there either.
 */

export type StandardAction = "pin-closer" | "review-comps";

/** Exact shipped chip copy — plain realtor language, no engine jargon. */
export const ACTION_COPY: Record<StandardAction, string> = {
  "pin-closer": "Pin a closer comparable",
  "review-comps": "Review the comp set",
};

/** Anchor ids report-view mounts on the evidence sections the chips target. */
export const ADD_COMP_SECTION_ID = "cb-add-comp";
export const COMPS_SECTION_ID = "cb-comp-set";

/**
 * Which action chips a STANDARD confidence result earns (≤2 by construction,
 * ordered pin-closer → review-comps). Empty on HIGH, and empty on a STANDARD
 * result whose drivers are neither thin comps nor method disagreement.
 */
export function standardActionsFor(conf: ConfidenceResult): StandardAction[] {
  if (conf.tier !== "standard") return [];
  const out: StandardAction[] = [];
  const { fewer, farther } = thinCompSignals(conf);
  if (fewer || farther) out.push("pin-closer");
  const diverge =
    (conf.methodSpreadPct != null && conf.methodSpreadPct > HIGH_MAX_SPREAD_PCT) ||
    (conf.agreementPct != null && conf.agreementPct > HIGH_ENS_MAX_AGREEMENT_PCT);
  if (diverge) out.push("review-comps");
  return out;
}

/** Scroll to + focus the evidence section a chip names (client-only). */
function focusStandardAction(action: StandardAction, reduceMotion: boolean): void {
  if (typeof document === "undefined") return;
  const el = document.getElementById(
    action === "pin-closer" ? ADD_COMP_SECTION_ID : COMPS_SECTION_ID,
  );
  if (!el) return;
  // Pin: focus the search itself (the collapsed "+ Add a comparable" button or
  // the open input). Review: focus the section wrapper (tabIndex=-1 in
  // report-view) so AT lands where the scroll does. preventScroll keeps the
  // smooth scrollIntoView from being cut short by the focus jump.
  const target =
    action === "pin-closer" ? (el.querySelector<HTMLElement>("input, button") ?? el) : el;
  target.focus({ preventScroll: true });
  el.scrollIntoView({
    behavior: reduceMotion ? "auto" : "smooth",
    block: action === "pin-closer" ? "center" : "start",
  });
}

/* ── PART A: per-method delta feedback ───────────────────────────────────────
 *
 * When a tuning recompute settles (exclude/pin/what-if), each method row whose
 * value changed briefly shows "old → new" with a signed % chip, then fades
 * back to the plain row. Pure helpers here; the panel drives them from a
 * previous-methods ref keyed by `subjectKey` (reset on subject change).
 * prefers-reduced-motion skips the fade timers entirely — the delta stays
 * static and clears on the next recompute (or subject change).
 */

/** Name + value of a method row, as compared across recomputes. */
export interface MethodSnapshot {
  name: string;
  value: number | null;
}

export type MethodDelta =
  | { kind: "changed"; from: number; to: number; /** (to−from)/from × 100 */ pct: number }
  | { kind: "new" }
  | { kind: "dropped"; from: number | null };

/** Positive finite dollars or null — a method "has a value" only past this. */
function methodValue(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null;
}

/**
 * Diff two method lists BY NAME. Unchanged rows are omitted; a method whose
 * value appeared (absent before, or previously valueless) reads "new", one
 * whose value vanished (or whose row left the list) reads "dropped", and a
 * value→value move carries the delta. Method identity = method name.
 */
export function computeMethodDeltas(
  prev: MethodSnapshot[],
  next: MethodSnapshot[],
): Map<string, MethodDelta> {
  const out = new Map<string, MethodDelta>();
  const prevBy = new Map(prev.map((m) => [m.name, methodValue(m.value)]));
  const seen = new Set<string>();
  for (const m of next) {
    seen.add(m.name);
    const to = methodValue(m.value);
    if (!prevBy.has(m.name)) {
      out.set(m.name, { kind: "new" });
      continue;
    }
    const from = prevBy.get(m.name) ?? null;
    if (from == null && to == null) continue;
    if (from == null) out.set(m.name, { kind: "new" });
    else if (to == null) out.set(m.name, { kind: "dropped", from });
    else if (from !== to)
      out.set(m.name, { kind: "changed", from, to, pct: ((to - from) / from) * 100 });
  }
  for (const m of prev) {
    if (!seen.has(m.name)) out.set(m.name, { kind: "dropped", from: methodValue(m.value) });
  }
  return out;
}

/** One tracked comparison frame: the subject it belongs to + what to show. */
export interface MethodDeltaFrame {
  key: string;
  snapshot: MethodSnapshot[];
  /** Deltas vs the previous frame — null on first sight of a subject or when nothing moved. */
  deltas: Map<string, MethodDelta> | null;
}

/**
 * Advance the previous-methods tracker for a settled valuation. A subject-key
 * change CLEARS the comparison (first sight of a subject never shows deltas);
 * a same-subject recompute diffs against the prior snapshot.
 */
export function advanceMethodDeltas(
  prev: MethodDeltaFrame | null,
  key: string,
  methods: MethodSnapshot[],
): MethodDeltaFrame {
  const snapshot = methods.map((m) => ({ name: m.name, value: m.value }));
  if (!prev || prev.key !== key) return { key, snapshot, deltas: null };
  const deltas = computeMethodDeltas(prev.snapshot, snapshot);
  return { key, snapshot, deltas: deltas.size ? deltas : null };
}

/** "+1.9%" / "-0.1%" — signed, one decimal, magnitude clamped ≥0.1 so a real move never prints ±0.0%. */
export function fmtDeltaChip(pct: number): string {
  const mag = Math.max(0.1, Math.round(Math.abs(pct) * 10) / 10);
  return `${pct < 0 ? "-" : "+"}${mag.toFixed(1)}%`;
}

/** "2" for ±1.95%, "0.4" for sub-1% moves — reads naturally before "percent". */
function spokenPct(pct: number): string {
  const abs = Math.abs(pct);
  if (abs >= 0.95) return String(Math.round(abs));
  return Math.max(0.1, Math.round(abs * 10) / 10).toFixed(1);
}

/**
 * One aria-live sentence naming the LARGEST mover, e.g. "Direct comparison
 * moved up 2 percent." — null when nothing changed. report-view appends this
 * to its existing recompute narration.
 */
export function largestMoverSentence(deltas: Map<string, MethodDelta> | null): string | null {
  if (!deltas) return null;
  let best: { name: string; pct: number } | null = null;
  for (const [name, d] of deltas) {
    if (d.kind !== "changed") continue;
    if (!best || Math.abs(d.pct) > Math.abs(best.pct)) best = { name, pct: d.pct };
  }
  if (!best) return null;
  return `${best.name} moved ${best.pct >= 0 ? "up" : "down"} ${spokenPct(best.pct)} percent.`;
}

/** How long a settled delta stays fully visible before the CSS fade begins. */
export const DELTA_VISIBLE_MS = 6000;
/** Matches the `duration-700` transition on the delta adornments. */
const DELTA_FADE_MS = 700;

/** Fade wrapper for every delta adornment — the ~6s timer flips `fading`. */
function deltaFadeClass(fading: boolean): string {
  return cn(
    "transition-opacity duration-700 motion-reduce:transition-none",
    fading && "opacity-0",
  );
}

const deltaChipClass =
  "rounded-full border border-border bg-secondary/60 px-1.5 py-px font-data text-[0.65rem] font-medium text-muted-foreground";
const newChipClass =
  "rounded-full border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] px-1.5 py-px text-[0.65rem] font-medium text-[var(--cb-ember-text)]";

function ValuationPanelImpl({
  valuation,
  nearestMi,
  farthestMi,
  compCount,
  supplementalShare = 0,
  locked = false,
  engineMid,
  tunedCount = 0,
  onResetTuning,
  busy = false,
  subjectKey = "",
  canPinComp = false,
  canReviewComps = false,
}: {
  valuation: Valuation;
  /** Distance (mi) of the closest comp — caps confidence when comps aren't local. */
  nearestMi?: number | null;
  /**
   * Distance (mi) of the farthest comp — the measured high-tier gate bounds
   * the WHOLE set, not just the closest sale. Undefined degrades gracefully
   * (nearest + the evidence gate still hold).
   */
  farthestMi?: number | null;
  /**
   * Number of comparable sales behind the estimate. Callers pass comps.length
   * on live reports and compsSummary.count on locked ones (both survive
   * redaction). Undefined = not wired: the facts line drops the count and the
   * tier stays "standard" (a verified comp count is a high-tier gate).
   */
  compCount?: number | null;
  /** Share (0–1) of comps sourced from public records — >50% caps the tier at standard. */
  supplementalShare?: number;
  /**
   * Evidence-redacted payload (methods stripped to [] for a non-Pro viewer).
   * The mid/low/high still render. The confidence tier is then computed from
   * the engine's divergence_pct (which survives redaction) instead of the
   * per-method values — see confidence.ts for what degrades.
   */
  locked?: boolean;
  /**
   * Comp workshop: the FIRST unmodified engine mid for this subject (captured
   * when the live profile loaded, before any pin/exclude). With `tunedCount`
   * > 0 it drives the realized-delta ticker "Engine set $X → yours $Y (+Z%)".
   * Display values on both sides ($5k-rounded, matching the headline and the
   * PDF) — the engine doesn't ship unrounded mids over the preview wire.
   */
  engineMid?: number | null;
  /** |excluded ∪ forced| — >0 means the comp set is agent-tuned right now. */
  tunedCount?: number;
  /** Clears every pin/exclusion and recomputes — the "Reset to engine picks" chip. */
  onResetTuning?: () => void;
  /** A recompute is in flight — disables the reset chip to avoid pile-ups. */
  busy?: boolean;
  /**
   * Subject identity (report-view's `parcel_id|address` key) — the
   * previous-methods delta tracker resets on it, so a delta can never leak
   * across a subject change. Empty string degrades to "one subject".
   */
  subjectKey?: string;
  /** Live unlocked report with the add-a-comparable search present — enables the "Pin a closer comparable" chip. */
  canPinComp?: boolean;
  /** Live unlocked report with the comps table present — enables the "Review the comp set" chip. */
  canReviewComps?: boolean;
}) {
  const mid = valuation.mid ?? null;
  const hasMid = mid != null && mid > 0;
  const methods = valuation.methods ?? [];
  const reduceMotion = useReducedMotion();

  // Realized estimate delta — only meaningful once the user actually tuned the
  // comp set on a live report. NOTE: no ghost baseline tick here — this panel
  // presents the low–high range as text, not on a scale, so there is no natural
  // axis to host a tick (per spec: don't invent a new chart for it).
  const tuned = tunedCount > 0 && typeof onResetTuning === "function";
  const showDelta = tuned && engineMid != null && engineMid > 0 && hasMid;
  // `+ 0` normalizes -0 so a tiny negative drift never prints "-0.0%".
  const deltaPct = showDelta ? Math.round(((mid! - engineMid!) / engineMid!) * 1000) / 10 + 0 : 0;
  const deltaStr = `${deltaPct > 0 ? "+" : ""}${deltaPct.toFixed(1)}%`;

  // Row-level cause-and-effect (PART A): diff the settled methods against the
  // previous valuation FOR THIS SUBJECT. The tracker ref is keyed by
  // subjectKey (advanceMethodDeltas clears across subjects), and the valuation
  // OBJECT identity is the recompute signal — the studio only mints a new one
  // when a recompute lands.
  const deltaFrameRef = useRef<MethodDeltaFrame | null>(null);
  const lastValuationRef = useRef<Valuation | null>(null);
  const [deltas, setDeltas] = useState<Map<string, MethodDelta> | null>(null);
  const [fading, setFading] = useState(false);

  useEffect(() => {
    if (lastValuationRef.current === valuation) return;
    lastValuationRef.current = valuation;
    const frame = advanceMethodDeltas(
      deltaFrameRef.current,
      subjectKey,
      valuation.methods ?? [],
    );
    deltaFrameRef.current = frame;
    setDeltas(frame.deltas);
    setFading(false);
  }, [valuation, subjectKey]);

  // The ~6s dwell → CSS fade → cleanup cycle. Reduced motion: no timers at all
  // — the delta stays static and clears on the next recompute/subject change.
  useEffect(() => {
    if (!deltas || reduceMotion) return;
    const fade = window.setTimeout(() => setFading(true), DELTA_VISIBLE_MS);
    const clear = window.setTimeout(() => {
      setDeltas(null);
      setFading(false);
    }, DELTA_VISIBLE_MS + DELTA_FADE_MS + 100);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(clear);
    };
  }, [deltas, reduceMotion]);

  // Methods that left the list entirely — rendered as fading ghost rows so
  // "dropped" is visible, not silent.
  const droppedRows = useMemo(() => {
    if (!deltas) return [] as { name: string; from: number | null }[];
    const present = new Set(methods.map((m) => m.name));
    const out: { name: string; from: number | null }[] = [];
    for (const [name, d] of deltas) {
      if (d.kind === "dropped" && !present.has(name)) out.push({ name, from: d.from });
    }
    return out;
  }, [deltas, methods]);

  // Locked payloads carry methods: [] — pass null (UNKNOWN) so the spread
  // falls back to divergence_pct rather than reading redaction as "no methods".
  const methodValues = locked
    ? null
    : methods
        .map((m) => m.value)
        .filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0);

  const conf = computeConfidenceFromSignals({
    compCount: compCount ?? null,
    nearestMi: nearestMi ?? null,
    farthestMi: farthestMi ?? null,
    methodValues,
    divergencePct: valuation.divergence_pct ?? null,
    mid,
    aiBlind: valuation.ai_blind ?? null,
    aiEnsemble: valuation.ai_ensemble ?? null,
    supplementalShare,
    // Engine-computed tier rides the valuation — authoritative when present,
    // so the studio badge always matches the generated report's hero.
    engineTier: valuation.confidence_tier ?? null,
  });

  // STANDARD tier flips the hero: the honest low–high RANGE takes the size the
  // mid holds on high-tier reports, and the mid demotes to "midpoint $X" in the
  // support row. Needs both ends — a range-less payload keeps the mid hero.
  const low = valuation.low ?? null;
  const high = valuation.high ?? null;
  const hasRange = low != null && low > 0 && high != null && high > 0;
  const rangeHero = conf.tier === "standard" && hasMid && hasRange;
  const heroFigureClass =
    "font-data text-5xl font-semibold leading-none tracking-tight text-[var(--cb-ember-text)] sm:text-6xl";

  // PART B: the range hero's next-step chips — live unlocked STANDARD only
  // (sample/locked callers pass both flags false; HIGH never range-heroes).
  const standardActions =
    rangeHero && !locked && (canPinComp || canReviewComps)
      ? standardActionsFor(conf).filter((a) =>
          a === "pin-closer" ? canPinComp : canReviewComps,
        )
      : [];

  return (
    <div className="flex flex-col gap-7">
      {/* headline value */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="cb-eyebrow text-muted-foreground">
            {rangeHero ? "Estimated range" : "Estimated value"}
          </span>
          <span className="inline-flex flex-wrap items-center gap-2">
            {locked ? <Pill tone="neutral">Method breakdown — Pro</Pill> : null}
            {hasMid ? <ConfidenceBadge confidence={conf} /> : null}
          </span>
        </div>

        {rangeHero ? (
          /* STANDARD — the range IS the answer */
          <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <CountUp to={low ?? 0} prefix="$" duration={1.4} className={heroFigureClass} />
            <span aria-hidden className="font-data text-3xl leading-none text-border sm:text-4xl">
              –
            </span>
            <span className="sr-only">to</span>
            <CountUp to={high ?? 0} prefix="$" duration={1.4} className={heroFigureClass} />
          </div>
        ) : (
          /* HIGH (or no range shipped) — the mid IS the answer */
          <div className="mt-2 flex items-baseline gap-3">
            {hasMid ? (
              <CountUp to={mid ?? 0} prefix="$" duration={1.4} className={heroFigureClass} />
            ) : (
              <span className={heroFigureClass}>—</span>
            )}
          </div>
        )}

        {/* the honest one-liner a range hero owes the reader */}
        {rangeHero ? (
          <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground">
            {rangeExplainer(conf)}
          </p>
        ) : null}

        {/* …and the next step it owes the agent (live unlocked reports only) */}
        {standardActions.length ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {standardActions.map((action) => (
              <button
                key={action}
                type="button"
                data-cb-action={action}
                onClick={() => focusStandardAction(action, reduceMotion === true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:border-[var(--cb-ember)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
              >
                {ACTION_COPY[action]}
                <svg viewBox="0 0 16 16" className="h-3 w-3 text-[var(--cb-ember)]" fill="none" aria-hidden>
                  <path
                    d="M8 3v10m0 0 4-4m-4 4-4-4"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            ))}
          </div>
        ) : null}

        {/* comp-evidence facts — always visible, caution copy when comps run thin */}
        {hasMid ? <ConfidenceFactsLine confidence={conf} className="mt-2.5" /> : null}

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-data text-sm text-muted-foreground">
          {rangeHero ? (
            <span>
              midpoint <span className="text-foreground">{usd(mid)}</span>
            </span>
          ) : (
            <span>
              {usd(valuation.low)} <span className="text-border">–</span> {usd(valuation.high)}
            </span>
          )}
          {valuation.comp_ppsf != null ? (
            <>
              <span aria-hidden className="text-border">
                ·
              </span>
              <span>{ppsf(valuation.comp_ppsf)}/sqft comps</span>
            </>
          ) : null}
        </div>

        {/* comp-workshop tuning readout: realized delta vs the engine's own
            picks + the way back. Renders only while excluded ∪ forced ≠ ∅. */}
        {tuned ? (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
            {showDelta ? (
              <p className="font-data text-xs text-muted-foreground">
                Engine set <span className="text-foreground">{usd(engineMid)}</span>{" "}
                <span aria-hidden>→</span>
                <span className="sr-only">to</span> yours{" "}
                <span className="text-[var(--cb-ember-text)]">{usd(mid)}</span> ({deltaStr})
              </p>
            ) : null}
            <button
              type="button"
              onClick={onResetTuning}
              disabled={busy}
              className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:border-[var(--cb-ember)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              Reset to engine picks
            </button>
          </div>
        ) : null}
      </div>

      {/* method breakdown — rows briefly carry their recompute delta (PART A).
          The ghost old value / % chip are aria-hidden: the accessible story is
          the aria-live largest-mover sentence report-view narrates. */}
      {methods.length || droppedRows.length ? (
        <div className="border-t border-border pt-5">
          <span className="cb-eyebrow text-muted-foreground">How we triangulated it</span>
          <ul className="mt-4 flex flex-col divide-y divide-border">
            {methods.map((m, i) => {
              const delta = deltas?.get(m.name);
              return (
                <li
                  key={`${m.name}-${i}`}
                  className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-baseline sm:gap-5"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 sm:w-56 sm:shrink-0">
                    <span className="text-sm font-medium text-foreground">{m.name}</span>
                    <span className="flex flex-wrap items-baseline justify-end gap-x-1.5 gap-y-0.5 font-data text-sm text-foreground">
                      {delta?.kind === "changed" ? (
                        <span
                          aria-hidden
                          className={cn("inline-flex items-baseline gap-x-1.5", deltaFadeClass(fading))}
                        >
                          <span className="text-muted-foreground/70">{usd(delta.from)}</span>
                          <span className="text-border">→</span>
                        </span>
                      ) : null}
                      <span>{usd(m.value)}</span>
                      {delta?.kind === "changed" ? (
                        <span aria-hidden className={cn(deltaChipClass, deltaFadeClass(fading))}>
                          {fmtDeltaChip(delta.pct)}
                        </span>
                      ) : null}
                      {delta?.kind === "new" ? (
                        <span className={cn(newChipClass, deltaFadeClass(fading))}>New</span>
                      ) : null}
                      {delta?.kind === "dropped" ? (
                        <span className={cn(deltaChipClass, deltaFadeClass(fading))}>Dropped</span>
                      ) : null}
                    </span>
                  </div>
                  <p className="text-xs leading-relaxed text-muted-foreground sm:flex-1">
                    {stripTags(m.rationale)}
                  </p>
                </li>
              );
            })}
            {/* methods that LEFT the list — visible ghosts, not a silent vanish */}
            {droppedRows.map(({ name, from }) => (
              <li
                key={`dropped-${name}`}
                className={cn(
                  "flex flex-col gap-1 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-baseline sm:gap-5",
                  deltaFadeClass(fading),
                  !fading && "opacity-70",
                )}
              >
                <div className="flex items-baseline justify-between gap-3 sm:w-56 sm:shrink-0">
                  <span className="text-sm font-medium text-muted-foreground">{name}</span>
                  <span className="flex items-baseline gap-x-1.5 font-data text-sm text-muted-foreground">
                    {from != null ? (
                      <span className="line-through decoration-border">{usd(from)}</span>
                    ) : null}
                    <span className={deltaChipClass}>Dropped</span>
                  </span>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground sm:flex-1">
                  No longer part of this estimate.
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** Memoized: the valuation object only changes identity when a recompute lands, so most re-renders skip the panel. (Confidence + workshop props are scalars or stable callbacks — the new subjectKey/canPinComp/canReviewComps props included; `busy` flips do re-render it now — that's the price of a live-disabled reset chip, and the subtree is small.) */
export const ValuationPanel = memo(ValuationPanelImpl);
