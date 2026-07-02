import { cn } from "@/lib/utils/cn";
import type { ProfileResult } from "@/lib/compbird/types";

/**
 * compbird's signature visual language — a tile-free "aerial" map. Server-safe
 * SVG + HTML; motion is pure CSS (keyframes in compbird.css), gated by
 * prefers-reduced-motion. The triangulation sightlines from subject → comps are
 * the literal picture of "extreme accuracy": value located by cross-reference.
 */

export interface AerialPoint {
  lat: number;
  lng: number;
  kind: "subject" | "comp";
  label?: string;
  atypical?: boolean;
}

/** Build aerial points from a profile (subject facts + comps with coordinates). */
export function pointsFromProfile(profile: ProfileResult): AerialPoint[] {
  const pts: AerialPoint[] = [];
  const f = profile.facts;
  if (f?.lat != null && f?.lng != null) {
    pts.push({ lat: f.lat, lng: f.lng, kind: "subject", label: "Subject" });
  }
  for (const c of profile.comps ?? []) {
    if (c.lat != null && c.lng != null) {
      pts.push({ lat: c.lat, lng: c.lng, kind: "comp", label: c.address, atypical: c.atypical });
    }
  }
  return pts;
}

function project(points: AerialPoint[]) {
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const latSpan = maxLat - minLat || 1;
  const lngSpan = maxLng - minLng || 1;
  const pad = 14;
  return points.map((p) => {
    const x = points.length === 1 ? 50 : pad + ((p.lng - minLng) / lngSpan) * (100 - pad * 2);
    const y = points.length === 1 ? 50 : pad + (1 - (p.lat - minLat) / latSpan) * (100 - pad * 2);
    return { ...p, x, y };
  });
}

export function AerialMap({
  points,
  height = 340,
  className,
  animate = true,
  showSightlines = true,
}: {
  points: AerialPoint[];
  height?: number;
  className?: string;
  animate?: boolean;
  showSightlines?: boolean;
}) {
  const projected = points && points.length ? project(points) : [];
  const subject = projected.find((p) => p.kind === "subject") ?? projected[0];
  const comps = projected.filter((p) => p.kind === "comp");

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border border-border bg-card",
        className,
      )}
      style={{ height }}
    >
      {/* warm parcel grid (kept square via CSS background) */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(to right, var(--cb-line) 1px, transparent 1px), linear-gradient(to bottom, var(--cb-line) 1px, transparent 1px)",
          backgroundSize: "34px 34px",
          maskImage: "radial-gradient(ellipse 90% 90% at 50% 45%, black 55%, transparent 92%)",
          WebkitMaskImage: "radial-gradient(ellipse 90% 90% at 50% 45%, black 55%, transparent 92%)",
        }}
      />

      {/* contours + sightlines (stretch with the box — reads as terrain) */}
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
        aria-hidden
      >
        {subject ? (
          <g>
            {[14, 25, 37, 50].map((r, i) => (
              <ellipse
                key={r}
                cx={subject.x}
                cy={subject.y}
                rx={r}
                ry={r * 0.82}
                fill="none"
                stroke="var(--cb-line-strong)"
                strokeWidth={0.25}
                opacity={0.5 - i * 0.08}
              />
            ))}
          </g>
        ) : null}
        {showSightlines && subject
          ? comps.map((c, i) => (
              <line
                key={`l-${i}`}
                x1={subject.x}
                y1={subject.y}
                x2={c.x}
                y2={c.y}
                stroke="var(--cb-ember)"
                strokeWidth={0.3}
                strokeDasharray="1.4 1.4"
                opacity={0.35}
              />
            ))
          : null}
      </svg>

      {/* sweeping scanline */}
      {animate ? (
        <div
          aria-hidden
          data-cb-anim
          className="absolute inset-x-0 top-0 h-16"
          style={{
            background:
              "linear-gradient(to bottom, transparent, var(--cb-tint) 60%, transparent)",
            animation: "cb-scan 6.5s ease-in-out infinite",
          }}
        />
      ) : null}

      {/* comp pins */}
      {comps.map((c, i) => (
        <span
          key={`c-${i}`}
          data-cb-anim={animate ? "" : undefined}
          className="absolute -translate-x-1/2 -translate-y-1/2"
          style={{
            left: `${c.x}%`,
            top: `${c.y}%`,
            animation: animate ? "cb-pin-pop 0.5s both" : undefined,
            animationDelay: animate ? `${0.4 + i * 0.12}s` : undefined,
          }}
          title={c.label}
        >
          <span
            className={cn(
              "block h-2.5 w-2.5 rounded-full border",
              c.atypical
                ? "border-[var(--negative)] bg-[var(--negative)]/30"
                : "border-foreground/40 bg-foreground/70",
            )}
          />
        </span>
      ))}

      {/* subject pin + pulse */}
      {subject ? (
        <span
          className="absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${subject.x}%`, top: `${subject.y}%` }}
        >
          {animate ? (
            <span
              aria-hidden
              data-cb-anim
              className="absolute left-1/2 top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--cb-ember)]"
              style={{ animation: "cb-pulse 2.4s ease-out infinite" }}
            />
          ) : null}
          <span className="relative block h-3.5 w-3.5 rounded-full border-2 border-[var(--background)] bg-[var(--cb-ember)] shadow-[0_0_0_3px_var(--cb-tint)]" />
        </span>
      ) : null}
    </div>
  );
}

/** Decorative contour field for section backgrounds (purely ornamental). */
export function ContourField({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 600 400"
      preserveAspectRatio="xMidYMid slice"
      className={cn("pointer-events-none absolute inset-0 h-full w-full", className)}
      aria-hidden
    >
      {Array.from({ length: 7 }).map((_, i) => {
        const o = i * 26;
        return (
          <path
            key={i}
            d={`M-20 ${120 + o} C 120 ${60 + o}, 240 ${180 + o}, 360 ${120 + o} S 560 ${60 + o}, 640 ${130 + o}`}
            fill="none"
            stroke="var(--cb-line)"
            strokeWidth={1}
          />
        );
      })}
    </svg>
  );
}
