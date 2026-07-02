import { cn } from "@/lib/utils/cn";

export interface GeoPoint {
  lat: number;
  lng: number;
  kind: "subject" | "comp";
  label?: string;
}

export interface GeoScatterProps {
  points: GeoPoint[];
  /** Drawing height in px. Defaults to 220. */
  height?: number;
  className?: string;
}

/**
 * Tile-free geographic scatter: normalizes lat/lng into a padded box over a
 * faint blueprint grid (.bg-grid-soft). The subject is a larger emerald dot
 * with a halo ring; comps are small muted dots. Pure SVG, no map keys/tiles.
 */
export function GeoScatter({ points, height = 220, className }: GeoScatterProps) {
  const W = 100;
  const H = 100;
  const pad = 10;

  const wrap = (children: React.ReactNode) => (
    <div
      className={cn(
        "bg-grid-soft relative w-full overflow-hidden rounded-lg border border-border bg-muted",
        className,
      )}
      style={{ height }}
    >
      {children}
    </div>
  );

  if (!points || points.length === 0) {
    return wrap(
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        No locations
      </div>,
    );
  }

  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const latSpan = maxLat - minLat || 1;
  const lngSpan = maxLng - minLng || 1;

  // Project: lng → x, lat → y (north up, so invert lat). Centers a single point.
  const project = (p: GeoPoint): readonly [number, number] => {
    const x =
      points.length === 1
        ? W / 2
        : pad + ((p.lng - minLng) / lngSpan) * (W - pad * 2);
    const y =
      points.length === 1
        ? H / 2
        : pad + (1 - (p.lat - minLat) / latSpan) * (H - pad * 2);
    return [x, y];
  };

  // Draw comps first, subject(s) on top.
  const ordered = [...points].sort((a, b) =>
    a.kind === "subject" ? 1 : b.kind === "subject" ? -1 : 0,
  );

  return wrap(
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="100%"
      preserveAspectRatio="none"
      role="img"
      aria-label={`Map scatter of ${points.length} locations: ${
        points.filter((p) => p.kind === "subject").length
      } subject, ${points.filter((p) => p.kind === "comp").length} comparables`}
    >
      {ordered.map((p, i) => {
        const [x, y] = project(p);
        if (p.kind === "subject") {
          return (
            <g key={`s-${i}`}>
              <circle
                cx={x}
                cy={y}
                r={5.5}
                fill="var(--primary)"
                fillOpacity={0.18}
              />
              <circle
                cx={x}
                cy={y}
                r={3}
                fill="var(--primary)"
                stroke="var(--card)"
                strokeWidth={0.8}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        }
        return (
          // Comp dots must read as meaningful marks on white: slate-600 at full
          // opacity clears 3:1 (the old muted-foreground @0.55 washed to ~2:1).
          <circle
            key={`c-${i}`}
            cx={x}
            cy={y}
            r={2}
            fill="#475569"
            fillOpacity={0.9}
          />
        );
      })}
    </svg>,
  );
}
