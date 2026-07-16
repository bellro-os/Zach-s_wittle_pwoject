"use client";

import { cn } from "@/lib/utils/cn";
import { usd, usdCompact, miles } from "@/lib/compbird/format";
import type { PortfolioItemDto as PortfolioItem } from "@/lib/compbird/portfolio";
import { portfolioTotals } from "./csv";

/**
 * The payoff surface: every property in the run as one dense, instrument-grade
 * table — estimate, per-row range bar, confidence, comp evidence — filling in
 * live while the run executes. Presentational on purpose (all state lives in
 * the studio) so the render fixture can exercise it directly.
 *
 * Desktop = a real table with a STICKY header inside its own scroll region
 * (audit removed the .cb-grid texture — stray ledger lines read as noise under
 * the data). Below sm it collapses to stacked cards — address, estimate,
 * confidence — so the page never scrolls horizontally.
 *
 * Row semantics:
 *   pending/running → shimmer bars in the figure cells;
 *   error           → muted row, the terse engine message, no link;
 *   done            → the ADDRESS is a real same-tab link into the comp studio
 *                     (ctrl/cmd/middle-click still new-tabs natively). The row
 *                     itself is NOT clickable, so selecting text is safe. The
 *                     href carries ?from=portfolio, which the studio renders
 *                     as a "Back to portfolio" chip — the return leg.
 */

/* ── Sort + filter contract (owned by the studio) ──────────────────────────── */

export type SortColumn = "estimate" | "confidence" | "match";
export type SortDir = "asc" | "desc";
/** `column: "none"` = original run order; otherwise a keyed direction. */
export type PortfolioSort =
  | { column: "none"; dir: SortDir }
  | { column: SortColumn; dir: SortDir };

/** The three toolbar views. "review" = status error OR caution true. */
export type PortfolioFilter = "all" | "high" | "review";

/** Confidence tier rank for sorting: high > standard > none. */
function tierRank(it: PortfolioItem): number {
  if (it.status !== "done") return -1;
  if (it.confidenceTier === "high") return 2;
  if (it.confidenceTier === "standard") return 1;
  return 0;
}

/**
 * Comp-studio deep link for a comped row — the same ?parcelId=&address=
 * contract the studio's planDeepLink consumes, plus from=portfolio for the
 * studio's "Back to portfolio" chip.
 */
function studioHref(it: PortfolioItem): string | null {
  if (it.status !== "done" || !it.resolvedAddress) return null;
  const qs = new URLSearchParams();
  if (it.parcelId) qs.set("parcelId", it.parcelId);
  qs.set("address", it.resolvedAddress);
  qs.set("from", "portfolio");
  return `/comps?${qs.toString()}`;
}

/** Display identity: label when given, address otherwise. */
function displayAddress(it: PortfolioItem): string {
  return it.resolvedAddress ?? it.inputAddress ?? "—";
}

