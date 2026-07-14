import Link from "next/link";
import {
  TrendingUp,
  DollarSign,
  CircleDollarSign,
  Briefcase,
  Home as HomeIcon,
  Clock,
  Tag,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getProductionStats, type DealRow } from "@/lib/data/analytics";
import { money, kMoney } from "@/lib/utils";
import { FadeIn, SpotCard, CountUp, Accent } from "@/components/ratified-ui";

export default async function AnalyticsPage() {
  const s = await getProductionStats();
  const peakMonthCommission = Math.max(1, ...s.monthly.map((m) => m.commission));

  return (
    <div className="space-y-5">
      <FadeIn className="bg-grid-fade -mx-4 -mt-4 px-4 pb-6 pt-8 sm:-mx-6 sm:px-6">
        <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
          <TrendingUp className="size-3.5" />
          Agent analytics
        </span>
        <h1 className="mt-4 max-w-3xl text-balance text-3xl font-semibold leading-[1.08] tracking-tight text-white sm:text-4xl">
          Production &amp; commission, <Accent>start to close</Accent>
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">
          The full picture across closed, pending, and active deals.
        </p>
      </FadeIn>

      {/* Headline */}
      <FadeIn className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <BigStat
          label="Closed YTD"
          value={s.closedCountYtd}
          countTo={s.closedCountYtd}
          sub={`${kMoney(s.closedVolumeYtd)} volume`}
          Icon={Briefcase}
        />
        <BigStat
          label="Net commission YTD"
          value={money(s.ytdNetCommission)}
          sub={`${money(s.earnedCommissionYtd)} gross − ${money(s.ytdSplitPaid)} split`}
          Icon={DollarSign}
          tone="success"
        />
        <BigStat
          label="Pending commission (net)"
          value={money(s.pendingCommissionNet)}
          sub={`${money(s.pendingCommission)} gross − ${money(s.pendingSplit)} split · ${s.pending.length} under contract`}
          Icon={Clock}
          tone="warning"
        />
        <BigStat
          label="Listing volume"
          value={money(s.listingsVolume)}
          sub={`${s.listings.length} active ${s.listings.length === 1 ? "listing" : "listings"} · at list price`}
          Icon={Tag}
        />
      </FadeIn>

      {/* ---- By year — gross / brokerage split / net ---- */}
      <SectionTitle Icon={CircleDollarSign} title="By year — gross, brokerage split, net" />
      <FadeIn>
      <Card className="p-5 gap-3">
        {s.byYear.length === 0 ? (
          <p className="text-sm text-(--color-muted-foreground) italic">
            No closed deals yet.
          </p>
        ) : (
          <div className="space-y-4">
            {s.byYear.map((y) => {
              const capPct = Math.min(100, (y.splitPaid / s.annualCap) * 100);
              // Softer-yellow extension: pending split stacked on the closed
              // portion, clamped so the two segments never exceed 100%.
              const pendingPct = Math.min(
                100 - capPct,
                (y.pendingSplit / s.annualCap) * 100,
              );
              const projectedTotal = y.splitPaid + y.pendingSplit;
              return (
                <div key={y.year} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-3 flex-wrap text-sm">
                    <span className="font-semibold tabular-nums">
                      {y.year}
                      <span className="ml-2 text-xs font-normal text-(--color-muted-foreground)">
                        {y.closedCount} {y.closedCount === 1 ? "close" : "closes"}
                      </span>
                    </span>
                    <span className="tabular-nums">
                      <span className="text-(--color-muted-foreground)">gross</span>{" "}
                      {money(y.gross)}
                      <span className="text-(--color-muted-foreground)">
                        {y.usesCapModel ? "  ·  brokerage split " : "  ·  team split "}
                      </span>
                      <span className="text-(--color-destructive)">
                        −{money(y.splitPaid)}
                      </span>
                      <span className="text-(--color-muted-foreground)">
                        {"  ·  net "}
                      </span>
                      <span className="font-bold text-(--color-success)">
                        {money(y.net)}
                      </span>
                    </span>
                  </div>
                  {y.usesCapModel ? (
                    /* 25% / $20k cap progress — solid = split paid on closed
                       deals, softer extension = projected split on pending. */
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 rounded-full bg-(--color-secondary)/50 overflow-hidden flex">
                        <div
                          className={
                            y.capReached
                              ? "h-full bg-(--color-success)"
                              : "h-full bg-(--color-warning)"
                          }
                          style={{ width: `${capPct}%` }}
                        />
                        {pendingPct > 0 && (
                          <div
                            className="h-full bg-(--color-warning)/35"
                            title={`${money(y.pendingSplit)} projected split from pending deals`}
                            style={{ width: `${pendingPct}%` }}
                          />
                        )}
                      </div>
                      <span className="text-[10px] text-(--color-muted-foreground) tabular-nums shrink-0 w-56 text-right">
                        {y.capReached
                          ? `${money(s.annualCap)} cap met — keeping 100%`
                          : y.pendingSplit > 0
                            ? `${money(y.splitPaid)} closed + ${money(y.pendingSplit)} pending · ${money(projectedTotal)} of ${money(s.annualCap)}`
                            : `${money(y.splitPaid)} of ${money(s.annualCap)} cap`}
                      </span>
                    </div>
                  ) : (
                    <p className="text-[10px] text-(--color-muted-foreground)">
                      Flat team split (ended 2025-12-31) — figure from the Bellro
                      year-end Agent Net Summary.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <p className="text-[10px] text-(--color-muted-foreground)">
          From 2026: brokerage split is {Math.round(s.splitRate * 100)}% of each
          closed commission, capped at {money(s.annualCap)} per calendar year —
          after the cap you keep 100%. Through 2025 a flat team split applied
          instead.
        </p>
      </Card>
      </FadeIn>

      {/* ---- Closed production ---- */}
      <SectionTitle Icon={TrendingUp} title="Closed production" />

      <FadeIn>
      <Card className="p-5 gap-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Closings — trailing 12 months</h3>
          <span className="text-xs text-(--color-muted-foreground)">
            commission per month
          </span>
        </div>
        {s.monthly.every((m) => m.closedCount === 0) ? (
          <p className="text-sm text-(--color-muted-foreground) italic py-6 text-center">
            No closed deals in the last 12 months yet.
          </p>
        ) : (
          <div className="space-y-1.5">
            {s.monthly.map((m) => (
              <div key={m.month} className="flex items-center gap-3 text-xs">
                <span className="w-14 shrink-0 text-(--color-muted-foreground) tabular-nums">
                  {m.label}
                </span>
                <div className="flex-1 h-6 rounded bg-(--color-secondary)/40 relative overflow-hidden">
                  <div
                    className="h-full bg-(--color-success)/30 border-r-2 border-(--color-success)"
                    style={{
                      width: `${Math.max(
                        m.commission > 0 ? 4 : 0,
                        (m.commission / peakMonthCommission) * 100,
                      )}%`,
                    }}
                  />
                  <span className="absolute inset-y-0 left-2 flex items-center gap-2 font-medium">
                    {m.closedCount > 0 && (
                      <>
                        <span className="tabular-nums">
                          {m.closedCount}{" "}
                          {m.closedCount === 1 ? "close" : "closes"}
                        </span>
                        <span className="text-(--color-muted-foreground) tabular-nums">
                          {money(m.commission)}
                        </span>
                      </>
                    )}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
      </FadeIn>

      <FadeIn>
      <Card className="p-5 gap-3">
        <h3 className="font-semibold text-sm inline-flex items-center gap-2">
          <HomeIcon className="size-4 text-emerald-300/80" />
          By side
        </h3>
        {s.bySide.length === 0 ? (
          <p className="text-sm text-(--color-muted-foreground) italic">
            No deals yet.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-(--color-muted-foreground) text-left border-b border-(--color-border)">
                  <th className="py-2 font-semibold">Side</th>
                  <th className="py-2 font-semibold text-right">Deals</th>
                  <th className="py-2 font-semibold text-right">Closed</th>
                  <th className="py-2 font-semibold text-right">Closed volume</th>
                  <th className="py-2 font-semibold text-right">Earned comm.</th>
                  <th className="py-2 font-semibold text-right">Projected (net)</th>
                </tr>
              </thead>
              <tbody>
                {s.bySide.map((row) => (
                  <tr
                    key={row.side}
                    className="border-b border-(--color-border) last:border-b-0"
                  >
                    <td className="py-2">
                      <Badge variant="secondary" className="capitalize">
                        {row.side}
                      </Badge>
                    </td>
                    <td className="py-2 text-right tabular-nums">{row.total}</td>
                    <td className="py-2 text-right tabular-nums">{row.closed}</td>
                    <td className="py-2 text-right tabular-nums">
                      {kMoney(row.closedVolume)}
                    </td>
                    <td className="py-2 text-right tabular-nums text-(--color-success)">
                      {money(row.earnedCommission)}
                    </td>
                    <td className="py-2 text-right tabular-nums text-(--color-muted-foreground)">
                      {money(row.projectedCommissionNet)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      </FadeIn>

      {/* ---- Pending sales ---- */}
      <SectionTitle Icon={Clock} title="Pending sales — under contract" />
      <FadeIn>
      <Card className="p-0 overflow-hidden">
        <DealTable
          rows={s.pending}
          emptyText="No deals under contract right now."
          dateLabel="Expected close"
          dateField="expectedClose"
          totalVolume={s.pendingVolume}
          totalCommission={s.pendingCommission}
        />
      </Card>
      </FadeIn>

      {/* ---- Current listings ---- */}
      <SectionTitle Icon={Tag} title="Current listings — actively marketed" />
      <FadeIn>
      <Card className="p-0 overflow-hidden">
        <DealTable
          rows={s.listings}
          emptyText="No active listings. Sell-side deals in the listing / showing / offer stages appear here."
          dateLabel="Listed"
          dateField="created"
          totalVolume={s.listingsVolume}
          totalCommission={null}
        />
      </Card>
      </FadeIn>

      <p className="text-xs text-(--color-muted-foreground)">
        Commission uses the actual figure when known (e.g. imported brokerage
        data); otherwise list price × commission %. Edit any deal on the{" "}
        <Link href="/pipeline" className="text-(--color-info) hover:underline">
          pipeline
        </Link>{" "}
        to correct it.
      </p>
    </div>
  );
}

function SectionTitle({
  Icon,
  title,
}: {
  Icon: typeof DollarSign;
  title: string;
}) {
  return (
    <FadeIn className="pt-2" y={16}>
      <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.16em] text-emerald-300">
        <Icon className="size-3.5" />
        {title}
      </span>
    </FadeIn>
  );
}

function DealTable({
  rows,
  emptyText,
  dateLabel,
  dateField,
  totalVolume,
  totalCommission,
}: {
  rows: DealRow[];
  emptyText: string;
  dateLabel: string;
  dateField: "expectedClose" | "created";
  totalVolume: number;
  totalCommission: number | null;
}) {
  if (rows.length === 0) {
    return (
      <div className="p-8 text-center text-sm text-(--color-muted-foreground) italic">
        {emptyText}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[680px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-(--color-muted-foreground) text-left border-b border-(--color-border)">
            <th className="py-2 px-4 font-semibold">Deal</th>
            <th className="py-2 px-4 font-semibold">Property</th>
            <th className="py-2 px-4 font-semibold">Side</th>
            <th className="py-2 px-4 font-semibold text-right">Price</th>
            <th className="py-2 px-4 font-semibold">{dateLabel}</th>
            <th className="py-2 px-4 font-semibold text-right">Commission</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.displayId}
              className="border-b border-(--color-border) hover:bg-(--color-accent)/40"
            >
              <td className="py-2 px-4">
                <Link
                  href={`/pipeline/${r.displayId}`}
                  className="font-mono text-xs text-(--color-info) hover:underline"
                >
                  {r.displayId}
                </Link>
              </td>
              <td className="py-2 px-4 max-w-[280px] truncate" title={r.property}>
                {r.property}
              </td>
              <td className="py-2 px-4">
                <Badge variant="secondary" className="capitalize">
                  {r.side}
                </Badge>
              </td>
              <td className="py-2 px-4 text-right tabular-nums">
                {money(r.price)}
              </td>
              <td className="py-2 px-4 tabular-nums text-(--color-muted-foreground)">
                {r[dateField] || "—"}
              </td>
              <td className="py-2 px-4 text-right tabular-nums">
                {money(r.commission)}
                {r.estimated && r.commission > 0 && (
                  <span
                    className="ml-1 text-[10px] text-(--color-muted-foreground)"
                    title="Estimated from commission %"
                  >
                    est
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="font-semibold border-t-2 border-(--color-border)">
            <td className="py-2 px-4" colSpan={3}>
              {rows.length} {rows.length === 1 ? "deal" : "deals"}
            </td>
            <td className="py-2 px-4 text-right tabular-nums">
              {money(totalVolume)}
            </td>
            <td className="py-2 px-4"></td>
            <td className="py-2 px-4 text-right tabular-nums">
              {totalCommission == null ? "—" : money(totalCommission)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function BigStat({
  label,
  value,
  countTo,
  sub,
  Icon,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  countTo?: number;
  sub: string;
  Icon: typeof DollarSign;
  tone?: "success" | "warning";
}) {
  const valueTone =
    tone === "success"
      ? "text-emerald-300"
      : tone === "warning"
        ? "text-amber-300"
        : "text-white";
  return (
    <SpotCard className="p-4">
      <div className="flex flex-col gap-1">
        <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 flex items-center gap-1.5">
          <Icon className="size-3 text-emerald-300/80" />
          {label}
        </div>
        <div className={`text-2xl font-semibold tracking-tight tabular-nums ${valueTone}`}>
          {countTo != null ? <CountUp to={countTo} /> : value}
        </div>
        <div className="text-xs text-slate-400">{sub}</div>
      </div>
    </SpotCard>
  );
}
