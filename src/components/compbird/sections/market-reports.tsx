"use client";

import { useEffect, useState } from "react";
import { SectionShell, Eyebrow, Pill } from "@/components/compbird/ui";
import { Reveal, SpotlightCard } from "@/components/compbird/motion";
import { Sparkline, TrendBadge } from "@/components/charts";
import { SAMPLE_MARKETS } from "@/lib/compbird/sample";
import { fetchMarkets } from "@/lib/compbird/api";
import type { NeighborhoodMarket } from "@/lib/compbird/types";
import { usd, ppsf, num, num1, pctDelta } from "@/lib/compbird/format";

/**
 * Neighborhood market reports — a tinted band on the paper page (the landing's
 * one true-dark slab lives in Coverage; rhythm rule in compbird.css).
 * Each card reads like a desk's tear-sheet: median, momentum, a 12-month
 * trend line, then the supply/velocity figures that explain the headline.
 *
 * Paints the bundled sample instantly (no flash, works with JS disabled paint),
 * then asks /api/compbird/markets for the live aggregates and swaps them in when
 * a non-empty array comes back. On an empty result or any error it keeps the
 * sample — and the header copy reflects which source is on screen, so the
 * "live market intelligence" claim is only made when it's actually true.
 */
export function MarketReports() {
  const [markets, setMarkets] = useState<NeighborhoodMarket[]>(SAMPLE_MARKETS);
  const [live, setLive] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchMarkets(ctrl.signal)
      .then((rows) => {
        if (Array.isArray(rows) && rows.length > 0) {
          setMarkets(rows);
          setLive(true);
        }
      })
      .catch(() => {
        /* keep the sample — the landing must never break on a cold engine */
      });
    return () => ctrl.abort();
  }, []);

  return (
    <SectionShell id="markets" width="wide" className="py-24 sm:py-32">
      <div className="relative overflow-hidden rounded-3xl border border-border bg-card px-5 py-20 sm:px-12 sm:py-24">
        {/* faint ember band wash — the light-system surface for accent bands */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[var(--cb-tint-band)]"
        />
        {/* ember bleed, top-left — keeps the slab from going flat */}
        <div
          aria-hidden
          className="cb-glow-ring pointer-events-none absolute -left-32 -top-40 h-[28rem] w-[28rem] opacity-50"
        />

        <div className="relative">
          {/* ── header ── */}
          <div className="max-w-2xl">
            <Reveal>
              <span className="inline-flex flex-wrap items-center gap-3">
                <Eyebrow>Neighborhood market reports</Eyebrow>
                {/* Live/sample state lives HERE as a stable badge — the heading
                    below never swaps copy mid-scroll. */}
                <Pill tone={live ? "ember" : "neutral"}>
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${live ? "bg-[var(--cb-ember)]" : "bg-muted-foreground"}`}
                    aria-hidden
                  />
                  {live ? "Live data" : "Sample data"}
                </Pill>
              </span>
            </Reveal>
            <Reveal delay={0.05}>
              <h2 className="font-display mt-6 text-4xl font-bold tracking-tight text-foreground text-balance sm:text-5xl">
                Read any neighborhood like a local.
              </h2>
            </Reveal>
            <Reveal delay={0.12}>
              <p className="mt-6 text-lg leading-relaxed text-muted-foreground text-balance">
                {live
                  ? "Median price, momentum, supply, and velocity for the New River Valley's busiest neighborhoods — aggregated from the same closed-sale records that price a report, refreshed as the feed updates."
                  : "Median, momentum, supply, and velocity for the streets that set price across the New River Valley — a representative read while the live feed loads."}
              </p>
            </Reveal>
          </div>

          {/* ── cards ── */}
          <ul className="mt-14 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {markets.map((m, i) => (
              <li key={m.name} className="h-full">
                <Reveal delay={0.06 * i} className="h-full">
                  <MarketCard market={m} />
                </Reveal>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </SectionShell>
  );
}

function MarketCard({ market: m }: { market: NeighborhoodMarket }) {
  const up = m.ppsfTrendPct >= 0;

  return (
    <SpotlightCard className="flex h-full flex-col p-6">
      {/* name + area + momentum */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-display truncate text-lg font-semibold tracking-tight text-foreground">
            {m.name}
          </h3>
          <p className="mt-0.5 truncate text-sm text-muted-foreground">{m.area}</p>
        </div>
        <TrendBadge pct={m.ppsfTrendPct} className="mt-0.5 shrink-0" />
      </div>

      {/* headline median */}
      <div className="mt-6">
        <span className="cb-eyebrow text-muted-foreground">Median price</span>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="font-data text-3xl font-semibold tracking-tight text-foreground">
            {usd(m.medianPrice)}
          </span>
        </div>
        <p className="mt-1.5 font-data text-xs text-muted-foreground">
          {ppsf(m.ppsf)}/sqft · {pctDelta(m.ppsfTrendPct)} YoY
        </p>
      </div>

      {/* 12-month trend */}
      <div className="mt-5">
        <Sparkline
          data={m.trend}
          fill
          color={up ? "var(--positive)" : "var(--negative)"}
          height={44}
        />
        <div className="mt-2 flex items-center justify-between text-[0.7rem] text-muted-foreground">
          <span>12-mo median</span>
          <Pill tone={up ? "positive" : "negative"} className="font-data">
            {pctDelta(m.ppsfTrendPct)}
          </Pill>
        </div>
      </div>

      {/* supply / velocity figures */}
      <dl className="mt-6 grid grid-cols-2 gap-x-4 gap-y-5 border-t border-border pt-5">
        <Figure label="Median DOM" value={`${num(m.medianDom)} days`} />
        <Figure label="Mo. supply" value={num1(m.monthsOfInventory)} />
        <Figure label="Sold · 12mo" value={num(m.soldCount)} />
        <Figure label="Active" value={num(m.activeCount)} />
      </dl>

      {/* takeaway */}
      <p className="mt-6 border-t border-border pt-4 text-sm leading-relaxed text-muted-foreground">
        {m.note}
      </p>
    </SpotlightCard>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="cb-eyebrow text-muted-foreground">{label}</dt>
      <dd className="font-data text-xl font-medium tracking-tight text-foreground">
        {value}
      </dd>
    </div>
  );
}
