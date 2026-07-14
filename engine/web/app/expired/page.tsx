import Link from "next/link";
import {
  Clock,
  ExternalLink,
  TrendingDown,
  AlertCircle,
  ChevronRight,
  MapPin,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ActionButtons } from "@/components/queue/action-buttons";
import { CitySelect } from "@/components/expired/city-select";
import {
  DEFAULT_EXPIRED_FILTERS,
  knownExpiredCities,
  queryExpired,
  type ExpiredListing,
} from "@/lib/data/expired";
import { cn, kMoney } from "@/lib/utils";
import { Accent, CountUp, FadeIn, SectionHeading } from "@/components/ratified-ui";

const DAYS_OPTIONS = [7, 14, 28, 60, 90];

function parseFilters(
  params: Record<string, string | string[] | undefined>,
): { city: string; daysBack: number; minPrice: number } {
  const get = (k: string) =>
    Array.isArray(params[k]) ? (params[k] as string[])[0] : (params[k] as string | undefined);
  const city = get("city") ?? DEFAULT_EXPIRED_FILTERS.city;
  const days = parseInt(get("days") ?? `${DEFAULT_EXPIRED_FILTERS.daysBack}`, 10);
  const minPrice = parseInt(get("min_price") ?? "0", 10);
  return {
    city,
    daysBack: isNaN(days) ? DEFAULT_EXPIRED_FILTERS.daysBack : days,
    minPrice: isNaN(minPrice) ? 0 : minPrice,
  };
}

function buildHref(over: Partial<{ city: string; days: number; min_price: number }>, current: { city: string; daysBack: number; minPrice: number }) {
  const params = new URLSearchParams();
  const city = over.city ?? current.city;
  const days = over.days ?? current.daysBack;
  const minPrice = over.min_price ?? current.minPrice;
  if (city) params.set("city", city);
  params.set("days", String(days));
  if (minPrice > 0) params.set("min_price", String(minPrice));
  return `/expired?${params.toString()}`;
}

export default async function ExpiredPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const filters = parseFilters(params);
  const [rows, cities] = await Promise.all([
    queryExpired(filters),
    knownExpiredCities(),
  ]);

  // Stats
  const totalValue = rows.reduce((n, r) => n + (r.lastListPrice ?? 0), 0);
  const avgDom =
    rows.length === 0
      ? 0
      : Math.round(
          rows.reduce((n, r) => n + (r.dom ?? 0), 0) / rows.length,
        );
  const cutCount = rows.filter((r) => (r.priceCutPct ?? 0) > 0).length;

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-ink-900/60 px-6 py-8 sm:px-8">
        <div className="bg-grid-fade pointer-events-none absolute inset-0" aria-hidden />
        <div
          className="pointer-events-none absolute -top-20 left-1/3 h-56 w-96 rounded-full bg-emerald-500/15 blur-[120px]"
          aria-hidden
        />
        <div className="relative">
          <SectionHeading
            align="left"
            eyebrow="Expired · no relist"
            title={
              <>
                Listings that <Accent>quietly went dark</Accent>
              </>
            }
            sub={`Off-market in the last ${filters.daysBack} days with no new listing on the same address.`}
          />
        </div>
      </div>

      {/* Stat strip */}
      <FadeIn>
        <Card className="px-5 py-3">
          <div className="flex items-stretch gap-5 overflow-x-auto">
            <Stat label="Listings" count={rows.length} />
            <Stat label="Last-list $ total" value={kMoney(totalValue)} />
            <Stat label="Avg DOM" count={avgDom} fallback="—" />
            <Stat label="With price cut" count={cutCount} />
          </div>
        </Card>
      </FadeIn>

      {/* Filter strip */}
      <FadeIn delay={0.05}>
        <Card className="gap-3 px-5 py-4">
          <div className="flex flex-wrap items-center gap-5 text-sm">
            <label className="inline-flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                City
              </span>
              <CitySelect
                cities={cities}
                value={filters.city}
                daysBack={filters.daysBack}
                minPrice={filters.minPrice}
              />
            </label>

            <div className="inline-flex items-center gap-1">
              <span className="mr-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Days back
              </span>
              {DAYS_OPTIONS.map((d) => (
                <Link
                  key={d}
                  href={buildHref({ days: d }, filters)}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                    d === filters.daysBack
                      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                      : "border-white/10 text-slate-400 hover:border-emerald-500/25 hover:text-(--color-foreground)",
                  )}
                >
                  {d}d
                </Link>
              ))}
            </div>
          </div>
        </Card>
      </FadeIn>

      {/* Table */}
      {rows.length === 0 ? (
        <FadeIn>
          <Card className="p-12 text-center text-slate-400">
            No expired listings without a relist match your filters. Try widening the days window or selecting a different city.
          </Card>
        </FadeIn>
      ) : (
        <FadeIn delay={0.1}>
          <Card className="overflow-hidden p-0">
            <div className="border-b border-white/10 px-4 py-3">
              <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                <Clock className="size-4 text-emerald-300" />
                Expired without relist
                <span className="font-normal text-slate-500">
                  {rows.length} {rows.length === 1 ? "listing" : "listings"}
                </span>
              </h2>
            </div>
            <div className="divide-y divide-white/10 overflow-x-auto">
              {rows.map((r) => (
                <ExpiredRow key={r.mlsId || r.parcelId || r.normalizedAddress} r={r} />
              ))}
            </div>
          </Card>
        </FadeIn>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  count,
  fallback,
}: {
  label: string;
  value?: React.ReactNode;
  count?: number;
  fallback?: string;
}) {
  return (
    <div className="flex min-w-[110px] flex-col gap-0.5 border-r border-white/10 pr-5 last:border-r-0">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="text-xl font-semibold tabular-nums text-white">
        {count != null ? (
          count === 0 && fallback ? (
            fallback
          ) : (
            <CountUp to={count} />
          )
        ) : (
          value
        )}
      </div>
    </div>
  );
}

