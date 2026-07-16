import { memo } from "react";
import { usdCompact } from "@/lib/compbird/format";
import type { ProfileResult } from "@/lib/compbird/types";

/**
 * Equity snapshot — "Bought $310K in 2019 → estimated $455K today → +$145K
 * (+47%)". Renders ONLY when the profile carries a usable prior sale in
 * `saleHistory` AND a headline estimate: the sale history is already on the
 * wire, so the card costs nothing new. redact.ts strips saleHistory → [] for
 * non-Pro callers, so this is effectively an UNLOCKED-report card — the
 * presence gate below handles that with no explicit tier check (verified:
 * saleHistory does NOT survive redaction).
 *
 * Figures ride the mono data font; the gain is tinted with the standard
 * positive/negative tokens (and spelled out, never color alone).
 */

/** The most recent sale-history entry with a positive price; null when none. */
export function priorSaleOf(
  saleHistory: ProfileResult["saleHistory"] | null | undefined,
): { price: number; year: number | null } | null {
  let best: { price: number; time: number; year: number | null } | null = null;
  for (const h of saleHistory ?? []) {
    const price = h?.price;
    if (price == null || !Number.isFinite(price) || price <= 0) continue;
    const parsed = h.date ? Date.parse(h.date) : NaN;
    const time = Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
    if (best == null || time > best.time) {
      const yearMatch = h.date?.match(/^(\d{4})/);
      best = { price, time, year: yearMatch ? Number(yearMatch[1]) : null };
    }
  }
  return best ? { price: best.price, year: best.year } : null;
}

function EquitySnapshotImpl({
  saleHistory,
  estimateMid,
}: {
  saleHistory: ProfileResult["saleHistory"];
  /** The headline valuation mid — "estimated $X today". */
  estimateMid: number | null;
}) {
  const prior = priorSaleOf(saleHistory);
  if (!prior || estimateMid == null || !Number.isFinite(estimateMid) || estimateMid <= 0) {
    return null;
  }

  const gain = estimateMid - prior.price;
  const pct = Math.round((gain / prior.price) * 100);
  const gainClass =
    gain >= 0 ? "text-[var(--positive-foreground)]" : "text-[var(--negative-foreground)]";

  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-secondary/30 px-4 py-3">
      <span className="cb-eyebrow text-muted-foreground">Equity snapshot</span>
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 font-data text-sm text-foreground">
        <span>
          Bought <span className="font-medium">{usdCompact(prior.price)}</span>
          {prior.year != null ? ` in ${prior.year}` : ""}
        </span>
        <span aria-hidden className="text-border">
          →
        </span>
        <span>
          estimated{" "}
          <span className="font-medium text-[var(--cb-ember-text)]">
            {usdCompact(estimateMid)}
          </span>{" "}
          today
        </span>
        <span aria-hidden className="text-border">
          →
        </span>
        <span className={`font-medium ${gainClass}`}>
          {gain >= 0 ? "+" : "−"}
          {usdCompact(Math.abs(gain))} ({pct >= 0 ? "+" : ""}
          {pct}%)
        </span>
      </p>
      <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
        Recorded prior sale vs today&rsquo;s estimate — not a payoff or net-proceeds figure.
      </p>
    </div>
  );
}

/** Memoized: saleHistory + the mid keep their identity across tuning re-renders. */
export const EquitySnapshot = memo(EquitySnapshotImpl);

export default EquitySnapshot;
