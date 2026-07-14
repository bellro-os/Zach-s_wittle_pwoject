"use client";

import { memo, useCallback, useEffect, useState } from "react";
import { Pill } from "@/components/compbird/ui";
import { usd, ppsf, num, miles, dateLong } from "@/lib/compbird/format";
import type { ProfileComp } from "@/lib/compbird/types";
import { AddCompSearch } from "./add-comp-search";
import { MatchPopover } from "./match-popover";

/**
 * The evidence: every closed comparable in one scannable grid. Figures are mono
 * tabular; atypical comps carry a small negative flag so the eye catches the
 * outlier the model down-weighted. Scrolls horizontally on narrow screens. As a
 * data-heavy panel it carries the faint parcel grid (`.cb-grid` — rule in
 * compbird.css: evidence surfaces may, forms and cards may not).
 *
 * On LIVE reports the studio passes `onToggle` + the current `excluded` set, so
 * each row gains a keyboard-accessible Exclude/Include control that drops a comp
 * from (or forces it back into) the valuation and recomputes. With no handler
 * (sample reports) the control is omitted entirely and the table is read-only.
 *
 * The studio may also pass a `forced` set — comps the user pinned in via the
 * "add a comparable" search. Those rows wear a "Pinned" badge so it's clear the
 * value rests on a comp the user added, not one the engine surfaced.
 *
 * When `onAddComp` is provided, the table grows a STICKY FOOTER (frosted, pins
 * to the viewport bottom while a long comp set scrolls) holding the '+'
 * add-a-comparable affordance plus the pinned comps as removable chips — the
 * comp controls live with the evidence they act on, not in a separate box.
 *
 * COMP WORKSHOP: when the engine scored the set (per-comp `similarity`,
 * CMA_COMP_SCORE_SURFACE=1), a Match column appears after Address — integer +
 * tier word + hairline ember bar, opening the six-axis breakdown popover
 * (match-popover.tsx). Unscored responses never grow the column.
 */

function baths(n: number | null): string {
  if (n == null) return "—";
  return n % 1 === 0 ? String(n) : n.toFixed(1);
}

/**
 * Stable identity for a comp across preview recomputes. `ProfileComp` carries no
 * parcel id, so the address is the key — it is the same token the studio sends
 * back to the engine in `excluded` / `forced`.
 */
export function compKey(c: ProfileComp): string {
  return c.address;
}

/**
 * A comp the table has seen for the current subject, remembered together with
 * the DISPLAYED index it first appeared at. `order` is what lets an excluded
 * row dim IN PLACE instead of teleporting: it is assigned once (first sight)
 * and never rewritten, while `comp` is refreshed on every recompute so the row
 * keeps carrying the engine's latest payload (rescored similarity etc.).
 */
export interface CachedComp {
  comp: ProfileComp;
  /** First-seen displayed index — the slot an excluded row is re-seated into. */
  order: number;
}

/**
 * Keep excluded comps VISIBLE — and IN PLACE — across recomputes. The engine
 * doesn't down-weight an excluded comp — it drops it from the response
 * entirely and backfills the set (verified against the live worker: /preview
 * with `excluded` returns comps without it). Without retention the row
 * vanishes the instant the recompute settles: no dimmed state, no Include
 * toggle, no way back short of a full reset. And without POSITION retention
 * the row the user just excluded teleports to the bottom of the table.
 *
 * Every comp the table has seen for this subject goes into `cache` (keyed by
 * compKey) stamped with the displayed index it FIRST appeared at. Any excluded
 * key missing from the live set is re-seated from the cache at that original
 * index — live rows keep the engine's order around it, and backfilled new
 * comps take the remaining slots — so it renders dimmed exactly where the
 * user last saw it, with its Include toggle. The caller owns the cache's
 * lifetime (reset it per subject).
 */
