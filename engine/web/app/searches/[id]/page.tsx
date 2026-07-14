import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  Sparkles,
  Bookmark,
  Pause,
  Play,
  Trash,
  Pencil,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  getSavedSearch,
  summarizeCriteria,
} from "@/lib/data/saved-searches";
import { kMoney } from "@/lib/utils";
import {
  toggleSavedSearchPause,
  deleteSavedSearchAction,
  runSavedSearchesAction,
} from "@/app/actions";
import { redirect } from "next/navigation";

interface PageProps {
  params: Promise<{ id: string }>;
}

function fmtDate(d: Date | null): string {
  if (!d) return "never";
  return d.toLocaleString();
}

export default async function SavedSearchDetailPage({ params }: PageProps) {
  const { id } = await params;
  const data = await getSavedSearch(id);
  if (!data) notFound();
  const { summary: s, results } = data;
  const newCount = results.filter((r) => r.isNew).length;

  async function togglePause(formData: FormData) {
    "use server";
    await toggleSavedSearchPause(formData);
  }
  async function deleteSearch(formData: FormData) {
    "use server";
    const r = await deleteSavedSearchAction(formData);
    if (r.success) redirect("/searches");
  }
  async function runNow() {
    "use server";
    await runSavedSearchesAction();
  }

  return (
    <div className="space-y-5">
      <Link
        href="/searches"
        className="inline-flex items-center gap-1 text-sm text-(--color-info) hover:underline"
      >
        <ArrowLeft className="size-4" /> back to searches
      </Link>

      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold inline-flex items-center gap-2">
            <Bookmark className="size-5" />
            {s.name}
            <span className="text-sm font-mono text-(--color-muted-foreground)">
              {s.displayId}
            </span>
            {s.isPaused && (
              <Badge variant="outline" className="text-[10px]">
                <Pause className="size-2.5" /> paused
              </Badge>
            )}
          </h1>
          {s.clientName && (
            <p className="text-sm text-(--color-muted-foreground) mt-1">
              For client:{" "}
              <Link
                href={`/clients/${s.clientId}`}
                className="font-medium text-(--color-foreground) hover:underline"
              >
                {s.clientName}
              </Link>
            </p>
          )}
          {s.description && (
            <p className="text-sm text-(--color-muted-foreground) mt-1 max-w-2xl">
              {s.description}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <form action={runNow}>
            <Button variant="outline" size="sm" type="submit">
              <RefreshCw className="size-3.5" /> Run now
            </Button>
          </form>
          <Link href={`/searches/${s.id}/edit`}>
            <Button variant="outline" size="sm">
              <Pencil className="size-3.5" />
              Edit
            </Button>
          </Link>
          <form action={togglePause}>
            <input type="hidden" name="id" value={s.id} />
            <input type="hidden" name="paused" value={s.isPaused ? "false" : "true"} />
            <Button variant="outline" size="sm" type="submit">
              {s.isPaused ? (
                <>
                  <Play className="size-3.5" /> Resume
                </>
              ) : (
                <>
                  <Pause className="size-3.5" /> Pause
                </>
              )}
            </Button>
          </form>
          <form action={deleteSearch}>
            <input type="hidden" name="id" value={s.id} />
            <Button variant="destructive" size="sm" type="submit">
              <Trash className="size-3.5" /> Delete
            </Button>
          </form>
        </div>
      </div>

      {/* Criteria card */}
      <Card className="p-4 gap-2">
        <div className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground)">
          Criteria
        </div>
        <div className="text-sm">
          {summarizeCriteria(s.criteria, s.centerLabel)}
        </div>
        <div className="text-[11px] text-(--color-muted-foreground) mt-1">
          Last run: <span className="font-medium">{fmtDate(s.lastRunAt)}</span>{" "}
          · {results.length} current matches · {newCount} new since last run
        </div>
        {s.lastError && (
          <div className="mt-2 rounded-md bg-(--color-destructive)/10 border border-(--color-destructive)/30 px-3 py-2 text-xs text-(--color-destructive) inline-flex items-center gap-1.5">
            <AlertTriangle className="size-3.5" />
            Last run errored: {s.lastError}
          </div>
        )}
      </Card>

      {/* Results table */}
      <Card className="p-0 overflow-hidden">
        <div className="border-b border-(--color-border) px-4 py-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Current matches</h2>
          {newCount > 0 && (
            <Badge variant="success" className="text-[10px]">
              <Sparkles className="size-2.5" />
              {newCount} new
            </Badge>
          )}
        </div>
        {results.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-(--color-muted-foreground) italic">
            {s.lastRunAt
              ? "No matches in the most recent run."
              : "Not run yet — wait for the next hourly run, or kick off `python tasks.py mls-saved-searches`."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[900px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-(--color-muted-foreground) text-left border-b border-(--color-border)">
                  <Th>Address</Th>
                  <Th align="right">Price</Th>
                  <Th align="right">Sqft</Th>
                  <Th align="right">Beds/Baths</Th>
                  <Th align="right">Acres</Th>
                  <Th align="right">Built</Th>
                  <Th align="right">DOM</Th>
                  <Th align="right">Distance</Th>
                  <Th>School / Listed by</Th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b border-(--color-border) hover:bg-(--color-accent)/40"
                  >
                    <Td>
                      <div className="font-medium inline-flex items-center gap-1.5">
                        {r.isNew && (
                          <Badge
                            variant="success"
                            className="text-[9px] py-0 px-1.5"
                          >
                            <Sparkles className="size-2.5" />
                            new
                          </Badge>
                        )}
                        {r.address ?? "—"}
                      </div>
                      <div className="text-[10px] text-(--color-muted-foreground)">
                        {r.city ?? "—"}
                      </div>
                    </Td>
                    <Td align="right">{r.price ? kMoney(r.price) : "—"}</Td>
                    <Td align="right">
                      {r.sqft ? r.sqft.toLocaleString() : "—"}
                    </Td>
                    <Td align="right">
                      {r.beds ?? "—"}br / {r.fullBaths ?? "—"}ba
                    </Td>
                    <Td align="right">
                      {r.acres != null ? r.acres.toFixed(2) : "—"}
                    </Td>
                    <Td align="right">{r.yearBuilt ?? "—"}</Td>
                    <Td align="right">
                      {r.feedDom != null ? `${r.feedDom}d` : "—"}
                    </Td>
                    <Td align="right">
                      {r.milesToCenter != null
                        ? `${r.milesToCenter.toFixed(1)} mi`
                        : "—"}
                    </Td>
                    <Td>
                      <div className="text-xs">{r.highSchool ?? "—"}</div>
                      <div className="text-[10px] text-(--color-muted-foreground) truncate max-w-[200px]">
                        {r.listOffice ?? ""}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-[10px] text-(--color-muted-foreground)">
        Auto-refresh: hourly via Windows Task Scheduler running{" "}
        <code>python tasks.py mls-hourly</code>. Manually:{" "}
        <code>python tasks.py mls-saved-searches</code>.
      </p>
    </div>
  );
}

function Th({
  align,
  children,
}: {
  align?: "right";
  children: React.ReactNode;
}) {
  return (
    <th
      className={`py-2 px-3 font-semibold ${align === "right" ? "text-right" : ""}`}
    >
      {children}
    </th>
  );
}

function Td({
  align,
  children,
}: {
  align?: "right";
  children: React.ReactNode;
}) {
  return (
    <td
      className={`py-2 px-3 ${align === "right" ? "text-right tabular-nums" : ""}`}
    >
      {children}
    </td>
  );
}
