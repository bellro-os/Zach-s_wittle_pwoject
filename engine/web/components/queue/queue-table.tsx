import Link from "next/link";
import {
  Phone,
  DoorOpen,
  Scale,
  ChevronRight,
  ExternalLink,
  MapPin,
  Printer,
} from "lucide-react";
import { ScoreCircle } from "@/components/queue/score-circle";
import { LeadTypeBadge } from "@/components/queue/lead-type-badge";
import { ActionButtons } from "@/components/queue/action-buttons";
import { BulkCheckbox } from "@/components/queue/bulk-checkbox";
import { Badge } from "@/components/ui/badge";
import { cn, kMoney } from "@/lib/utils";
import type { Prospect } from "@/lib/data/prospects";
import { openerFor } from "@/lib/data/call-scripts";
import { daysSince } from "@/lib/utils";
import { db } from "@/lib/data/db";
import { buildQuery } from "@/lib/filters";
import type { QueueFilters } from "@/lib/data/prospects";

type LastContact = {
  daysSince: number | null;
  channel: string | null;
  outcome: string | null;
};

async function loadLastContacts(rows: Prospect[]): Promise<Map<string, LastContact>> {
  const keys = rows.map((r) => ({ parcelId: r.parcelId, county: r.county }));
  if (!keys.length) return new Map();
  const parcelIds = keys.map((k) => k.parcelId);
  const [calls, knocks] = await Promise.all([
    db.call.findMany({
      where: { parcelId: { in: parcelIds } },
      select: { parcelId: true, county: true, outcome: true, timestamp: true },
      orderBy: { timestamp: "desc" },
    }),
    db.doorknock.findMany({
      where: { parcelId: { in: parcelIds } },
      select: { parcelId: true, county: true, outcome: true, timestamp: true },
      orderBy: { timestamp: "desc" },
    }),
  ]);
  const map = new Map<string, LastContact>();
  for (const c of calls) {
    const key = `${c.parcelId}|${c.county.toUpperCase()}`;
    if (!map.has(key)) {
      map.set(key, {
        daysSince: daysSince(c.timestamp),
        channel: "call",
        outcome: c.outcome,
      });
    }
  }
  for (const k of knocks) {
    const key = `${k.parcelId}|${k.county.toUpperCase()}`;
    const existing = map.get(key);
    const ds = daysSince(k.timestamp);
    if (!existing || (ds !== null && (existing.daysSince ?? Infinity) > ds)) {
      map.set(key, { daysSince: ds, channel: "knock", outcome: k.outcome });
    }
  }
  return map;
}

function ChannelIcon({ hint }: { hint: Prospect["channelHint"] }) {
  const cls =
    hint.channel === "call"
      ? "text-(--color-info)"
      : hint.channel === "knock"
        ? "text-(--color-warning)"
        : "text-(--color-muted-foreground)";
  return (
    <span title={hint.reason} className={cn("inline-flex cursor-help", cls)}>
      {hint.channel === "call" ? (
        <Phone className="size-3.5" />
      ) : hint.channel === "knock" ? (
        <DoorOpen className="size-3.5" />
      ) : (
        <Scale className="size-3.5" />
      )}
    </span>
  );
}

function LastContactCell({ lc }: { lc: LastContact | undefined }) {
  if (!lc || lc.daysSince == null) {
    return (
      <Badge variant="secondary" className="text-xs">
        Never
      </Badge>
    );
  }
  const tone =
    lc.daysSince < 7 ? "warning" : lc.daysSince < 30 ? "info" : "success";
  return (
    <Badge variant={tone} className="text-xs">
      {lc.daysSince}d ago
    </Badge>
  );
}

function groupBySubdivision(rows: Prospect[]): Map<string, Prospect[]> {
  const map = new Map<string, Prospect[]>();
  for (const r of rows) {
    const key = (r.subdivision || "").trim() || "(no subdivision)";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(r);
  }
  // Order subdivisions by parcel count desc then avg score desc
  const sorted = [...map.entries()].sort(([, a], [, b]) => {
    if (b.length !== a.length) return b.length - a.length;
    const avgA = a.reduce((s, r) => s + r.score, 0) / a.length;
    const avgB = b.reduce((s, r) => s + r.score, 0) / b.length;
    return avgB - avgA;
  });
  return new Map(sorted);
}

