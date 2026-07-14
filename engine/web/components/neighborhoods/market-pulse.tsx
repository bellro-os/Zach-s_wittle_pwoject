import type { Neighborhood } from "@/lib/data/neighborhoods";
import {
  Flame,
  TrendingDown,
  DollarSign,
  Building2,
  type LucideIcon,
} from "lucide-react";
import { kMoney } from "@/lib/utils";
import { SpotCard } from "@/components/ratified-ui";

const MIN_RECENT_CLOSES = 3;   // filter out noise — need real activity to qualify
const HOT_VELOCITY = 1.3;
const COOLING_VELOCITY = 0.7;
const VELOCITY_SENTINEL_CUTOFF = 50;  // neighborhoods.py uses 99.0 for prev=0

export function MarketPulse({ rows }: { rows: Neighborhood[] }) {
  const hot = [...rows]
    .filter(
      (r) =>
        r.velocityTrend >= HOT_VELOCITY &&
        r.velocityTrend < VELOCITY_SENTINEL_CUTOFF &&
        r.closes6mo >= MIN_RECENT_CLOSES &&
        r.closesPrior6mo >= 2,
    )
    .sort((a, b) => b.velocityTrend - a.velocityTrend)
    .slice(0, 4);

  const cooling = [...rows]
    .filter(
      (r) =>
        r.velocityTrend > 0 &&
        r.velocityTrend < COOLING_VELOCITY &&
        r.closesPrior6mo >= MIN_RECENT_CLOSES,
    )
    .sort((a, b) => a.velocityTrend - b.velocityTrend)
    .slice(0, 4);

  const totalVolume = rows.reduce((n, r) => n + r.volume12mo, 0);
  const byVolume = [...rows]
    .filter((r) => r.volume12mo > 0)
    .sort((a, b) => b.volume12mo - a.volume12mo)
    .slice(0, 5);
  const maxVolume = byVolume[0]?.volume12mo ?? 0;

  const concentrated = [...rows]
    .filter(
      (r) =>
        r.topOffice && r.topOfficeSharePct >= 50 && r.closes12mo >= 4,
    )
    .sort((a, b) => b.topOfficeSharePct - a.topOfficeSharePct)
    .slice(0, 4);

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Panel
          title="Heating up"
          icon={Flame}
          accent="success"
          empty={
            hot.length === 0
              ? "No subdivisions trending materially up right now."
              : null
          }
        >
          {hot.map((r) => (
            <Row
              key={r.subdivision}
              label={r.subdivision}
              value={`${r.velocityTrend.toFixed(2)}×`}
              sub={`${r.closes6mo} closes last 6mo · ${r.closesPrior6mo} prior`}
              tone="success"
            />
          ))}
        </Panel>

        <Panel
          title="Cooling off"
          icon={TrendingDown}
          accent="destructive"
          empty={
            cooling.length === 0
              ? "Nothing cooling materially."
              : null
          }
        >
          {cooling.map((r) => (
            <Row
              key={r.subdivision}
              label={r.subdivision}
              value={`${r.velocityTrend.toFixed(2)}×`}
              sub={`${r.closes6mo} closes last 6mo · ${r.closesPrior6mo} prior`}
              tone="destructive"
            />
          ))}
        </Panel>

        <Panel title="Volume leaders (12mo)" icon={DollarSign}>
          {byVolume.length === 0 ? (
            <Empty text="No volume data yet." />
          ) : (
            byVolume.map((r) => {
              const share =
                totalVolume > 0 ? (r.volume12mo / totalVolume) * 100 : 0;
              return (
                <BarRow
                  key={r.subdivision}
                  label={r.subdivision}
                  value={kMoney(r.volume12mo)}
                  sub={`${share.toFixed(1)}% of city · ${r.closes12mo} closes`}
                  fillPct={
                    maxVolume > 0 ? (r.volume12mo / maxVolume) * 100 : 0
                  }
                />
              );
            })
          )}
        </Panel>

        <Panel
          title="Brokerage concentration"
          icon={Building2}
          empty={
            concentrated.length === 0
              ? "No subdivisions where one office controls a majority."
              : null
          }
        >
          {concentrated.map((r) => (
            <Row
              key={r.subdivision}
              label={r.subdivision}
              value={`${r.topOfficeSharePct.toFixed(0)}%`}
              sub={r.topOffice}
              tone="muted"
            />
          ))}
        </Panel>
      </div>

      <p className="text-[10px] text-(--color-muted-foreground) leading-relaxed">
        Velocity compares last 6mo closes vs prior 6mo (≥1.3× = heating,
        &lt;0.7× = cooling). Brokerage concentration ≥50% means one office owns
        the relationship — a barrier in that subdivision but a clear competitive
        opening if you don&apos;t already have a foothold there.
      </p>
    </div>
  );
}

function Panel({
  title,
  icon: Icon,
  accent,
  empty,
  children,
}: {
  title: string;
  icon: LucideIcon;
  accent?: "success" | "destructive";
  empty?: string | null;
  children?: React.ReactNode;
}) {
  const accentCls =
    accent === "success"
      ? "text-emerald-300"
      : accent === "destructive"
        ? "text-rose-300"
        : "text-emerald-300/80";
  return (
    <SpotCard className="p-3 space-y-2">
      <div
        className={`text-[11px] font-semibold uppercase tracking-wider inline-flex items-center gap-1.5 ${accentCls}`}
      >
        <Icon className="size-3.5" />
        {title}
      </div>
      {empty ? <Empty text={empty} /> : <div className="space-y-2">{children}</div>}
    </SpotCard>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="text-xs text-(--color-muted-foreground) italic">{text}</div>
  );
}

function Row({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "success" | "destructive" | "muted";
}) {
  const tCls =
    tone === "success"
      ? "text-emerald-300"
      : tone === "destructive"
        ? "text-rose-300"
        : tone === "muted"
          ? "text-slate-400"
          : "text-white";
  return (
    <div className="flex items-baseline justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium truncate">{label}</div>
        {sub && (
          <div className="text-[10px] text-slate-500 truncate">
            {sub}
          </div>
        )}
      </div>
      <div className={`text-sm font-semibold tabular-nums ${tCls}`}>{value}</div>
    </div>
  );
}

function BarRow({
  label,
  value,
  sub,
  fillPct,
}: {
  label: string;
  value: string;
  sub?: string;
  fillPct: number;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-sm font-medium truncate min-w-0 flex-1">
          {label}
        </div>
        <div className="text-sm font-semibold tabular-nums text-white">{value}</div>
      </div>
      <div className="h-1.5 rounded-full bg-white/8 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-500/60 to-emerald-300"
          style={{ width: `${Math.min(100, Math.max(0, fillPct))}%` }}
        />
      </div>
      {sub && (
        <div className="text-[10px] text-slate-500">{sub}</div>
      )}
    </div>
  );
}
