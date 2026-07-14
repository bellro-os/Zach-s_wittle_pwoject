import { MapPin, Flame, Briefcase, Activity } from "lucide-react";
import { Card } from "@/components/ui/card";
import { getNeighborhoods } from "@/lib/data/neighborhoods";
import { MarketPulse } from "@/components/neighborhoods/market-pulse";
import { NeighborhoodTable } from "@/components/neighborhoods/neighborhoods-table";
import { kMoney } from "@/lib/utils";
import { FadeIn, SpotCard, CountUp, Accent } from "@/components/ratified-ui";

export default async function NeighborhoodsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const sort = (Array.isArray(sp.sort) ? sp.sort[0] : sp.sort) ?? "closes12mo";
  const dir = (Array.isArray(sp.dir) ? sp.dir[0] : sp.dir) ?? "desc";

  const rows = await getNeighborhoods("Blacksburg");

  // Stat strip
  const totalVolume = rows.reduce((n, r) => n + r.volume12mo, 0);
  const totalCloses = rows.reduce((n, r) => n + r.closes12mo, 0);
  const hotCount = rows.filter((r) => r.isHot).length;
  const top = [...rows].sort((a, b) => b.closes12mo - a.closes12mo)[0];

  return (
    <div className="space-y-5">
      <FadeIn className="bg-grid-fade -mx-4 -mt-4 px-4 pb-6 pt-8 sm:-mx-6 sm:px-6">
        <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
          <MapPin className="size-3.5" /> Neighborhoods
        </span>
        <h1 className="mt-4 max-w-3xl text-balance text-3xl font-semibold leading-[1.08] tracking-tight text-white sm:text-4xl">
          Blacksburg, <Accent>block by block</Accent>
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">
          {rows.length} subdivisions with recent activity, on rolling 12-month
          windows.
        </p>
      </FadeIn>

      <FadeIn className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat
          label="Subdivisions tracked"
          value={rows.length}
          countTo={rows.length}
          Icon={MapPin}
        />
        <Stat label="Closes (12mo)" value={totalCloses} countTo={totalCloses} />
        <Stat label="Volume (12mo)" value={kMoney(totalVolume)} Icon={Briefcase} />
        <Stat
          label="Hot"
          value={hotCount}
          countTo={hotCount}
          sub="top quartile by close count"
          Icon={Flame}
          tone="success"
        />
        <Stat
          label="Top subdivision"
          value={top?.subdivision ?? "—"}
          sub={top ? `${top.closes12mo} closes · ${kMoney(top.volume12mo)}` : ""}
        />
      </FadeIn>

      <FadeIn>
      <Card className="p-4 gap-3">
        <h2 className="text-sm font-semibold inline-flex items-center gap-2">
          <Activity className="size-4 text-emerald-300/80" /> Market pulse
        </h2>
        <MarketPulse rows={rows} />
      </Card>
      </FadeIn>

      <FadeIn>
      <Card className="p-0 overflow-hidden">
        <div className="border-b border-(--color-border) px-4 py-3">
          <h2 className="text-sm font-semibold inline-flex items-center gap-2">
            Per-subdivision performance · click any column to re-sort · click a
            row to see the brokerage breakdown.
          </h2>
        </div>
        <NeighborhoodTable rows={rows} sort={sort} dir={dir} />
      </Card>
      </FadeIn>

      <p className="text-[10px] text-(--color-muted-foreground)">
        Dominant brokerage = office with the most closed listings in the past
        12 months. Top agent shown by MLS agent ID; mapping IDs to names
        requires running <code>mls-pull-directory</code> + a future agent join.
      </p>
    </div>
  );
}

function Stat({
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
  sub?: string;
  Icon?: typeof MapPin;
  tone?: "success" | "warning" | "danger";
}) {
  const toneCls =
    tone === "success"
      ? "text-emerald-300"
      : tone === "warning"
        ? "text-amber-300"
        : tone === "danger"
          ? "text-rose-300"
          : "text-white";
  return (
    <SpotCard className="p-4">
      <div className="flex flex-col gap-0.5">
        <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 flex items-center gap-1.5">
          {Icon && <Icon className="size-3 text-emerald-300/80" />}
          {label}
        </div>
        <div className={`text-lg font-semibold tracking-tight tabular-nums ${toneCls}`}>
          {countTo != null ? <CountUp to={countTo} /> : value}
        </div>
        {sub && <div className="text-[10px] text-slate-400">{sub}</div>}
      </div>
    </SpotCard>
  );
}

