import Link from "next/link";
import {
  Phone,
  MessageCircle,
  Mail,
  Mic2,
  Send,
  Users,
  Edit3,
  Activity,
} from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FadeIn, SectionHeading, Accent } from "@/components/ratified-ui";
import { cn } from "@/lib/utils";

const TOUCH_ICONS: Record<string, typeof Edit3> = {
  call: Phone,
  text: MessageCircle,
  email: Mail,
  in_person: Mic2,
  letter: Send,
  meeting: Users,
  note: Edit3,
};

const KINDS = ["call", "text", "email", "in_person", "letter", "meeting", "note"];

function param(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

const RANGE_DAYS: Record<string, number | null> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
  ytd: null, // handled specially
  all: null,
};

export default async function ActivityPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const kindFilter = param(sp.kind);
  const direction = param(sp.direction);
  const clientId = param(sp.clientId);
  const range = param(sp.range) || "30d";

  let dateFilter: { gte: Date } | undefined;
  if (range === "ytd") {
    dateFilter = { gte: new Date(new Date().getFullYear(), 0, 1) };
  } else if (range !== "all" && RANGE_DAYS[range]) {
    dateFilter = {
      gte: new Date(Date.now() - RANGE_DAYS[range]! * 86_400_000),
    };
  }

  const [touches, allClients] = await Promise.all([
    db.touch.findMany({
      where: {
        ...(kindFilter ? { kind: kindFilter } : {}),
        ...(direction ? { direction } : {}),
        ...(clientId ? { clientId } : {}),
        ...(dateFilter ? { timestamp: dateFilter } : {}),
      },
      orderBy: { timestamp: "desc" },
      include: {
        client: {
          select: { id: true, displayId: true, name: true, category: true },
        },
      },
      take: 200,
    }),
    db.client.findMany({
      where: { deletedAt: null },
      select: { id: true, displayId: true, name: true },
      orderBy: { name: "asc" },
    }),
  ]);
  const selectedClient = clientId
    ? allClients.find((c) => c.id === clientId)
    : null;

  return (
    <div className="space-y-6">
      {/* Page header — blueprint grid + eyebrow/headline */}
      <div className="bg-grid-fade -mx-4 -mt-4 px-4 pt-6 pb-2 sm:-mx-6 sm:px-6">
        <SectionHeading
          align="left"
          eyebrow="Engagement log"
          title={
            <>
              Every <Accent>touch</Accent>, in order
            </>
          }
          sub={`Calls, texts, emails, and notes across all clients — last ${touches.length} shown.`}
        />
      </div>

      <FadeIn>
      <Card className="p-3 space-y-2 text-xs">
        {selectedClient && (
          <div className="flex items-center gap-2 pb-2 border-b border-white/10">
            <span className="font-semibold uppercase tracking-wider text-slate-500">
              Client
            </span>
            <Link
              href={`/clients/${selectedClient.id}`}
              className="font-semibold text-emerald-300 hover:underline"
            >
              {selectedClient.name}
            </Link>
            <Link
              href={buildHref({ kind: kindFilter, direction, range })}
              className="text-slate-400 hover:text-white hover:underline ml-2"
            >
              clear
            </Link>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-slate-500 font-semibold uppercase tracking-wider">
            Range
          </span>
          {[
            ["7d", "7d"],
            ["30d", "30d"],
            ["90d", "90d"],
            ["ytd", "YTD"],
            ["all", "all-time"],
          ].map(([v, l]) => (
            <FilterChip
              key={v}
              href={buildHref({ kind: kindFilter, direction, clientId, range: v })}
              active={range === v}
              label={l}
            />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-slate-500 font-semibold uppercase tracking-wider">
            Kind
          </span>
          <FilterChip
            href={buildHref({ direction, clientId, range })}
            active={!kindFilter}
            label="all"
          />
          {KINDS.map((k) => (
            <FilterChip
              key={k}
              href={buildHref({ kind: k, direction, clientId, range })}
              active={kindFilter === k}
              label={k.replace(/_/g, " ")}
            />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-slate-500 font-semibold uppercase tracking-wider">
            Direction
          </span>
          <FilterChip
            href={buildHref({ kind: kindFilter, clientId, range })}
            active={!direction}
            label="any"
          />
          <FilterChip
            href={buildHref({ kind: kindFilter, direction: "outbound", clientId, range })}
            active={direction === "outbound"}
            label="→ outbound"
          />
          <FilterChip
            href={buildHref({ kind: kindFilter, direction: "inbound", clientId, range })}
            active={direction === "inbound"}
            label="← inbound"
          />
        </div>
      </Card>
      </FadeIn>

      {touches.length === 0 ? (
        <FadeIn>
          <Card className="p-12 text-center text-slate-400">
            No touches yet. Log one from any client&apos;s detail page.
          </Card>
        </FadeIn>
      ) : (
        <FadeIn>
        <Card className="overflow-hidden py-0">
          <ol className="divide-y divide-white/10">
            {touches.map((t) => {
              const Icon = TOUCH_ICONS[t.kind] ?? Edit3;
              return (
                <li key={t.id} className="p-3 flex items-start gap-3">
                  <span className="size-8 rounded-full border border-emerald-500/25 bg-emerald-500/10 flex items-center justify-center shrink-0">
                    <Icon className="size-4 text-emerald-300" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 text-sm flex-wrap">
                      <Link
                        href={`/clients/${t.client.id}`}
                        className="font-semibold hover:underline"
                      >
                        {t.client.name}
                      </Link>
                      <span className="text-slate-500 text-xs font-mono">
                        {t.client.displayId}
                      </span>
                      {t.client.category && (
                        <Badge
                          variant={
                            t.client.category === "A"
                              ? "success"
                              : t.client.category === "B"
                                ? "info"
                                : "secondary"
                          }
                          className="text-[10px]"
                        >
                          {t.client.category}
                        </Badge>
                      )}
                      <span className="text-slate-400 text-xs capitalize">
                        · {t.kind.replace(/_/g, " ")}
                      </span>
                      {t.direction && (
                        <span className="text-[10px] text-slate-500">
                          {t.direction === "outbound" ? "→" : "←"}
                        </span>
                      )}
                      <Link
                        href={`/touches/${t.id}`}
                        className="ml-auto text-xs text-slate-500 tabular-nums hover:text-white hover:underline"
                      >
                        {t.timestamp.toISOString().replace("T", " ").slice(0, 16)} ›
                      </Link>
                    </div>
                    {t.notes && (
                      <p className="text-sm text-slate-400 mt-0.5 whitespace-pre-wrap">
                        {t.notes}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </Card>
        </FadeIn>
      )}
    </div>
  );
}

function FilterChip({
  href,
  active,
  label,
}: {
  href: string;
  active?: boolean;
  label: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-full border px-2.5 py-0.5 transition-colors capitalize",
        active
          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300 font-semibold"
          : "border-white/10 text-slate-400 hover:border-emerald-500/25 hover:text-white",
      )}
    >
      {label}
    </Link>
  );
}

function buildHref(p: {
  kind?: string;
  direction?: string;
  clientId?: string;
  range?: string;
}): string {
  const params = new URLSearchParams();
  if (p.kind) params.set("kind", p.kind);
  if (p.direction) params.set("direction", p.direction);
  if (p.clientId) params.set("clientId", p.clientId);
  if (p.range && p.range !== "30d") params.set("range", p.range);
  const q = params.toString();
  return q ? `/activity?${q}` : "/activity";
}
