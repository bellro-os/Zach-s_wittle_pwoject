"use client";

import { useState } from "react";
import { cn } from "@/lib/utils/cn";
import { usdCompact, dateLong } from "@/lib/compbird/format";
import type { PortfolioRunSummaryDto as PortfolioRunSummary } from "@/lib/compbird/portfolio";

/**
 * Previous runs as a real labeled list — the studio's Recents idiom, one row per
 * run: a status dot, the run's display name, then a mono meta line
 * (date · N properties · total value when the summary carries it). Click loads
 * the run (onPick); the trailing × arms a two-step inline confirm (no
 * window.confirm) before the DELETE fires.
 *
 * The summary DTO usually carries portfolioMid, so the total value shows; when
 * it's null (nothing landed yet, or a failed run) the row falls back to
 * date · count, never a fabricated "$0".
 */

function statusDot(status: PortfolioRunSummary["status"]): string {
  if (status === "running") return "bg-[var(--cb-ember)] animate-pulse motion-reduce:animate-none";
  if (status === "failed") return "bg-[var(--negative)]/80";
  return "bg-muted-foreground/60";
}

function statusWord(status: PortfolioRunSummary["status"]): string {
  if (status === "running") return "Running";
  if (status === "failed") return "Failed";
  return "Done";
}

export function RunsStrip({
  runs,
  activeId,
  busy,
  onPick,
  onDelete,
}: {
  runs: PortfolioRunSummary[];
  activeId: string | null;
  busy: boolean;
  onPick: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  // The one row whose delete is armed ("Delete? yes / no").
  const [armed, setArmed] = useState<string | null>(null);

  if (!runs.length) return null;

  return (
    <section aria-label="Previous runs" className="flex flex-col gap-2.5">
      <span aria-hidden className="cb-eyebrow text-muted-foreground">
        Previous runs
      </span>
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {runs.map((r) => {
          const label = r.firstLabel || dateLong(r.createdAt);
          const isArmed = armed === r.id;
          const active = activeId === r.id;
          const meta = [
            dateLong(r.createdAt),
            `${r.total} ${r.total === 1 ? "property" : "properties"}`,
            r.portfolioMid != null ? usdCompact(r.portfolioMid) : null,
          ]
            .filter(Boolean)
            .join(" · ");

          return (
            <li key={r.id}>
              <div
                className={cn(
                  "group relative flex items-center gap-3 rounded-xl border px-3.5 py-3 transition-colors",
                  active
                    ? "border-[var(--cb-ember)]/40 bg-[var(--cb-tint)]"
                    : "border-border bg-card hover:border-[var(--cb-ember)]/30",
                )}
              >
                {isArmed ? (
                  <div className="flex w-full items-center justify-between gap-2">
                    <span className="truncate text-xs text-foreground">
                      Delete <span className="font-medium">{label}</span>?
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setArmed(null);
                          onDelete(r.id);
                        }}
                        disabled={busy}
                        aria-label={`Confirm delete of run ${label}`}
                        className="rounded-full px-2 py-1 text-xs font-semibold text-[var(--negative-foreground)] transition-colors hover:bg-[var(--negative)]/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
                      >
                        Yes
                      </button>
                      <button
                        type="button"
                        onClick={() => setArmed(null)}
                        aria-label={`Keep run ${label}`}
                        className="rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)]"
                      >
                        No
                      </button>
                    </span>
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onPick(r.id)}
                      disabled={busy}
                      title={`${label} · ${r.completed} of ${r.total}${r.portfolioMid != null ? ` · ${usdCompact(r.portfolioMid)}` : ""}`}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
                    >
                      <span
                        className={cn("mt-0.5 h-2 w-2 shrink-0 self-start rounded-full", statusDot(r.status))}
                        aria-hidden
                      />
                      <span className="flex min-w-0 flex-col">
                        <span
                          className={cn(
                            "truncate text-sm font-medium",
                            active ? "text-[var(--cb-ember-text)]" : "text-foreground",
                          )}
                        >
                          {label}
                        </span>
                        <span className="font-data truncate text-[11px] text-muted-foreground">
                          {meta}
                        </span>
                      </span>
                    </button>
                    <span className="sr-only">{statusWord(r.status)}</span>
                    <button
                      type="button"
                      onClick={() => setArmed(r.id)}
                      disabled={busy}
                      aria-label={`Delete run ${label}`}
                      className="relative inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
                    >
                      <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" aria-hidden>
                        <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                      </svg>
                    </button>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