function ExpiredRow({ r }: { r: ExpiredListing }) {
  const cut = r.priceCutPct && r.priceCutPct > 0 ? r.priceCutPct : null;
  return (
    <details className="group queue-row">
      <summary className="grid grid-cols-[80px_minmax(240px,1.6fr)_minmax(180px,1fr)_110px_120px_minmax(280px,auto)] gap-3 items-center px-4 py-3 cursor-pointer hover:bg-emerald-500/5 transition-colors list-none [&::-webkit-details-marker]:hidden min-w-[1100px]">
        {/* Days off market */}
        <div className="flex flex-col items-start">
          <Badge variant={(r.daysOffMarket ?? 99) <= 7 ? "warning" : "secondary"} className="text-xs">
            {r.daysOffMarket != null ? `${r.daysOffMarket}d ago` : "—"}
          </Badge>
          <span className="mt-0.5 text-[10px] text-slate-500">
            {r.expiredAt}
          </span>
        </div>

        {/* Address + owner */}
        <div className="min-w-0">
          <Link
            href={`/property/${encodeURIComponent(r.parcelId)}?county=${r.county}`}
            className="block truncate text-sm font-semibold text-white transition-colors hover:text-emerald-300"
            target="_blank"
            rel="noreferrer"
          >
            {r.address}
          </Link>
          <div className="truncate text-xs text-slate-400" title={r.owner}>
            {r.owner || "—"}
            {r.ownerOccupied === "yes" && (
              <span className="ml-1 text-emerald-300">· owner-occupied</span>
            )}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            {r.city}
            {r.subdivision ? ` · ${r.subdivision}` : ""}
            {r.yearBuilt ? ` · ${r.yearBuilt}` : ""}
            {r.bedrooms ? ` · ${r.bedrooms}BR` : ""}
            {r.fullBaths ? `/${r.fullBaths}BA` : ""}
            {r.sqft ? ` · ${r.sqft.toLocaleString()}sf` : ""}
          </div>
        </div>

        {/* Prior list office */}
        <div className="truncate text-xs text-slate-400" title={r.priorListOffice}>
          {r.priorListOffice || "—"}
        </div>

        {/* Price */}
        <div className="text-sm">
          <div className="font-semibold tabular-nums text-white">{kMoney(r.lastListPrice)}</div>
          {cut && (
            <div className="inline-flex items-center gap-0.5 text-[10px] tabular-nums text-rose-300">
              <TrendingDown className="size-3" />
              {cut}% cut
            </div>
          )}
          {r.dom != null && (
            <div className="text-[10px] tabular-nums text-slate-500">
              {r.dom}d on mkt
            </div>
          )}
        </div>

        {/* DOM badge */}
        <div>
          {r.dom != null && r.dom >= 90 && (
            <Badge variant="danger" className="text-xs">
              <AlertCircle className="size-3 mr-0.5" />
              stale
            </Badge>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3">
          <ActionButtons
            prospect={{
              parcelId: r.parcelId,
              county: r.county,
              owner: r.owner,
              siteAddr: r.address,
            }}
            mode="call"
          />
          <ChevronRight className="size-4 text-slate-500 transition-transform group-open:rotate-90" />
        </div>
      </summary>
      <ExpiredDetail r={r} />
    </details>
  );
}

function ExpiredDetail({ r }: { r: ExpiredListing }) {
  return (
    <div className="border-t border-white/10 bg-ink-950/40 px-4 pb-4 text-sm">
      <div className="grid grid-cols-1 gap-6 pt-3 md:grid-cols-2">
        <div>
          <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Listing history
          </h4>
          <dl className="space-y-1 text-xs">
            <Row k="MLS#" v={r.mlsId} />
            <Row k="Listed" v={r.listDate} />
            <Row k="Expired" v={r.expiredAt} />
            <Row k="Original list" v={kMoney(r.originalListPrice)} />
            <Row k="Last list" v={kMoney(r.lastListPrice)} />
            {r.assessedTotal != null && (
              <Row k="Assessed" v={kMoney(r.assessedTotal)} />
            )}
          </dl>
        </div>
        <div>
          <h4 className="mb-2 inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            <MapPin className="size-3 text-emerald-300" />
            Owner lookup
          </h4>
          <div className="flex flex-wrap gap-3 text-xs">
            <Link
              href={`/clients/new?from=${encodeURIComponent(r.parcelId)}&county=${r.county}&owner=${encodeURIComponent(r.owner)}&addr=${encodeURIComponent(r.address)}`}
              className="inline-flex items-center gap-1 font-medium text-emerald-300 transition-colors hover:text-emerald-200"
            >
              Convert to client <ExternalLink className="size-3" />
            </Link>
            {r.whitepagesUrl && (
              <a
                href={r.whitepagesUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-slate-400 transition-colors hover:text-emerald-300"
              >
                Whitepages <ExternalLink className="size-3" />
              </a>
            )}
            {r.truePeopleUrl && (
              <a
                href={r.truePeopleUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-slate-400 transition-colors hover:text-emerald-300"
              >
                TruePeople <ExternalLink className="size-3" />
              </a>
            )}
            {r.sccUrl && (
              <a
                href={r.sccUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-slate-400 transition-colors hover:text-emerald-300"
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

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right tabular-nums text-(--color-foreground)">{v || "—"}</dd>
    </div>
  );
}
