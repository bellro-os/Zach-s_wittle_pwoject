"use client";

import { useEffect, useState } from "react";
import { FadeIn } from "@/components/ratified-ui";
import { AddressTypeahead, type PropertyMatch } from "./_address_typeahead";

interface SubjectSummary {
  address?: string | null;
  city?: string | null;
  county?: string | null;
  subdivision?: string | null;
  parcel_id?: string | null;
  status?: string | null;
  list_price?: number | null;
  sqft?: number | null;
  acres?: number | null;
  year_built?: number | null;
  bedrooms?: number | null;
  full_baths?: number | null;
  half_baths?: number | null;
  assessed_total?: number | null;
  deed_last_sale_date?: string | null;
  deed_last_sale_price?: number | null;
  owner?: string | null;
  feed_dom?: number | null;
}

interface CompRow {
  address?: string | null;
  city?: string | null;
  county?: string | null;
  subdivision?: string | null;
  parcel_id?: string | null;
  listing_id?: string | null;
  sold_price?: number | null;
  original_list_price?: number | null;
  sqft?: number | null;
  acres?: number | null;
  year_built?: number | null;
  bedrooms?: number | null;
  full_baths?: number | null;
  half_baths?: number | null;
  dom?: number | null;
  close_date?: string | null;
  score?: number | null;
  distance_mi?: number | null;
  cohort?: string | null;
  atypical_sale?: boolean;
  atypical_reason?: string | null;
  appearance?: string | null;
  appearance_tier?: number | null;
  appearance_adj_pct?: number | null;
  pending?: boolean;
  status?: string | null;
  forced?: boolean;
}

interface ValuationMethod {
  name: string;
  value: number | null;
  low?: number | null;
  high?: number | null;
  rationale: string;
}

interface ValuationSummary {
  low: number;
  mid: number;
  high: number;
  ppsf: number;
  divergence_pct: number;
  methods: ValuationMethod[];
}

interface CmaCritique {
  overall: string;
  confidence: string;
  weak_comps: Array<{ address: string; why: string }>;
  missing: string[];
  value_check: string;
}

interface PreviewResponse {
  ok: boolean;
  error?: string;
  subject?: SubjectSummary;
  comps?: CompRow[];
  valuation?: ValuationSummary;
  hygiene_dropped?: string[];
  cma_critique?: CmaCritique | null;
  elapsed_seconds?: number;
}

function money(n?: number | null): string {
  if (n == null || !isFinite(n)) return "—";
  return "$" + Math.round(n).toLocaleString();
}

