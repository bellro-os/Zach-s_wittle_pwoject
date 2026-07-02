"use client";

import { memo } from "react";

import { Pill } from "@/components/compbird/ui";
import { CountUp } from "@/components/compbird/motion";
import { usd, ppsf, pct, stripTags } from "@/lib/compbird/format";
import type { Valuation } from "@/lib/compbird/types";

/**
 * The headline number. The mid value reads LARGE with an animated count-up; the
 * low–high range, comp $/sqft and a divergence "confidence" pill sit beneath,
 * then the three valuation methods are itemized as rows with their rationale.
 */

type Confidence =
  | { kind: "none" }
  | { kind: "pill"; label: string; tone: "positive" | "neutral" | "negative" };

/**
 * Tighter spread ⇒ higher confidence — but a tight spread only MEANS something
 * once at least two independent comp-based methods agree. A single-method
 * valuation reports divergence 0.0; treating that as "high confidence" is a lie.
 * With no real estimate, we show no pill at all.
 */
function confidence(
  mid: number | null,
  agreeingMethods: number,
  divergence: number | null,
  nearestMi: number | null,
): Confidence {
  if (mid == null || mid <= 0) return { kind: "none" };
  // Non-local comps can never read as high confidence — when the nearest
  // comparable is far away, the headline number is geographic, not local
  // evidence (the engine falls back to distant sales where local ones are scarce).
  if (nearestMi != null && nearestMi > 40)
    return {
      kind: "pill",
      label: `Comps ~${Math.round(nearestMi)} mi away · Low confidence`,
      tone: "negative",
    };
  if (agreeingMethods < 2)
    return { kind: "pill", label: "Single method · limited evidence", tone: "neutral" };
  if (divergence == null)
    return { kind: "pill", label: "Confidence —", tone: "neutral" };
  const far = nearestMi != null && nearestMi > 15;
  if (divergence > 10)
    return { kind: "pill", label: `${pct(divergence)} spread · Wide spread`, tone: "negative" };
  if (divergence > 5 || far)
    return {
      kind: "pill",
      label: far
        ? `Comps ~${Math.round(nearestMi as number)} mi away · Moderate confidence`
        : `${pct(divergence)} spread · Moderate confidence`,
      tone: "neutral",
    };
  return { kind: "pill", label: `${pct(divergence)} spread · High confidence`, tone: "positive" };
}

/**
 * Methods whose value actually came from comparable sales. The model-based and
 * trend-based methods (AVM, prior-sale-plus-trend) corroborate but are not
 * "agreement among comps", so they don't count toward divergence confidence.
 */
const NON_COMP_METHODS = new Set(["Prior sale + trend", "AVM (model)"]);

function ValuationPanelImpl({
  valuation,
  nearestMi,
}: {
  valuation: Valuation;
  /** Distance (mi) of the closest comp — caps confidence when comps aren't local. */
  nearestMi?: number | null;
}) {
  const mid = valuation.mid ?? null;
  const hasMid = mid != null && mid > 0;
  const methods = valuation.methods ?? [];
  const agreeingMethods = methods.filter(
    (m) => m.value != null && !NON_COMP_METHODS.has(m.name),
  ).length;
  const conf = confidence(mid, agreeingMethods, valuation.divergence_pct, nearestMi ?? null);

  return (
    <div className="flex flex-col gap-7">
      {/* headline value */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="cb-eyebrow text-muted-foreground">Estimated value</span>
          {conf.kind === "pill" ? (
            <Pill tone={conf.tone}>{conf.label}</Pill>
          ) : null}
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

/** Memoized: the valuation object only changes identity when a recompute lands, so tuning-flag re-renders skip the whole panel. */
export const ValuationPanel = memo(ValuationPanelImpl);
