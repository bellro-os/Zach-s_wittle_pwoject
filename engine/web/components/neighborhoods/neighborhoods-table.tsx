"use client";

import { useState } from "react";
import Link from "next/link";
import { Flame, TrendingDown, ChevronRight } from "lucide-react";
import type { Neighborhood } from "@/lib/data/neighborhoods";
import { Badge } from "@/components/ui/badge";
import { kMoney, money } from "@/lib/utils";

type SortKey =
  | "subdivision"
  | "closes12mo"
  | "volume12mo"
  | "avgDom"
  | "medianPrice"
  | "avgListToSalePct"
  | "velocityTrend"
  | "topOfficeSharePct";

interface Col {
  key: SortKey;
  label: string;
  align: "left" | "right";
  cls?: string;
}

const COLS: Col[] = [
  { key: "subdivision", label: "Subdivision", align: "left" },
  { key: "closes12mo", label: "Closes 12mo", align: "right" },
  { key: "volume12mo", label: "Volume", align: "right" },
  { key: "avgDom", label: "Avg DOM", align: "right" },
  { key: "medianPrice", label: "Median price", align: "right" },
  { key: "avgListToSalePct", label: "L/S %", align: "right" },
  { key: "velocityTrend", label: "Velocity", align: "right" },
  { key: "topOfficeSharePct", label: "Top brokerage", align: "left" },
];

function compare(a: Neighborhood, b: Neighborhood, key: SortKey): number {
  const va = a[key];
  const vb = b[key];
  if (typeof va === "string" && typeof vb === "string") {
    return va.localeCompare(vb);
  }
  return (Number(va) || 0) - (Number(vb) || 0);
}

function buildHref(key: SortKey, currentSort: string, currentDir: string): string {
  let nextDir = "desc";
  if (currentSort === key) {
    nextDir = currentDir === "desc" ? "asc" : "desc";
  } else if (key === "subdivision" || key === "avgDom") {
    nextDir = "asc"; // these read better ascending by default
  }
  const params = new URLSearchParams();
  params.set("sort", key);
  params.set("dir", nextDir);
  return `/neighborhoods?${params.toString()}`;
}

