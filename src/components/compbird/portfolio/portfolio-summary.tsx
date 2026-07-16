"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils/cn";
import { usd, usdCompact } from "@/lib/compbird/format";
import type { PortfolioItemDto as PortfolioItem } from "@/lib/compbird/portfolio";
import { portfolioTotals } from "./csv";

/**
 * Portfolio intelligence — the book read at a glance, above the per-property
 * table. Everything here is derived from `portfolioTotals(items)` + the items
 * themselves; it never invents a field the DTO doesn't carry, and it updates
 * live as items land (the studio re-renders it every poll beat).
 *
 * Three reads, top to bottom:
 *   HERO         total estimated value + summed low–high range;
 *   STAT ROW     properties / comped / needs-review / average / largest / smallest;
 *   CONFIDENCE   a segmented mix bar (high · standard · error) with a legend;
 *   DISTRIBUTION a sorted per-property value strip — bar length ∝ mid, tinted by
 *                confidence — so spread and outliers are scannable.
 *
 * Pure CSS/inline-style throughout (no chart lib, framer-free). Renders only
 * once at least one item is done (the studio gates on that); below three done
 * items the distribution strip steps aside for a plain worth line, so it never
 * shows a lonely single bar pretending to be a chart.
 */

/** A done item reduced to what the summary visualizes. */
interface DoneRow {
  id: string;
  label: string;
  mid: number;
  tier: "high" | "standard" | null;
}

interface SummaryModel {
  /** Done items with a finite mid, richest → poorest (distribution order). */
  done: DoneRow[];
  /** Mean mid across done items. */
  avg: number | null;
  largest: DoneRow | null;
  smallest: DoneRow | null;
  /** Confidence mix — counts across the whole run. */
  high: number;
  standard: number;
  /** status === "error" OR caution === true — the "needs review" set. */
  review: number;
  /** status === "error" only — the mix bar's negative segment. */
  errored: number;
}

/** Reduce the run to the summary model — one pass, no fabricated fields. */
function buildModel(items: PortfolioItem[]): SummaryModel {
  const done: DoneRow[] = [];
  let high = 0;
  let standard = 0;
  let review = 0;
  let errored = 0;
  let sum = 0;

  for (const it of items) {
    if (it.status === "error") {
      errored++;
      review++;
      continue;
    }
    if (it.caution) review++;
    if (it.status === "done" && it.mid != null && Number.isFinite(it.mid)) {
      done.push({
        id: it.id,
        label: it.label ?? it.resolvedAddress ?? it.inputAddress ?? "—",
        mid: it.mid,
        tier: it.confidenceTier,
      });
      sum += it.mid;
      if (it.confidenceTier === "high") high++;
      else standard++;
    }
  }

  done.sort((a, b) => b.mid - a.mid);
  return {
    done,
    avg: done.length ? sum / done.length : null,
    largest: done[0] ?? null,
    smallest: done.length ? done[done.length - 1] : null,
    high,
    standard,
    review,
    errored,
  };
}

/** Tier → the bar/segment fill it carries. */
function tierFill(tier: "high" | "standard" | null): string {
  return tier === "high" ? "var(--cb-ember)" : "var(--muted-foreground)";
}

/** One stat cell — cb-eyebrow label over a mono figure, the coverage idiom. */
function StatCell({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="cb-eyebrow text-muted-foreground">{label}</span>
      <span
        className={cn(
          "font-data text-lg font-semibold tracking-tight",
          accent ? "text-[var(--cb-ember-text)]" : "text-foreground",
        )}
      >
        {value}
      </span>
      {sub ? <span className="truncate text-xs text-muted-foreground">{sub}</span> : null}
    </div>
  );
}

