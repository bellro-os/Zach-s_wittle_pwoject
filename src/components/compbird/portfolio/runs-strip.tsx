"use client";

import { useState } from "react";
import { cn } from "@/lib/utils/cn";
import { usd, dateLong } from "@/lib/compbird/format";
import type { PortfolioRunSummaryDto as PortfolioRunSummary } from "@/lib/compbird/portfolio";

/**
 * Previous runs as a quiet chip strip above the results — the same language as
 * the studio's Recents row. Click loads that run; the small × arms a two-step
 * inline confirm (no window.confirm) before the DELETE fires.
 */

function statusDot(status: PortfolioRunSummary["status"]): string {
  if (status === "running") return "bg-[var(--cb-ember)] animate-pulse motion-reduce:animate-none";
  if (status === "failed") return "bg-[var(--negative)]/80";
  return "bg-muted-foreground/60";
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
  // The one chip whose delete is armed ("Delete? yes / no").
  const [armed, setArmed] = useState<string | null>(null);

  if (!runs.length) return null;

  return (
    <div role="group" aria-label="Previous runs" className="flex flex-wrap items-center gap-2">
      <span aria-hidden className="cb-eyebrow mr-1 text-muted-foreground">Previous runs</span>
      {runs.map((r) => {
        const label = r.firstLabel || dateLong(r.createdAt);
        const isArmed = armed === r.id;
        return (
          <span
            key={r.id}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border py-1 pl-3 pr-1.5 text-xs transition-colors",
              activeId === r.id
                ? "border-[var(--cb-ember)]/40 bg-[var(--cb-tint)] text-[var(--cb-ember-text)]"
                : "border-border bg-card/60 text-muted-foreground",
            )}
          >
            {isArmed ? (
              <>
                <span className="font-medium text-foreground">Delete?</span>
                <button
                  type="button"
                  onClick={() => {
                    setArmed(null);
                    onDelete(r.id);
                  }}
                  disabled={busy}
                  aria-label={`Confirm delete of run ${label}`}
                  className="relative rounded-full px-1.5 py-0.5 font-semibold text-[var(--negative-foreground)] transition-colors after:absolute after:-inset-2 after:content-[''] hover:bg-[var(--negative)]/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
                >
                  Yes
                </button>
                <button
                  type="button"
                  onClick={() => setArmed(null)}
                  aria-label={`Keep run ${label}`}
                  className="relative rounded-full px-1.5 py-0.5 transition-colors after:absolute after:-inset-2 after:content-[''] hover:bg-secondary/70 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)]"
                >
                  No
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => onPick(r.id)}
                  disabled={busy}
                  title={`${label} · ${r.completed} of ${r.total}${r.portfolioMid != null ? ` · ${usd(r.portfolioMid)}` : ""}`}
                  className="inline-flex items-center gap-2 rounded-full transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
                >
                  <span className={cn("h-1.5 w-1.5 rounded-full", statusDot(r.status))} aria-hidden />
                  <span className="max-w-[11rem] truncate">{label}</span>
                  <span className="font-data text-[11px] opacity-80">
                    {r.total} {r.total === 1 ? "property" : "properties"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => setArmed(r.id)}
                  disabled={busy}
                  aria-label={`Delete run ${label}`}
                  className="relative inline-flex h-5 w-5 items-center justify-center rounded-full transition-colors after:absolute after:-inset-2 after:content-[''] hover:bg-secondary/70 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
                >
                  <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" aria-hidden>
                    <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                  </svg>
                </button>
              </>
            )}
          </span>
        );
      })}
    </div>
  );
}
