import { memo } from "react";
import { ppsf } from "@/lib/compbird/format";
import type { ProfileComp } from "@/lib/compbird/types";

/**
 * $/sqft across the comp set, ascending — the spread the valuation reasons over.
 * Hand-rolled horizontal bars (pure CSS, no chart lib): each bar's length is
 * proportional to its value above a BASELINE just under the set's minimum
 * (min − 5%), so the spread reads as real differences — zero-based bars all
 * rendered near-identical and looked like an unloaded skeleton. A dashed
 * vertical rule marks the median (mono-labeled); bars carry the brand blue at
 * low opacity with the median bar tinted stronger, and each row's title
 * tooltip names the full address + $/sqft.
 */

function shortLabel(address: string): string {
  // First token (street number) keeps the axis labels compact and unambiguous.
  return address.split(/\s+/)[0] ?? address.slice(0, 6);
}

function PpsfBarsImpl({ comps }: { comps: ProfileComp[] }) {
  const rows = comps
    .filter((c) => c.ppsf != null && Number.isFinite(c.ppsf))
    .map((c) => ({ label: shortLabel(c.address), address: c.address, value: c.ppsf as number }))
    .sort((a, b) => a.value - b.value);

  if (rows.length < 2) return null;

  // Median value (lower-middle on even counts) — the rule + the stronger bar.
  const medianIdx = Math.floor((rows.length - 1) / 2);
  const median = rows[medianIdx].value;

  // Length encodes position in the observed spread, not distance from zero.
  // Scaled to 90% so the longest bar always leaves room for its value label.
  const min = rows[0].value;
  const max = rows[rows.length - 1].value;
  const base = min * 0.95;
  const span = Math.max(max - base, 1e-9);
  const pct = (v: number) => Math.min(90, Math.max(2, ((v - base) / span) * 90));

  const medianPct = pct(median);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="cb-eyebrow text-muted-foreground">$/sqft by comp</span>
        <span className="text-xs text-muted-foreground">
          {rows.length} comps, ascending
        </span>
      </div>

      <div
        className="flex gap-3"
        role="img"
        aria-label={`Comparable $/sqft, ascending: ${rows
          .map((r) => `${r.label} ${ppsf(r.value)}`)
          .join(", ")} — median ${ppsf(median)}`}
      >
        {/* street-number labels, row-aligned with the bars beside them */}
        <div className="flex w-12 shrink-0 flex-col gap-1.5 pt-5">
          {rows.map((r, i) => (
            <span
              key={`${r.address}-${i}`}
              className="flex h-5 items-center justify-end truncate font-data text-[10px] text-muted-foreground"
            >
              {r.label}
            </span>
          ))}
        </div>

        {/* bars + the median rule, sharing one coordinate space */}
        <div className="relative min-w-0 flex-1">
          <span
            aria-hidden
            className="absolute bottom-0 top-5 w-px border-l border-dashed border-[var(--cb-ember)]/50"
            style={{ left: `${medianPct}%` }}
          />
          <span
            aria-hidden
            className="absolute top-0 whitespace-nowrap font-data text-[10px] leading-none text-[var(--cb-ember-text)]"
            style={{
              left: `${medianPct}%`,
              transform:
                medianPct > 78 ? "translateX(-100%)" : medianPct < 12 ? "none" : "translateX(-50%)",
            }}
          >
            median {ppsf(median)}
          </span>
          <div className="flex flex-col gap-1.5 pt-5">
            {rows.map((r, i) => (
              <div
                key={`${r.address}-${i}`}
                className="flex h-5 items-center"
                title={`${r.address} — ${ppsf(r.value)}/sqft`}
              >
                <span
                  className="h-3.5 rounded-r-sm rounded-l-[2px]"
                  style={{
                    width: `${pct(r.value)}%`,
                    background: "var(--cb-ember)",
                    opacity: i === medianIdx ? 0.75 : 0.3,
                  }}
                />
                <span className="ml-2 shrink-0 font-data text-[10px] text-muted-foreground">
                  {ppsf(r.value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Memoized: re-renders only when the comp set itself changes. */
export const PpsfBars = memo(PpsfBarsImpl);
