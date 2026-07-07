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
}) {
  const mid = valuation.mid ?? null;
  const hasMid = mid != null && mid > 0;
  const methods = valuation.methods ?? [];

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

/** Memoized: the valuation object only changes identity when a recompute lands, so tuning-flag re-renders skip the whole panel. (New confidence props are scalars — memo stays effective.) */
export const ValuationPanel = memo(ValuationPanelImpl);
