"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { X, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  ALL_LEAD_TYPES,
  leadTypeLabel,
  leadTypeBadgeVariant,
} from "@/lib/data/lead-types";

export function QueueToolbar({
  counts,
  selectedLeadTypes,
  selectedCounties,
  knownCounties,
  minScore,
  suppressDays,
  sortBy,
  maxRows,
  ownerTypes,
  signals,
  skipFlippers,
  mode,
}: {
  counts: Record<string, number>;
  selectedLeadTypes: string[];
  selectedCounties: string[];
  knownCounties: string[];
  minScore: number;
  suppressDays: number;
  sortBy: string;
  maxRows: number;
  ownerTypes: string[];
  signals: string[];
  skipFlippers: boolean;
  mode: "call" | "knock";
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function update(updates: Record<string, string | string[] | undefined>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      params.delete(k);
      if (Array.isArray(v)) {
        for (const item of v) if (item) params.append(k, item);
      } else if (v != null && v !== "") {
        params.set(k, String(v));
      }
    }
    router.push(`/?${params.toString()}`, { scroll: false });
  }

  const toggleLeadType = (lt: string) => {
    const next = selectedLeadTypes.includes(lt)
      ? selectedLeadTypes.filter((x) => x !== lt)
      : [...selectedLeadTypes, lt];
    update({ lead_types: next });
  };

  const removeCounty = (c: string) =>
    update({ counties: selectedCounties.filter((x) => x !== c) });

  const addCounty = (c: string) => {
    if (!c || selectedCounties.includes(c)) return;
    update({ counties: [...selectedCounties, c] });
  };

  const reset = () => router.push("/?mode=" + mode, { scroll: false });

  return (
    <div className="space-y-4">
      {/* Lead-type filter chip group */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-(--color-muted-foreground)">
            Filter by lead type
          </span>
          {selectedLeadTypes.length > 0 && (
            <button
              type="button"
              onClick={() => update({ lead_types: [] })}
              className="text-xs text-(--color-muted-foreground) hover:text-(--color-foreground) inline-flex items-center gap-1"
            >
              <X className="size-3" /> clear
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {ALL_LEAD_TYPES.filter(
            (lt) => (counts[lt] ?? 0) > 0 || selectedLeadTypes.includes(lt),
          ).map((lt) => {
            const checked = selectedLeadTypes.includes(lt);
            const variant = leadTypeBadgeVariant(lt);
            return (
              <button
                key={lt}
                type="button"
                onClick={() => toggleLeadType(lt)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-all",
                  checked
                    ? "border-(--color-primary) bg-(--color-primary)/10"
                    : "border-(--color-border) bg-(--color-card) hover:bg-(--color-accent)",
                )}
              >
                <Badge variant={variant} className="px-1.5 py-0">
                  {leadTypeLabel(lt)}
                </Badge>
                <span className="tabular-nums text-(--color-muted-foreground)">
                  {counts[lt] ?? 0}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Min score slider */}
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-(--color-muted-foreground) flex justify-between mb-1.5">
            Min score
            <span className="tabular-nums text-(--color-foreground)">{minScore}</span>
          </label>
          <input
            type="range"
            min={20}
            max={100}
            step={5}
            value={minScore}
            onChange={(e) => update({ min_score: e.target.value })}
            className="w-full accent-(--color-primary)"
          />
        </div>

        {/* Suppress slider */}
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-(--color-muted-foreground) flex justify-between mb-1.5">
            Suppress ≤ days
            <span className="tabular-nums text-(--color-foreground)">{suppressDays}</span>
          </label>
          <input
            type="range"
            min={0}
            max={180}
            step={15}
            value={suppressDays}
            onChange={(e) => update({ suppress_days: e.target.value })}
            className="w-full accent-(--color-primary)"
          />
        </div>

        {/* Counties chip-input */}
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider text-(--color-muted-foreground) mb-1.5 block">
            Counties
          </label>
          <div className="flex flex-wrap items-center gap-1 mb-1.5 min-h-7">
            {selectedCounties.map((c) => (
              <span
                key={c}
                className="inline-flex items-center gap-1 rounded-full bg-(--color-primary) text-(--color-primary-foreground) px-2 py-0.5 text-xs font-medium"
              >
                {c}
                <button
                  type="button"
                  onClick={() => removeCounty(c)}
                  className="hover:bg-white/20 rounded-full p-0.5"
                >
                  <X className="size-3" />
                </button>
              </span>
            ))}
          </div>
          <input
            type="text"
            list="county-options"
            placeholder="+ add county"
            className="h-7 w-full rounded-md border border-(--color-input) bg-(--color-background) px-2 text-xs focus:outline-none focus:ring-2 focus:ring-(--color-ring)"
            onChange={(e) => {
              const v = e.target.value.toUpperCase().trim();
              if (v && knownCounties.includes(v)) {
                addCounty(v);
                e.target.value = "";
              }
            }}
          />
          <datalist id="county-options">
            {knownCounties.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>

        {/* Sort + max rows */}
        <div className="space-y-2">
          {mode === "call" && (
            <div>
              <label className="text-xs font-semibold uppercase tracking-wider text-(--color-muted-foreground) mb-1 block">
                Sort by
              </label>
              <select
                value={sortBy}
                onChange={(e) => update({ sort_by: e.target.value })}
                className="h-7 w-full rounded-md border border-(--color-input) bg-(--color-background) px-2 text-xs"
              >
                <option value="score">Score (high→low)</option>
                <option value="tenure">Tenure (long→short)</option>
                <option value="equity">Equity (high→low)</option>
                <option value="county">County</option>
              </select>
            </div>
          )}
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-(--color-muted-foreground) mb-1 block">
              Show top
            </label>
            <select
              value={maxRows}
              onChange={(e) => update({ max_rows: e.target.value })}
              className="h-7 w-full rounded-md border border-(--color-input) bg-(--color-background) px-2 text-xs"
            >
              {[25, 50, 100, 200].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between pt-2 border-t border-(--color-border)">
        <div className="flex items-center gap-3 text-xs">
          {mode === "call" && (
            <>
              <span className="text-(--color-muted-foreground)">Owner type:</span>
              {["person", "entity"].map((t) => (
                <label key={t} className="inline-flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={ownerTypes.includes(t)}
                    onChange={() =>
                      update({
                        owner_types: ownerTypes.includes(t)
                          ? ownerTypes.filter((x) => x !== t)
                          : [...ownerTypes, t],
                      })
                    }
                  />
                  {t}
                </label>
              ))}
              <label className="inline-flex items-center gap-1.5 cursor-pointer ml-3">
                <input
                  type="checkbox"
                  checked={skipFlippers}
                  onChange={() => update({ skip_flippers: skipFlippers ? "0" : "1" })}
                />
                Skip flippers
              </label>
            </>
          )}
          {signals.length > 0 && (
            <span className="text-(--color-muted-foreground)">
              required: {signals.join(", ")}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={reset}
          className="text-xs text-(--color-muted-foreground) hover:text-(--color-foreground) inline-flex items-center gap-1"
        >
          <RotateCcw className="size-3" /> reset all
        </button>
      </div>
    </div>
  );
}