function shortMoney(n?: number | null): string {
  if (n == null || !isFinite(n)) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1000)}k`;
  return `$${Math.round(n)}`;
}

function cohortLabel(c?: string | null): string {
  if (!c) return "—";
  const m = c.match(/^within_([\d.]+)mi$/);
  if (m) return `Within ${m[1]} mi`;
  switch (c) {
    case "subdivision": return "Same subdivision";
    case "county_strict": return "Same county";
    case "county_wider": return "Same county (wide)";
    case "any_strict": return "Outside county";
    case "any_wider": return "Outside county (wide)";
    case "county_only": return "Same county";
    case "any": return "All counties";
    default: return c;
  }
}

function cohortChip(c?: string | null): string {
  const base = "rounded-full text-[10px] uppercase tracking-wider px-2 py-0.5 font-semibold border ";
  if (c === "subdivision") return base + "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  const m = c?.match(/^within_([\d.]+)mi$/);
  if (m) {
    const mi = parseFloat(m[1]);
    if (mi <= 1) return base + "border-emerald-500/25 bg-emerald-500/10 text-emerald-300";
    if (mi <= 5) return base + "border-sky-400/30 bg-sky-400/10 text-sky-300";
    return base + "border-sky-400/20 bg-sky-400/[0.07] text-sky-300/80";
  }
  return base + "border-white/10 bg-white/[0.04] text-slate-400";
}

interface Props {
  address: string;
  parcelId?: string;
  months: number;
  aiHygiene?: boolean;
  excluded: string[];
  forced: string[];
  onExcludedChange: (addr: string[]) => void;
  onForcedChange: (addr: string[]) => void;
  onResult?: (r: PreviewResponse) => void;
}

export function CompPreview({
  address,
  parcelId,
  months,
  aiHygiene,
  excluded,
  forced,
  onExcludedChange,
  onForcedChange,
  onResult,
}: Props) {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [forceInputValue, setForceInputValue] = useState("");

  useEffect(() => {
    if (!address && !parcelId) {
      setData(null);
      return;
    }
    let aborted = false;
    setLoading(true);
    const ctrl = new AbortController();
    (async () => {
      try {
        const res = await fetch("/api/cma/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            address,
            parcelId,
            months,
            aiHygiene: aiHygiene || undefined,
            excluded: excluded.length ? excluded : undefined,
            forced: forced.length ? forced : undefined,
          }),
          signal: ctrl.signal,
        });
        const json: PreviewResponse = await res.json();
        if (!aborted) {
          setData(json);
          onResult?.(json);
        }
      } catch (e) {
        if (!aborted && (e as Error).name !== "AbortError") {
          setData({ ok: false, error: String(e) });
        }
      } finally {
        if (!aborted) setLoading(false);
      }
    })();
    return () => {
      aborted = true;
      ctrl.abort();
    };
  }, [address, parcelId, months, aiHygiene, excluded.join("|"), forced.join("|")]);

  if (!address && !parcelId) return null;

  if (loading && !data) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-ink-900/80 p-6 text-sm text-slate-400">
        <span className="size-2 animate-pulse rounded-full bg-emerald-400" />
        Previewing comps and valuation…
      </div>
    );
  }
  if (!data) return null;
  if (!data.ok) {
    return (
      <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 p-6 text-sm text-rose-200/90">
        Preview failed: {data.error}
      </div>
    );
  }

  const valuation = data.valuation;
  const comps = data.comps ?? [];
  const subject = data.subject ?? {};

  function removeComp(addr: string) {
    if (!addr) return;
    if (!excluded.includes(addr)) onExcludedChange([...excluded, addr]);
  }
  function addForce(m: PropertyMatch) {
    if (!m.address) return;
    if (!forced.includes(m.address)) onForcedChange([...forced, m.address]);
    setForceInputValue("");
  }
  function removeForce(addr: string) {
    onForcedChange(forced.filter((a) => a !== addr));
  }

  return (
    <FadeIn>
    <div className="edge-light overflow-hidden rounded-2xl border border-white/10 bg-ink-900/80">
      {/* Subject summary */}
      <div className="grid gap-3 border-b border-white/10 bg-white/[0.03] px-6 py-5 sm:grid-cols-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Subject</div>
          <div className="font-semibold text-white mt-1">{subject.address}</div>
          <div className="text-xs text-slate-400">
            {[subject.city, subject.county].filter(Boolean).join(", ")}
            {subject.subdivision && subject.subdivision !== "None" ? ` · ${subject.subdivision}` : ""}
            {subject.parcel_id ? ` · parcel ${subject.parcel_id}` : ""}
          </div>
          <div className="text-xs text-slate-300 mt-1">
            {[
              subject.sqft ? `${subject.sqft.toLocaleString()} sf` : null,
              subject.acres ? `${subject.acres.toFixed(2)} ac` : null,
              subject.year_built ? `built ${subject.year_built}` : null,
              subject.bedrooms && subject.full_baths
                ? `${subject.bedrooms}bd/${subject.full_baths}ba`
                : null,
              subject.status ? subject.status : null,
              subject.list_price ? `list ${money(subject.list_price)}` : null,
            ].filter(Boolean).join(" · ")}
          </div>
          {(subject.deed_last_sale_price || subject.assessed_total || subject.owner) && (
            <div className="text-xs text-slate-400 mt-1">
              {subject.deed_last_sale_price
                ? `Last sold ${String(subject.deed_last_sale_date ?? "").slice(0, 10)} ${money(subject.deed_last_sale_price)}`
                : ""}
              {subject.assessed_total ? ` · assessed ${money(subject.assessed_total)}` : ""}
              {subject.owner ? ` · owner ${subject.owner.slice(0, 30)}` : ""}
            </div>
          )}
        </div>
        {valuation && (
          <div className="sm:text-right">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Triangulated value</div>
            <div className="text-3xl font-semibold tracking-tight text-emerald-300 mt-1">{shortMoney(valuation.mid)}</div>
            <div className="text-xs text-slate-400">
              {shortMoney(valuation.low)} – {shortMoney(valuation.high)}
            </div>
            <div className={`text-[10px] mt-1 ${valuation.divergence_pct > 15 ? "text-amber-300" : "text-slate-500"}`}>
              methods diverge {valuation.divergence_pct.toFixed(0)}%
            </div>
          </div>
        )}
      </div>

      {/* Comp table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-white/10 bg-white/[0.03] text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Cohort</th>
              <th className="px-4 py-3 text-left font-medium">Address</th>
              <th className="px-4 py-3 text-right font-medium">Sold</th>
              <th className="px-4 py-3 text-right font-medium">Price</th>
              <th className="px-4 py-3 text-right font-medium">sf</th>
              <th className="px-4 py-3 text-right font-medium">ac</th>
              <th className="px-4 py-3 text-right font-medium">$/sf</th>
              <th className="px-4 py-3 text-right font-medium">Dist</th>
              <th className="px-4 py-3 text-right font-medium sr-only">Remove</th>
            </tr>
          </thead>
          <tbody>
            {comps.map((c, i) => {
              const ppsf = c.sqft && c.sold_price ? c.sold_price / c.sqft : null;
              return (
                <tr key={`${c.parcel_id || c.address}-${i}`} className="border-t border-white/8 transition-colors hover:bg-white/[0.02]">
                  <td className="px-4 py-3 align-top">
                    <span className={cohortChip(c.cohort)}>{cohortLabel(c.cohort)}</span>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <div className="font-medium text-white">
                      {c.address}
                      {c.pending && (
                        <span className="ml-2 rounded-full border border-sky-400/30 bg-sky-400/10 text-sky-300 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider align-middle">
                          Pending
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-400">
                      {[c.city, c.county].filter(Boolean).join(", ")}
                      {c.subdivision && c.subdivision !== "None" ? ` · ${c.subdivision}` : ""}
                      {c.appearance_tier != null &&
                        c.appearance_adj_pct != null &&
                        Math.abs(c.appearance_adj_pct) >= 1 && (
                          <span className="ml-1 text-slate-500">
                            · cond{" "}
                            {["needs work", "fair", "average", "good", "renovated", "new-build"][
                              c.appearance_tier
                            ] ?? "?"}{" "}
                            ({c.appearance_adj_pct > 0 ? "+" : ""}
                            {Math.round(c.appearance_adj_pct)}%)
                          </span>
                        )}
                    </div>
                    {c.atypical_sale && (
                      <div className="text-[10px] mt-1.5">
                        <span className="rounded-full border border-amber-400/30 bg-amber-400/10 text-amber-300 px-2 py-0.5 font-semibold uppercase tracking-wider">
                          Atypical
                        </span>
                        <span className="text-amber-300/90 ml-1.5">{c.atypical_reason}</span>
                      </div>
                    )}
                    {c.forced && (
                      <div className="text-[10px] mt-1.5">
                        <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 px-2 py-0.5 font-semibold uppercase tracking-wider">
                          Forced
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 align-top text-right text-slate-400">
                    {c.pending ? (
                      <span className="text-sky-300">pending {String(c.close_date ?? "").slice(0, 10)}</span>
                    ) : (
                      String(c.close_date ?? "").slice(0, 10)
                    )}
                  </td>
                  <td className="px-4 py-3 align-top text-right font-medium text-white">
                    {money(c.sold_price)}
                    {c.pending && <span className="text-[10px] font-normal text-slate-500"> est</span>}
                  </td>
                  <td className="px-4 py-3 align-top text-right text-slate-400">
                    {c.sqft != null ? c.sqft.toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-3 align-top text-right text-slate-400">
                    {c.acres != null ? c.acres.toFixed(1) : "—"}
                  </td>
                  <td className="px-4 py-3 align-top text-right text-slate-400">
                    {ppsf ? `$${Math.round(ppsf)}` : "—"}
                  </td>
                  <td className="px-4 py-3 align-top text-right text-slate-400">
                    {c.distance_mi != null && isFinite(c.distance_mi) ? `${c.distance_mi.toFixed(1)}mi` : "—"}
                  </td>
                  <td className="px-4 py-3 align-top text-right">
                    <button
                      type="button"
                      onClick={() => removeComp(c.address ?? "")}
                      className="text-xs text-slate-500 transition-colors hover:text-rose-300"
                      title="Remove from comp set"
                    >
                      × remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Excluded list + force-include row */}
      <div className="space-y-2 border-t border-white/10 bg-white/[0.03] px-6 py-4">
        {excluded.length > 0 && (
          <div className="text-xs text-slate-400">
            Excluded:{" "}
            {excluded.map((a) => (
              <span key={a} className="mr-1.5 mb-1 inline-flex items-center rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-0.5">
                <span className="text-slate-300">{a}</span>
                <button
                  type="button"
                  onClick={() => onExcludedChange(excluded.filter((x) => x !== a))}
                  className="ml-2 text-slate-500 hover:text-white"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        {forced.length > 0 && (
          <div className="text-xs text-slate-400">
            Force-included:{" "}
            {forced.map((a) => (
              <span key={a} className="mr-1.5 mb-1 inline-flex items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-emerald-300">
                <span>{a}</span>
                <button
                  type="button"
                  onClick={() => removeForce(a)}
                  className="ml-2 text-emerald-300/60 hover:text-emerald-200"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="text-[11px] uppercase tracking-wider text-slate-500">
          Add a specific comp by address
        </div>
        <div className="max-w-md">
          <AddressTypeahead
            value={forceInputValue}
            onChange={setForceInputValue}
            onSelect={(m) => {
              if (m) addForce(m);
            }}
            placeholder='e.g. "4900 Morris Rd"'
          />
        </div>
      </div>

      {/* AI hygiene + adversarial review (Layers 1 & 3) */}
      {(data.cma_critique || (data.hygiene_dropped && data.hygiene_dropped.length > 0)) && (
        <div className="space-y-2 border-t border-white/10 bg-emerald-500/[0.04] px-6 py-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
              AI review
            </span>
            {data.cma_critique?.confidence && (
              <span className="text-slate-400">confidence: {data.cma_critique.confidence}</span>
            )}
          </div>
          {data.hygiene_dropped && data.hygiene_dropped.length > 0 && (
            <div className="text-slate-300">
              <span className="font-semibold text-amber-300">Dropped by hygiene:</span>{" "}
              {data.hygiene_dropped.join(", ")}
            </div>
          )}
          {data.cma_critique?.overall && (
            <div className="text-slate-300">{data.cma_critique.overall}</div>
          )}
          {data.cma_critique?.weak_comps && data.cma_critique.weak_comps.length > 0 && (
            <div className="text-slate-300">
              <span className="font-semibold text-white">Flagged:</span>
              <ul className="ml-5 mt-0.5 list-disc">
                {data.cma_critique.weak_comps.map((w, i) => (
                  <li key={i}>
                    <span className="font-medium text-white">{w.address}</span> — {w.why}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.cma_critique?.missing && data.cma_critique.missing.length > 0 && (
            <div className="text-slate-300">
              <span className="font-semibold text-white">Missing:</span> {data.cma_critique.missing.join("; ")}
            </div>
          )}
          {data.cma_critique?.value_check && (
            <div className="italic text-slate-400">{data.cma_critique.value_check}</div>
          )}
        </div>
      )}

      {/* Methods detail */}
      {valuation && (
        <div className="space-y-1.5 border-t border-white/10 px-6 py-4 text-xs">
          {valuation.methods.map((m) => (
            <div key={m.name} className="text-slate-300">
              <span className="font-semibold text-white">{m.name}:</span>{" "}
              <span className="text-slate-400" dangerouslySetInnerHTML={{ __html: m.rationale }} />
            </div>
          ))}
          {data.elapsed_seconds != null && (
            <div className="text-slate-500">preview in {data.elapsed_seconds.toFixed(1)}s</div>
          )}
        </div>
      )}
    </div>
    </FadeIn>
  );
}
