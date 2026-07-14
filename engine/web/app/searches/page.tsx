import Link from "next/link";
import {
  Bookmark,
  Plus,
  AlertTriangle,
  Pause,
  Sparkles,
  RefreshCw,
  CalendarClock,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  listSavedSearches,
  summarizeCriteria,
} from "@/lib/data/saved-searches";
import {
  runSavedSearchesAction,
  installHourlyScheduleAction,
} from "@/app/actions";
import {
  isHourlyScheduleInstalled,
  installHourlySchedule,
} from "@/lib/data/saved-searches-runner";
import { FadeIn, SpotCard, CountUp, Accent } from "@/components/ratified-ui";

function fmtAge(d: Date | null): string {
  if (!d) return "never";
  const mins = Math.floor((Date.now() - d.getTime()) / 60_000);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default async function SearchesPage() {
  const [rows, initialSchedule] = await Promise.all([
    listSavedSearches(),
    isHourlyScheduleInstalled(),
  ]);
  // Auto-install on Windows if missing. Silent on success, surfaces an error
  // banner if PowerShell rejected it (e.g. group policy blocking Register-
  // ScheduledTask). Cheap once installed — the check just queries the OS.
  let schedule = initialSchedule;
  let autoInstallError: string | null = null;
  if (!schedule.installed && process.platform === "win32") {
    const r = await installHourlySchedule();
    if (r.ok) {
      schedule = await isHourlyScheduleInstalled();
    } else {
      autoInstallError = r.error ?? r.output.slice(-200) ?? "unknown error";
    }
  }
  const totalNew = rows.reduce((n, r) => n + r.newSinceLastRun, 0);

  async function runAll() {
    "use server";
    await runSavedSearchesAction();
  }
  async function installSchedule() {
    "use server";
    await installHourlyScheduleAction();
  }

  return (
    <div className="space-y-5">
      <FadeIn className="bg-grid-fade -mx-4 -mt-4 px-4 pb-6 pt-8 sm:-mx-6 sm:px-6">
        <div className="flex items-end justify-between flex-wrap gap-3">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
              <Bookmark className="size-3.5" /> Saved searches
            </span>
            <h1 className="mt-4 max-w-3xl text-balance text-3xl font-semibold leading-[1.08] tracking-tight text-white sm:text-4xl">
              Listings that find <Accent>you</Accent>
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">
              Re-run hourly. New matches surface the moment they hit the MLS.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {rows.length > 0 && (
              <form action={runAll}>
                <Button variant="outline" size="sm" type="submit">
                  <RefreshCw className="size-3.5" /> Run all now
                </Button>
              </form>
            )}
            <Link
              href="/searches/new"
              className="group inline-flex items-center justify-center gap-2 rounded-full bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-ink-950 shadow-[0_0_28px_rgba(16,185,129,0.35)] transition-all duration-300 hover:bg-emerald-300 hover:shadow-[0_0_44px_rgba(16,185,129,0.5)]"
            >
              <Plus className="size-4" /> New search
            </Link>
          </div>
        </div>
      </FadeIn>

      {/* Schedule status — only shown if something needs attention. Steady-
          state is silent (hourly task is installed and humming). */}
      {!schedule.installed && autoInstallError && (
        <div className="flex items-center justify-between rounded-md border border-(--color-destructive)/40 bg-(--color-destructive)/10 px-3 py-2 text-xs">
          <span className="inline-flex items-center gap-1.5 text-(--color-destructive)">
            <AlertTriangle className="size-3.5" />
            Auto-install of the hourly task failed: {autoInstallError}
          </span>
          <form action={installSchedule}>
            <Button variant="default" size="sm" type="submit">
              <CalendarClock className="size-3" /> Retry
            </Button>
          </form>
        </div>
      )}

      <FadeIn className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Saved searches"
          value={rows.length}
          countTo={rows.length}
        />
        <Stat
          label="Active"
          value={rows.filter((r) => !r.isPaused).length}
          countTo={rows.filter((r) => !r.isPaused).length}
        />
        <Stat
          label="New matches"
          value={totalNew}
          countTo={totalNew}
          sub="since most-recent run per search"
          tone="success"
        />
        <Stat
          label="Last run"
          value={
            rows[0]?.lastRunAt
              ? fmtAge(
                  rows
                    .filter((r) => r.lastRunAt)
                    .sort(
                      (a, b) =>
                        (b.lastRunAt?.getTime() ?? 0) -
                        (a.lastRunAt?.getTime() ?? 0),
                    )[0]?.lastRunAt ?? null,
                )
              : "never"
          }
          sub="auto-runs hourly via mls-hourly"
        />
      </FadeIn>

      {rows.length === 0 ? (
        <FadeIn>
        <Card className="p-8 text-center flex flex-col items-center gap-3">
          <p className="text-slate-400 max-w-md">
            No saved searches yet. Saved searches re-run hourly and flag new
            matches as they hit the MLS.
          </p>
          <Link
            href="/searches/new"
            className="group inline-flex items-center justify-center gap-2 rounded-full bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-ink-950 shadow-[0_0_28px_rgba(16,185,129,0.35)] transition-all duration-300 hover:bg-emerald-300 hover:shadow-[0_0_44px_rgba(16,185,129,0.5)]"
          >
            <Plus className="size-4" /> Create your first search
          </Link>
        </Card>
        </FadeIn>
      ) : (
        <FadeIn className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {rows.map((r) => (
            <Link
              key={r.id}
              href={`/searches/${r.id}`}
              className="spot-card block rounded-2xl border border-white/10 bg-ink-900/80 p-4 transition-colors duration-300 hover:border-emerald-500/25"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="font-semibold inline-flex items-center gap-1.5">
                    {r.isPaused && (
                      <Pause className="size-3 text-slate-500" />
                    )}
                    {r.name}
                    <span className="text-[10px] font-mono text-slate-500">
                      {r.displayId}
                    </span>
                  </div>
                  {r.clientName && (
                    <div className="text-[11px] text-slate-400 mt-0.5">
                      For: <span className="font-medium text-slate-300">{r.clientName}</span>
                    </div>
                  )}
                  <div className="text-xs text-slate-400 mt-1">
                    {summarizeCriteria(r.criteria, r.centerLabel)}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <div className="text-2xl font-semibold tracking-tight tabular-nums leading-none text-white">
                    {r.lastMatchCount}
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">
                    matches
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between mt-3 text-[11px] text-slate-500">
                <div className="inline-flex items-center gap-2">
                  {r.newSinceLastRun > 0 && (
                    <Badge variant="success" className="text-[10px] py-0 px-1.5">
                      <Sparkles className="size-2.5" />
                      {r.newSinceLastRun} new
                    </Badge>
                  )}
                  {r.lastError && (
                    <Badge variant="destructive" className="text-[10px] py-0 px-1.5">
                      <AlertTriangle className="size-2.5" />
                      error
                    </Badge>
                  )}
                </div>
                <span>last run {fmtAge(r.lastRunAt)}</span>
              </div>
            </Link>
          ))}
        </FadeIn>
      )}

      <p className="text-[10px] text-(--color-muted-foreground)">
        New searches are run immediately on save. The hourly{" "}
        <code>MLSHourly</code> task re-runs them in the background — install
        once via the banner above. NEW badge fires when a listing first
        matches a search&apos;s criteria.
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  countTo,
  sub,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  countTo?: number;
  sub?: string;
  tone?: "success";
}) {
  return (
    <SpotCard className="p-4">
      <div className="flex flex-col gap-0.5">
        <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">
          {label}
        </div>
        <div
          className={`text-lg font-semibold tracking-tight tabular-nums ${
            tone === "success" ? "text-emerald-300" : "text-white"
          }`}
        >
          {countTo != null ? <CountUp to={countTo} /> : value}
        </div>
        {sub && <div className="text-[10px] text-slate-400">{sub}</div>}
      </div>
    </SpotCard>
  );
}
