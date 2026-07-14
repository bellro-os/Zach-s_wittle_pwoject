import Link from "next/link";
import { Pencil } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { kMoney } from "@/lib/utils";
import { AddDealModal } from "@/components/clients/add-deal-modal";
import { DealStageSelect } from "@/components/pipeline/deal-stage-select";
import { EditDealForm } from "@/components/pipeline/edit-deal-form";
import { LeadTypeBadge } from "@/components/queue/lead-type-badge";
import { leadTypeLabel } from "@/lib/data/lead-types";
import { FadeIn, SectionHeading, Accent, CountUp } from "@/components/ratified-ui";

const STAGES = ["lead", "listing", "showing", "offer", "contract", "closing", "closed"];
/** Sell-side deals in these stages are on-market inventory ("active listings"). */
const ON_MARKET = new Set(["listing", "showing", "offer"]);

export default async function PipelinePage() {
  const [deals, clients] = await Promise.all([
    db.deal.findMany({
      where: { deletedAt: null },
      orderBy: { created: "desc" },
    }),
    db.client.findMany({
      where: { deletedAt: null },
      select: { id: true, displayId: true, name: true },
      orderBy: { name: "asc" },
    }),
  ]);
  const clientById = new Map(clients.map((c) => [c.id, c.name]));
  const byStage: Record<string, typeof deals> = Object.fromEntries(
    STAGES.map((s) => [s, []]),
  );
  for (const d of deals) {
    const s = d.stage.toLowerCase();
    if (byStage[s]) byStage[s].push(d);
    else byStage[s] = [d];
  }
  const totals = Object.fromEntries(
    STAGES.map((s) => [
      s,
      {
        count: (byStage[s] || []).length,
        dollars: (byStage[s] || []).reduce(
          (sum, d) => sum + (d.listPrice ?? 0),
          0,
        ),
      },
    ]),
  );

  // Sub-counts by lead_type within the Lead column — surfaces what's hot.
  const leadTypeCounts = new Map<string, number>();
  for (const d of byStage["lead"] || []) {
    if (!d.leadType) continue;
    leadTypeCounts.set(d.leadType, (leadTypeCounts.get(d.leadType) ?? 0) + 1);
  }
  const leadTypeBreakdown = [...leadTypeCounts.entries()].sort(
    (a, b) => b[1] - a[1],
  );

  // Active-listing inventory: sell-side deals on the market (listing volume,
  // at list price — kept separate from pending and closed volume).
  const activeListings = deals.filter(
    (d) => d.side.toLowerCase() === "sell" && ON_MARKET.has(d.stage.toLowerCase()),
  );
  const listingVolume = activeListings.reduce(
    (sum, d) => sum + (d.listPrice ?? 0),
    0,
  );

  return (
    <div className="space-y-8">
      {/* Header */}
      <FadeIn>
        <div className="bg-grid-fade relative overflow-hidden rounded-2xl border border-white/10 bg-ink-900/60 p-6 sm:p-8">
          <div className="pointer-events-none absolute -top-24 left-1/3 h-64 w-64 rounded-full bg-emerald-500/15 blur-[120px]" />
          <div className="relative flex items-end justify-between gap-6 flex-wrap">
            <div className="flex flex-col gap-3">
              <span className="inline-flex w-fit items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
                Pipeline
              </span>
              <h1 className="text-balance text-4xl font-semibold leading-[1.05] tracking-tight text-white sm:text-5xl">
                Every deal, <Accent>start to close</Accent>
              </h1>
            </div>
            <div className="flex items-center gap-5">
              <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-right">
                <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">
                  Active listings
                </div>
                <div className="text-2xl font-semibold tracking-tight text-white tabular-nums">
                  <CountUp to={activeListings.length} />
                  <span className="mx-1.5 text-slate-600">·</span>
                  {kMoney(listingVolume)}
                </div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500">
                  list volume
                </div>
              </div>
              <AddDealModal />
            </div>
          </div>
        </div>
      </FadeIn>

      <FadeIn className="grid grid-cols-2 lg:grid-cols-7 gap-3">
        {STAGES.map((s) => (
          <Card key={s} className="p-3 gap-2">
            <div className="flex items-center justify-between">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                {s}
              </h2>
              <Badge variant="secondary">{totals[s].count}</Badge>
            </div>
            <div className="text-xs text-slate-500 tabular-nums">
              {kMoney(totals[s].dollars)}
            </div>
            {s === "lead" && leadTypeBreakdown.length > 0 && (
              <div className="text-[10px] text-slate-500 leading-relaxed">
                {leadTypeBreakdown.map(([lt, n], i) => (
                  <span key={lt}>
                    {i > 0 && <span className="opacity-50"> · </span>}
                    <span>
                      {leadTypeLabel(lt)}: <span className="font-semibold tabular-nums text-emerald-300">{n}</span>
                    </span>
                  </span>
                ))}
              </div>
            )}
            <div className="space-y-2">
              {(byStage[s] || []).map((d) => (
                <div
                  key={d.id}
                  className="rounded-xl border border-white/8 bg-ink-950/70 p-2 text-xs space-y-1 transition-colors hover:border-emerald-500/25"
                >
                  <Link
                    href={`/pipeline/${d.displayId}`}
                    className="block hover:opacity-80"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-semibold text-white truncate">
                        {d.clientId
                          ? clientById.get(d.clientId) || "—"
                          : "—"}
                      </div>
                      <span className="text-slate-500 font-mono text-[10px]">
                        {d.displayId}
                      </span>
                    </div>
                    <div className="text-slate-400 truncate">
                      {d.property}
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400">{d.side}</span>
                      <span className="font-semibold tabular-nums text-white">
                        {kMoney(d.listPrice)}
                      </span>
                    </div>
                  </Link>
                  {d.leadType && (
                    <div className="pt-0.5">
                      <LeadTypeBadge leadType={d.leadType} />
                    </div>
                  )}
                  {d.parcelId && (
                    <Link
                      href={`/prospect/${encodeURIComponent(d.parcelId)}${d.county ? `?county=${encodeURIComponent(d.county)}` : ""}`}
                      className="inline-block text-[10px] text-slate-500 hover:text-emerald-300 hover:underline"
                    >
                      via prospect →
                    </Link>
                  )}
                  <div className="flex items-center gap-1">
                    <div className="flex-1 min-w-0">
                      <DealStageSelect
                        dealId={d.displayId}
                        currentStage={d.stage}
                        stages={STAGES}
                      />
                    </div>
                    <EditDealForm
                      deal={d}
                      clients={clients}
                      trigger={
                        <button
                          type="button"
                          title="Edit deal"
                          className="shrink-0 inline-flex items-center justify-center size-7 rounded-md border border-white/10 text-slate-400 transition-colors hover:border-emerald-500/25 hover:text-emerald-300 hover:bg-emerald-500/10"
                        >
                          <Pencil className="size-3" />
                        </button>
                      }
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </FadeIn>
    </div>
  );
}
