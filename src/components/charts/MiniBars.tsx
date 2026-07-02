import { cn } from "@/lib/utils/cn";

export interface MiniBarItem {
  label: string;
  value: number;
  /** Highlight this bar in emerald (e.g. the subject property). */
  highlight?: boolean;
}

export interface MiniBarsProps {
  items: MiniBarItem[];
  /** Total drawing height in px. Defaults to 120. */
  height?: number;
  /** Format the value shown above each bar (e.g. "$/sqft"). */
  formatValue?: (value: number) => string;
  /** Show the value caption above each bar. Defaults to true. */
  showValues?: boolean;
  className?: string;
}

/**
 * Compact vertical bar chart (e.g. comparable $/sqft). The highlighted bar is
 * emerald; the rest are muted. Labels sit beneath, values above. Pure SVG +
 * flex layout, dark-safe.
 */
export function MiniBars({
  items,
  height = 120,
  formatValue = (v) => Math.round(v).toLocaleString("en-US"),
  showValues = true,
  className,
}: MiniBarsProps) {
  if (!items || items.length === 0) {
    return <div className={cn("h-0", className)} aria-hidden />;
  }

  const max = Math.max(...items.map((i) => i.value), 0) || 1;
  const valueRow = showValues ? 16 : 0;
  const labelRow = 18;
  const barArea = Math.max(8, height - valueRow - labelRow);

  return (
    <div
      className={cn("flex w-full items-end gap-2", className)}
      role="img"
      aria-label={`Bar chart: ${items
        .map((i) => `${i.label} ${formatValue(i.value)}`)
        .join(", ")}`}
      style={{ height }}
    >
      {items.map((it, idx) => {
        const h = Math.max(2, (it.value / max) * barArea);
        // Comparison bars must stay legible on white: slate-600 at 0.6 alpha
        // clears the 3:1 non-text floor (the old muted-foreground @0.32 washed
        // out to ~2:1). Highlighted bar keeps the solid emerald accent.
        const tone = it.highlight ? "var(--primary)" : "#475569";
        const op = it.highlight ? 1 : 0.6;
        return (
          <div
            key={`${it.label}-${idx}`}
            className="flex min-w-0 flex-1 flex-col items-center justify-end"
            style={{ height }}
          >
            {showValues ? (
              <span
                className="tabular-nums mb-1 truncate text-[10px] font-medium leading-none"
                style={{
                  height: valueRow,
                  color: it.highlight
                    ? "var(--positive-foreground)"
                    : "var(--muted-foreground)",
                }}
              >
                {formatValue(it.value)}
              </span>
            ) : null}
            <div
              className="w-full overflow-hidden rounded-t-[3px]"
              style={{ height: barArea, display: "flex", alignItems: "flex-end" }}
            >
              <div
                className="w-full rounded-t-[3px]"
                style={{ height: h, background: tone, opacity: op }}
              />
            </div>
            <span
              className="mt-1 w-full truncate text-center text-[10px] leading-tight text-muted-foreground"
              style={{ height: labelRow }}
              title={it.label}
            >
              {it.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
