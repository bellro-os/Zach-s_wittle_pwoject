import { cn } from "@/lib/utils/cn";

export interface SparklineProps {
  /** Series of values, oldest → newest. */
  data: number[];
  /** Stroke/dot/fill color. Any CSS color; defaults to the emerald accent. */
  color?: string;
  /** Drawing height in px (the SVG scales to the container width). */
  height?: number;
  /** Render a low-opacity flat area fill beneath the line. */
  fill?: boolean;
  /** Render the end-of-series dot. Defaults to true. */
  endDot?: boolean;
  className?: string;
}

/**
 * Dependency-free sparkline: a smooth (Catmull-Rom → cubic-Bézier) polyline
 * with an optional end dot and a flat low-opacity area fill (no gradients).
 * Dark-safe — color defaults to var(--primary). Pure presentational SVG.
 */
export function Sparkline({
  data,
  color = "var(--primary)",
  height = 40,
  fill = false,
  endDot = true,
  className,
}: SparklineProps) {
  const W = 100;
  const H = height;
  const pad = 3;

  if (!data || data.length === 0) {
    return (
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        preserveAspectRatio="none"
        className={cn("block", className)}
        role="img"
        aria-label="No data"
      />
    );
  }

  const n = data.length;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;

  // Single point → a centered dot.
  const points = data.map((v, i) => {
    const x = n === 1 ? W / 2 : pad + (i / (n - 1)) * (W - pad * 2);
    const y = pad + (1 - (v - min) / span) * (H - pad * 2);
    return [x, y] as const;
  });

  const linePath = smoothPath(points);
  const last = points[points.length - 1];
  const first = points[0];
  const areaPath = `${linePath} L ${last[0].toFixed(2)} ${H - pad} L ${first[0].toFixed(
    2,
  )} ${H - pad} Z`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      preserveAspectRatio="none"
      className={cn("block overflow-visible", className)}
      role="img"
      aria-label={`Trend sparkline, ${n} points, latest ${round(data[n - 1])}`}
    >
      {fill && n > 1 ? (
        <path d={areaPath} fill={color} fillOpacity={0.12} stroke="none" />
      ) : null}
      {n > 1 ? (
        <path
          d={linePath}
          fill="none"
          stroke={color}
          strokeWidth={1.75}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
      {endDot ? (
        <circle
          cx={last[0]}
          cy={last[1]}
          r={2.25}
          fill={color}
          stroke="var(--card)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
    </svg>
  );
}

/** Catmull-Rom → cubic Bézier smoothing for a clean, low-tension curve. */
function smoothPath(pts: ReadonlyArray<readonly [number, number]>): string {
  if (pts.length === 0) return "";
  if (pts.length === 1) return `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  if (pts.length === 2) {
    return `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)} L ${pts[1][0].toFixed(
      2,
    )} ${pts[1][1].toFixed(2)}`;
  }

  let d = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i === 0 ? 0 : i - 1];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2 < pts.length ? i + 2 : pts.length - 1];

    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;

    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(
      2,
    )}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return d;
}

function round(v: number): number {
  return Math.round(v);
}
