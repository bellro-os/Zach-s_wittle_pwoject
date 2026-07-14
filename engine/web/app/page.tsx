import Link from "next/link";
import {
  Phone,
  DoorOpen,
  Flame,
  Clock,
  Briefcase,
  DollarSign,
  Home as HomeIcon,
  Cake,
  AlertCircle,
} from "lucide-react";
import { parseFilters, buildQuery } from "@/lib/filters";
import {
  queryQueue,
  leadTypeCounts,
  knownCounties,
  type QueueFilters,
} from "@/lib/data/prospects";
import { db } from "@/lib/data/db";
import { crmStats } from "@/lib/data/crm";
import { HOT_OUTCOMES } from "@/lib/data/outcomes";
import { Card } from "@/components/ui/card";
import { QueueToolbar } from "@/components/queue/queue-toolbar";
import { QueueTable } from "@/components/queue/queue-table";
import { QueueKeyboard } from "@/components/queue/queue-keyboard";
import { KeyboardHelp } from "@/components/queue/keyboard-help";
import { BulkActionBar } from "@/components/queue/bulk-action-bar";
import { HotAndFollowupsBanner } from "@/components/shared/hot-and-followups";
import {
  FadeIn,
  SectionHeading,
  Accent,
  SpotCard,
  CountUp,
} from "@/components/ratified-ui";
import { cn, kMoney } from "@/lib/utils";

async function quickStats() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const weekStart = new Date(today);
  weekStart.setDate(weekStart.getDate() - weekStart.getDay());
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);

  const [calls, deals, hotCount, dueCount] = await Promise.all([
    db.call.findMany({ select: { timestamp: true, outcome: true } }),
    db.deal.findMany({ select: { stage: true, listPrice: true } }),
    db.call.count({
      where: {
        outcome: { in: [...HOT_OUTCOMES] },
        timestamp: { gte: new Date(Date.now() - 30 * 86_400_000) },
      },
    }),
    db.call.count({
      where: {
        nextFollowup: {
          gte: new Date(),
          lte: new Date(Date.now() + 3 * 86_400_000),
        },
      },
    }),
  ]);

  const callsToday = calls.filter((c) => c.timestamp >= today).length;
  const callsWeek = calls.filter((c) => c.timestamp >= weekStart).length;
  const callsMonth = calls.filter((c) => c.timestamp >= monthStart).length;
  const activeDeals = deals.filter(
    (d) => !["closed", "lost", "dead"].includes(d.stage.toLowerCase()),
  );
  const pipelineDollars = activeDeals.reduce(
    (acc, d) => acc + (d.listPrice ?? 0),
    0,
  );

  return {
    callsToday,
    callsWeek,
    callsMonth,
    activeDeals: activeDeals.length,
    pipelineDollars,
    hotCount,
    followupsDueCount: dueCount,
  };
}

