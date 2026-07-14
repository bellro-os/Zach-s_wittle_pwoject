import Link from "next/link";
import { ArrowLeft, MapPin } from "lucide-react";
import { parseFilters } from "@/lib/filters";
import { queryQueue } from "@/lib/data/prospects";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LeadTypeBadge } from "@/components/queue/lead-type-badge";
import { ScoreCircle } from "@/components/queue/score-circle";
import { PrintButton } from "@/components/route/print-button";

interface PageProps {
  params: Promise<{ subdivision: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function WalkingRoutePage({
  params,
  searchParams,
}: PageProps) {
  const { subdivision: rawSub } = await params;
  const sp = await searchParams;
  const subdivision = decodeURIComponent(rawSub);
  const isFullQueue = subdivision === "_queue";

  // Force knock mode for the route — use the existing filter set
  const filters = parseFilters({ ...sp, mode: "knock" });
  filters.maxRows = 200;

  let rows = await queryQueue(filters);

  if (!isFullQueue) {
    rows = rows.filter(
      (r) => (r.subdivision || "").toLowerCase() === subdivision.toLowerCase(),
    );
  }

  const title = isFullQueue
    ? `Door-knock route · top ${rows.length} prospects`
    : `Door-knock route · ${subdivision}`;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap no-print">
        <div>
          <Link
            href="/?mode=knock"
            className="inline-flex items-center gap-1 text-sm text-(--color-info) hover:underline"
          >
            <ArrowLeft className="size-4" /> back to dashboard
          </Link>
          <h1 className="text-2xl font-bold mt-2 inline-flex items-center gap-2">
            <MapPin className="size-5" /> {title}
          </h1>
          <p className="text-sm text-(--color-muted-foreground) mt-1">
            {rows.length} {rows.length === 1 ? "parcel" : "parcels"}, ordered by score
            within subdivision. (Geographic walking-route optimization arrives with
            the MLS integration in Tier 18.)
          </p>
        </div>
        <PrintButton />
      </div>

      {rows.length === 0 ? (
        <Card className="p-12 text-center text-(--color-muted-foreground)">
          No parcels match for this subdivision under the current filters.
        </Card>
      ) : (
        <div className="space-y-3 route-list">
          {rows.map((r, idx) => (
            <Card
              key={`${r.parcelId}-${r.county}`}
              className="route-card p-4 flex items-start gap-4 break-inside-avoid"
            >
              <div className="text-center" style={{ minWidth: 64 }}>
                <div className="text-3xl font-extrabold text-(--color-muted-foreground) leading-none">
                  {idx + 1}
                </div>
                <div className="mt-2 text-xs text-(--color-muted-foreground)">
                  □
                </div>
              </div>

              <div className="flex-1 min-w-0">
                <div className="text-lg font-bold leading-tight">{r.siteAddr}</div>
                <div className="text-sm text-(--color-muted-foreground) mt-0.5">
                  {r.owner}
                  {r.subdivision ? ` · ${r.subdivision}` : ""}
                </div>
                <div className="mt-2 flex items-center gap-2 flex-wrap text-xs">
                  <ScoreCircle score={r.score} size="sm" />
                  <LeadTypeBadge leadType={r.leadType} />
                  {r.topSignals.slice(0, 3).map((s) => (
                    <Badge key={s.key} variant="secondary" className="text-[10px]">
                      {s.label}
                    </Badge>
                  ))}
                </div>
                <div className="text-xs text-(--color-muted-foreground) mt-1">
                  Parcel {r.parcelId} · {r.county}
                  {r.yearBuilt ? ` · built ${r.yearBuilt}` : ""}
                  {r.tenureYears
                    ? ` · ${Math.round(r.tenureYears)}y tenure`
                    : ""}
                </div>
              </div>

              <div className="text-xs text-(--color-muted-foreground) hidden md:block" style={{ minWidth: 240 }}>
                <div className="border-b border-(--color-border) h-5" />
                <div className="border-b border-(--color-border) h-5" />
                <div className="border-b border-(--color-border) h-5" />
                <div className="border-b border-(--color-border) h-5" />
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