export function NeighborhoodTable({
  rows,
  sort,
  dir,
}: {
  rows: Neighborhood[];
  sort: string;
  dir: string;
}) {
  const sortKey = (COLS.find((c) => c.key === sort)?.key ?? "closes12mo") as SortKey;
  const sorted = [...rows].sort((a, b) => {
    const cmp = compare(a, b, sortKey);
    return dir === "asc" ? cmp : -cmp;
  });

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[1000px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-(--color-muted-foreground) text-left border-b border-(--color-border)">
            {COLS.map((c) => (
              <th key={c.key} className={`py-2 px-3 font-semibold ${c.align === "right" ? "text-right" : ""}`}>
                <Link
                  href={buildHref(c.key, sort, dir)}
                  className={`hover:text-(--color-foreground) ${sort === c.key ? "text-(--color-foreground)" : ""}`}
                >
                  {c.label} {sort === c.key && (dir === "desc" ? "↓" : "↑")}
                </Link>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <Row key={r.subdivision} r={r} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({ r }: { r: Neighborhood }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        onClick={() => setOpen((o) => !o)}
        className={`border-b border-(--color-border) hover:bg-(--color-accent)/40 cursor-pointer ${
          open ? "bg-(--color-accent)/20" : ""
        }`}
      >
        <td className="py-2 px-3">
          <div className="font-semibold inline-flex items-center gap-1.5">
            <ChevronRight
              className={`size-3 transition-transform ${open ? "rotate-90" : ""}`}
            />
            {r.subdivision}
            {r.isHot && (
              <Badge variant="success" className="text-[9px] py-0 px-1.5">
                <Flame className="size-2.5" />
                hot
              </Badge>
            )}
          </div>
          <div className="text-[10px] text-(--color-muted-foreground)">
            {r.closesAllTime} all-time
          </div>
        </td>
        <td className="py-2 px-3 text-right tabular-nums">{r.closes12mo}</td>
        <td className="py-2 px-3 text-right tabular-nums">{kMoney(r.volume12mo)}</td>
        <td className="py-2 px-3 text-right tabular-nums">
          {r.avgDom != null ? Math.round(r.avgDom) + "d" : "—"}
        </td>
        <td className="py-2 px-3 text-right tabular-nums">{money(r.medianPrice)}</td>
        <td className="py-2 px-3 text-right tabular-nums">
          {r.avgListToSalePct != null ? r.avgListToSalePct.toFixed(1) + "%" : "—"}
        </td>
        <td className="py-2 px-3 text-right tabular-nums">
          <VelocityCell v={r.velocityTrend} />
        </td>
        <td className="py-2 px-3">
          <div className="font-medium truncate max-w-[220px]" title={r.topOffice}>
            {r.topOffice || "—"}
          </div>
          {r.topOfficeSharePct > 0 && (
            <div className="text-[10px] text-(--color-muted-foreground)">
              {r.topOfficeCloses} of {r.closes12mo} closes ·{" "}
              <span className="font-semibold text-(--color-foreground)">
                {r.topOfficeSharePct.toFixed(0)}% share
              </span>
            </div>
          )}
        </td>
      </tr>
      {open && (
        <tr className="bg-(--color-secondary)/40 border-b border-(--color-border)">
          <td colSpan={8} className="px-4 py-3">
            <AgentBreakdown r={r} />
          </td>
        </tr>
      )}
    </>
  );
}

function VelocityCell({ v }: { v: number }) {
  if (v === 0) return <span className="text-slate-500">—</span>;
  if (v >= 99) {
    return (
      <span className="inline-flex items-center gap-0.5 text-emerald-300 font-semibold">
        <Flame className="size-3" />
        new
      </span>
    );
  }
  if (v >= 1.3) {
    return (
      <span className="inline-flex items-center gap-0.5 text-emerald-300 font-semibold">
        <Flame className="size-3" />
        {v.toFixed(2)}×
      </span>
    );
  }
  if (v < 0.7) {
    return (
      <span className="inline-flex items-center gap-0.5 text-rose-300">
        <TrendingDown className="size-3" />
        {v.toFixed(2)}×
      </span>
    );
  }
  return <span className="text-slate-400">{v.toFixed(2)}×</span>;
}

function AgentBreakdown({ r }: { r: Neighborhood }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
      <div>
        <div className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) mb-1">
          Brokerage market share (last 12mo)
        </div>
        {r.topOffice ? (
          <>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 rounded-full bg-white/8 overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-emerald-500/60 to-emerald-300"
                  style={{ width: `${Math.min(100, r.topOfficeSharePct)}%` }}
                />
              </div>
              <span className="font-semibold tabular-nums shrink-0 w-16 text-right">
                {r.topOfficeSharePct.toFixed(1)}%
              </span>
            </div>
            <div className="mt-1 text-(--color-muted-foreground)">
              <span className="font-medium text-(--color-foreground)">{r.topOffice}</span>{" "}
              has {r.topOfficeCloses} of {r.closes12mo} closes — the rest split among
              other brokerages.
            </div>
          </>
        ) : (
          <p className="italic text-(--color-muted-foreground)">No brokerage data.</p>
        )}
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) mb-1">
          Top listing-agent IDs (last 12mo)
        </div>
        {r.topAgents.length === 0 ? (
          <p className="italic text-(--color-muted-foreground)">No agent data.</p>
        ) : (
          <ul className="space-y-0.5">
            {r.topAgents.map((a, i) => (
              <li key={a.id} className="flex items-center gap-2">
                <span className="text-(--color-muted-foreground) w-4 text-right">
                  {i + 1}.
                </span>
                <span className="font-mono">#{a.id}</span>
                <span className="text-(--color-muted-foreground)">— {a.n} closes</span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-(--color-muted-foreground) mt-1">
          IDs only — name mapping pending an agent-directory join.
        </p>
      </div>
    </div>
  );
}