export function retainExcludedComps(
  comps: ProfileComp[],
  excluded: Set<string> | undefined,
  cache: Map<string, CachedComp>,
): ProfileComp[] {
  // Rows to re-seat: excluded keys the engine dropped, in first-seen order.
  const present = new Set(comps.map(compKey));
  const retained: CachedComp[] = [];
  if (excluded && excluded.size) {
    for (const key of excluded) {
      if (present.has(key)) continue;
      const hit = cache.get(key);
      if (hit) retained.push(hit);
    }
    retained.sort((a, b) => a.order - b.order);
  }

  // Single walk over the output slots: a retained row claims the slot matching
  // its original index (clamped to the end when the set has shrunk past it);
  // live rows — engine order intact, backfills included — fill everything else
  // and are cached at the slot they first render in.
  const out: ProfileComp[] = [];
  const total = comps.length + retained.length;
  let live = 0;
  let next = 0;
  for (let slot = 0; slot < total; slot++) {
    if (next < retained.length && (retained[next].order <= slot || live >= comps.length)) {
      out.push(retained[next].comp);
      next += 1;
      continue;
    }
    const c = comps[live];
    live += 1;
    const key = compKey(c);
    const prev = cache.get(key);
    if (prev) {
      prev.comp = c; // refresh the payload; the first-seen slot is sticky
    } else {
      cache.set(key, { comp: c, order: slot });
    }
    out.push(c);
  }
  // Nothing re-seated ⇒ hand back the engine's array untouched so memoized
  // consumers keep their referential-equality fast path.
  return retained.length ? out : comps;
}

// `mobile: false` columns collapse below sm — phones keep the decision-driving
// figures (price, $/sqft, beds/baths, distance) without a 44rem side-scroll.
interface Col {
  key: string;
  label: string;
  align: "left" | "right";
  mobile: boolean;
}
const COLS: readonly Col[] = [
  { key: "address", label: "Address", align: "left", mobile: true },
  { key: "sold", label: "Sold", align: "right", mobile: true },
  { key: "ppsf", label: "$/sqft", align: "right", mobile: true },
  { key: "sqft", label: "Sqft", align: "right", mobile: false },
  { key: "bdba", label: "Bd / Ba", align: "right", mobile: true },
  { key: "yr", label: "Yr", align: "right", mobile: false },
  { key: "closed", label: "Closed", align: "right", mobile: false },
  { key: "dom", label: "DOM", align: "right", mobile: false },
  { key: "dist", label: "Dist", align: "right", mobile: true },
];

/**
 * Comp-workshop Match column, inserted right after Address ONLY when at least
 * one comp carries an engine similarity score. Older engine responses (and any
 * profile served without CMA_COMP_SCORE_SURFACE=1) simply never grow the
 * column — no placeholder header, no empty cells. Mobile keeps it: the score
 * is the wow figure the workshop exists for.
 */
const MATCH_COL: Col = { key: "match", label: "Match", align: "right", mobile: true };

/* ── One-time Match-chip hint ─────────────────────────────────────────────────
 *
 * The Match cell opens the six-axis breakdown, but a score can read as a
 * static readout — so the FIRST time a browser renders a LIVE scored table,
 * one quiet line under the table header says the column is tappable. Same
 * once-per-browser discipline as the studio's demo gate (comp-studio.tsx):
 * the flag is written the moment the hint shows, a popover open retires it
 * for the session, and it never renders on sample/read-only tables (no
 * `onToggle`) or unscored sets. Pure + storage-injected so the gate
 * unit-tests under plain Node (comps-table.match-hint.test.ts).
 */

/** localStorage flag: this browser has already been shown the Match hint. */
export const MATCH_HINT_KEY = "cb-match-hint-shown";

/** The exact shipped hint line. */
export const MATCH_HINT_TEXT = "Tap any match score to see why.";

export type HintFlagStore = {
  get(key: string): string | null;
  set(key: string, value: string): void;
};

/** localStorage as a HintFlagStore — only ever touched inside effects. */
const browserHintStore: HintFlagStore = {
  get: (k) => window.localStorage.getItem(k),
  set: (k, v) => window.localStorage.setItem(k, v),
};

