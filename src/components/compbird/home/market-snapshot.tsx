import { Sparkline, TrendBadge } from "@/components/charts";
import { Card, Pill } from "@/components/compbird/ui";
import type { NeighborhoodMarket } from "@/lib/compbird/types";
import { usd, ppsf, num, num1, pctDelta } from "@/lib/compbird/format";

/**
 * The hub's live neighborhood snapshot — the same tear-sheet card the landing's
 * market section paints, WITH the engine-computed heat row, but rendered
 * server-side from markets the page already fetched (no client fetch, no
 * framer-motion). Purely presentational and server-safe: the shared Card /
 * Pill primitives + the dependency-free chart SVGs. The page hides this section
 * entirely when `markets` is empty, so this always has rows to draw.
 */
export function MarketSnapshot({ markets }: { markets: NeighborhoodMarket[] }) {
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {markets.map((m) => (
        <li key={m.name} className="h-full">
          <MarketCard market={m} />
        </li>
      ))}
    </ul>
  );
}

function MarketCard({ market: m }: { market: NeighborhoodMarket }) {
  const up = m.ppsfTrendPct >= 0;
  return (
    <Card className="flex h-full flex-col p-5">
      {/* name + area + momentum */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-display truncate text-base font-semibold tracking-tight text-foreground">
            {m.name}
          </h3>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">{m.area}</p>
        </div>
        <TrendBadge pct={m.ppsfTrendPct} className="mt-0.5 shrink-0" />
      </div>

      {/* headline median */}
      <div className="mt-4">
        <span className="cb-eyebrow text-muted-foreground">Median price</span>
        <div className="mt-1 font-data text-2xl font-semibold tracking-tight text-foreground">
          {usd(m.medianPrice)}
        </div>
        <p className="mt-1 font-data text-xs text-muted-foreground">
          {ppsf(m.ppsf)}/sqft · {pctDelta(m.ppsfTrendPct)} YoY
        </p>
      </div>

      {/* 12-month trend */}
      <div className="mt-4">
        <Sparkline
          data={m.trend}
          fill
          color={up ? "var(--positive)" : "var(--negative)"}
          height={40}
        />
      </div>

      {/* supply / velocity figures */}
      <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-border pt-4">
        <Figure label="Median DOM" value={`${num(m.medianDom)} days`} />
        <Figure label="Mo. supply" value={num1(m.monthsOfInventory)} />
        <Figure label="Sold · 12mo" value={num(m.soldCount)} />
        <Figure label="Active" value={num(m.activeCount)} />
      </dl>

      {/* market heat — engine-computed additions, all optional on the wire.
          Mirrors market-reports.tsx: the row only renders when a heat field is
          present, so older engines that omit them simply show no heat. */}
      {m.heat != null || m.pct_over_ask != null || m.cut_share != null ? (
        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border pt-4">
          {m.heat != null ? <HeatChip heat={m.heat} /> : null}
          {m.pct_over_ask != null || m.cut_share != null ? (
            <span
              className="font-data text-xs text-muted-foreground"
              title={
                m.sold_to_list != null
                  ? `Median sold-to-list ratio ${(m.sold_to_list * 100).toFixed(1)}%`
                  : undefined
              }
            >
              {[
                m.pct_over_ask != null
                  ? `${Math.round(m.pct_over_ask * 100)}% closed over ask`
                  : null,
                m.cut_share != null ? `${Math.round(m.cut_share * 100)}% took a cut` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

/**
 * Compact market-heat chip — identical scale to market-reports.tsx: cool (info)
 * under 34, neutral through 66, hot (ember) from 67, plus a hairline meter. The
 * number carries the signal, so tint is never the only cue.
 */
function HeatChip({ heat }: { heat: number }) {
  const h = Math.max(0, Math.min(100, Math.round(heat)));
  const tone =
    h >= 67
      ? "border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] text-[var(--cb-ember-text)]"
      : h < 34
        ? "border-[var(--info)]/30 bg-[var(--info-tint)] text-[var(--info-foreground)]"
        : "border-border bg-secondary/60 text-muted-foreground";
  return (
    <span
      title="Market heat, 0–100 — an engine-side composite of pace (days on market), supply (months of inventory), over-ask share, and price-cut share."
      className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[0.65rem] font-semibold uppercase tracking-[0.12em] ${tone}`}
    >
      Heat
      <span className="font-data text-xs normal-case tracking-normal">{h}</span>
      <span className="block h-1 w-10 overflow-hidden rounded-full bg-border/60" aria-hidden>
        <span
          className="block h-full rounded-full bg-current opacity-70"
          style={{ width: `${h}%` }}
        />
      </span>
    </span>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="cb-eyebrow text-muted-foreground">{label}</dt>
      <dd className="font-data text-lg font-medium tracking-tight text-foreground">
        {value}
      </dd>
    </div>
  );
}
