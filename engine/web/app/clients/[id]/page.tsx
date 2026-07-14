import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  Phone,
  Mail,
  Cake,
  Home,
  Tag,
  Users,
  MessageCircle,
  Mic2,
  Send,
  Edit3,
  ExternalLink,
  Bookmark,
  Plus,
  Sparkles,
} from "lucide-react";
import {
  listSavedSearches,
  summarizeCriteria,
} from "@/lib/data/saved-searches";
import { getClientDetail, allClientsLite } from "@/lib/data/crm";
import { getProspect } from "@/lib/data/prospects";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LeadTypeBadge } from "@/components/queue/lead-type-badge";
import { ScoreCircle } from "@/components/queue/score-circle";
import { openerFor } from "@/lib/data/call-scripts";
import { kMoney } from "@/lib/utils";
import { formatPhone } from "@/lib/format";
import { ClientModal } from "@/components/clients/client-modal";
import { TouchLogForm } from "@/components/clients/touch-log-form";
import { DeleteTouchButton } from "@/components/clients/delete-touch-button";
import { EditTouchButton } from "@/components/clients/edit-touch";
import { AddDealModal } from "@/components/clients/add-deal-modal";
import { DismissReminder } from "@/components/clients/dismiss-reminder";
import { RecordingsSection } from "@/components/clients/recordings-section";
import { ConfirmDelete } from "@/components/ui/confirm-delete";
import { deleteClient } from "@/app/actions";
import { FadeIn } from "@/components/ratified-ui";

function categoryTone(cat: string | null | undefined) {
  if (cat === "A") return "success" as const;
  if (cat === "B") return "info" as const;
  if (cat === "C") return "secondary" as const;
  return "secondary" as const;
}

function lastContactBadge(days: number | null) {
  if (days == null)
    return { variant: "secondary" as const, label: "Never contacted" };
  if (days <= 30) return { variant: "success" as const, label: `${days}d ago` };
  if (days <= 90) return { variant: "warning" as const, label: `${days}d ago` };
  return { variant: "danger" as const, label: `Stale · ${days}d ago` };
}

const TOUCH_ICONS: Record<string, typeof Edit3> = {
  call: Phone,
  text: MessageCircle,
  email: Mail,
  in_person: Mic2,
  letter: Send,
  meeting: Users,
  note: Edit3,
};

