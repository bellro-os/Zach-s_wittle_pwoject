import { cn } from "@/lib/utils/cn";

export interface TrendBadgeProps {
  /** Signed percentage change. Positive → emerald up, negative → rose down. */
  pct: number;
  /** Override the rounding precision for the displayed number. Defaults to 1. */
  decimals?: number;
  /** Treat zero as neutral (muted) rather than positive. Defaults to true. */
  neutralZero?: boolean;
  className?: string;
}

/**
 * Small up/down delta chip with a triangle glyph. Emerald for gains, rose for
 * losses, muted for flat. Dark-safe via the positive/negative semantic tokens.
 */
export function TrendBadge({
  pct,
  decimals = 1,
  neutralZero = true,
  className,
}: TrendBadgeProps) {
  const isZero = Math.abs(pct) < Math.pow(10, -decimals) / 2;
  const neutral = neutralZero && isZero;
  const up = pct > 0;

  const tone = neutral
    ? {
        color: "var(--muted-foreground)",
        bg: "color-mix(in srgb, var(--muted-foreground) 14%, transparent)",
      }
    : up
      ? { color: "var(--positive)", bg: "var(--positive-tint)" }
      : { color: "var(--negative)", bg: "var(--negative-tint)" };

  const magnitude = Math.abs(pct).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  const sign = neutral ? "" : up ? "+" : "−";

  return (
    <span
      className={cn(
        "tabular-nums inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold leading-none",
        className,
      )}
      style={{ color: tone.color, backgroundColor: tone.bg }}
    >
      {!neutral ? (
        <svg
          viewBox="0 0 8 8"
          width="8"
          height="8"
          aria-hidden
          className={up ? "" : "rotate-180"}
        >
          <path d="M4 1 7 6.5H1Z" fill="currentColor" />
        </svg>
      ) : (
        <svg viewBox="0 0 8 8" width="8" height="8" aria-hidden>
          <rect x="1" y="3.25" width="6" height="1.5" rx="0.75" fill="currentColor" />
        </svg>
      )}
      <span>
        {sign}
        {magnitude}%
      </span>
    </span>
  );
}
