"use client";

import { cn } from "@/lib/utils/cn";
import type { PortfolioFilter } from "./results-table";

/**
 * The results header toolbar — the live "N of M comped" read on the left, then
 * the filter segmented control and Export CSV on the right. The filter is a
 * three-way view switch ("All · High confidence · Needs review"); its state is
 * owned by the studio, this is presentation. Export stays the prominent
 * affordance (it's the whole point of a batch run).
 *
 * Below sm the toolbar wraps: the progress line sits above a full-width row of
 * segments + export, so nothing crowds on a phone.
 */

const FILTERS: Array<{ id: PortfolioFilter; label: string; short: string }> = [
  { id: "all", label: "All", short: "All" },
  { id: "high", label: "High confidence", short: "High" },
  { id: "review", label: "Needs review", short: "Review" },
];

function DownloadGlyph() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" aria-hidden>
      <path
        d="M8 2v8m0 0 3-3m-3 3L5 7M3 11v2a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-2"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function PortfolioResultsToolbar({
  filter,
  onFilter,
  reviewCount,
  filteredCount,
  totalCount,
  canExport,
  onExport,
}: {
  filter: PortfolioFilter;
  onFilter: (f: PortfolioFilter) => void;
  /** Whole-run "needs review" count (error OR caution) — badged on the switch. */
  reviewCount: number;
  /** Rows in the current view. */
  filteredCount: number;
  /** Rows in the whole run. */
  totalCount: number;
  /** At least one item is done — Export is meaningful. */
  canExport: boolean;
  onExport: () => void;
}) {
  const noun = totalCount === 1 ? "property" : "properties";

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-xs text-muted-foreground" aria-live="polite">
        {filter === "all" ? (
          <>
            <span className="font-data text-foreground">{totalCount}</span> {noun}
            {reviewCount > 0 ? (
              <>
                {" · "}
                <span className="font-data text-[var(--negative-foreground)]">{reviewCount}</span>{" "}
                need review
              </>
            ) : null}
          </>
        ) : (
          <>
            <span className="font-data text-foreground">{filteredCount}</span> of {totalCount} {noun}
          </>
        )}
      </span>

      <div className="flex flex-wrap items-center gap-2">
        {/* segmented filter */}
        <div
          role="group"
          aria-label="Filter properties"
          className="inline-flex items-center gap-0.5 rounded-full border border-border bg-secondary/40 p-0.5"
        >
          {FILTERS.map((f) => {
            const active = filter === f.id;
            const badge = f.id === "review" && reviewCount > 0 ? reviewCount : null;
            return (
              <button
                key={f.id}
                type="button"
                aria-pressed={active}
                onClick={() => onFilter(f.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
                  active
                    ? "bg-card text-foreground shadow-[0_1px_3px_-1px_rgba(17,23,38,0.18)]"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="hidden sm:inline">{f.label}</span>
                <span className="sm:hidden">{f.short}</span>
                {badge != null ? (
                  <span
                    className={cn(
                      "font-data rounded-full px-1.5 py-px text-[10px] leading-none",
                      active
                        ? "bg-[var(--negative)]/15 text-[var(--negative-foreground)]"
                        : "bg-[var(--negative)]/10 text-[var(--negative-foreground)]",
                    )}
                  >
                    {badge}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>

        {/* export */}
        {canExport ? (
          <button
            type="button"
            onClick={onExport}
            className="inline-flex items-center gap-2 rounded-full border border-[var(--cb-ember)]/40 bg-[var(--cb-tint)] px-3.5 py-2 text-xs font-semibold text-[var(--cb-ember-text)] transition-colors hover:border-[var(--cb-ember)]/60 hover:bg-[var(--cb-tint)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            <DownloadGlyph />
            Export CSV
          </button>
        ) : null}
      </div>
    </div>
  );
}
