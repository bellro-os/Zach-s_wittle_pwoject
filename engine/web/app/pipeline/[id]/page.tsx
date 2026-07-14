import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Calendar, DollarSign, Briefcase, FileText, Activity, MapPin } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ConfirmDelete } from "@/components/ui/confirm-delete";
import { DealStageSelect } from "@/components/pipeline/deal-stage-select";
import { EditDealForm } from "@/components/pipeline/edit-deal-form";
import { LeadTypeBadge } from "@/components/queue/lead-type-badge";
import { kMoney, money } from "@/lib/utils";
import { deleteDeal } from "@/app/actions";
import { FadeIn } from "@/components/ratified-ui";

const STAGES = ["lead", "listing", "showing", "offer", "contract", "closing", "closed", "lost"];

const STAGE_TONE: Record<string, "secondary" | "info" | "success" | "warning" | "danger"> = {
  lead: "secondary",
  listing: "info",
  showing: "info",
  offer: "info",
  contract: "warning",
  closing: "warning",
  closed: "success",
  lost: "danger",
};

export default async function DealDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [deal, clients] = await Promise.all([
    db.deal.findUnique({
      where: { displayId: id },
      include: {
        client: { select: { id: true, displayId: true, name: true, category: true } },
        stageHistory: { orderBy: { changedAt: "desc" } },
      },
    }),
    db.client.findMany({
      where: { deletedAt: null },
      select: { id: true, displayId: true, name: true },
      orderBy: { name: "asc" },
    }),
  ]);
  if (!deal || deal.deletedAt) notFound();

  const commission =
    deal.listPrice && deal.estCommissionPct
      ? deal.listPrice * (deal.estCommissionPct / 100)
      : null;

  return (
    <div className="space-y-5">
      <Link
        href="/pipeline"
        className="inline-flex items-center gap-1 text-sm text-emerald-300 hover:underline"
      >
        <ArrowLeft className="size-4" /> back to pipeline
      </Link>

      {/* Hero */}
      <FadeIn>
        <Card className="bg-grid-fade relative overflow-hidden p-6">
          <div className="pointer-events-none absolute -top-24 right-1/4 h-64 w-64 rounded-full bg-emerald-500/15 blur-[120px]" />
          <div className="relative flex items-start justify-between gap-6 flex-wrap">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-3xl font-semibold tracking-tight text-white flex items-center gap-2">
                <Briefcase className="size-6 text-emerald-300" />
                Deal {deal.displayId}
              </h1>
              <Badge variant={STAGE_TONE[deal.stage] ?? "secondary"}>
                {deal.stage}
              </Badge>
              <Badge variant="secondary">{deal.side}</Badge>
              {deal.leadType && <LeadTypeBadge leadType={deal.leadType} />}
            </div>
            <div className="mt-3 text-lg font-semibold text-white">{deal.property}</div>
            {deal.parcelId && (
              <div className="mt-1 text-xs text-slate-400 inline-flex items-center gap-1.5">
                <MapPin className="size-3" />
                <span className="font-mono">{deal.parcelId}</span>
                {deal.county && <span>· {deal.county}</span>}
                <Link
                  href={`/prospect/${encodeURIComponent(deal.parcelId)}${deal.county ? `?county=${encodeURIComponent(deal.county)}` : ""}`}
                  className="ml-2 text-emerald-300 hover:underline"
                >
                  View original prospect →
                </Link>
              </div>
            )}
            {deal.client ? (
              <Link
                href={`/clients/${deal.client.id}`}
                className="text-sm text-emerald-300 hover:underline mt-1 inline-block"
              >
                {deal.client.name} ({deal.client.displayId})
              </Link>
            ) : (
              <p className="text-sm text-slate-500 mt-1 italic">
                Unlinked deal — no client attached
              </p>
            )}
          </div>

          <div className="flex items-center gap-2">
            <EditDealForm deal={deal} clients={clients} />
            <ConfirmDelete
              action={deleteDeal}
              fields={{ displayId: deal.displayId }}
              title={`Delete deal ${deal.displayId}?`}
              description="This soft-deletes the deal. Stage history and linked records are preserved."
            />
          </div>
          </div>
        </Card>
      </FadeIn>

      {/* Quick stats */}
      <FadeIn className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="List / sale price" value={money(deal.listPrice)} Icon={DollarSign} />
        <Stat label="Commission %" value={deal.estCommissionPct ? `${deal.estCommissionPct}%` : "—"} />
        <Stat label="Est. commission" value={commission ? money(commission) : "—"} />
        <Stat
          label="Expected close"
          value={
            deal.expectedClose ? deal.expectedClose.toISOString().slice(0, 10) : "—"
          }
          Icon={Calendar}
        />
      </FadeIn>

      {/* Stage change */}
      <FadeIn>
        <Card className="p-5">
          <h2 className="font-semibold text-white mb-3 inline-flex items-center gap-2">
            <Activity className="size-4 text-emerald-300" /> Change stage
          </h2>
          <DealStageSelect
            dealId={deal.displayId}
            currentStage={deal.stage}
            stages={STAGES}
          />
        </Card>
      </FadeIn>

      {/* Stage history */}
      <FadeIn>
        <Card className="p-5">
          <h2 className="font-semibold text-white mb-3">Stage history</h2>
          {deal.stageHistory.length === 0 ? (
            <p className="text-sm text-slate-500 italic">
              No stage changes recorded yet — change the stage above to start the history.
            </p>
          ) : (
            <ol className="relative border-l-2 border-white/10 ml-3 space-y-3">
              {deal.stageHistory.map((s) => (
                <li key={s.id} className="ml-5 relative">
                  <span className="absolute -left-7 top-1 size-6 rounded-full bg-ink-800 border-2 border-emerald-500/25 flex items-center justify-center text-xs text-emerald-300">
                    ●
                  </span>
                  <div className="flex items-center gap-2 text-sm flex-wrap">
                    <Badge variant={STAGE_TONE[s.stage] ?? "secondary"}>{s.stage}</Badge>
                    {s.notes && (
                      <span className="text-slate-400 text-xs">{s.notes}</span>
                    )}
                    <span className="ml-auto text-xs text-slate-500 tabular-nums">
                      {s.changedAt.toISOString().replace("T", " ").slice(0, 16)}
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </FadeIn>

      {/* Notes */}
      {deal.notes && (
        <FadeIn>
          <Card className="p-5">
            <h2 className="font-semibold text-white mb-2 inline-flex items-center gap-2">
              <FileText className="size-4 text-emerald-300" /> Notes
            </h2>
            <p className="text-sm whitespace-pre-wrap text-slate-300">{deal.notes}</p>
          </Card>
        </FadeIn>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  Icon,
}: {
  label: string;
  value: React.ReactNode;
  Icon?: typeof DollarSign;
}) {
  return (
    <Card className="p-3 gap-1">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold flex items-center gap-1">
        {Icon && <Icon className="size-3 text-emerald-300/70" />}
        {label}
      </div>
      <div className="font-semibold text-base tabular-nums text-white">{value}</div>
    </Card>
  );
}

// Force the page to be a server component so kMoney is in scope (silences ts).
void kMoney;
