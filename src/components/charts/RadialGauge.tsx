import { cn } from "@/lib/utils/cn";

export interface RadialGaugeProps {
  /** Completion / readiness, 0–100 (clamped). */
  value: number;
  /** Caption rendered under the centered figure. */
  label?: string;
  /** Diameter in px. Defaults to 96. */
  size?: number;
  /** Arc color. Defaults to the emerald accent. */
  color?: string;
  /** Stroke thickness in px. Defaults to ~10% of size. */
  thickness?: number;
  /** Show the big "NN%" figure in the center. Defaults to true. */
  showValue?: boolean;
  className?: string;
}

/**
 * SVG ring gauge: an emerald completion arc on a muted track, with a centered
 * percentage and optional caption. Pure presentational SVG, dark-safe.
 */
export function RadialGauge({
  value,
  label,
  size = 96,
  color = "var(--primary)",
  thickness,
  showValue = true,
  className,
}: RadialGaugeProps) {
  const v = Math.max(0, Math.min(100, value));
  const stroke = thickness ?? Math.max(6, Math.round(size * 0.1));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const cx = size / 2;
  const cy = size / 2;
  const dash = (v / 100) * c;
  const display = Math.round(v);

  return (
    <div
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        role="img"
        aria-label={`${display} percent${label ? ` ${label}` : ""}`}
      >
        {/* track */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--border)"
          strokeWidth={stroke}
        />
        {/* progress arc — starts at 12 o'clock, sweeps clockwise */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash.toFixed(2)} ${(c - dash).toFixed(2)}`}
          strokeDashoffset={c / 4}
          transform={`scale(1,-1) translate(0 ${-size})`}
        />
      </svg>
      {showValue || label ? (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center leading-none">
          {showValue ? (
            <span
              className="tabular-nums font-semibold text-foreground"
              style={{ fontSize: Math.round(size * 0.26) }}
            >
              {display}
              <span
                className="text-muted-foreground"
                style={{ fontSize: Math.round(size * 0.14) }}
              >
                %
              </span>
            </span>
          ) : null}
          {label ? (
            <span
              className="mt-1 max-w-[80%] truncate text-muted-foreground"
              style={{ fontSize: Math.max(9, Math.round(size * 0.11)) }}
            >
              {label}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