export function PortfolioSummary({ items }: { items: PortfolioItem[] }) {
  const totals = portfolioTotals(items);
  const model = useMemo(() => buildModel(items), [items]);

  // The studio only mounts this once an item is done; guard anyway so a direct
  // mount (fixture) never divides by zero.
  if (totals.done === 0) return null;

  const { done, avg, largest, smallest, high, standard, errored } = model;
  const mixTotal = high + standard + errored;
  const seg = (n: number) => (mixTotal ? (n / mixTotal) * 100 : 0);

  // Distribution scale: bar length is position in the observed spread, not
  // distance from zero (a zero-based strip of six $400k homes reads flat). Base
  // just under the minimum so the shortest bar is still visibly a bar.
  const maxMid = done.length ? done[0].mid : 0;
  const minMid = done.length ? done[done.length - 1].mid : 0;
  const base = minMid * 0.92;
  const span = Math.max(maxMid - base, 1e-9);
  const barPct = (v: number) => Math.min(100, Math.max(6, ((v - base) / span) * 100));

  // The distribution strip earns its space only with real spread to show.
  const showDistribution = done.length >= 3;

  const legend = [
    high > 0 ? `${high} high` : null,
    standard > 0 ? `${standard} standard` : null,
    errored > 0 ? `${errored} error` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section
      aria-label="Portfolio summary"
      className="relative overflow-hidden rounded-2xl border border-border bg-card p-5 sm:p-7"
    >
      {/* ── Hero: total worth + summed range ─────────────────────────────── */}
      <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-1.5">
          <span className="cb-eyebrow text-muted-foreground">Total estimated value</span>
          <span className="font-data text-4xl font-semibold tracking-tight text-[var(--cb-ember-text)] sm:text-5xl">
            {usd(totals.mid)}
          </span>
          <span className="font-data text-xs text-muted-foreground">
            {totals.low != null && totals.high != null
              ? `${usd(totals.low)} – ${usd(totals.high)} range`
              : "range pending"}
          </span>
        </div>

        {/* ── Confidence mix bar + legend ────────────────────────────────── */}
        <div className="flex w-full max-w-xs flex-col gap-2 sm:w-64">
          <div className="flex items-baseline justify-between gap-2">
            <span className="cb-eyebrow text-muted-foreground">Confidence mix</span>
            <span className="font-data text-[11px] text-muted-foreground">{legend || "—"}</span>
          </div>
          <div
            className="flex h-2.5 w-full overflow-hidden rounded-full bg-secondary/70"
            role="img"
            aria-label={`Confidence mix: ${legend || "no results yet"}`}
          >
            {high > 0 ? (
              <span
                className="h-full bg-[var(--cb-ember)]"
                style={{ width: `${seg(high)}%` }}
                title={`${high} high confidence`}
              />
            ) : null}
            {standard > 0 ? (
              <span
                className="h-full bg-muted-foreground/45"
                style={{ width: `${seg(standard)}%` }}
                title={`${standard} standard`}
              />
            ) : null}
            {errored > 0 ? (
              <span
                className="h-full bg-[var(--negative)]/70"
                style={{ width: `${seg(errored)}%` }}
                title={`${errored} couldn't be comped`}
              />
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            {high > 0 ? <LegendDot className="bg-[var(--cb-ember)]" label={`${high} high`} /> : null}
            {standard > 0 ? (
              <LegendDot className="bg-muted-foreground/45" label={`${standard} standard`} />
            ) : null}
            {errored > 0 ? (
              <LegendDot className="bg-[var(--negative)]/70" label={`${errored} error`} />
            ) : null}
          </div>
        </div>
      </div>

      {/* ── Stat row ─────────────────────────────────────────────────────── */}
      <dl className="mt-6 grid grid-cols-2 gap-x-4 gap-y-5 border-t border-border pt-6 sm:grid-cols-3 lg:grid-cols-6">
        <StatCell label="Properties" value={totals.total} />
        <StatCell label="Comped" value={totals.done} />
        <StatCell
          label="Need review"
          value={model.review}
          accent={model.review > 0}
        />
        <StatCell label="Average" value={usdCompact(avg)} />
        <StatCell
          label="Largest"
          value={usdCompact(largest?.mid)}
          sub={largest?.label}
        />
        <StatCell
          label="Smallest"
          value={usdCompact(smallest?.mid)}
          sub={smallest?.label}
        />
      </dl>

      {/* ── Value distribution strip ─────────────────────────────────────── */}
      {showDistribution ? (
        <div className="mt-6 flex flex-col gap-2.5 border-t border-border pt-6">
          <div className="flex items-baseline justify-between gap-2">
            <span className="cb-eyebrow text-muted-foreground">Value distribution</span>
            <span className="text-xs text-muted-foreground">
              {done.length} comped, high → low
            </span>
          </div>
          <div
            className="flex items-end gap-1 sm:gap-1.5"
            role="img"
            aria-label={`Value distribution across ${done.length} comped properties, from ${usd(
              maxMid,
            )} down to ${usd(minMid)}`}
          >
            {done.map((r) => (
              <span
                key={r.id}
                title={`${r.label} — ${usd(r.mid)}`}
                aria-hidden
                className="min-w-0 flex-1 rounded-t-[2px]"
                style={{
                  height: `${barPct(r.mid) * 0.72}px`,
                  minHeight: "6px",
                  background: tierFill(r.tier),
                  opacity: r.tier === "high" ? 0.85 : 0.4,
                }}
              />
            ))}
          </div>
          <div className="flex items-center justify-between font-data text-[10px] text-muted-foreground">
            <span>{usdCompact(maxMid)}</span>
            <span>{usdCompact(minMid)}</span>
          </div>
        </div>
      ) : (
        <p className="mt-6 border-t border-border pt-6 text-xs leading-relaxed text-muted-foreground">
          The value spread graphs here once at least three properties have comped.
        </p>
      )}
    </section>
  );
}

/** Legend chip: a small tinted dot + its count label. */
function LegendDot({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", className)} />
      <span className="font-data">{label}</span>
    </span>
  );
}
