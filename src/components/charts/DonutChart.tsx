import { cn } from "@/lib/utils/cn";

export interface DonutSegment {
  /** Segment label (used in the composed aria-label). */
  name: string;
  /** Numeric weight of the segment. Non-positive segments are dropped. */
  value: number;
  /** Any CSS color — flows through fill, so CSS vars are fine. */
  color: string;
}

export interface DonutChartProps {
  segments: DonutSegment[];
  /** Diameter in px. Defaults to 160 (matches the old recharts donut box). */
  size?: number;
  /** Inner hole radius in px. Defaults to 42. */
  innerRadius?: number;
  /** Outer arc radius in px. Defaults to 68. */
  outerRadius?: number;
  /** Gap between segments, in degrees. Defaults to 2. */
  padAngle?: number;
  /** Accessible label override. Defaults to a composed summary. */
  ariaLabel?: string;
  className?: string;
}

/** Polar → cartesian, 12 o'clock = 0deg, sweeping clockwise. */
function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

/** SVG path for a single donut segment (annular sector) between two angles. */
function arcPath(
  cx: number,
  cy: number,
  rInner: number,
  rOuter: number,
  startDeg: number,
  endDeg: number
): string {
  const largeArc = endDeg - startDeg > 180 ? 1 : 0;
  const [ox1, oy1] = polar(cx, cy, rOuter, startDeg);
  const [ox2, oy2] = polar(cx, cy, rOuter, endDeg);
  const [ix2, iy2] = polar(cx, cy, rInner, endDeg);
  const [ix1, iy1] = polar(cx, cy, rInner, startDeg);
  return [
    `M ${ox1.toFixed(3)} ${oy1.toFixed(3)}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${ox2.toFixed(3)} ${oy2.toFixed(3)}`,
    `L ${ix2.toFixed(3)} ${iy2.toFixed(3)}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 0 ${ix1.toFixed(3)} ${iy1.toFixed(3)}`,
    "Z",
  ].join(" ");
}

/**
 * Dependency-free donut/pie chart. A drop-in replacement for the small recharts
 * donut: same geometry (inner/outer radius, padding angle) and dark-safe colors
 * via fill (CSS vars welcome). Pure presentational SVG — no hooks, no client.
 *
 * A single full-circle segment is drawn as a ring (two concentric circles) so it
 * doesn't degenerate into an invisible zero-length arc.
 */
export function DonutChart({
  segments,
  size = 160,
  innerRadius = 42,
  outerRadius = 68,
  padAngle = 2,
  ariaLabel,
  className,
}: DonutChartProps) {
  const data = segments.filter((s) => s.value > 0);
  const total = data.reduce((sum, s) => sum + s.value, 0);
  const cx = size / 2;
  const cy = size / 2;

  const label =
    ariaLabel ??
    `Donut chart of ${total}: ${data
      .map((s) => `${s.name} ${s.value}`)
      .join(", ")}`;

  if (data.length === 0 || total === 0) {
    return (
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width="100%"
        height="100%"
        role="img"
        aria-label="Donut chart with no data"
        className={cn(className)}
      >
        <circle
          cx={cx}
          cy={cy}
          r={(innerRadius + outerRadius) / 2}
          fill="none"
          stroke="var(--border)"
          strokeWidth={outerRadius - innerRadius}
        />
      </svg>
    );
  }

  // A single full segment renders as a clean ring (avoids a 360deg arc that
  // collapses to nothing because start and end points coincide).
  if (data.length === 1) {
    const only = data[0];
    return (
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width="100%"
        height="100%"
        role="img"
        aria-label={label}
        className={cn(className)}
      >
        <circle
          cx={cx}
          cy={cy}
          r={(innerRadius + outerRadius) / 2}
          fill="none"
          stroke={only.color}
          strokeWidth={outerRadius - innerRadius}
        />
      </svg>
    );
  }

  // Padding eats into each segment's sweep; clamp so tiny slices don't invert.
  const totalPad = padAngle * data.length;
  const usableSweep = Math.max(0, 360 - totalPad);

  // Precompute each slice's [start, end] angles with an immutable fold (no
  // render-time variable reassignment): the first slice starts half a pad-gap
  // in, and every later slice begins a full pad-gap after the previous end.
  const arcs = data.reduce<Array<{ seg: DonutSegment; start: number; end: number }>>(
    (acc, seg) => {
      const start = acc.length === 0 ? padAngle / 2 : acc[acc.length - 1].end + padAngle;
      const sweep = (seg.value / total) * usableSweep;
      return [...acc, { seg, start, end: start + sweep }];
    },
    []
  );

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      width="100%"
      height="100%"
      role="img"
      aria-label={label}
      className={cn(className)}
    >
      {arcs.map(({ seg, start, end }, i) => (
        <path
          key={`${seg.name}-${i}`}
          d={arcPath(cx, cy, innerRadius, outerRadius, start, end)}
          fill={seg.color}
        />
      ))}
    </svg>
  );
}