/** May the one-time hint show right now? live = tunable table (sample passes false). */
export function shouldShowMatchHint(env: {
  /** The table is a live, user-tunable one — sample/read-only mounts pass false. */
  live: boolean;
  /** At least one comp carries an engine match score. */
  scored: boolean;
  store: HintFlagStore;
}): boolean {
  if (!env.live || !env.scored) return false;
  try {
    return env.store.get(MATCH_HINT_KEY) == null;
  } catch {
    return false; // unreadable storage ⇒ can't prove once-per-browser ⇒ never
  }
}

/** Write the once-per-browser flag the moment the hint renders. */
export function markMatchHintShown(store: HintFlagStore): void {
  try {
    store.set(MATCH_HINT_KEY, "shown");
  } catch {
    /* unwritable storage — shouldShowMatchHint() already fails safe */
  }
}

/** The quiet line itself — muted, one sentence, sits under the table header. */
export function MatchHintLine() {
  return (
    <p data-cb-match-hint="" className="mb-2 text-xs text-muted-foreground">
      {MATCH_HINT_TEXT}
    </p>
  );
}

/** Hidden below sm for `mobile: false` columns (headers + cells in lockstep). */
const desktopOnly = "hidden sm:table-cell";

export const CompsTable = memo(function CompsTable({
  comps,
  excluded,
  forced,
  onToggle,
  onAddComp,
  onRemoveForced,
  busy = false,
}: {
  comps: ProfileComp[];
  /** Keys (compKey) the user has dropped from the set. Live reports only. */
  excluded?: Set<string>;
  /** Keys (compKey) the user pinned IN via search — wear a "Pinned" badge. */
  forced?: Set<string>;
  /** Toggle a comp in/out of the valuation. Absent ⇒ read-only (sample). */
  onToggle?: (key: string, exclude: boolean) => void;
  /** Pin a searched address IN as a comp — enables the sticky add-comp footer. */
  onAddComp?: (address: string) => void;
  /** Drop a previously-pinned address back out of the set (footer chips). */
  onRemoveForced?: (address: string) => void;
  /** A recompute is in flight — disable the toggles to avoid pile-ups. */
  busy?: boolean;
}) {
  const tunable = typeof onToggle === "function";
  const excludedSet = excluded ?? EMPTY;
  const forcedSet = forced ?? EMPTY;
  const hasFooter = tunable && typeof onAddComp === "function";
  // Match column exists only when the engine actually scored the set (rule:
  // hide it entirely — never placeholders — for unscored/older responses).
  const hasMatch = comps.some((c) => typeof c.similarity === "number");
  const cols = hasMatch ? [COLS[0], MATCH_COL, ...COLS.slice(1)] : COLS;

  // One-time Match hint: client-effect only (never in server markup, so no
  // hydration flash), shown at most once per browser, retired for the session
  // by the first popover open. Gate + flag live above as pure helpers.
  const [matchHint, setMatchHint] = useState(false);
  useEffect(() => {
    if (shouldShowMatchHint({ live: tunable, scored: hasMatch, store: browserHintStore })) {
      setMatchHint(true);
      markMatchHintShown(browserHintStore);
    }
  }, [tunable, hasMatch]);
  const retireMatchHint = useCallback(() => setMatchHint(false), []);
  const hint = matchHint && tunable && hasMatch ? <MatchHintLine /> : null;

  // Pinned chips: match each forced address back to a resolved row when present
  // so the chip shows the engine's canonical address.
  const pinnedChips = hasFooter
    ? Array.from(forcedSet).map((address) => {
        const comp = comps.find((c) => compKey(c) === address) ?? null;
        return { address, label: (comp?.address ?? address).split(",")[0] };
      })
    : [];

  // Sticky comp-controls footer — frosted (bg-card/85 + blur per the surface
  // ladder) so it stays legible pinned over scrolling rows.
  const footer = hasFooter ? (
    <div className="sticky bottom-0 z-10 -mx-1 mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-border/70 bg-card/85 px-3 py-2.5 backdrop-blur">
      <div className="min-w-[15rem] max-w-md flex-1">
        <AddCompSearch onAdd={onAddComp!} busy={busy} pinned={forcedSet} dropUp />
      </div>
      {pinnedChips.length ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="cb-eyebrow mr-0.5 text-muted-foreground">Pinned</span>
          {pinnedChips.map(({ address, label }) => (
            <span
              key={address}
              className="inline-flex items-center gap-1.5 rounded-full border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] py-1 pl-3 pr-1.5 text-xs font-medium text-[var(--cb-ember-text)]"
            >
              <span className="max-w-[16rem] truncate" title={address}>
                {label}
              </span>
              <button
                type="button"
                onClick={() => onRemoveForced?.(address)}
                disabled={busy}
                aria-label={`Remove ${address} from the comp set`}
                className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[var(--cb-ember-text)] transition-colors hover:bg-[var(--cb-ember)]/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" aria-hidden>
                  <path
                    d="M4 4l8 8M12 4l-8 8"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  ) : null;

  if (!comps.length) {
    // An empty live set is exactly when adding a comparable matters most —
    // keep the add affordance alongside the empty notice.
    return (
      <div className="flex flex-col">
        <p className="rounded-xl border border-border bg-card/60 p-6 text-sm text-muted-foreground">
          No comparable sales matched within the search window.
        </p>
        {footer}
      </div>
    );
  }

  const table = (
    <div
      tabIndex={0}
      role="region"
      aria-label="Comparable sales table"
      className="cb-grid -mx-1 overflow-x-auto rounded-lg px-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
    >
      <table className="w-full border-collapse text-sm sm:min-w-[44rem]">
        <thead>
          <tr className="border-b border-border">
            {cols.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`cb-eyebrow whitespace-nowrap pb-3 font-semibold text-muted-foreground ${
                  c.align === "right" ? "pl-4 text-right" : "pr-4 text-left"
                } ${c.mobile ? "" : desktopOnly}`}
              >
                {c.label}
              </th>
            ))}
            {tunable ? (
              <th
                scope="col"
                className="cb-eyebrow whitespace-nowrap pb-3 pl-4 text-right font-semibold text-muted-foreground"
              >
                <span className="sr-only">Include in valuation</span>
                <span aria-hidden>Use</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {comps.map((c, i) => {
            const key = compKey(c);
            const isExcluded = excludedSet.has(key);
            const isForced = forcedSet.has(key);
            return (
              <tr
                key={`${key}-${i}`}
                // Keyboard path: focus a row, press Space or X to toggle it in/out
                // of the valuation — no mouse trip to the Use column required.
                tabIndex={tunable ? 0 : undefined}
                onKeyDown={
                  tunable
                    ? (e) => {
                        // Only when the ROW itself is focused — a Space/X aimed
                        // at a control inside the row (the Match popover
                        // trigger, the Exclude button) must reach that control,
                        // not silently toggle the comp.
                        if (e.target !== e.currentTarget) return;
                        if (e.key === " " || e.key.toLowerCase() === "x") {
                          e.preventDefault();
                          if (!busy) onToggle!(key, !isExcluded);
                        }
                      }
                    : undefined
                }
                aria-label={tunable ? `${c.address} — press Space to ${isExcluded ? "include" : "exclude"}` : undefined}
                className={`border-b border-border/60 transition-colors last:border-0 hover:bg-secondary/40 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--cb-ember)] ${
                  isExcluded ? "opacity-45" : ""
                } ${isForced && !isExcluded ? "bg-[var(--cb-tint)]/25" : ""}`}
              >
                <td className="max-w-[16rem] py-3 pr-4 align-middle">
                  <div className="flex items-center gap-2">
                    <span
                      className={`truncate font-medium text-foreground ${
                        isExcluded ? "line-through decoration-border" : ""
                      }`}
                      title={c.address}
                    >
                      {c.address}
                    </span>
                    {isExcluded ? (
                      <Pill tone="neutral" className="shrink-0">
                        Excluded
                      </Pill>
                    ) : null}
                    {isForced ? (
                      <Pill tone="ember" className="shrink-0">
                        Pinned
                      </Pill>
                    ) : null}
                    {c.source === "supplemental" ? (
                      <span
                        className="shrink-0"
                        title="Sale sourced from public records, not an MLS feed — sold price and location verified; list price and days-on-market unavailable."
                      >
                        <Pill tone="neutral" className="shrink-0">
                          Public records
                        </Pill>
                      </span>
                    ) : null}
                    {c.atypical ? (
                      <span
                        className="shrink-0"
                        title={
                          c.atypical_reason
                            ? `Given less weight in the valuation: ${c.atypical_reason}`
                            : "An unusual sale — given less weight in the valuation"
                        }
                      >
                        <Pill tone="negative" className="shrink-0">
                          Atypical
                        </Pill>
                      </span>
                    ) : null}
                    {c.pending ? (
                      <Pill tone="neutral" className="shrink-0">
                        Pending
                      </Pill>
                    ) : null}
                  </div>
                  {c.subdivision || c.cohort ? (
                    <span
                      className="text-xs text-muted-foreground"
                      title={c.cohort ? `Comp cohort: ${c.cohort}` : undefined}
                    >
                      {c.subdivision ?? c.cohort}
                    </span>
                  ) : null}
                </td>
                {hasMatch ? (
                  <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                    {typeof c.similarity === "number" ? (
                      <MatchPopover comp={c} pinned={isForced} onOpen={retireMatchHint} />
                    ) : (
                      // Mixed set: this comp predates the score surface — an
                      // em-dash, matching every other unknown cell in the table.
                      <span className="font-data text-muted-foreground">—</span>
                    )}
                  </td>
                ) : null}
                <td
                  className={`whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-foreground ${
                    isExcluded ? "line-through decoration-border" : ""
                  }`}
                >
                  {usd(c.sold_price)}
                </td>
                <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-foreground">
                  {ppsf(c.ppsf)}
                </td>
                <td className={`whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground ${desktopOnly}`}>
                  {num(c.sqft)}
                </td>
                <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground">
                  {c.beds ?? "—"} / {baths(c.baths)}
                </td>
                <td className={`whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground ${desktopOnly}`}>
                  {c.year_built ?? "—"}
                </td>
                <td className={`whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground ${desktopOnly}`}>
                  {dateLong(c.close_date)}
                </td>
                <td className={`whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground ${desktopOnly}`}>
                  {c.dom ?? "—"}
                </td>
                <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-muted-foreground">
                  {miles(c.distance_mi)}
                </td>
                {tunable ? (
                  <td className="whitespace-nowrap py-3 pl-4 text-right align-middle">
                    <button
                      type="button"
                      onClick={() => onToggle!(key, !isExcluded)}
                      disabled={busy}
                      aria-pressed={!isExcluded}
                      aria-label={`${isExcluded ? "Include" : "Exclude"} ${c.address} ${
                        isExcluded ? "in" : "from"
                      } the valuation`}
                      className={`inline-flex min-h-[32px] items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:cursor-not-allowed disabled:opacity-50 ${
                        isExcluded
                          ? "border-border bg-secondary/60 text-muted-foreground hover:border-[var(--cb-ember)]/40 hover:text-foreground"
                          : "border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] text-[var(--cb-ember-text)] hover:border-[var(--cb-ember)]/50"
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          isExcluded ? "bg-muted-foreground" : "bg-[var(--cb-ember)]"
                        }`}
                        aria-hidden
                      />
                      {isExcluded ? "Include" : "Exclude"}
                    </button>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  // Read-only (sample/locked) or footer-less, hint-less mounts: just the table.
  if (!footer && !hint) return table;

  return (
    <div className="flex flex-col">
      {hint}
      {table}
      {footer}
    </div>
  );
});

const EMPTY: Set<string> = new Set();
