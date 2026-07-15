"use client";

import { useId, useState } from "react";
import { cn } from "@/lib/utils/cn";
import type { ConfidenceResult } from "@/lib/compbird/confidence";

/**
 * Instrument-style confidence readout for the headline estimate:
 *
 *   - <ConfidenceBadge/>  — compact HIGH CONFIDENCE / STANDARD chip with a
 *     hover/tap popover listing the human-readable drivers ("6 comparable
 *     sales", "nearest 0.1 mi") or the honest caveats ("only 3 comparable
 *     sales nearby"). TWO tiers only — no scary red tier.
 *   - <ConfidenceFactsLine/> — the always-visible one-liner under the figure
 *     ("Based on 6 comparable sales · nearest 0.1 mi"). Works from the
 *     redaction-surviving compsSummary fields, so LOCKED viewers see it too.
 *     Thin-comp evidence (result.caution) swaps in explicit caution copy.
 */

export function ConfidenceBadge({
  confidence,
  className,
}: {
  confidence: ConfidenceResult;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const high = confidence.tier === "high";

  return (
    <span
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={popId}
        aria-label={`${high ? "High confidence" : "Standard confidence"} — show why`}
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
        className={cn(
          "inline-flex cursor-help select-none items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.12em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] sm:py-0.5",
          high
            ? "border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] text-[var(--cb-ember-text)]"
            : "border-border bg-secondary/60 text-muted-foreground",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            high ? "bg-[var(--cb-ember)]" : "bg-muted-foreground/50",
          )}
        />
        {high ? "High confidence" : "Standard"}
      </button>

      {open && confidence.reasons.length ? (
        <div
          id={popId}
          role="tooltip"
          className="absolute right-0 top-full z-30 mt-2 w-60 rounded-xl border border-border bg-card p-3 text-left shadow-[0_16px_40px_-16px_rgba(0,0,0,0.35)]"
        >
          <span className="cb-eyebrow text-muted-foreground">Why this rating</span>
          <ul className="mt-2 flex flex-col gap-1">
            {confidence.reasons.map((r, i) => (
              <li key={i} className="flex items-baseline gap-2 text-xs text-foreground">
                <span
                  aria-hidden
                  className="h-px w-2.5 shrink-0 translate-y-[-0.2em] bg-[var(--cb-ember)]/70"
                />
                {r}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </span>
  );
}

/** "0.3 mi", clamped so a 400-ft comp never prints "0.0 mi". */
function fmtMi(d: number): string {
  return `${Math.max(0.1, Math.round(d * 10) / 10).toFixed(1)} mi`;
}

export function ConfidenceFactsLine({
  confidence,
  className,
}: {
  confidence: ConfidenceResult;
  className?: string;
}) {
  const { compCount, nearestMi, caution } = confidence;

  const facts: string[] = [];
  if (compCount != null && compCount > 0) {
    facts.push(`Based on ${compCount} comparable ${compCount === 1 ? "sale" : "sales"}`);
  }
  if (nearestMi != null) {
    // With no count leading the sentence, the distance carries it.
    facts.push(facts.length ? `nearest ${fmtMi(nearestMi)}` : `Nearest comparable ${fmtMi(nearestMi)}`);
  }

  if (!facts.length && !caution) return null;

  if (caution) {
    return (
      <p className={cn("flex flex-wrap items-baseline gap-x-2 text-xs", className)}>
        <span className="inline-flex items-center gap-1.5 font-medium text-[var(--negative-foreground)]">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[var(--negative)]/70" />
          Limited comparable data in this area
        </span>
        {facts.length ? (
          <span className="font-data text-muted-foreground">— {facts.join(" · ").toLowerCase()}</span>
        ) : null}
      </p>
    );
  }

  return (
    <p className={cn("font-data text-xs text-muted-foreground", className)}>
      {facts.join(" · ")}
    </p>
  );
}