function Metric({
  label,
  value,
  href,
  tone,
  Icon,
}: {
  label: string;
  value: React.ReactNode;
  href?: string;
  /** Emerald for positive/hot, amber for due, rose for stale — defaults to neutral white. */
  tone?: "emerald" | "amber" | "rose";
  Icon?: typeof Phone;
}) {
  const valueCls = cn(
    "text-2xl font-semibold tracking-tight tabular-nums",
    tone === "emerald" && "text-emerald-300",
    tone === "amber" && "text-amber-400",
    tone === "rose" && "text-rose-300",
    !tone && "text-white",
  );
  // CountUp animates whole-number stats; pre-formatted strings (e.g. "$1.2M") render as-is.
  const renderedValue =
    typeof value === "number" ? (
      <CountUp to={value} className={valueCls} />
    ) : (
      <span className={valueCls}>{value}</span>
    );
  const inner = (
    <>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold text-slate-500">
        {Icon && <Icon className="size-3" />}
        {label}
        {href && (
          <span className="ml-auto text-emerald-400/70 transition-transform group-hover:translate-x-0.5">
            →
          </span>
        )}
      </div>
      <div className="mt-1">{renderedValue}</div>
    </>
  );
  const baseCls =
    "flex min-w-[120px] flex-col rounded-xl border border-white/10 bg-ink-900/80 px-4 py-3 transition-colors";
  // Only Links get a hover/cursor affordance — non-link metrics are visibly static.
  return href ? (
    <Link
      href={href}
      className={cn(baseCls, "group cursor-pointer hover:border-emerald-500/25")}
    >
      {inner}
    </Link>
  ) : (
    <div className={cn(baseCls, "cursor-default")}>{inner}</div>
  );
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const filters: QueueFilters = parseFilters(params);

  const [rows, counts, counties, stats, crm] = await Promise.all([
    queryQueue(filters),
    leadTypeCounts(filters.minScore),
    knownCounties(),
    quickStats(),
    crmStats(),
  ]);

  return (
    <div className="space-y-6">
      {/* Page header — blueprint grid + eyebrow/headline */}
      <div className="bg-grid-fade -mx-4 -mt-4 px-4 pt-6 pb-2 sm:-mx-6 sm:px-6">
        <SectionHeading
          align="left"
          eyebrow="Daily workflow"
          title={
            <>
              Work the <Accent>queue</Accent>
            </>
          }
          sub="Your highest-value prospects, ranked and ready to call or knock."
        />
      </div>

      {/* Inline metrics strip */}
      <FadeIn>
        <div className="flex items-stretch gap-3 overflow-x-auto pb-1">
          <Metric label="Calls today" value={stats.callsToday} Icon={Phone} />
          <Metric label="This week" value={stats.callsWeek} />
          <Metric label="This month" value={stats.callsMonth} />
          <Metric label="Active deals" value={stats.activeDeals} href="/pipeline" Icon={Briefcase} />
          <Metric
            label="Pipeline $"
            value={kMoney(stats.pipelineDollars)}
            href="/pipeline"
            Icon={DollarSign}
          />
          <Metric
            label="Hot"
            value={stats.hotCount}
            href={`/?mode=${filters.mode}&min_score=60`}
            Icon={Flame}
            tone={stats.hotCount ? "emerald" : undefined}
          />
          {stats.followupsDueCount > 0 && (
            <Metric
              label="Follow-ups due"
              value={stats.followupsDueCount}
              Icon={Clock}
              tone="amber"
            />
          )}
          {crm.anniversariesIn30d > 0 && (
            <Metric
              label="Anniversaries 30d"
              value={crm.anniversariesIn30d}
              href="/clients?view=anniversaries"
              Icon={HomeIcon}
              tone="emerald"
            />
          )}
          {crm.birthdaysIn7d > 0 && (
            <Metric
              label="Birthdays 7d"
              value={crm.birthdaysIn7d}
              href="/clients?view=birthdays"
              Icon={Cake}
              tone="amber"
            />
          )}
          {crm.staleCount > 0 && (
            <Metric
              label="Stale clients"
              value={crm.staleCount}
              href="/clients?view=stale"
              Icon={AlertCircle}
              tone="rose"
            />
          )}
        </div>
      </FadeIn>

      {/* Mode tabs — preserve all filter state across mode switch */}
      <div className="flex gap-6 border-b border-white/10">
        <Link
          href={`/?${buildQuery(filters, { mode: "call" })}`}
          className={cn(
            "py-3 inline-flex items-center gap-2 text-sm font-semibold border-b-2 transition-colors -mb-px",
            filters.mode === "call"
              ? "border-emerald-400 text-white"
              : "border-transparent text-slate-400 hover:text-white",
          )}
        >
          <Phone className="size-4" />
          Call queue
        </Link>
        <Link
          href={`/?${buildQuery(filters, { mode: "knock" })}`}
          className={cn(
            "py-3 inline-flex items-center gap-2 text-sm font-semibold border-b-2 transition-colors -mb-px",
            filters.mode === "knock"
              ? "border-emerald-400 text-white"
              : "border-transparent text-slate-400 hover:text-white",
          )}
        >
          <DoorOpen className="size-4" />
          Door-knock routes
        </Link>
      </div>

      {/* Hot prospects + follow-ups due — shared component, also on /pipeline + /clients */}
      <HotAndFollowupsBanner />

      {/* Filter toolbar */}
      <FadeIn>
      <Card className="px-5 py-4 gap-3">
        <QueueToolbar
          counts={counts}
          selectedLeadTypes={filters.leadTypes}
          selectedCounties={filters.counties}
          knownCounties={counties}
          minScore={filters.minScore}
          suppressDays={filters.suppressDays}
          sortBy={filters.sortBy}
          maxRows={filters.maxRows}
          ownerTypes={filters.ownerTypes}
          signals={filters.signals}
          skipFlippers={filters.skipFlippers}
          mode={filters.mode}
        />
      </Card>
      </FadeIn>

      {/* Sticky bulk-action bar (appears when ≥1 checkbox checked) */}
      <BulkActionBar mode={filters.mode} />

      {/* Queue table */}
      <FadeIn>
        <QueueTable rows={rows} mode={filters.mode} filters={filters} />
      </FadeIn>

      {/* Keyboard handler + help dialog (client components, no UI footprint) */}
      <QueueKeyboard />
      <KeyboardHelp />
    </div>
  );
}