function ProspectRow({
  p,
  mode,
  lastContacts,
}: {
  p: Prospect;
  mode: "call" | "knock";
  lastContacts: Map<string, LastContact>;
}) {
  return (
    <details
      key={`${p.parcelId}-${p.county}`}
      data-row-key={`${p.parcelId}|${p.county}`}
      className="group queue-row data-[active=true]:bg-(--color-accent)/60"
    >
      <summary className="grid grid-cols-[28px_44px_140px_minmax(220px,1.5fr)_minmax(180px,1fr)_80px_90px_minmax(280px,auto)] gap-3 items-center px-4 py-3 cursor-pointer hover:bg-(--color-accent)/40 list-none [&::-webkit-details-marker]:hidden min-w-[1100px]">
        <BulkCheckbox
          parcelId={p.parcelId}
          county={p.county}
          owner={p.owner}
          siteAddr={p.siteAddr}
        />
        <div className="flex flex-col items-center gap-1.5">
          <ScoreCircle score={p.score} />
          <ChannelIcon hint={p.channelHint} />
        </div>
        <div className="flex flex-col items-start gap-1">
          <LeadTypeBadge leadType={p.leadType} title={openerFor(p)} />
          {p.ownerType === "entity" && (
            <span className="text-[10px] text-(--color-muted-foreground) uppercase tracking-wide">
              entity
            </span>
          )}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 min-w-0">
            <div className="font-semibold text-sm truncate" title={p.owner}>
              {p.owner}
            </div>
            {p.otherParcels && p.otherParcels.length > 0 && (
              <Badge
                variant="info"
                className="text-[10px] py-0 px-1.5 shrink-0"
                title={`This owner has ${p.otherParcels.length + 1} parcels — one call covers all of them. Expand row to see siblings.`}
              >
                +{p.otherParcels.length} parcels
              </Badge>
            )}
          </div>
          <Link
            href={`/property/${encodeURIComponent(p.parcelId)}?county=${p.county}`}
            className="text-(--color-info) text-sm hover:underline truncate block"
            target="_blank"
            rel="noreferrer"
          >
            {p.siteAddr}
          </Link>
          <div className="text-xs text-(--color-muted-foreground) mt-0.5">
            {p.county}
            {p.subdivision ? ` · ${p.subdivision}` : ""}
            {p.yearBuilt ? ` · ${p.yearBuilt}` : ""}
            {p.bedrooms ? ` · ${p.bedrooms}BR` : ""}
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {p.topSignals.slice(0, 3).map((s) => (
            <Badge
              key={s.key}
              variant="secondary"
              className="text-[10px] py-0 px-1.5"
            >
              {s.label}
              <span className="ml-0.5 opacity-60 font-bold">+{s.points}</span>
            </Badge>
          ))}
        </div>
        <div className="text-sm">
          {p.tenureYears != null && (
            <div className="font-semibold tabular-nums">
              {Math.round(p.tenureYears)}y
            </div>
          )}
          <div className="text-xs text-(--color-muted-foreground) tabular-nums">
            {kMoney(p.estimatedEquity)}
          </div>
        </div>
        <div>
          <LastContactCell lc={lastContacts.get(`${p.parcelId}|${p.county}`)} />
        </div>
        <div className="flex items-center gap-3 justify-end">
          <ActionButtons prospect={p} mode={mode} />
          <ChevronRight className="size-4 text-(--color-muted-foreground) transition-transform group-open:rotate-90" />
        </div>
      </summary>

      <ProspectWhyPanel p={p} />
    </details>
  );
}