/** A row is in the "needs review" set when it errored or carries thin-comp caution. */
function needsReview(it: PortfolioItem): boolean {
  return it.status === "error" || it.caution === true;
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

/**
 * Per-row range bar: low–mid–high positioned within the portfolio's overall
 * min-low..max-high span, so a glance reads both the property's own spread AND
 * where it sits in the book. The mid is a tick; the bar is tinted by confidence.
 * Falls back to nothing (renders "—") when a row lacks a full low/high.
 */
function RangeBar({
  it,
  spanLo,
  spanHi,
}: {
  it: PortfolioItem;
  spanLo: number;
  spanHi: number;
}) {
  if (it.low == null || it.high == null || it.mid == null) {
    return <span className="font-data text-muted-foreground">—</span>;
  }
  const span = Math.max(spanHi - spanLo, 1e-9);
  const clamp = (v: number) => Math.min(100, Math.max(0, ((v - spanLo) / span) * 100));
  const left = clamp(it.low);
  const right = clamp(it.high);
  const midPos = clamp(it.mid);
  const width = Math.max(right - left, 1.5);
  const high = it.confidenceTier === "high";

  return (
    <div className="flex flex-col items-end gap-1">
      <span className="font-data text-[11px] text-muted-foreground">
        {usdCompact(it.low)} – {usdCompact(it.high)}
      </span>
      <div
        className="relative h-1.5 w-full min-w-[6rem] max-w-[10rem] overflow-visible rounded-full bg-secondary/60"
        role="img"
        aria-label={`Range ${usd(it.low)} to ${usd(it.high)}, estimate ${usd(it.mid)}`}
      >
        <span
          className="absolute top-0 h-full rounded-full"
          style={{
            left: `${left}%`,
            width: `${width}%`,
            background: high ? "var(--cb-ember)" : "var(--muted-foreground)",
            opacity: high ? 0.55 : 0.35,
          }}
        />
        <span
          aria-hidden
          className="absolute top-1/2 h-2.5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{
            left: `${midPos}%`,
            background: high ? "var(--cb-ember)" : "var(--foreground)",
          }}
        />
      </div>
    </div>
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
  "cb-eyebrow whitespace-nowrap bg-card pb-3 pt-1 font-semibold text-muted-foreground";

/** A sortable header button — glyph reflects this column's active direction. */
function SortHeader({
  label,
  column,
  sort,
  onToggle,
}: {
  label: string;
  column: SortColumn;
  sort: PortfolioSort;
  onToggle?: (column: SortColumn) => void;
}) {
  const active = sort.column === column;
  const glyph = !active ? "↕" : sort.dir === "desc" ? "↓" : "↑";
  const ariaSort = active
    ? sort.dir === "desc"
      ? "descending"
      : "ascending"
    : "none";
  if (!onToggle) return <span aria-sort="none">{label}</span>;
  return (
    <button
      type="button"
      onClick={() => onToggle(column)}
      aria-sort={ariaSort}
      className="cb-eyebrow inline-flex items-center gap-1.5 font-semibold text-muted-foreground transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
      aria-label={`Sort by ${label.toLowerCase()} (${
        active ? (sort.dir === "desc" ? "highest first" : "lowest first") : "unsorted"
      })`}
    >
      {label}
      <span aria-hidden className={active ? "text-[var(--cb-ember-text)]" : "opacity-50"}>
        {glyph}
      </span>
    </button>
  );
}

export function PortfolioResultsTable({
  items,
  sort = { column: "none", dir: "desc" },
  filter = "all",
  onToggleSort,
}: {
  items: PortfolioItem[];
  /** Column + direction sort state; owned by the studio. */
  sort?: PortfolioSort;
  /** Active view — "all" | "high" | "review". Owned by the studio. */
  filter?: PortfolioFilter;
  /** Absent ⇒ static header (the fixture / non-interactive mounts). */
  onToggleSort?: (column: SortColumn) => void;
}) {
  // Totals are ALWAYS over the full run (a filtered view still reports the whole
  // book's worth — the footer is portfolio truth, not the current slice).
  const totals = portfolioTotals(items);

  // Overall low..high span for the per-row range bars, across every done item.
  let spanLo = Infinity;
  let spanHi = -Infinity;
  for (const it of items) {
    if (it.status === "done" && it.low != null && it.high != null) {
      if (it.low < spanLo) spanLo = it.low;
      if (it.high > spanHi) spanHi = it.high;
    }
  }
  const haveSpan = Number.isFinite(spanLo) && Number.isFinite(spanHi) && spanHi > spanLo;

  // Filter first (view), then sort — so counts reflect the current view but the
  // footer/totals stay whole-run.
  const filtered = items.filter((it) => {
    if (filter === "high") return it.status === "done" && it.confidenceTier === "high";
    if (filter === "review") return needsReview(it);
    return true;
  });

  const rows =
    sort.column === "none"
      ? filtered
      : [...filtered].sort((a, b) => {
          const dir = sort.dir === "desc" ? 1 : -1;
          if (sort.column === "estimate") {
            const av = a.status === "done" && a.mid != null ? a.mid : null;
            const bv = b.status === "done" && b.mid != null ? b.mid : null;
            if (av == null && bv == null) return a.position - b.position;
            if (av == null) return 1;
            if (bv == null) return -1;
            return dir * (bv - av);
          }
          if (sort.column === "match") {
            const av = a.status === "done" && a.avgMatch != null ? a.avgMatch : null;
            const bv = b.status === "done" && b.avgMatch != null ? b.avgMatch : null;
            if (av == null && bv == null) return a.position - b.position;
            if (av == null) return 1;
            if (bv == null) return -1;
            return dir * (bv - av);
          }
          // confidence
          const ar = tierRank(a);
          const br = tierRank(b);
          if (ar === br) return a.position - b.position;
          return dir * (br - ar);
        });

  const errorNote =
    totals.errored > 0
      ? `${totals.errored} ${totals.errored === 1 ? "property" : "properties"} couldn't be comped — not included in totals`
      : null;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Desktop: the dense table (no grid texture, sticky header) ────── */}
      <div
        tabIndex={0}
        role="region"
        aria-label="Portfolio results table"
        className="-mx-1 hidden max-h-[34rem] overflow-auto rounded-lg px-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] sm:block"
      >
        <table className="w-full min-w-[48rem] border-collapse text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-border">
              <th scope="col" className={cn(th, "pr-4 text-left")}>
                Label / Address
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                <SortHeader label="Estimate" column="estimate" sort={sort} onToggle={onToggleSort} />
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                Range
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                <SortHeader label="Confidence" column="confidence" sort={sort} onToggle={onToggleSort} />
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                Comps
              </th>
              <th scope="col" className={cn(th, "pl-4 text-right")}>
                <SortHeader label="Avg match" column="match" sort={sort} onToggle={onToggleSort} />
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  {filter === "high"
                    ? "No high-confidence properties in this run yet."
                    : filter === "review"
                      ? "Nothing needs review — every property comped cleanly."
                      : "No properties."}
                </td>
              </tr>
            ) : null}
            {rows.map((it) => {
              const href = studioHref(it);
              const busy = it.status === "pending" || it.status === "running";
              const failed = it.status === "error";
              return (
                <tr
                  key={it.id}
                  className={cn(
                    "border-b border-border/50 transition-colors last:border-0 odd:bg-secondary/20",
                    href && "hover:bg-[var(--cb-tint)]",
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
                      <td className="py-3 pl-4 align-middle">
                        {haveSpan ? (
                          <RangeBar it={it} spanLo={spanLo} spanHi={spanHi} />
                        ) : (
                          <span className="font-data text-xs text-muted-foreground">
                            {it.low != null && it.high != null
                              ? `${usd(it.low)} – ${usd(it.high)}`
                              : "—"}
                          </span>
                        )}
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
          <tfoot className="sticky bottom-0 z-10">
            <tr className="border-t border-border bg-card">
              <td className="bg-card py-3.5 pr-4 align-middle">
                <span className="cb-eyebrow text-muted-foreground">Portfolio estimate</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {totals.done} of {totals.total} comped
                  {errorNote ? <span className="text-[var(--negative-foreground)]"> · {errorNote}</span> : null}
                </span>
              </td>
              <td className="whitespace-nowrap bg-card py-3.5 pl-4 text-right align-middle font-data text-base font-semibold text-[var(--cb-ember-text)]">
                {usd(totals.mid)}
              </td>
              <td className="whitespace-nowrap bg-card py-3.5 pl-4 text-right align-middle font-data text-muted-foreground">
                {totals.low != null && totals.high != null ? `${usd(totals.low)} – ${usd(totals.high)}` : "—"}
              </td>
              <td className="bg-card" colSpan={3} />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* ── Mobile: stacked cards, no side-scroll ───────────────────────── */}
      <ul className="flex flex-col gap-2.5 sm:hidden" aria-label="Portfolio results">
        {rows.length === 0 ? (
          <li className="rounded-xl border border-dashed border-border bg-background/40 px-4 py-6 text-center text-sm text-muted-foreground">
            {filter === "high"
              ? "No high-confidence properties yet."
              : filter === "review"
                ? "Nothing needs review."
                : "No properties."}
          </li>
        ) : null}
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
                {!busy && !failed && it.low != null && it.high != null ? (
                  <span className="font-data text-[11px] text-muted-foreground">
                    {usdCompact(it.low)} – {usdCompact(it.high)}
                  </span>
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
            "flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3";
          return (
            <li key={it.id}>
              {href ? (
                <a
                  href={href}
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
