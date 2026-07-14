"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { CompbirdApiError } from "@/lib/compbird/api";
import type {
  PortfolioRunDto as PortfolioRun,
  PortfolioRunSummaryDto as PortfolioRunSummary,
} from "@/lib/compbird/portfolio";
import { PortfolioInputPanel } from "./input-panel";
import { PortfolioResultsTable, type EstimateSort } from "./results-table";
import { RunsStrip } from "./runs-strip";
import { buildResultsCsv, portfolioCsvFilename, type ParsedEntry } from "./csv";

/**
 * The portfolio studio: input panel → POST → 2.5s polling → the results grid
 * filling in live, plus the previous-runs strip and the CSV export. All wire
 * traffic speaks the /api/compbird/portfolio contract; entity shapes come from
 * the shared portfolio module (type-only, backend-owned).
 */

const POLL_MS = 2500;

/* ── Wire helpers (contract envelope shapes, local on purpose) ─────────────── */

async function apiError(res: Response): Promise<CompbirdApiError> {
  let message: string | undefined;
  let code: string | undefined;
  try {
    const data = (await res.json()) as { error?: unknown; code?: unknown };
    if (typeof data?.error === "string") message = data.error;
    if (typeof data?.code === "string") code = data.code;
  } catch {
    /* non-JSON body — generic message */
  }
  return new CompbirdApiError(res.status, message, code);
}

async function createRun(items: ParsedEntry[]): Promise<string> {
  const res = await fetch("/api/compbird/portfolio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
    cache: "no-store",
  });
  if (!res.ok) throw await apiError(res);
  const data = (await res.json()) as { ok?: boolean; runId?: string };
  if (!data?.ok || !data.runId) throw new CompbirdApiError(500, "Malformed response.");
  return data.runId;
}

async function fetchRun(id: string, signal?: AbortSignal): Promise<PortfolioRun> {
  const res = await fetch(`/api/compbird/portfolio?id=${encodeURIComponent(id)}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw await apiError(res);
  const data = (await res.json()) as { ok?: boolean; run?: PortfolioRun };
  if (!data?.ok || !data.run) throw new CompbirdApiError(500, "Malformed response.");
  return data.run;
}

async function fetchRuns(signal?: AbortSignal): Promise<PortfolioRunSummary[]> {
  const res = await fetch("/api/compbird/portfolio", { cache: "no-store", signal });
  if (!res.ok) throw await apiError(res);
  const data = (await res.json()) as { ok?: boolean; runs?: PortfolioRunSummary[] };
  return data?.runs ?? [];
}

async function deleteRun(id: string): Promise<void> {
  const res = await fetch(`/api/compbird/portfolio?id=${encodeURIComponent(id)}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) throw await apiError(res);
}

