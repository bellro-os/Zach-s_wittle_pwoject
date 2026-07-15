"use client";

import { memo, useMemo } from "react";
import { usd, ppsf as fmtPpsf } from "@/lib/compbird/format";
import type { ProfileComp, Valuation } from "@/lib/compbird/types";

/**
 * Live analytics over THIS lookup's evidence — every mark derives from the
 * comps and method values the engine just returned (they recompute when the
 * user tunes the comp set). Three reads, one idiom: hand-rolled SVG, muted
 * axes, ember as the only accent, honest degradation when data is thin.
 *
 * Perf shape: the exported component is memo'd on (comps, valuation), and the
 * derived point arrays are useMemo'd on the same inputs — so chart geometry is
 * computed exactly once per data change, never on parent churn. The scale
 * math inside each chart body is deliberately NOT memoized further: those
 * components only render when their (memoized) points changed, at which point
 * the geometry must be recomputed anyway.
 */

const EMBER = "var(--cb-ember)";
const MUTED = "var(--muted-foreground)";
const LINE = "var(--border)";

function niceUsd(v: number): string {
  return v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M` : `$${Math.round(v / 1000)}k`;
}

/* ── derived data (memoized once in LiveAnalytics, shared by the charts) ───── */

type TimelinePt = { t: number; y: number; label: string; atypical: boolean };
type LocalityPt = { x: number; y: number; label: string; atypical: boolean };

function timelinePoints(comps: ProfileComp[]): TimelinePt[] {
  return comps
    .filter((c) => c.sold_price != null && c.close_date)
    .map((c) => ({
      t: new Date(c.close_date as string).getTime(),
      y: c.sold_price as number,
      label: `${c.address} — ${usd(c.sold_price)} · ${(c.close_date as string).slice(0, 7)}`,
      atypical: !!c.atypical,
    }))
    .filter((p) => Number.isFinite(p.t))
    .sort((a, b) => a.t - b.t);
}

function localityPoints(comps: ProfileComp[]): LocalityPt[] {
  return comps
    .filter((c) => c.ppsf != null && c.distance_mi != null && Number.isFinite(c.distance_mi))
    .map((c) => ({
      x: c.distance_mi as number,
      y: c.ppsf as number,
      label: `${c.address} — ${fmtPpsf(c.ppsf)}/sqft · ${(c.distance_mi as number).toFixed(2)} mi`,
      atypical: !!c.atypical,
    }));
}

/* ── 1. Sale prices over time: comp closings vs the estimate band ─────────── */

function Timeline({ pts, valuation }: { pts: TimelinePt[]; valuation: Valuation | null }) {
  if (pts.length < 3) return null;

  const mid = valuation?.mid ?? null;
  const lo = valuation?.low ?? null;
  const hi = valuation?.high ?? null;

  const W = 560, H = 170, padL = 46, padR = 10, padT = 12, padB = 22;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t || t0 + 1;
  const ys = pts.map((p) => p.y).concat(mid ? [mid] : []).concat(lo ? [lo] : []).concat(hi ? [hi] : []);
  const y0 = Math.min(...ys) * 0.96, y1 = Math.max(...ys) * 1.04;
  const X = (t: number) => padL + ((t - t0) / Math.max(t1 - t0, 1)) * (W - padL - padR);
  const Y = (v: number) => padT + (1 - (v - y0) / Math.max(y1 - y0, 1)) * (H - padT - padB);

  const months = (t1 - t0) / (30.44 * 24 * 3600 * 1000);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="cb-eyebrow text-muted-foreground">Sale prices over time</span>
        <span className="text-xs text-muted-foreground">
          {pts.length} closings · {Math.max(1, Math.round(months))} mo
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label={`Comparable sale prices over the last ${Math.round(months)} months against the estimate band`}>
        {/* estimate band + mid line */}
        {lo != null && hi != null ? (
          <rect x={padL} y={Y(hi)} width={W - padL - padR} height={Math.max(2, Y(lo) - Y(hi))}
                fill={EMBER} opacity="0.07" />
        ) : null}
        {mid != null ? (
          <>
            <line x1={padL} x2={W - padR} y1={Y(mid)} y2={Y(mid)}
                  stroke={EMBER} strokeWidth="1" strokeDasharray="4 3" opacity="0.7" />
            {/* label sits at the LEFT of the line (right edge holds the newest
                comp dot); a small tint plate keeps it legible over the band */}
            <rect x={padL + 3} y={Y(mid) - 16} width="106" height="15" rx="2"
                  fill="var(--card)" opacity="0.85" />
            <text x={padL + 6} y={Y(mid) - 4} textAnchor="start" fontSize="12"
                  fill={EMBER} className="font-data">estimate {niceUsd(mid)}</text>
          </>
        ) : null}
        {/* y axis ticks */}
        {[y0 + (y1 - y0) * 0.15, (y0 + y1) / 2, y1 - (y1 - y0) * 0.15].map((v, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={Y(v)} y2={Y(v)} stroke={LINE} strokeWidth="0.5" />
            <text x={padL - 5} y={Y(v) + 3} textAnchor="end" fontSize="12" fill={MUTED}
                  className="font-data">{niceUsd(v)}</text>
          </g>
        ))}
        {/* comp dots */}
        {pts.map((p, i) => (
          <circle key={i} cx={X(p.t)} cy={Y(p.y)} r="4.5"
                  fill={p.atypical ? "var(--negative)" : EMBER}
                  opacity={p.atypical ? 0.55 : 0.9}
                  stroke="var(--card)" strokeWidth="1.5">
            {/* Single text child: two adjacent expressions here SSR with a
                comment separator that can trip React hydration inside <title>. */}
            <title>{p.atypical ? `${p.label} · atypical` : p.label}</title>
          </circle>
        ))}
        {/* x labels: first + last month */}
        <text x={padL} y={H - 6} fontSize="12" fill={MUTED} className="font-data">
          {new Date(t0).toLocaleDateString("en-US", { month: "short", year: "2-digit" })}
        </text>
        <text x={W - padR} y={H - 6} textAnchor="end" fontSize="12" fill={MUTED} className="font-data">
          {new Date(t1).toLocaleDateString("en-US", { month: "short", year: "2-digit" })}
        </text>
      </svg>
    </div>
  );
}

/* ── 2. $/sqft vs distance: how local is the evidence ─────────────────────── */

function Locality({ pts, valuation }: { pts: LocalityPt[]; valuation: Valuation | null }) {
  if (pts.length < 3) return null;

  const ref = valuation?.comp_ppsf ?? null;
  const W = 270, H = 150, padL = 38, padR = 8, padT = 10, padB = 22;
  const x1 = Math.max(...pts.map((p) => p.x)) * 1.15 || 1;
  const ys = pts.map((p) => p.y).concat(ref ? [ref] : []);
  const y0 = Math.min(...ys) * 0.92, y1 = Math.max(...ys) * 1.08;
  const X = (v: number) => padL + (v / x1) * (W - padL - padR);
  const Y = (v: number) => padT + (1 - (v - y0) / Math.max(y1 - y0, 1)) * (H - padT - padB);

  return (
    <div className="flex flex-col gap-2">
      <span className="cb-eyebrow text-muted-foreground">$/sqft by distance</span>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label="Comparable $/sqft plotted against distance from the subject">
        {ref != null ? (
          <>
            <line x1={padL} x2={W - padR} y1={Y(ref)} y2={Y(ref)}
                  stroke={EMBER} strokeWidth="1" strokeDasharray="4 3" opacity="0.7" />
            <text x={W - padR} y={Y(ref) - 4} textAnchor="end" fontSize="9" fill={EMBER}
                  className="font-data">comp median</text>
          </>
        ) : null}
        {[0.25, 0.75].map((f, i) => (
          <line key={i} x1={X(x1 * f)} x2={X(x1 * f)} y1={padT} y2={H - padB}
                stroke={LINE} strokeWidth="0.5" />
        ))}
        {pts.map((p, i) => (
          <circle key={i} cx={X(p.x)} cy={Y(p.y)} r="4.5"
                  fill={p.atypical ? "var(--negative)" : EMBER}
                  opacity={p.atypical ? 0.55 : 0.9}
                  stroke="var(--card)" strokeWidth="1.5">
            <title>{p.label}</title>
          </circle>
        ))}
        <text x={padL} y={H - 6} fontSize="9" fill={MUTED} className="font-data">0 mi</text>
        <text x={W - padR} y={H - 6} textAnchor="end" fontSize="9" fill={MUTED}
              className="font-data">{x1.toFixed(1)} mi</text>
        <text x={padL - 5} y={Y(y1 - (y1 - y0) * 0.1) + 3} textAnchor="end" fontSize="9"
              fill={MUTED} className="font-data">{fmtPpsf(y1 - (y1 - y0) * 0.1)}</text>
        <text x={padL - 5} y={Y(y0 + (y1 - y0) * 0.1) + 3} textAnchor="end" fontSize="9"
              fill={MUTED} className="font-data">{fmtPpsf(y0 + (y1 - y0) * 0.1)}</text>
      </svg>
    </div>
  );
}

/* ── 3. Method convergence: the landing's flagship, live per lookup ────────── */

function Convergence({
  methods,
  mid,
  divergencePct,
}: {
  methods: { name: string; value: number }[];
  mid: number;
  divergencePct: number | null;
}) {
  if (methods.length < 2) return null;

  const vals = methods.map((m) => m.value).concat([mid]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = Math.max(hi - lo, 1) * 1.3;
  const floor = lo - (span - (hi - lo)) / 2;
  const P = (v: number) => 6 + ((v - floor) / span) * 88; // percent, padded

  return (
    <div className="flex flex-col gap-2">
      <span className="cb-eyebrow text-muted-foreground">Method convergence</span>
      {/* role="img" makes descendants presentational — so the consensus/spread
          caption lives OUTSIDE this container, where AT can still read it. */}
      <div className="flex flex-col gap-2.5 pt-4" role="img"
           aria-label={`${methods.length} valuation methods converging near ${usd(mid)}`}>
        {methods.map((m) => (
          <div key={m.name} className="relative">
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate text-[0.7rem] text-muted-foreground">{m.name}</span>
              <span className="font-data shrink-0 text-[0.7rem] font-medium text-foreground">
                {niceUsd(m.value)}
              </span>
            </div>
            <div className="relative mt-1 h-1.5 rounded-full bg-secondary/60">
              <span className="absolute -inset-y-0.5 w-px bg-[var(--cb-ember)]"
                    style={{ left: `${P(mid)}%` }} aria-hidden />
              <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-[var(--card)] bg-[var(--cb-ember)]"
                    style={{ left: `${P(m.value)}%` }} aria-hidden />
            </div>
          </div>
        ))}
      </div>
      <p className="text-[0.7rem] text-muted-foreground">
        consensus <span className="font-data text-foreground">{usd(mid)}</span>
        {divergencePct != null ? (
          <> · spread <span className="font-data text-foreground">{divergencePct}%</span></>
        ) : null}
      </p>
    </div>
  );
}

/* ── composition ──────────────────────────────────────────────────────────── */

/**
 * True when at least one chart clears its data floor — the same predicate
 * LiveAnalytics uses to decide whether to render anything at all. Callers
 * (report-view.tsx) use it to gate the section heading/divider so a "Live
 * analytics" heading never sits over nothing in thin-comp markets.
 */
export function hasAnalytics(comps: ProfileComp[], valuation: Valuation | null): boolean {
  return (
    timelinePoints(comps).length >= 3 ||
    localityPoints(comps).length >= 3 ||
    ((valuation?.methods ?? []).filter((m) => m.value != null && m.value > 0).length >= 2 &&
      valuation?.mid != null)
  );
}

function LiveAnalyticsImpl({ comps, valuation }: { comps: ProfileComp[]; valuation: Valuation | null }) {
  // Geometry inputs, computed once per data change (the memo() boundary already
  // blocks parent churn; these guard against the comps→points mapping re-running
  // when only the valuation changed, and vice versa).
  const timelinePts = useMemo(() => timelinePoints(comps), [comps]);
  const localityPts = useMemo(() => localityPoints(comps), [comps]);
  const methods = useMemo(
    () =>
      (valuation?.methods ?? [])
        .filter((m) => m.value != null && m.value > 0)
        .map((m) => ({ name: m.name, value: m.value as number })),
    [valuation],
  );

  const mid = valuation?.mid ?? null;
  const showTimeline = timelinePts.length >= 3;
  const showLocality = localityPts.length >= 3;
  const showConvergence = methods.length >= 2 && mid != null;

  // Honest degradation: render nothing at all if no chart has enough data.
  // (Checked on the DATA — a rendered element is always truthy even when the
  // child returns null, which used to leave an empty panel shell behind.)
  if (!showTimeline && !showLocality && !showConvergence) return null;

  return (
    <div className="flex flex-col gap-7">
      {showTimeline ? <Timeline pts={timelinePts} valuation={valuation} /> : null}
      {showLocality || showConvergence ? (
        <div className="grid gap-7 sm:grid-cols-2">
          {showLocality ? <Locality pts={localityPts} valuation={valuation} /> : null}
          {showConvergence ? (
            <Convergence
              methods={methods}
              mid={mid as number}
              divergencePct={valuation?.divergence_pct ?? null}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Memoized: re-renders only when the tuned comp set / valuation change. */
export const LiveAnalytics = memo(LiveAnalyticsImpl);
