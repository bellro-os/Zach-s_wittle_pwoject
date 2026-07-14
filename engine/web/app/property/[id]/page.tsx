import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Phone } from "lucide-react";
import { getProspect } from "@/lib/data/prospects";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LeadTypeBadge } from "@/components/queue/lead-type-badge";
import { ScoreCircle } from "@/components/queue/score-circle";
import { openerFor } from "@/lib/data/call-scripts";
import { kMoney, money } from "@/lib/utils";
import { FadeIn, SpotCard } from "@/components/ratified-ui";

export default async function PropertyPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ county?: string }>;
}) {
  const { id } = await params;
  const { county = "" } = await searchParams;
  const prospect = await getProspect(decodeURIComponent(id), county);
  if (!prospect) notFound();

  const calls = await db.call.findMany({
    where: { parcelId: prospect.parcelId },
    orderBy: { timestamp: "desc" },
    take: 50,
  });

  return (
    <div className="space-y-6">
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-emerald-300 transition-colors hover:text-emerald-200"
      >
        <ArrowLeft className="size-4" /> back to queue
      </Link>

      {/* Property hero */}
      <FadeIn>
        <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-ink-900/60 px-6 py-7">
          <div className="bg-grid-fade pointer-events-none absolute inset-0" aria-hidden />
          <div
            className="pointer-events-none absolute -top-20 right-0 h-56 w-80 rounded-full bg-emerald-500/15 blur-[120px]"
            aria-hidden
          />
          <div className="relative flex items-start gap-4">
            <ScoreCircle score={prospect.score} />
            <div className="min-w-0 flex-1">
              <h1 className="text-balance text-2xl font-semibold tracking-tight text-white">
                {prospect.siteAddr || "—"}
              </h1>
              <div className="mt-1 text-sm text-slate-400">
                {prospect.owner}
                {prospect.subdivision ? ` · ${prospect.subdivision}` : ""}
                {prospect.county ? ` · ${prospect.county}` : ""}
                <span className="ml-2 font-mono text-xs text-slate-500">
                  parcel {prospect.parcelId}
                </span>
              </div>
              <div className="mt-2">
                <LeadTypeBadge leadType={prospect.leadType} />
              </div>
            </div>
          </div>
        </div>
      </FadeIn>

      <FadeIn delay={0.05}>
        <Card className="edge-light border-l-4 border-l-emerald-400 p-5 italic">
          <div className="mb-2 text-[10px] font-semibold uppercase not-italic tracking-wider text-slate-500">
            Conversation opener · {prospect.leadType}
          </div>
          <p className="text-(--color-foreground)">&ldquo;{openerFor(prospect)}&rdquo;</p>
        </Card>
      </FadeIn>

      <FadeIn delay={0.1}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <SpotCard className="p-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Year built</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-white">{prospect.yearBuilt ?? "—"}</div>
          </SpotCard>
          <SpotCard className="p-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Tenure</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-white">
              {prospect.tenureYears ? `${prospect.tenureYears.toFixed(1)}y` : "—"}
            </div>
          </SpotCard>
          <SpotCard className="p-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Last sale</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-white">
              {prospect.lastSaleDate || "—"}
            </div>
            {prospect.lastSalePrice ? (
              <div className="text-xs text-slate-400">
                {money(prospect.lastSalePrice)}
              </div>
            ) : null}
          </SpotCard>
          <SpotCard className="p-3">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Assessed</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-white">{kMoney(prospect.assessedTotal)}</div>
            {prospect.estimatedEquity != null && (
              <div className="text-xs text-slate-400">
                equity {kMoney(prospect.estimatedEquity)}
              </div>
            )}
          </SpotCard>
        </div>
      </FadeIn>

      <FadeIn delay={0.05}>
        <Card className="p-5">
          <h2 className="mb-3 font-semibold text-white">Signal breakdown</h2>
          <div className="flex flex-wrap gap-1">
            {prospect.positiveSignals.map((s) => (
              <Badge key={s.key} variant="info" className="text-xs">
                {s.label} <span className="font-bold opacity-70">+{s.points}</span>
              </Badge>
            ))}
            {prospect.negativeSignals.map((s) => (
              <Badge key={s.key} variant="danger" className="text-xs">
                {s.label} <span className="font-bold opacity-70">{s.points > 0 ? `+${s.points}` : s.points}</span>
              </Badge>
            ))}
          </div>
        </Card>
      </FadeIn>

      <FadeIn delay={0.05}>
        <Card className="p-5">
          <h2 className="mb-3 inline-flex items-center gap-2 font-semibold text-white">
            <Phone className="size-4 text-emerald-300" /> Call history
          </h2>
          {calls.length === 0 ? (
            <p className="text-sm text-slate-400">
              Never called this owner before.
            </p>
          ) : (
            <ul className="divide-y divide-white/10 text-sm">
              {calls.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-3 py-2">
                  <span>
                    <strong className="text-white">{c.outcome}</strong>
                    {c.notes ? ` · ${c.notes}` : ""}
                  </span>
                  <span className="text-xs tabular-nums text-slate-500">
                    {c.timestamp.toISOString().slice(0, 16).replace("T", " ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </FadeIn>
    </div>
  );
}
