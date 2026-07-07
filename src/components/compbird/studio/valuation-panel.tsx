"use client";

import { memo } from "react";

import { Pill } from "@/components/compbird/ui";
import { CountUp } from "@/components/compbird/motion";
import { usd, ppsf, stripTags } from "@/lib/compbird/format";
import { computeConfidenceFromSignals } from "@/lib/compbird/confidence";
import { ConfidenceBadge, ConfidenceFactsLine } from "./confidence-badge";
import type { Valuation } from "@/lib/compbird/types";

/**
 * The headline number. The mid value reads LARGE with an animated count-up; a
 * two-tier confidence badge (src/lib/compbird/confidence.ts) sits beside it
 * with the honest drivers in a popover; the low–high range, comp $/sqft and an
 * always-visible comp-evidence facts line sit beneath, then the valuation
 * methods are itemized as rows with their rationale.
 *
 * Confidence renders for LOCKED viewers too — it is computed from fields that
 * survive redaction (compsSummary count/nearest + divergence_pct), so it works
 * as a selling point for the unlock without moving any gated data client-side.
 */

function ValuationPanelImpl({
  valuation,
  nearestMi,
  compCount,
  supplementalShare = 0,
  locked = false,
  engineMid,
  tunedCount = 0,
  onResetTuning,
  busy = false,
}: {
  valuation: Valuation;
  /** Distance (mi) of the closest comp — caps confidence when comps aren't local. */
  nearestMi?: number | null;
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
}) {
  const mid = valuation.mid ?? null;
  const hasMid = mid != null && mid > 0;
  const methods = valuation.methods ?? [];

  // Realized estimate delta — only meaningful once the user actually tuned the
  // comp set on a live report. NOTE: no ghost baseline tick here — this panel
  // presents the low–high range as text, not on a scale, so there is no natural
  // axis to host a tick (per spec: don't invent a new chart for it).
  const tuned = tunedCount > 0 && typeof onResetTuning === "function";
  const showDelta = tuned && engineMid != null && engineMid > 0 && hasMid;
  // `+ 0` normalizes -0 so a tiny negative drift never prints "-0.0%".
  const deltaPct = showDelta ? Math.round(((mid! - engineMid!) / engineMid!) * 1000) / 10 + 0 : 0;
  const deltaStr = `${deltaPct > 0 ? "+" : ""}${deltaPct.toFixed(1)}%`;

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
    methodValues,
    divergencePct: valuation.divergence_pct ?? null,
    mid,
    supplementalShare,
  });

  return (
    <div className="flex flex-col gap-7">
      {/* headline value */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="cb-eyebrow text-muted-foreground">Estimated value</span>
          <span className="inline-flex flex-wrap items-center gap-2">
            {locked ? <Pill tone="neutral">Method breakdown — Pro</Pill> : null}
            {hasMid ? <ConfidenceBadge confidence={conf} /> : null}
          </span>
        </div>

        <div className="mt-2 flex items-baseline gap-3">
          {hasMid ? (
            <CountUp
              to={mid ?? 0}
              prefix="$"
              duration={1.4}
              className="font-data text-5xl font-semibold leading-none tracking-tight text-[var(--cb-ember-text)] sm:text-6xl"
            />
          ) : (
            <span className="font-data text-5xl font-semibold leading-none tracking-tight text-[var(--cb-ember-text)] sm:text-6xl">
              —
            </span>
          )}
        </div>

        {/* comp-evidence facts — always visible, caution copy when comps run thin */}
        {hasMid ? <ConfidenceFactsLine confidence={conf} className="mt-2.5" /> : null}

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-data text-sm text-muted-foreground">
          <span>
            {usd(valuation.low)} <span className="text-border">–</span> {usd(valuation.high)}
          </span>
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

      {/* method breakdown */}
      {methods.length ? (
        <div className="border-t border-border pt-5">
          <span className="cb-eyebrow text-muted-foreground">How we triangulated it</span>
          <ul className="mt-4 flex flex-col divide-y divide-border">
            {methods.map((m, i) => (
              <li
                key={`${m.name}-${i}`}
                className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-baseline sm:gap-5"
              >
                <div className="flex items-baseline justify-between gap-3 sm:w-56 sm:shrink-0">
                  <span className="text-sm font-medium text-foreground">{m.name}</span>
                  <span className="font-data text-sm text-foreground">
                    {usd(m.value)}
                  </span>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground sm:flex-1">
                  {stripTags(m.rationale)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** Memoized: the valuation object only changes identity when a recompute lands, so most re-renders skip the panel. (Confidence + workshop props are scalars or stable callbacks; `busy` flips do re-render it now — that's the price of a live-disabled reset chip, and the subtree is small.) */
export const ValuationPanel = memo(ValuationPanelImpl);
