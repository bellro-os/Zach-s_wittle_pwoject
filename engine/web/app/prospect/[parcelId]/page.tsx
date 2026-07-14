import Link from "next/link";
import { ArrowLeft, ExternalLink, Sparkles } from "lucide-react";
import { db } from "@/lib/data/db";
import { getProspect } from "@/lib/data/prospects";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LeadTypeBadge } from "@/components/queue/lead-type-badge";
import { ScoreCircle } from "@/components/queue/score-circle";
import { openerFor } from "@/lib/data/call-scripts";
import { kMoney } from "@/lib/utils";
import { ProspectNotes } from "@/components/prospect/prospect-notes";
import { FadeIn } from "@/components/ratified-ui";

interface PageProps {
  params: Promise<{ parcelId: string }>;
  searchParams: Promise<{ county?: string }>;
}

export default async function ProspectPage({ params, searchParams }: PageProps) {
  const { parcelId: raw } = await params;
  const parcelId = decodeURIComponent(raw);
  const { county = "" } = await searchParams;

  const [prospect, notes] = await Promise.all([
    getProspect(parcelId, county),
    db.prospectNote.findMany({
      where: { parcelId, ...(county ? { county: county.toUpperCase() } : {}) },
      orderBy: { timestamp: "desc" },
    }),
  ]);

  // The prospect may not be in seller_scores.csv (e.g. low-score parcels);
  // still render the notes view so the user can record what they know.
  const fallbackCounty = (county || "").toUpperCase();

  return (
    <div className="space-y-5">
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-emerald-300 hover:underline"
      >
        <ArrowLeft className="size-4" /> back to queue
      </Link>

      {prospect ? (
        <FadeIn>
          <Card className="bg-grid-fade relative overflow-hidden p-6">
          <div className="pointer-events-none absolute -top-24 right-1/4 h-64 w-64 rounded-full bg-emerald-500/15 blur-[120px]" />
          <div className="relative flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-4 flex-1 min-w-0">
              <ScoreCircle score={prospect.score} />
              <div className="min-w-0 flex-1">
                <h1 className="text-3xl font-semibold tracking-tight text-white">{prospect.siteAddr || "—"}</h1>
                <div className="text-slate-400 text-sm mt-1">
                  {prospect.owner}
                  {prospect.subdivision ? ` · ${prospect.subdivision}` : ""}
                  {prospect.county ? ` · ${prospect.county}` : ""}
                  <span className="ml-2 font-mono text-xs text-slate-500">parcel {prospect.parcelId}</span>
                </div>
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                  <LeadTypeBadge leadType={prospect.leadType} />
                  {prospect.topSignals.slice(0, 3).map((s) => (
                    <Badge key={s.key} variant="secondary" className="text-[10px]">
                      {s.label}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Link
                href={`/property/${encodeURIComponent(prospect.parcelId)}?county=${prospect.county}`}
              >
                <Button variant="outline" size="sm">
                  Full property page <ExternalLink className="size-3" />
                </Button>
              </Link>
              <Link
                href={`/clients/new?from=${encodeURIComponent(prospect.parcelId)}&county=${prospect.county}&owner=${encodeURIComponent(prospect.owner)}&addr=${encodeURIComponent(prospect.siteAddr)}`}
              >
                <Button size="sm">
                  <Sparkles className="size-3.5" /> Convert to client
                </Button>
              </Link>
            </div>
          </div>
          </Card>
        </FadeIn>
      ) : (
        <FadeIn>
          <Card className="bg-grid-fade relative overflow-hidden p-6">
            <div className="pointer-events-none absolute -top-20 right-1/4 h-56 w-56 rounded-full bg-emerald-500/15 blur-[120px]" />
            <h1 className="relative text-2xl font-semibold tracking-tight text-white">
              Parcel <span className="font-mono">{parcelId}</span>
            </h1>
            <p className="relative text-sm text-slate-400 mt-2">
              This parcel isn&apos;t in the current seller-scores feed (low score or
              absent). You can still capture notes about it here.
            </p>
          </Card>
        </FadeIn>
      )}

      {prospect && (
        <FadeIn>
          <Card className="p-5">
            <h2 className="font-semibold text-white mb-2">Conversation opener</h2>
            <p className="italic text-sm text-slate-300 border-l-2 border-emerald-400 pl-3">
              &ldquo;{openerFor(prospect)}&rdquo;
            </p>
          </Card>
        </FadeIn>
      )}

      <ProspectNotes
        parcelId={parcelId}
        county={(prospect?.county || fallbackCounty || "").toString()}
        notes={notes}
      />

      {prospect && (
        <FadeIn>
          <Card className="p-5">
            <h2 className="font-semibold text-white mb-3">Signal breakdown</h2>
            <div className="flex flex-wrap gap-1">
              {prospect.positiveSignals.map((s) => (
                <Badge key={s.key} variant="info" className="text-xs">
                  {s.label}{" "}
                  <span className="opacity-70 font-bold">+{s.points}</span>
                </Badge>
              ))}
              {prospect.negativeSignals.map((s) => (
                <Badge key={s.key} variant="danger" className="text-xs">
                  {s.label}{" "}
                  <span className="opacity-70 font-bold">
                    {s.points > 0 ? `+${s.points}` : s.points}
                  </span>
                </Badge>
              ))}
            </div>
            <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <Stat label="Assessed" value={kMoney(prospect.assessedTotal)} />
              <Stat label="Equity" value={kMoney(prospect.estimatedEquity)} />
              <Stat label="Last sale" value={prospect.lastSaleDate || "—"} />
              <Stat label="Tenure" value={prospect.tenureYears ? `${prospect.tenureYears.toFixed(1)}y` : "—"} />
            </div>
          </Card>
        </FadeIn>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/8 bg-ink-950/70 p-3">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
        {label}
      </div>
      <div className="font-semibold tabular-nums text-sm text-white">{value}</div>
    </div>
  );
}
