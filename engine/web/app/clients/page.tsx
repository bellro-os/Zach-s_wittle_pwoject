import Link from "next/link";
import { Users, Cake, Home, AlertCircle } from "lucide-react";
import { listClientsWithMeta, crmStats, allClientsLite } from "@/lib/data/crm";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ClientModal } from "@/components/clients/client-modal";
import { HotAndFollowupsBanner } from "@/components/shared/hot-and-followups";
import { cn } from "@/lib/utils";
import { formatPhone } from "@/lib/format";
import { FadeIn, Accent, CountUp, SpotCard } from "@/components/ratified-ui";

const CATEGORIES = [
  { value: "A", label: "Tier A — VIP", tone: "success" as const },
  { value: "B", label: "Tier B — Active", tone: "info" as const },
  { value: "C", label: "Tier C — Cold", tone: "secondary" as const },
];

const SOURCES = [
  "referral",
  "past_client",
  "SOI",
  "cold",
  "website",
  "open_house",
  "other",
];

function lcBadge(days: number | null) {
  if (days == null)
    return { variant: "secondary" as const, label: "Never" };
  if (days <= 30) return { variant: "success" as const, label: `${days}d` };
  if (days <= 90) return { variant: "warning" as const, label: `${days}d` };
  return { variant: "danger" as const, label: `${days}d` };
}