/** Trigger a client-side download of the results CSV. */
function downloadCsv(run: PortfolioRun) {
  const blob = new Blob([buildResultsCsv(run.items)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = portfolioCsvFilename();
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function PortfolioStudio({ pro }: { pro: boolean }) {
  const [runs, setRuns] = useState<PortfolioRunSummary[]>([]);
  // Until the first runs fetch settles, history is UNKNOWN — the input panel
  // treats unknown as "has runs" so a returning user never sees the first-visit
  // empty state flash before their strip loads. FREE never fetches (the panel
  // sits behind the upsell blur), so it counts as settled immediately.
  const [runsLoaded, setRunsLoaded] = useState(false);
  const [run, setRun] = useState<PortfolioRun | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [loadingRun, setLoadingRun] = useState(false);
  const [sort, setSort] = useState<EstimateSort>("none");

  // One-shot guard so a failed run only toasts once per arrival.
  const failedToastFor = useRef<string | null>(null);

  const refreshRuns = useCallback(() => {
    if (!pro) {
      setRunsLoaded(true);
      return;
    }
    fetchRuns()
      .then((rs) => {
        setRuns(rs);
        setRunsLoaded(true);
      })
      .catch(() => {
        // The strip just doesn't refresh — never toast a background list. For
        // the empty-state decision a failed first fetch reads as "no history".
        setRunsLoaded(true);
      });
  }, [pro]);

  useEffect(() => {
    refreshRuns();
  }, [refreshRuns]);

  // ── Poll the active run every 2.5s until it settles ─────────────────────
  useEffect(() => {
    if (!activeId) return;
    let stopped = false;
    let timer: number | undefined;
    const ctrl = new AbortController();

    async function tick(first: boolean) {
      try {
        const r = await fetchRun(activeId!, ctrl.signal);
        if (stopped) return;
        setRun(r);
        setLoadingRun(false);
        if (r.status === "running") {
          timer = window.setTimeout(() => void tick(false), POLL_MS);
          return;
        }
        // Settled: surface failure once, refresh the strip either way.
        if (r.status === "failed" && failedToastFor.current !== r.id) {
          failedToastFor.current = r.id;
          toast.error("Portfolio run failed — no results for this run.");
        }
        refreshRuns();
      } catch (e) {
        if (stopped || (e instanceof DOMException && e.name === "AbortError")) return;
        setLoadingRun(false);
        if (first) {
          toast.error(e instanceof CompbirdApiError ? e.message : "Couldn't load that run.");
          setActiveId(null);
          setRun(null);
        } else {
          // Mid-run blip: keep what we have and try again next beat.
          timer = window.setTimeout(() => void tick(false), POLL_MS);
        }
      }
    }

    void tick(true);
    return () => {
      stopped = true;
      ctrl.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeId, refreshRuns]);

  // ── Actions ──────────────────────────────────────────────────────────────
  const startRun = useCallback(
    async (items: ParsedEntry[]) => {
      if (starting) return;
      setStarting(true);
      try {
        const runId = await createRun(items);
        setSort("none");
        setRun(null);
        setLoadingRun(true);
        setActiveId(runId);
        refreshRuns();
      } catch (e) {
        const msg =
          e instanceof CompbirdApiError
            ? e.code === "pro_required"
              ? "Portfolio comping is part of Pro — $20/mo."
              : e.message
            : "Couldn't start the portfolio run.";
        toast.error(msg);
      } finally {
        setStarting(false);
      }
    },
    [starting, refreshRuns],
  );

  const pickRun = useCallback(
    (id: string) => {
      if (id === activeId) return;
      setSort("none");
      setRun(null);
      setLoadingRun(true);
      setActiveId(id);
    },
    [activeId],
  );

  const removeRun = useCallback(
    async (id: string) => {
      try {
        await deleteRun(id);
        setRuns((rs) => rs.filter((r) => r.id !== id));
        if (id === activeId) {
          setActiveId(null);
          setRun(null);
        }
      } catch (e) {
        toast.error(e instanceof CompbirdApiError ? e.message : "Couldn't delete that run.");
      }
    },
    [activeId],
  );

  const toggleSort = useCallback(() => {
    setSort((s) => (s === "none" ? "desc" : s === "desc" ? "asc" : "none"));
  }, []);

  const running = run?.status === "running";

  return (
    <div className="flex flex-col gap-8">
      <PortfolioInputPanel
        pro={pro}
        busy={starting || running === true}
        hasRuns={(pro && !runsLoaded) || runs.length > 0 || activeId !== null}
        onRun={(items) => void startRun(items)}
      />

      {pro ? (
        <RunsStrip
          runs={runs}
          activeId={activeId}
          busy={starting}
          onPick={pickRun}
          onDelete={(id) => void removeRun(id)}
        />
      ) : null}

      {/* ── Results panel ───────────────────────────────────────────────── */}
      {activeId && (run || loadingRun) ? (
        <div
          className="rounded-2xl border border-border bg-card/70 p-5 sm:p-7"
          aria-busy={running === true}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* aria-live on the PERSISTENT wrapper (not the conditional <p>) so
                the region exists before its first update and progress beats
                actually announce. */}
            <div className="flex flex-col gap-1" aria-live="polite">
              <span className="cb-eyebrow text-muted-foreground">Results</span>
              {run ? (
                <p className="text-sm text-foreground">
                  {running ? (
                    <>
                      <span className="font-data font-medium text-[var(--cb-ember-text)]">
                        {run.completed} of {run.total}
                      </span>{" "}
                      comped
                    </>
                  ) : run.status === "failed" ? (
                    <span className="text-[var(--negative-foreground)]">Run failed.</span>
                  ) : (
                    <>
                      <span className="font-data font-medium">{run.completed} of {run.total}</span>{" "}
                      comped
                    </>
                  )}
                </p>
              ) : (
                <span className="skeleton-shimmer inline-block h-4 w-28 rounded-md" aria-hidden />
              )}
            </div>
            {run && run.items.some((i) => i.status === "done") ? (
              <button
                type="button"
                onClick={() => downloadCsv(run)}
                className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3.5 py-2 text-xs font-medium text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
              >
                <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" aria-hidden>
                  <path
                    d="M8 2v8m0 0 3-3m-3 3L5 7M3 11v2a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-2"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                Export CSV
              </button>
            ) : null}
          </div>

          {/* live progress bar while the run executes */}
          {run && running ? (
            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={run.total}
              aria-valuenow={run.completed}
              aria-label="Portfolio run progress"
              className="mt-4 h-1 overflow-hidden rounded-full bg-secondary/70"
            >
              <div
                className="h-full rounded-full bg-[var(--cb-ember)] transition-[width] duration-700"
                style={{ width: `${run.total ? Math.round((run.completed / run.total) * 100) : 0}%` }}
              />
            </div>
          ) : null}

          <div className="mt-5">
            {run ? (
              <PortfolioResultsTable items={run.items} sort={sort} onToggleSort={toggleSort} />
            ) : (
              // First fetch of a picked run — table-shaped shimmer.
              <div className="flex flex-col gap-2.5" aria-hidden>
                {[88, 76, 82, 70].map((w, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="skeleton-shimmer h-4 rounded-md" style={{ width: `${w}%` }} />
                    <span className="skeleton-shimmer h-4 w-20 shrink-0 rounded-md" />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
