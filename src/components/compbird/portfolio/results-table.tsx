"use client";

import { cn } from "@/lib/utils/cn";
import { usd, miles } from "@/lib/compbird/format";
import type { PortfolioItemDto as PortfolioItem } from "@/lib/compbird/portfolio";
import { portfolioTotals } from "./csv";

/**
 * The payoff surface: every property in the run as one dense, instrument-grade
 * grid — estimate, range, confidence, comp evidence — filling in live while the
 * run executes. Presentational on purpose (all state lives in the studio) so
 * the render fixture can exercise it directly.
 *
 * Desktop = a real table on the faint parcel grid (data-heavy panels may carry
 * .cb-grid). Below sm it collapses to stacked cards — address, estimate,
 * confidence — so the page never scrolls horizontally.
 *
 * Row semantics:
 *   pending/running → shimmer bars in the figure cells;
 *   error           → muted row, the terse engine message, no link;
 *   done            → click-through to the comp studio for that address
 *                     (new tab — the run stays where it is).
 */

export type EstimateSort = "none" | "desc" | "asc";

/** Comp-studio deep link for a comped row. */
function studioHref(it: PortfolioItem): string | null {
  if (it.status !== "done" || !it.resolvedAddress) return null;
  return `/comps?address=${encodeURIComponent(it.resolvedAddress)}`;
}

/** Display identity: label when given, address otherwise. */
function displayAddress(it: PortfolioItem): string {
  return it.resolvedAddress ?? it.inputAddress ?? "—";
}

/**
 * Tiny HIGH / STANDARD chip — same visual vocabulary as the studio's
 * ConfidenceBadge (ember tint for high, quiet neutral for standard), minus the
 * popover: forty of these in a grid need to read at a glance, not explain
 * themselves. Thin-comp caution keeps the honest negative dot + title copy.
 */
export function TierChip({
  tier,
  caution,
  className,
}: {
  tier: "high" | "standard" | null;
  caution?: boolean | null;
  className?: string;
}) {
  if (!tier) return <span className="font-data text-muted-foreground">—</span>;
  const high = tier === "high";
  return (
    <span
      title={caution ? "Limited comparable data in this area" : undefined}
      className={cn(
        "inline-flex select-none items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-[0.12em]",
        high
          ? "border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] text-[var(--cb-ember-text)]"
          : "border-border bg-secondary/60 text-muted-foreground",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          caution
            ? "bg-[var(--negative)]/80"
            : high
              ? "bg-[var(--cb-ember)]"
              : "bg-muted-foreground/50",
        )}
      />
      {high ? "High confidence" : "Standard"}
      {caution ? <span className="sr-only"> — limited comparable data</span> : null}
    </span>
  );
}

/** Shimmer stand-in for a figure that hasn't landed yet. */
function ShimmerCell({ w = "w-16" }: { w?: string }) {
  return (
    <span
      aria-hidden
      className={cn("skeleton-shimmer inline-block h-3.5 rounded-md align-middle", w)}
    />
  );
}

/** "6 · 0.4 mi" — count and proximity in one glance. */
function compsCell(it: PortfolioItem): string {
  if (it.compCount == null) return "—";
  return it.nearestMi != null ? `${it.compCount} · ${miles(it.nearestMi)}` : String(it.compCount);
}

const th =
  "cb-eyebrow whitespace-nowrap pb-3 font-semibold text-muted-foreground";