export default async function ClientsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const tierFilter = ([] as string[]).concat(sp.tier ?? []);
  const sourceFilter = ([] as string[]).concat(sp.source ?? []);
  const view = sp.view ?? "";

  const sort = (Array.isArray(sp.sort) ? sp.sort[0] : sp.sort) ?? "";
  const dir = (Array.isArray(sp.dir) ? sp.dir[0] : sp.dir) ?? "desc";

  const [allClients, stats, lite] = await Promise.all([
    listClientsWithMeta(),
    crmStats(),
    allClientsLite(),
  ]);
  const staleTierA = allClients.filter(
    (c) => c.category === "A" && c.isStale,
  ).length;

  let clients = allClients;
  if (tierFilter.length)
    clients = clients.filter((c) => c.category && tierFilter.includes(c.category));
  if (sourceFilter.length)
    clients = clients.filter((c) => c.source && sourceFilter.includes(c.source));
  if (view === "stale") clients = clients.filter((c) => c.isStale);
  if (view === "stale_tier_a")
    clients = clients.filter((c) => c.isStale && c.category === "A");
  if (view === "anniversaries")
    clients = clients.filter(
      (c) => c.anniversaryIn != null && c.anniversaryIn <= 30,
    );
  if (view === "birthdays")
    clients = clients.filter(
      (c) => c.birthdayIn != null && c.birthdayIn <= 7,
    );

  // Apply column sorting
  if (sort) {
    const sortKey = sort as
      | "name"
      | "tier"
      | "lastContact"
      | "touches"
      | "deals"
      | "created";
    const asc = dir === "asc";
    const cmp = (a: typeof clients[number], b: typeof clients[number]) => {
      let d = 0;
      switch (sortKey) {
        case "name":
          d = a.name.localeCompare(b.name);
          break;
        case "tier":
          d = (a.category ?? "Z").localeCompare(b.category ?? "Z");
          break;
        case "lastContact":
          d = (a.lastContactDays ?? Number.MAX_SAFE_INTEGER) -
              (b.lastContactDays ?? Number.MAX_SAFE_INTEGER);
          break;
        case "touches":
          d = a._count.touches - b._count.touches;
          break;
        case "deals":
          d = a._count.deals - b._count.deals;
          break;
        case "created":
          d = a.created.getTime() - b.created.getTime();
          break;
      }
      return asc ? d : -d;
    };
    clients = [...clients].sort(cmp);
  }

  return (
    <div className="space-y-6">
      {/* Header + add button */}
      <FadeIn>
        <div className="bg-grid-fade relative overflow-hidden rounded-2xl border border-white/10 bg-ink-900/60 p-6 sm:p-8">
          <div className="pointer-events-none absolute -top-24 left-1/4 h-64 w-64 rounded-full bg-emerald-500/15 blur-[120px]" />
          <div className="relative flex items-end justify-between gap-6 flex-wrap">
            <div className="flex flex-col gap-3">
              <span className="inline-flex w-fit items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
                <Users className="size-3.5" /> Sphere of influence
              </span>
              <h1 className="text-balance text-4xl font-semibold leading-[1.05] tracking-tight text-white sm:text-5xl">
                Your <Accent>relationships</Accent>
                <span className="ml-3 align-middle text-lg font-normal text-slate-500 tabular-nums">
                  {clients.length}
                  {clients.length !== allClients.length && ` / ${allClients.length}`}
                </span>
              </h1>
            </div>
            <ClientModal mode="add" allClients={lite} />
          </div>
        </div>
      </FadeIn>

      <HotAndFollowupsBanner compact />

      {/* Quick-jump stat tiles */}
      <FadeIn className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatTile
          icon={Users}
          label="Total"
          value={stats.totalClients}
          href="/clients"
          active={!view && !tierFilter.length && !sourceFilter.length}
        />
        <StatTile
          icon={Home}
          label="Anniversaries in 30d"
          value={stats.anniversariesIn30d}
          href="/clients?view=anniversaries"
          active={view === "anniversaries"}
          tone="success"
        />
        <StatTile
          icon={Cake}
          label="Birthdays in 7d"
          value={stats.birthdaysIn7d}
          href="/clients?view=birthdays"
          active={view === "birthdays"}
          tone="warning"
        />
        <StatTile
          icon={AlertCircle}
          label={`Stale ≥90d`}
          value={stats.staleCount}
          href="/clients?view=stale"
          active={view === "stale"}
          tone="danger"
        />
        <StatTile
          icon={AlertCircle}
          label="Stale Tier A"
          value={staleTierA}
          href="/clients?view=stale_tier_a"
          active={view === "stale_tier_a"}
          tone="danger"
        />
      </FadeIn>

      {/* Tier + source chip filters */}
      <FadeIn>
        <Card className="p-4 gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 mb-1.5">
              Tier
            </div>
            <div className="flex flex-wrap gap-1.5">
              {CATEGORIES.map((c) => {
                const active = tierFilter.includes(c.value);
                const nextTiers = active
                  ? tierFilter.filter((x) => x !== c.value)
                  : [...tierFilter, c.value];
                return (
                  <Link
                    key={c.value}
                    href={`/clients?${qs({ tier: nextTiers, source: sourceFilter, view: view as string })}`}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-all",
                      active
                        ? "border-emerald-500/40 bg-emerald-500/10"
                        : "border-white/10 bg-ink-950/40 hover:border-emerald-500/25 hover:bg-emerald-500/10",
                    )}
                  >
                    <Badge variant={c.tone} className="px-1.5 py-0">
                      {c.label}
                    </Badge>
                  </Link>
                );
              })}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 mb-1.5">
              Source
            </div>
            <div className="flex flex-wrap gap-1.5">
              {SOURCES.map((s) => {
                const active = sourceFilter.includes(s);
                const next = active
                  ? sourceFilter.filter((x) => x !== s)
                  : [...sourceFilter, s];
                return (
                  <Link
                    key={s}
                    href={`/clients?${qs({ tier: tierFilter, source: next, view: view as string })}`}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-xs font-medium transition-all",
                      active
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                        : "border-white/10 bg-ink-950/40 text-slate-300 hover:border-emerald-500/25 hover:bg-emerald-500/10",
                    )}
                  >
                    {s.replace(/_/g, " ")}
                  </Link>
                );
              })}
            </div>
          </div>
        </Card>
      </FadeIn>

      {/* Table */}
      <FadeIn>
        <Card className="overflow-hidden py-0">
        {clients.length === 0 ? (
          <div className="p-12 text-center text-slate-500">
            {allClients.length === 0 ? (
              <>No clients yet. Click <strong className="text-emerald-300">+ Add client</strong> to start.</>
            ) : (
              <>No clients match the current filters.</>
            )}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-ink-800/60 text-slate-500 text-[10px] uppercase tracking-wider">
              <tr>
                <th className="px-3 py-2 text-left w-16">ID</th>
                <SortableHeader
                  label="Name"
                  field="name"
                  currentSort={sort}
                  currentDir={dir}
                  tier={tierFilter}
                  source={sourceFilter}
                  view={view as string}
                />
                <SortableHeader
                  label="Tier"
                  field="tier"
                  currentSort={sort}
                  currentDir={dir}
                  tier={tierFilter}
                  source={sourceFilter}
                  view={view as string}
                />
                <th className="px-3 py-2 text-left">Source</th>
                <th className="px-3 py-2 text-left">Phone</th>
                <th className="px-3 py-2 text-left">Email</th>
                <SortableHeader
                  label="Last contact"
                  field="lastContact"
                  currentSort={sort}
                  currentDir={dir}
                  tier={tierFilter}
                  source={sourceFilter}
                  view={view as string}
                />
                <SortableHeader
                  label="Touches"
                  field="touches"
                  currentSort={sort}
                  currentDir={dir}
                  tier={tierFilter}
                  source={sourceFilter}
                  view={view as string}
                />
                <SortableHeader
                  label="Deals"
                  field="deals"
                  currentSort={sort}
                  currentDir={dir}
                  tier={tierFilter}
                  source={sourceFilter}
                  view={view as string}
                />
                <th className="px-3 py-2 text-left">Anniv.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/8">
              {clients.map((c) => {
                const lc = lcBadge(c.lastContactDays);
                return (
                  <tr
                    key={c.id}
                    className="hover:bg-emerald-500/5 cursor-pointer transition-colors"
                  >
                    <td className="px-3 py-2 font-mono text-xs text-slate-500">
                      <Link
                        href={`/clients/${c.id}`}
                        className="block"
                      >
                        {c.displayId}
                      </Link>
                    </td>
                    <td className="px-3 py-2 font-semibold text-white">
                      <Link
                        href={`/clients/${c.id}`}
                        className="block hover:text-emerald-300 hover:underline"
                      >
                        {c.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2">
                      {c.category && (
                        <Badge
                          variant={
                            c.category === "A"
                              ? "success"
                              : c.category === "B"
                                ? "info"
                                : "secondary"
                          }
                          className="text-[10px]"
                        >
                          {c.category}
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {c.source && (
                        <span className="text-slate-400">
                          {c.source.replace(/_/g, " ")}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-slate-300">{formatPhone(c.phone)}</td>
                    <td className="px-3 py-2 text-emerald-300/90 text-xs">
                      {c.email}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={lc.variant} className="text-[10px]">
                        {lc.label}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs tabular-nums text-slate-300">
                      {c._count.touches}
                    </td>
                    <td className="px-3 py-2 text-xs tabular-nums text-slate-300">
                      {c._count.deals}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {c.anniversaryIn != null && c.anniversaryIn <= 30 && (
                        <span
                          className={cn(
                            "tabular-nums font-semibold",
                            c.anniversaryIn <= 7
                              ? "text-emerald-300"
                              : "text-slate-500",
                          )}
                        >
                          {c.anniversaryIn === 0
                            ? "today"
                            : `${c.anniversaryIn}d`}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        </Card>
      </FadeIn>
    </div>
  );
}

function StatTile({
  icon: Icon,
  label,
  value,
  href,
  active,
  tone,
}: {
  icon: typeof Users;
  label: string;
  value: number;
  href: string;
  active?: boolean;
  tone?: "success" | "warning" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "text-emerald-300"
      : tone === "warning"
        ? "text-amber-400"
        : tone === "danger"
          ? "text-rose-300"
          : "text-emerald-300";
  return (
    <SpotCard
      className={cn(
        active ? "border-emerald-500/40 bg-emerald-500/10" : "",
      )}
    >
      <Link href={href} className="flex items-start gap-3 p-4">
        <Icon className={cn("size-5", value > 0 ? toneClass : "text-slate-500")} />
        <div className="flex-1">
          <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">
            {label}
          </div>
          <div
            className={cn(
              "text-2xl font-semibold tracking-tight tabular-nums",
              value > 0 ? toneClass : "text-white",
            )}
          >
            <CountUp to={value} />
          </div>
        </div>
      </Link>
    </SpotCard>
  );
}

function qs(o: Record<string, string | string[]>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (Array.isArray(v)) for (const x of v) if (x) p.append(k, x);
    else if (v) p.append(k, v);
  }
  return p.toString();
}

function SortableHeader({
  label,
  field,
  currentSort,
  currentDir,
  tier,
  source,
  view,
}: {
  label: string;
  field: string;
  currentSort: string;
  currentDir: string;
  tier: string[];
  source: string[];
  view: string;
}) {
  const active = currentSort === field;
  const nextDir = active && currentDir === "desc" ? "asc" : active ? "" : "desc";
  // Inline URL construction so we can sanity-check the params.
  const params = new URLSearchParams();
  for (const c of tier) if (c) params.append("tier", c);
  for (const s of source) if (s) params.append("source", s);
  if (view) params.set("view", view);
  if (nextDir) {
    params.set("sort", field);
    params.set("dir", nextDir);
  }
  const href = `/clients?${params.toString()}`;
  return (
    <th className="px-3 py-2 text-left">
      <Link
        href={href}
        className={cn(
          "inline-flex items-center gap-1 transition-colors",
          active
            ? "text-emerald-300 font-semibold"
            : "hover:text-slate-200",
        )}
      >
        {label}
        {active && (
          <span className="text-[10px]">
            {currentDir === "asc" ? "▲" : "▼"}
          </span>
        )}
      </Link>
    </th>
  );
}
