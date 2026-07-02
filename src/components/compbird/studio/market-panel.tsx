import { memo } from "react";
import { TrendBadge, Sparkline } from "@/components/charts";
import { ppsf, num, num1, usd, monthYear, placeLabel } from "@/lib/compbird/format";
import type { MarketContext, ProfileResult } from "@/lib/compbird/types";

/**
 * Reads the neighborhood like a local: median $/sqft and its trend, days-on-
 * market, months of inventory, and the active/sold balance — plus the subject's
 * own recorded sale history as a quiet timeline.
 */

function Metric({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="cb-eyebrow text-muted-foreground">{label}</span>
      <span className="font-data text-2xl font-medium leading-none tracking-tight text-foreground">
        {value}
      </span>
      {sub ? <span className="text-xs text-muted-foreground">{sub}</span> : null}
    </div>
  );
}

function inventoryTone(moi: number | null): string {
  if (moi == null) return "muted";
  if (moi < 3) return "tight";
  if (moi < 6) return "balanced";
  return "soft";
}

function MarketPanelImpl({
  market,
  saleHistory,
}: {
  market: MarketContext;
  saleHistory: ProfileResult["saleHistory"];
}) {
  const history = (saleHistory ?? []).filter((h) => h.price != null);
  // Oldest → newest for the sparkline.
  const spark = [...history].reverse().map((h) => h.price as number);

  return (
    <div className="flex flex-col gap-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="cb-eyebrow text-muted-foreground">Neighborhood market</span>
        {(() => {
          const scopeLabel = placeLabel(market.scope_value) || market.scope;
          return scopeLabel ? (
            <span className="text-sm text-muted-foreground">{scopeLabel}</span>
          ) : null;
        })()}
      </div>

      <div className="grid grid-cols-1 gap-x-6 gap-y-6 min-[420px]:grid-cols-2 min-[420px]:gap-y-7 sm:grid-cols-3">
        <Metric
          label="Median $/sqft"
          value={ppsf(market.median_ppsf ?? market.ppsf_median)}
          sub={(() => {
            const trend = market.ppsf_trend_pct ?? market.ppsf_trend;
            return trend != null ? (
              <span className="inline-flex items-center gap-1.5">
                <TrendBadge pct={trend} /> year over year
              </span>
            ) : null;
          })()}
        />
        <Metric
          label="Median days on market"
          value={market.median_dom != null ? num(market.median_dom) : "—"}
          sub="from list to contract"
        />
        <Metric
          label="Months of inventory"
          value={market.months_of_inventory != null ? num1(market.months_of_inventory) : "—"}
          sub={`${inventoryTone(market.months_of_inventory)} · seller's market under 3`}
        />
        <Metric
          label="Active listings"
          value={market.active_count != null ? num(market.active_count) : "—"}
          sub="on market now"
        />
        <Metric
          label="Closed sales"
          value={market.sold_count != null ? num(market.sold_count) : "—"}
          sub="trailing window"
        />
        {history.length ? (
          // Full row in the 1- and 2-col tiers (a base col-span-2 inside the
          // 1-col grid would conjure a phantom implicit column); one cell at sm.
          <div className="col-span-full flex flex-col gap-2 sm:col-span-1">
            <span className="cb-eyebrow text-muted-foreground">Subject sale history</span>
            {spark.length > 1 ? (
              <Sparkline data={spark} height={34} fill color="var(--muted-foreground)" />
            ) : null}
            <ul className="flex flex-col gap-0.5">
              {history.map((h, i) => (
                <li
                  key={i}
                  className="flex items-baseline justify-between gap-3 font-data text-xs text-muted-foreground"
                >
                  <span>{monthYear(h.date)}</span>
                  <span className="text-foreground">{usd(h.price)}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Memoized: market context + sale history are stable across comp-tuning
 *  re-renders, so the whole panel skips them. */
export const MarketPanel = memo(MarketPanelImpl);
