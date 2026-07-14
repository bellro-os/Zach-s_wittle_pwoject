/** URL-search-param helpers for the queue filters. Centralized so the page
 * server component and the toolbar client component agree on shape. */

import type { QueueFilters } from "@/lib/data/prospects";
import { DEFAULT_FILTERS } from "@/lib/data/prospects";

type RawParams = Record<string, string | string[] | undefined>;

function arr(v: string | string[] | undefined): string[] {
  if (!v) return [];
  if (Array.isArray(v)) return v.filter(Boolean);
  return v.split(",").filter(Boolean);
}

function intParam(v: string | string[] | undefined, fallback: number): number {
  if (!v) return fallback;
  const s = Array.isArray(v) ? v[0] : v;
  const n = parseInt(s);
  return isNaN(n) ? fallback : n;
}

export function parseFilters(searchParams: RawParams): QueueFilters {
  const mode = ((Array.isArray(searchParams.mode) ? searchParams.mode[0] : searchParams.mode) ?? "call") as
    | "call"
    | "knock";
  return {
    mode: mode === "knock" ? "knock" : "call",
    minScore: intParam(searchParams.min_score, DEFAULT_FILTERS.minScore),
    counties: arr(searchParams.counties),
    ownerTypes: arr(searchParams.owner_types),
    leadTypes: arr(searchParams.lead_types),
    signals: arr(searchParams.signals),
    suppressDays: intParam(searchParams.suppress_days, DEFAULT_FILTERS.suppressDays),
    sortBy: ((Array.isArray(searchParams.sort_by)
      ? searchParams.sort_by[0]
      : searchParams.sort_by) ?? "score") as QueueFilters["sortBy"],
    maxRows: intParam(searchParams.max_rows, DEFAULT_FILTERS.maxRows),
    skipFlippers:
      (Array.isArray(searchParams.skip_flippers)
        ? searchParams.skip_flippers[0]
        : searchParams.skip_flippers) !== "0",
  };
}

/** Build a query string preserving filters with arbitrary overrides. */
export function buildQuery(
  base: QueueFilters,
  overrides: Partial<Record<keyof QueueFilters, string | string[] | number | boolean>> = {},
): string {
  const params = new URLSearchParams();
  const merged: Record<string, unknown> = {
    mode: base.mode,
    min_score: base.minScore,
    counties: base.counties,
    owner_types: base.ownerTypes,
    lead_types: base.leadTypes,
    signals: base.signals,
    suppress_days: base.suppressDays,
    sort_by: base.sortBy,
    max_rows: base.maxRows,
    skip_flippers: base.skipFlippers ? "1" : "0",
  };
  for (const [k, v] of Object.entries(overrides)) merged[snake(k)] = v;
  for (const [k, v] of Object.entries(merged)) {
    if (Array.isArray(v)) {
      for (const x of v) if (x) params.append(k, String(x));
    } else if (v != null && v !== "" && v !== false) {
      params.append(k, String(v));
    }
  }
  return params.toString();
}

function snake(s: string): string {
  return s.replace(/([A-Z])/g, "_$1").toLowerCase();
}
