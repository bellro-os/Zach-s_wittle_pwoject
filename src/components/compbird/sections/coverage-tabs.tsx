"use client";

import { useEffect, useRef, useState } from "react";
import { Marquee, Pill } from "@/components/compbird/ui";
import { fetchMarkets } from "@/lib/compbird/api";
import type { NeighborhoodMarket } from "@/lib/compbird/types";
import { num } from "@/lib/compbird/format";
import { cn } from "@/lib/utils/cn";

/**
 * Coverage footprint tabs — LIVE NOW vs COMING NEXT.
 *
 * Paints the static jurisdiction marquee instantly (server-render + no-JS safe,
 * and the honest default while the feed loads), then asks /api/compbird/markets
 * for the live neighborhood aggregates — the same source the market-reports
 * band uses. When a non-empty array comes back, the marquee upgrades to a
 * two-tab read: LIVE NOW carries the real tracked neighborhoods with their
 * trailing-year closing counts, COMING NEXT lists the expansion markets. On an
 * empty result or any error we keep the static marquee — a coverage claim is
 * only upgraded to "live" when the engine actually answered.
 */

const TABS = [
  { id: "live", label: "Live now" },
  { id: "next", label: "Coming next" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export function CoverageTabs({
  places,
  coming,
}: {
  /** Static fallback marquee — the jurisdictions the engine already reads. */
  places: string[];
  /** Expansion markets, in rollout order — the COMING NEXT tab. */
  coming: string[];
}) {
  const [live, setLive] = useState<NeighborhoodMarket[] | null>(null);
  const [tab, setTab] = useState<TabId>("live");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchMarkets(ctrl.signal)
      .then((rows) => {
        if (Array.isArray(rows) && rows.length > 0) setLive(rows);
      })
      .catch(() => {
        /* keep the static marquee — the landing must never break on a cold engine */
      });
    return () => ctrl.abort();
  }, []);

  /* ── fallback: the static marquee, exactly as before ── */
  if (!live) {
    return (
      <div>
        <div className="mb-4 flex items-center justify-between gap-4">
          <span className="cb-eyebrow text-muted-foreground">
            Reading the map across Virginia
          </span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            Now live across the New River Valley — expanding statewide.
          </span>
        </div>
        <div className="cb-mask-fade relative overflow-hidden rounded-2xl border border-border bg-card/60 py-4">
          <Marquee items={places} />
        </div>
      </div>
    );
  }

  /* ── live: LIVE NOW vs COMING NEXT tabs ── */
  const totalSold = live.reduce((n, m) => n + (m.soldCount || 0), 0);

  function onTablistKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const idx = TABS.findIndex((t) => t.id === tab);
    const next = (idx + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    setTab(TABS[next].id);
    tabRefs.current[next]?.focus();
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
        <span className="inline-flex flex-wrap items-center gap-3">
          <span className="cb-eyebrow text-muted-foreground">
            Reading the map across Virginia
          </span>
          {/* Live/static state as a stable badge — same honesty idiom as the
              market-reports band. */}
          <Pill tone="ember">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--cb-ember)]" aria-hidden />
            Live data
          </Pill>
        </span>

        <div
          role="tablist"
          aria-label="Coverage footprint"
          onKeyDown={onTablistKeyDown}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-card/60 p-1"
        >
          {TABS.map((t, i) => {
            const selected = tab === t.id;
            return (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[i] = el;
                }}
                type="button"
                role="tab"
                id={`cb-coverage-tab-${t.id}`}
                aria-selected={selected}
                aria-controls={`cb-coverage-panel-${t.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => setTab(t.id)}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
                  selected
                    ? "bg-[var(--cb-ember)] text-[var(--cb-on-ember)]"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* LIVE NOW — the tracked neighborhoods with real trailing-year counts */}
      <div
        role="tabpanel"
        id="cb-coverage-panel-live"
        aria-labelledby="cb-coverage-tab-live"
        hidden={tab !== "live"}
        className="rounded-2xl border border-border bg-card/60 p-4 sm:p-5"
      >
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {live.map((m) => (
            <li
              key={`${m.name}-${m.area}`}
              className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-3.5 py-3"
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-foreground">
                  {m.name}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {m.area}
                </span>
              </span>
              <span className="font-data shrink-0 text-right text-xs leading-snug text-[var(--cb-ember-text)]">
                {num(m.soldCount)} closed
                <span className="block text-muted-foreground">12 mo</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
          The busiest tracked neighborhoods by closings in the trailing year —{" "}
          <span className="font-data text-foreground">{num(totalSold)}</span> recorded
          sales across {live.length} neighborhoods, aggregated live from the same
          closed-sale records that price a report.
        </p>
      </div>

      {/* COMING NEXT — expansion markets, a roadmap signal rather than a gap */}
      <div
        role="tabpanel"
        id="cb-coverage-panel-next"
        aria-labelledby="cb-coverage-tab-next"
        hidden={tab !== "next"}
        className="rounded-2xl border border-border bg-card/60 p-4 sm:p-5"
      >
        <ul className="flex flex-wrap gap-2">
          {coming.map((place) => (
            <li key={place}>
              <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3.5 py-1.5 text-sm text-muted-foreground">
                <span
                  className="h-1.5 w-1.5 rounded-full border border-[var(--cb-ember)]/60"
                  aria-hidden
                />
                {place}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
          Deep-MLS markets widen as each feed comes online; recorded closed sales
          from public records already back the comp pool across 130 Virginia and
          D.C. localities in the meantime.
        </p>
      </div>
    </div>
  );
}
