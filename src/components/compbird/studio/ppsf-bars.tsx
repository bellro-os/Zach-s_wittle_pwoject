import { memo } from "react";
import { MiniBars, type MiniBarItem } from "@/components/charts";
import { ppsf } from "@/lib/compbird/format";
import type { ProfileComp } from "@/lib/compbird/types";

/**
 * $/sqft across the comp set, ascending — the spread the valuation reasons over.
 * Bars render neutral (no single-bar highlight) to keep ember as the sole accent;
 * the median is called out in the caption instead. Short addresses become the
 * axis labels.
 */

function shortLabel(address: string): string {
  // First token (street number) keeps the axis compact and unambiguous.
  return address.split(/\s+/)[0] ?? address.slice(0, 6);
}

function PpsfBarsImpl({ comps }: { comps: ProfileComp[] }) {
  const rows = comps
    .filter((c) => c.ppsf != null && Number.isFinite(c.ppsf))
    .map((c) => ({ label: shortLabel(c.address), value: c.ppsf as number }))
    .sort((a, b) => a.value - b.value);

  if (rows.length < 2) return null;

  // Median value (lower-middle on even counts) — called out in the caption only,
  // no per-bar highlight so all bars stay neutral.
  const medianIdx = Math.floor((rows.length - 1) / 2);
  const items: MiniBarItem[] = rows.map((r) => ({ ...r }));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="cb-eyebrow text-muted-foreground">$/sqft by comp</span>
        <span className="text-xs text-muted-foreground">
          median <span className="font-data text-foreground">{ppsf(rows[medianIdx].value)}</span>
        </span>
      </div>
      <MiniBars items={items} height={132} formatValue={(v) => ppsf(v)} />
    </div>
  );
}

/** Memoized: re-renders only when the comp set itself changes. */
export const PpsfBars = memo(PpsfBarsImpl);