function ProspectWhyPanel({ p }: { p: Prospect }) {
  return (
    <div className="px-4 pb-4 bg-(--color-secondary)/30 border-t border-(--color-border)">
      <div className="rounded-lg bg-(--color-card) border-l-4 border-(--color-primary) p-4 my-3 italic">
        <div className="text-[10px] uppercase tracking-wide not-italic font-semibold text-(--color-muted-foreground) mb-1.5">
          Conversation opener · {p.leadType}
        </div>
        &ldquo;{openerFor(p)}&rdquo;
      </div>
      {p.otherParcels && p.otherParcels.length > 0 && (
        <div className="rounded-lg bg-(--color-card) border border-(--color-info)/40 p-3 mb-3">
          <div className="text-[10px] uppercase tracking-wide font-semibold text-(--color-muted-foreground) mb-2 inline-flex items-center gap-1.5">
            <MapPin className="size-3" />
            Same owner · {p.otherParcels.length} other{" "}
            {p.otherParcels.length === 1 ? "parcel" : "parcels"}
          </div>
          <ul className="space-y-1 text-xs">
            {p.otherParcels.map((o) => (
              <li
                key={`${o.parcelId}|${o.county}`}
                className="flex items-center gap-2 min-w-0"
              >
                <span className="font-mono tabular-nums text-(--color-muted-foreground) text-[10px] shrink-0 w-7">
                  {o.score}
                </span>
                <Link
                  href={`/property/${encodeURIComponent(o.parcelId)}?county=${o.county}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-(--color-info) hover:underline truncate"
                >
                  {o.siteAddr || `Parcel ${o.parcelId}`}
                </Link>
                <span className="text-(--color-muted-foreground) text-[10px] shrink-0">
                  {o.county}
                  {o.subdivision ? ` · ${o.subdivision}` : ""}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-(--color-muted-foreground) mt-2">
            Logging an outcome on this row suppresses all of these too — one
            call covers the whole owner.
          </p>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
        <div>
          <h4 className="text-[10px] uppercase tracking-wide font-semibold text-(--color-muted-foreground) mb-2">
            Score breakdown
          </h4>
          <div className="flex flex-wrap gap-1 mb-3">
            {p.positiveSignals.map((s) => (
              <Badge key={s.key} variant="info" className="text-[11px]">
                {s.label}
                <span className="ml-0.5 opacity-70 font-bold">+{s.points}</span>
              </Badge>
            ))}
          </div>
          {p.negativeSignals.length > 0 && (
            <>
              <div className="text-[10px] text-(--color-destructive) uppercase tracking-wide font-semibold mb-1">
                Negative signals
              </div>
              <div className="flex flex-wrap gap-1">
                {p.negativeSignals.map((s) => (
                  <Badge key={s.key} variant="danger" className="text-[11px]">
                    {s.label}{" "}
                    <span className="opacity-70 font-bold">
                      {s.points > 0 ? `+${s.points}` : s.points}
                    </span>
                  </Badge>
                ))}
              </div>
            </>
          )}
        </div>
        <div>
          <h4 className="text-[10px] uppercase tracking-wide font-semibold text-(--color-muted-foreground) mb-2">
            Property
          </h4>
          <dl className="space-y-1 text-xs">
            <div className="flex justify-between">
              <dt className="text-(--color-muted-foreground)">Last sale</dt>
              <dd className="tabular-nums">
                {p.lastSaleDate || "—"}
                {p.lastSalePrice ? ` · ${kMoney(p.lastSalePrice)}` : ""}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-(--color-muted-foreground)">Assessed</dt>
              <dd className="tabular-nums">{kMoney(p.assessedTotal)}</dd>
            </div>
            {p.rateAtPurchase != null && (
              <div className="flex justify-between">
                <dt className="text-(--color-muted-foreground)">Rate at purchase</dt>
                <dd className="tabular-nums">
                  {p.rateAtPurchase}%
                  {p.rateDeltaNow != null && (
                    <span className="text-(--color-destructive) ml-1">
                      Δ {p.rateDeltaNow}
                    </span>
                  )}
                </dd>
              </div>
            )}
            <div className="flex justify-between">
              <dt className="text-(--color-muted-foreground)">Mail</dt>
              <dd className="text-right max-w-[60%] truncate">
                {p.mailAddr || "—"}
              </dd>
            </div>
            {p.canonicalOwnerId && (
              <div className="flex justify-between">
                <dt className="text-(--color-muted-foreground)">Owner ID</dt>
                <dd className="font-mono text-[10px]">{p.canonicalOwnerId}</dd>
              </div>
            )}
          </dl>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            <Link
              href={`/clients/new?from=${encodeURIComponent(p.parcelId)}&county=${p.county}&owner=${encodeURIComponent(p.owner)}&addr=${encodeURIComponent(p.siteAddr)}`}
              className="text-(--color-info) hover:underline inline-flex items-center gap-1 font-medium"
            >
              Convert to client <ExternalLink className="size-3" />
            </Link>
            {p.whitepagesUrl && (
              <a
                href={p.whitepagesUrl}
                target="_blank"
                rel="noreferrer"
                className="text-(--color-info) hover:underline inline-flex items-center gap-1"
              >
                Whitepages <ExternalLink className="size-3" />
              </a>
            )}
            {p.truePeopleUrl && (
              <a
                href={p.truePeopleUrl}
                target="_blank"
                rel="noreferrer"
                className="text-(--color-info) hover:underline inline-flex items-center gap-1"
              >
                TruePeople <ExternalLink className="size-3" />
              </a>
            )}
            {p.sccLookupUrl && (
              <a
                href={p.sccLookupUrl}
                target="_blank"
                rel="noreferrer"
                className="text-(--color-info) hover:underline inline-flex items-center gap-1"
              >
                VA SCC <ExternalLink className="size-3" />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export async function QueueTable({
  rows,
  mode,
  filters,
}: {
  rows: Prospect[];
  mode: "call" | "knock";
  filters: QueueFilters;
}) {
  const lastContacts = await loadLastContacts(rows);

  if (!rows.length) {
    return (
      <div className="rounded-md border border-(--color-border) bg-(--color-card) p-12 text-center text-(--color-muted-foreground)">
        No prospects match these filters. Try lowering the min score or clearing the lead-type filter.
      </div>
    );
  }

  const grouped = mode === "knock" ? groupBySubdivision(rows) : null;
  const totalParcels = rows.reduce(
    (n, r) => n + 1 + (r.otherParcels?.length ?? 0),
    0,
  );
  const mergedCount = totalParcels - rows.length;

  return (
    <div className="rounded-md border border-(--color-border) bg-(--color-card) overflow-hidden">
      <div className="border-b border-(--color-border) px-4 py-3 flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold inline-flex items-center gap-2">
          {mode === "knock" ? (
            <DoorOpen className="size-4" />
          ) : (
            <Phone className="size-4" />
          )}
          {mode === "knock" ? "Door-knock routes" : "Call queue"}
          <span className="text-(--color-muted-foreground) font-normal">
            {rows.length} {rows.length === 1 ? "owner" : "owners"}
            {mergedCount > 0 && (
              <span title={`${mergedCount} extra parcels merged into their owner rows — one call covers them all`}>
                {" "}
                · {totalParcels} parcels
              </span>
            )}
          </span>
        </h2>
        {mode === "knock" && (
          <Link
            href={`/route/_queue?${buildQuery(filters, { mode: "knock" })}`}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-(--color-info) hover:underline inline-flex items-center gap-1"
          >
            <Printer className="size-3.5" />
            Print full route
          </Link>
        )}
      </div>
      <div className="divide-y divide-(--color-border) overflow-x-auto">
        {grouped ? (
          [...grouped.entries()].map(([sub, subRows]) => {
            const avgScore = Math.round(
              subRows.reduce((s, r) => s + r.score, 0) / subRows.length,
            );
            const topScore = Math.max(...subRows.map((r) => r.score));
            return (
              <div key={sub}>
                <div className="px-4 py-2 bg-(--color-secondary)/60 border-b border-(--color-border) flex items-center justify-between gap-3 flex-wrap">
                  <div className="inline-flex items-center gap-2 text-sm font-semibold">
                    <MapPin className="size-3.5" />
                    {sub}
                    <span className="text-xs text-(--color-muted-foreground) font-normal">
                      {subRows.length}{" "}
                      {subRows.length === 1 ? "parcel" : "parcels"} · avg{" "}
                      {avgScore} · top {topScore}
                    </span>
                  </div>
                  {sub !== "(no subdivision)" && (
                    <Link
                      href={`/route/${encodeURIComponent(sub)}?${buildQuery(filters, { mode: "knock" })}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-(--color-info) hover:underline"
                    >
                      Build walking route →
                    </Link>
                  )}
                </div>
                <div className="divide-y divide-(--color-border)">
                  {subRows.map((p) => (
                    <ProspectRow
                      key={`${p.parcelId}-${p.county}`}
                      p={p}
                      mode={mode}
                      lastContacts={lastContacts}
                    />
                  ))}
                </div>
              </div>
            );
          })
        ) : (
          rows.map((p) => (
            <ProspectRow
              key={`${p.parcelId}-${p.county}`}
              p={p}
              mode={mode}
              lastContacts={lastContacts}
            />
          ))
        )}
      </div>
    </div>
  );
}