export default async function ClientDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [client, allClients, savedSearches] = await Promise.all([
    getClientDetail(id),
    allClientsLite(),
    listSavedSearches({ clientId: id }),
  ]);
  if (!client) notFound();

  const ownProspect =
    client.parcelId && client.county
      ? await getProspect(client.parcelId, client.county)
      : null;

  const lc = lastContactBadge(client.lastContactDays);
  const tags = (client.tags || "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

  // Build defaults shape for ClientModal edit
  const editDefaults = {
    id: client.id,
    name: client.name,
    phone: client.phone ?? "",
    altPhone: client.altPhone ?? "",
    email: client.email ?? "",
    source: client.source ?? "",
    category: client.category ?? "",
    tags: client.tags ?? "",
    anniversary: client.anniversary,
    birthday: client.birthday,
    parcelId: client.parcelId ?? "",
    county: client.county ?? "",
    referredById: client.referredById ?? "",
    notes: client.notes ?? "",
  };

  return (
    <div className="space-y-5">
      <Link
        href="/clients"
        className="inline-flex items-center gap-1 text-sm text-emerald-300 hover:underline"
      >
        <ArrowLeft className="size-4" /> back to clients
      </Link>

      {/* Hero */}
      <FadeIn>
        <Card className="bg-grid-fade relative overflow-hidden p-6">
          <div className="pointer-events-none absolute -top-24 right-1/4 h-64 w-64 rounded-full bg-emerald-500/15 blur-[120px]" />
          <div className="relative flex items-start justify-between gap-6 flex-wrap">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-3xl font-semibold tracking-tight text-white">{client.name}</h1>
              <span className="text-slate-500 font-mono text-sm">
                {client.displayId}
              </span>
              {client.category && (
                <Badge variant={categoryTone(client.category)} className="text-xs">
                  Tier {client.category}
                </Badge>
              )}
              {client.source && (
                <Badge variant="secondary" className="text-xs uppercase">
                  {client.source.replace(/_/g, " ")}
                </Badge>
              )}
              <Badge variant={lc.variant} className="text-xs">
                {lc.label}
              </Badge>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-slate-300">
              {client.phone && (
                <a
                  href={`tel:${client.phone}`}
                  className="inline-flex items-center gap-1.5 hover:text-emerald-300"
                >
                  <Phone className="size-4 text-slate-500" />
                  {formatPhone(client.phone)}
                </a>
              )}
              {client.altPhone && (
                <a
                  href={`tel:${client.altPhone}`}
                  className="inline-flex items-center gap-1.5 hover:text-emerald-300"
                >
                  <Phone className="size-4 text-slate-500" />
                  {formatPhone(client.altPhone)}
                  <span className="text-xs text-slate-500">alt</span>
                </a>
              )}
              {client.email && (
                <a
                  href={`mailto:${client.email}`}
                  className="inline-flex items-center gap-1.5 hover:text-emerald-300"
                >
                  <Mail className="size-4 text-slate-500" />
                  {client.email}
                </a>
              )}
              {tags.length > 0 && (
                <span className="inline-flex items-center gap-1 text-slate-500">
                  <Tag className="size-3.5" />
                  {tags.map((t) => (
                    <Badge key={t} variant="outline" className="text-[10px] py-0">
                      {t}
                    </Badge>
                  ))}
                </span>
              )}
            </div>

            {client.referredBy && (
              <p className="mt-2 text-xs text-slate-500">
                Referred by{" "}
                <Link
                  href={`/clients/${client.referredBy.id}`}
                  className="text-emerald-300 hover:underline font-medium"
                >
                  {client.referredBy.name}
                </Link>
              </p>
            )}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <AddDealModal
              clientCuid={client.id}
              clientDisplayId={client.displayId}
              buttonLabel="New deal"
            />
            <ClientModal mode="edit" defaults={editDefaults} allClients={allClients} />
            <ConfirmDelete
              action={deleteClient}
              fields={{ id: client.id }}
              title={`Delete ${client.name}?`}
              description="Soft-delete: hidden from lists, referral chains preserved. Restore from /clients?view=trash."
            />
          </div>
          </div>
        </Card>
      </FadeIn>

      {/* Reminder cards: anniversary + birthday */}
      {((client.anniversaryIn != null && client.anniversaryIn <= 60) ||
        (client.birthdayIn != null && client.birthdayIn <= 60)) && (
        <FadeIn className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {client.anniversaryIn != null && client.anniversaryIn <= 60 && (
            <Card className="p-4 border-l-4 border-l-emerald-400">
              <div className="flex items-center gap-3">
                <Home className="size-8 text-emerald-300" />
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">
                      Home anniversary
                    </div>
                    <DismissReminder clientId={client.id} kind="anniversary" />
                  </div>
                  <div className="font-semibold text-white">
                    {client.anniversaryIn === 0
                      ? "Today"
                      : client.anniversaryIn === 1
                        ? "Tomorrow"
                        : `${client.anniversaryIn} days`}
                    {client.anniversaryYears != null &&
                      ` · ${client.anniversaryYears + 1}-year`}
                  </div>
                  {client.anniversary && (
                    <div className="text-xs text-slate-500">
                      Closed {client.anniversary.toISOString().slice(0, 10)}
                    </div>
                  )}
                </div>
              </div>
            </Card>
          )}
          {client.birthdayIn != null && client.birthdayIn <= 60 && (
            <Card className="p-4 border-l-4 border-l-amber-400">
              <div className="flex items-center gap-3">
                <Cake className="size-8 text-amber-400" />
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">
                      Birthday
                    </div>
                    <DismissReminder clientId={client.id} kind="birthday" />
                  </div>
                  <div className="font-semibold text-white">
                    {client.birthdayIn === 0
                      ? "Today"
                      : client.birthdayIn === 1
                        ? "Tomorrow"
                        : `${client.birthdayIn} days`}
                  </div>
                  {client.birthday && (
                    <div className="text-xs text-slate-500">
                      {client.birthday.toISOString().slice(5, 10)}
                    </div>
                  )}
                </div>
              </div>
            </Card>
          )}
        </FadeIn>
      )}

      {/* Their home + seller-score */}
      {client.parcelId && (
        <FadeIn>
          <Card className="p-5">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-white inline-flex items-center gap-2">
                <Home className="size-4 text-emerald-300" /> Their home
              </h2>
              {ownProspect && (
                <Link
                  href={`/property/${encodeURIComponent(ownProspect.parcelId)}?county=${ownProspect.county}`}
                  className="text-xs text-emerald-300 hover:underline inline-flex items-center gap-1"
                >
                  Full property page <ExternalLink className="size-3" />
                </Link>
              )}
            </div>
            {ownProspect ? (
              <div className="flex items-start gap-4">
                <ScoreCircle score={ownProspect.score} />
                <div className="flex-1">
                  <div className="font-semibold text-white">{ownProspect.siteAddr}</div>
                  <div className="text-xs text-slate-500">
                    {ownProspect.county}
                    {ownProspect.subdivision ? ` · ${ownProspect.subdivision}` : ""}
                    {ownProspect.yearBuilt ? ` · built ${ownProspect.yearBuilt}` : ""}
                    {ownProspect.bedrooms ? ` · ${ownProspect.bedrooms}BR` : ""}
                  </div>
                  <div className="mt-2">
                    <LeadTypeBadge leadType={ownProspect.leadType} />
                  </div>
                  <p className="mt-3 text-sm italic text-slate-400 border-l-2 border-emerald-400 pl-3">
                    Suggested opener: &ldquo;{openerFor(ownProspect)}&rdquo;
                  </p>
                </div>
                <div className="text-right text-xs space-y-1 hidden md:block">
                  <div>
                    <span className="text-slate-500">Assessed:</span>{" "}
                    <span className="tabular-nums text-slate-200">
                      {kMoney(ownProspect.assessedTotal)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">Tenure:</span>{" "}
                    <span className="tabular-nums text-slate-200">
                      {ownProspect.tenureYears
                        ? `${ownProspect.tenureYears.toFixed(1)}y`
                        : "—"}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">Equity:</span>{" "}
                    <span className="tabular-nums text-slate-200">
                      {kMoney(ownProspect.estimatedEquity)}
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-400">
                Parcel <span className="font-mono">{client.parcelId}</span> linked,
                but no seller-score row found. Regenerate seller_scores.csv or
                check the county is set.
              </p>
            )}
          </Card>
        </FadeIn>
      )}

      {/* Recordings */}
      <RecordingsSection clientId={client.id} />

      {/* Touch log: form + timeline */}
      <FadeIn>
        <Card className="p-5">
          <h2 className="font-semibold text-white mb-3 inline-flex items-center gap-2">
            <MessageCircle className="size-4 text-emerald-300" /> Touch log
            <span className="text-slate-500 font-normal text-sm">
              ({client.touches.length})
            </span>
          </h2>

          <TouchLogForm clientId={client.id} />

          {client.touches.length === 0 ? (
            <p className="text-sm text-slate-500 italic">
              No touches yet. Log the first one above to start the timeline.
            </p>
          ) : (
            <ol className="relative border-l-2 border-white/10 ml-3 space-y-3">
              {client.touches.map((t) => {
                const Icon = TOUCH_ICONS[t.kind] ?? Edit3;
                return (
                  <li key={t.id} className="ml-5 relative">
                    <span className="absolute -left-7 top-1 size-6 rounded-full bg-ink-800 border-2 border-emerald-500/25 flex items-center justify-center">
                      <Icon className="size-3 text-emerald-300" />
                    </span>
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <span className="font-semibold text-white capitalize">
                        {t.kind.replace(/_/g, " ")}
                      </span>
                      {t.direction && (
                        <span className="text-[10px]">
                          {t.direction === "outbound" ? "→" : "←"}
                        </span>
                      )}
                      <span className="tabular-nums">
                        {t.timestamp.toISOString().replace("T", " ").slice(0, 16)}
                      </span>
                      {t.duration && (
                        <span className="text-[10px]">{t.duration}min</span>
                      )}
                      <EditTouchButton touch={t} />
                      <DeleteTouchButton
                        touchId={t.id}
                        clientId={client.id}
                        preview={t.notes ?? undefined}
                      />
                    </div>
                    {t.notes && (
                      <p className="text-sm mt-0.5 whitespace-pre-wrap text-slate-300">{t.notes}</p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </Card>
      </FadeIn>

      {/* Linked deals */}
      <FadeIn>
        <Card className="p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-white">
              Deals{" "}
              <span className="text-slate-500 font-normal text-sm">
                ({client.deals.length})
              </span>
            </h2>
          </div>
          {client.deals.length === 0 ? (
            <p className="text-sm text-slate-500 italic">
              No deals yet. Click <strong className="text-emerald-300">New deal</strong> in the header to add one.
            </p>
          ) : (
            <ul className="divide-y divide-white/8">
              {client.deals.map((d) => (
                <li
                  key={d.id}
                  className="py-2 flex items-center justify-between gap-3 text-sm"
                >
                  <div>
                    <span className="font-mono text-xs text-slate-500 mr-2">
                      {d.displayId}
                    </span>
                    <span className="font-medium text-slate-200">{d.property}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <Badge variant="secondary">{d.side}</Badge>
                    <Badge variant="info">{d.stage}</Badge>
                    <span className="tabular-nums text-slate-400">
                      {kMoney(d.listPrice)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </FadeIn>

      {/* Referrals network */}
      {(client.referrals?.length ?? 0) > 0 && (
        <FadeIn>
          <Card className="p-5">
            <h2 className="font-semibold text-white mb-3 inline-flex items-center gap-2">
              <Users className="size-4 text-emerald-300" /> Has referred {client.referrals.length}{" "}
              {client.referrals.length === 1 ? "client" : "clients"}
            </h2>
            <ul className="divide-y divide-white/8">
              {client.referrals.map((r) => (
                <li
                  key={r.id}
                  className="py-2 flex items-center justify-between text-sm"
                >
                  <Link
                    href={`/clients/${r.id}`}
                    className="text-emerald-300 hover:underline"
                  >
                    {r.name}
                  </Link>
                  <span className="text-xs text-slate-500 font-mono">
                    {r.displayId}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </FadeIn>
      )}

      {/* Saved searches for this client */}
      <FadeIn>
        <Card className="p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-white inline-flex items-center gap-2">
              <Bookmark className="size-4 text-emerald-300" /> Saved searches
              {savedSearches.length > 0 && (
                <span className="text-xs text-slate-500">
                  ({savedSearches.length})
                </span>
              )}
            </h2>
            <Link
              href={`/searches/new?clientId=${id}`}
              className="inline-flex items-center gap-1 text-xs text-emerald-300 hover:underline"
            >
              <Plus className="size-3.5" /> Add search
            </Link>
          </div>
          {savedSearches.length === 0 ? (
            <p className="text-xs text-slate-500 italic">
              No saved searches for this client yet. Add one to auto-monitor the
              MLS for matches.
            </p>
          ) : (
            <ul className="divide-y divide-white/8">
              {savedSearches.map((s) => (
                <li key={s.id} className="py-2">
                  <Link
                    href={`/searches/${s.id}`}
                    className="flex items-center justify-between gap-3 hover:bg-emerald-500/5 -mx-2 px-2 py-1 rounded-md transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-slate-200 inline-flex items-center gap-2">
                        {s.name}
                        <span className="text-[10px] font-mono text-slate-500">
                          {s.displayId}
                        </span>
                        {s.newSinceLastRun > 0 && (
                          <Badge
                            variant="success"
                            className="text-[10px] py-0 px-1.5"
                          >
                            <Sparkles className="size-2.5" />
                            {s.newSinceLastRun} new
                          </Badge>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 truncate">
                        {summarizeCriteria(s.criteria, s.centerLabel)}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-sm font-semibold tabular-nums text-white">
                        {s.lastMatchCount}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-slate-500">
                        matches
                      </div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </FadeIn>

      {/* Free-text notes */}
      {client.notes && (
        <FadeIn>
          <Card className="p-5">
            <h2 className="font-semibold text-white mb-2">Notes</h2>
            <p className="text-sm whitespace-pre-wrap text-slate-300">{client.notes}</p>
          </Card>
        </FadeIn>
      )}
    </div>
  );
}
