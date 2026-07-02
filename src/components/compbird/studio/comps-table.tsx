import { memo } from "react";
import { Pill } from "@/components/compbird/ui";
import { usd, ppsf, num, miles, dateLong } from "@/lib/compbird/format";
import type { ProfileComp } from "@/lib/compbird/types";

/**
 * The evidence: every closed comparable in one scannable grid. Figures are mono
 * tabular; atypical comps carry a small negative flag so the eye catches the
 * outlier the model down-weighted. Scrolls horizontally on narrow screens.
 *
 * On LIVE reports the studio passes `onToggle` + the current `excluded` set, so
 * each row gains a keyboard-accessible Exclude/Include control that drops a comp
 * from (or forces it back into) the valuation and recomputes. With no handler
 * (sample reports) the control is omitted entirely and the table is read-only.
 *
 * The studio may also pass a `forced` set — comps the user pinned in via the
 * "add a comparable" search. Those rows wear a "Pinned" badge so it's clear the
 * value rests on a comp the user added, not one the engine surfaced.
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

// `mobile: false` columns collapse below sm — phones keep the decision-driving
// figures (price, $/sqft, beds/baths, distance) without a 44rem side-scroll.
const COLS = [
  { key: "address", label: "Address", align: "left", mobile: true },
  { key: "sold", label: "Sold", align: "right", mobile: true },
  { key: "ppsf", label: "$/sqft", align: "right", mobile: true },
  { key: "sqft", label: "Sqft", align: "right", mobile: false },
  { key: "bdba", label: "Bd / Ba", align: "right", mobile: true },
  { key: "yr", label: "Yr", align: "right", mobile: false },
  { key: "closed", label: "Closed", align: "right", mobile: false },
  { key: "dom", label: "DOM", align: "right", mobile: false },
  { key: "dist", label: "Dist", align: "right", mobile: true },
] as const;

/** Hidden below sm for `mobile: false` columns (headers + cells in lockstep). */
const desktopOnly = "hidden sm:table-cell";

export const CompsTable = memo(function CompsTable({
  comps,
  excluded,
  forced,
  onToggle,
  busy = false,
}: {
  comps: ProfileComp[];
  /** Keys (compKey) the user has dropped from the set. Live reports only. */
  excluded?: Set<string>;
  /** Keys (compKey) the user pinned IN via search — wear a "Pinned" badge. */
  forced?: Set<string>;
  /** Toggle a comp in/out of the valuation. Absent ⇒ read-only (sample). */
  onToggle?: (key: string, exclude: boolean) => void;
  /** A recompute is in flight — disable the toggles to avoid pile-ups. */
  busy?: boolean;
}) {
  if (!comps.length) {
    return (
      <p className="rounded-xl border border-border bg-card/60 p-6 text-sm text-muted-foreground">
        No comparable sales matched within the search window.
      </p>
    );
  }

  const tunable = typeof onToggle === "function";
  const excludedSet = excluded ?? EMPTY;
  const forcedSet = forced ?? EMPTY;

  return (
    <div
      tabIndex={0}
      role="region"
      aria-label="Comparable sales table"
      className="-mx-1 overflow-x-auto rounded-lg px-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
    >
      <table className="w-full border-collapse text-sm sm:min-w-[44rem]">
        <thead>
          <tr className="border-b border-border">
            {COLS.map((c) => (
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
                    {isForced ? (
                      <Pill tone="ember" className="shrink-0">
                        Pinned
                      </Pill>
                    ) : null}
                    {c.atypical ? (
                      <span
                        className="shrink-0"
                        title={
                          c.atypical_reason
                            ? `Down-weighted by the engine: ${c.atypical_reason}`
                            : "Flagged atypical — down-weighted in the valuation"
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
                <td className="whitespace-nowrap py-3 pl-4 text-right align-middle font-data text-foreground">
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
});

const EMPTY: Set<string> = new Set();