export function PortfolioResultsTable({
  items,
  sort = "none",
  onToggleSort,
}: {
  items: PortfolioItem[];
  /** Estimate-column sort state; owned by the studio. */
  sort?: EstimateSort;
  /** Absent ⇒ static header (the fixture / non-interactive mounts). */
  onToggleSort?: () => void;
}) {
  const totals = portfolioTotals(items);

  // Client-side estimate sort: done rows order by mid, everything without a
  // figure sinks below them in original run order.
  const rows =
    sort === "none"
      ? items
      : [...items].sort((a, b) => {
          const av = a.status === "done" && a.mid != null ? a.mid : null;
          const bv = b.status === "done" && b.mid != null ? b.mid : null;
          if (av == null && bv == null) return a.position - b.position;
          if (av == null) return 1;
          if (bv == null) return -1;
          return sort === "desc" ? bv - av : av - bv;
        });

  const errorNote =
    totals.errored > 0
      ? `${totals.errored} ${totals.errored === 1 ? "property" : "properties"} couldn't be comped — not included in totals`
      : null;

  const sortGlyph = sort === "desc" ? "↓" : sort === "asc" ? "↑" : "↕";

  return (
    <div className="flex flex-col gap-4">
      {/* ── Desktop: the dense grid ─────────────────────────────────────── */}
      <div
        tabIndex={0}
        role="region"
        aria-label="Portfolio results table"
        className="cb-grid -mx-1 hidden overflow-x-auto rounded-lg px-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] sm:block"
      >
        <table className="w-full min-w-[44rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className={cn(th, "pr-4 text-left")}>
                Label / Address
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")} aria-sort={
                sort === "desc" ? "descending" : sort === "asc" ? "ascending" : "none"
              }>
                {onToggleSort ? (
                  <button
                    type="button"
                    onClick={onToggleSort}
                    className="cb-eyebrow inline-flex items-center gap-1.5 font-semibold text-muted-foreground transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
                    aria-label={`Sort by estimate (${sort === "desc" ? "highest first" : sort === "asc" ? "lowest first" : "unsorted"})`}
                  >
                    Estimate
                    <span aria-hidden className={sort === "none" ? "opacity-50" : "text-[var(--cb-ember-text)]"}>
                      {sortGlyph}
                    </span>
                  </button>
                ) : (
                  "Estimate"
                )}
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                Range
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                Confidence
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                Comps
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                Avg match
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((it) => {
              const href = studioHref(it);
              const busy = it.status === "pending" || it.status === "running";
              const failed = it.status === "error";
              return (
                <tr
                  key={it.id}
                  onClick={
                    href
                      ? (e) => {
                          // The address anchor handles itself — don't double-open.
                          if ((e.target as HTMLElement).closest("a")) return;
                          window.open(href, "_blank", "noopener");
                        }
                      : undefined
                  }
                  className={cn(
                    "border-b border-border/60 transition-colors last:border-0",
                    href && "cursor-pointer hover:bg-secondary/40",
                    failed && "opacity-55",
                  )}
                >
                  <td className="max-w-[20rem] py-3 pr-4 align-middle">
                    <div className="flex min-w-0 flex-col">
                      {it.label ? (
                        <span className="truncate text-xs text-muted-foreground" title={it.label}>
                          {it.label}
                        </span>
                      ) : null}
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener"
                          title={`Open ${displayAddress(it)} in the comp studio`}
                          className="truncate font-medium text-foreground underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
                        >
                          {displayAddress(it)}
                        </a>
                      ) : (
                        <span
                          className={cn("truncate font-medium", failed ? "text-muted-foreground" : "text-foreground")}
                          title={displayAddress(it)}
                        >
                          {displayAddress(it)}
                        </span>
                      )}
                      {failed && it.error ? (
                        <span className="truncate text-xs text-muted-foreground" title={it.error}>
                          {it.error}
                        </span>
                      ) : null}
                    </div>
                  </td>
                  {busy ? (
                    <>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                        <ShimmerCell w="w-20" />
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                        <ShimmerCell w="w-28" />
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                        <ShimmerCell w="w-16" />
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                        <ShimmerCell w="w-12" />
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                        <ShimmerCell w="w-8" />
                      </td>
                    </>
                  ) : failed ? (
                    <td colSpan={5} className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                      <span className="font-data text-xs text-muted-foreground">not comped</span>
                    </td>
                  ) : (
                    <>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data font-medium text-foreground">
                        {usd(it.mid)}
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground">
                        {it.low != null && it.high != null ? `${usd(it.low)} – ${usd(it.high)}` : "—"}
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                        <TierChip tier={it.confidenceTier} caution={it.caution} />
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground">
                        {compsCell(it)}
                      </td>
                      <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground">
                        {it.avgMatch != null ? Math.round(it.avgMatch) : "—"}
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-border">
              <td className="py-3.5 pr-4 align-middle">
                <span className="cb-eyebrow text-muted-foreground">Portfolio estimate</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {totals.done} of {totals.total} comped
                  {errorNote ? <span className="text-[var(--negative-foreground)]"> · {errorNote}</span> : null}
                </span>
              </td>
              <td className="whitespace-nowrap py-3.5 pl-4 text-right align-middle font-data text-base font-semibold text-[var(--cb-ember-text)]">
                {usd(totals.mid)}
              </td>
              <td className="whitespace-nowrap py-3.5 pl-4 text-right align-middle font-data text-muted-foreground">
                {totals.low != null && totals.high != null ? `${usd(totals.low)} – ${usd(totals.high)}` : "—"}
              </td>
              <td colSpan={3} />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* ── Mobile: stacked cards, no side-scroll ───────────────────────── */}
      <ul className="flex flex-col gap-2.5 sm:hidden" aria-label="Portfolio results">
        {rows.map((it) => {
          const href = studioHref(it);
          const busy = it.status === "pending" || it.status === "running";
          const failed = it.status === "error";
          const body = (
            <>
              <div className="flex min-w-0 flex-col gap-0.5">
                {it.label ? (
                  <span className="truncate text-xs text-muted-foreground">{it.label}</span>
                ) : null}
                <span
                  className={cn(
                    "truncate text-sm font-medium",
                    failed ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {displayAddress(it)}
                </span>
                {failed && it.error ? (
                  <span className="truncate text-xs text-muted-foreground">{it.error}</span>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                {busy ? (
                  <ShimmerCell w="w-20" />
                ) : failed ? (
                  <span className="font-data text-xs text-muted-foreground">not comped</span>
                ) : (
                  <>
                    <span className="font-data text-base font-semibold text-foreground">
                      {usd(it.mid)}
                    </span>
                    <TierChip tier={it.confidenceTier} caution={it.caution} />
                  </>
                )}
              </div>
            </>
          );
          const cardCls =
            "flex items-center justify-between gap-3 rounded-xl border border-border bg-card/70 px-4 py-3";
          return (
            <li key={it.id}>
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener"
                  className={cn(
                    cardCls,
                    "transition-colors hover:border-[var(--cb-ember)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
                  )}
                >
                  {body}
                </a>
              ) : (
                <div className={cn(cardCls, failed && "opacity-55")}>{body}</div>
              )}
            </li>
          );
        })}
        {/* mobile totals card */}
        <li className="flex items-center justify-between gap-3 rounded-xl border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] px-4 py-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="cb-eyebrow text-muted-foreground">Portfolio estimate</span>
            <span className="text-xs text-muted-foreground">
              {totals.done} of {totals.total} comped
              {errorNote ? ` · ${errorNote}` : ""}
            </span>
          </div>
          <span className="font-data shrink-0 text-base font-semibold text-[var(--cb-ember-text)]">
            {usd(totals.mid)}
          </span>
        </li>
      </ul>
    </div>
  );
}
