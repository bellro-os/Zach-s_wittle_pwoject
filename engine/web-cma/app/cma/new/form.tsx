"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { BrandSummary } from "@/lib/brands";
import { FadeIn, SpotCard } from "@/components/ratified-ui";
import { AddressTypeahead, type PropertyMatch } from "./_address_typeahead";
import { CompPreview } from "./_comp_preview";

interface GenerateResponse {
  ok: boolean;
  error?: string;
  pdfName?: string;
  htmlName?: string;
  subject?: string;
  valueLow?: number;
  valueMid?: number;
  valueHigh?: number;
  compCount?: number;
  pages?: number;
  elapsedSeconds?: number;
  stderr?: string;
}

function formatMoney(n?: number | null): string {
  if (n == null || !isFinite(n)) return "—";
  return "$" + Math.round(n).toLocaleString();
}

function statusChipClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "active") return "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (s === "closed") return "border border-white/10 bg-white/[0.06] text-slate-300";
  if (s === "pending") return "border border-amber-400/30 bg-amber-400/10 text-amber-300";
  return "border border-white/10 bg-white/[0.04] text-slate-400"; // off-market
}

export function NewCmaForm({ brands }: { brands: BrandSummary[] }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [address, setAddress] = useState("");
  const [selected, setSelected] = useState<PropertyMatch | null>(null);
  const [brand, setBrand] = useState(brands[0]?.name ?? "gravity");
  const [agent, setAgent] = useState("");
  const [comps, setComps] = useState("");
  const [months, setMonths] = useState(24);
  const [allowMultiPage, setAllowMultiPage] = useState(false);
  const [aiHygiene, setAiHygiene] = useState(false);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  // Pass B — comp preview state. ``excluded`` and ``forced`` are passed both
  // to the preview endpoint (to re-fetch) and to the generate endpoint (so
  // the PDF reflects the trimmed set).
  const [excluded, setExcluded] = useState<string[]>([]);
  const [forced, setForced] = useState<string[]>([]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setResult(null);
    startTransition(async () => {
      const res = await fetch("/api/cma/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          // Prefer the parcel_id from the selected match — more precise than
          // free-form address parsing on the backend.
          parcelId: selected?.parcel_id || undefined,
          address: selected?.address || address,
          brand,
          agent: agent || undefined,
          // Merge the legacy comma-separated "comps" field (free-form override)
          // with the preview-driven ``forced`` list — both go to the same
          // ``--comps`` mechanism in the Python builder.
          comps: [
            ...(comps ? comps.split(",").map((s) => s.trim()).filter(Boolean) : []),
            ...forced,
          ].length
            ? [
                ...(comps ? comps.split(",").map((s) => s.trim()).filter(Boolean) : []),
                ...forced,
              ]
            : undefined,
          excluded: excluded.length ? excluded : undefined,
          months,
          allowMultiPage,
          aiHygiene,
        }),
      });
      const data: GenerateResponse = await res.json().catch(() => ({
        ok: false,
        error: "Server returned non-JSON response",
      }));
      setResult(data);
      if (data.ok) {
        // Refresh the home-page "Recent CMAs" list when the user navigates back.
        router.refresh();
      }
    });
  }

  const selectedBrand = brands.find((b) => b.name === brand);

  return (
    <div className="space-y-6">
      <FadeIn>
      <form onSubmit={handleSubmit} className="edge-light space-y-5 rounded-2xl border border-white/10 bg-ink-900/80 p-6">
        <div>
          <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-slate-500">Subject address *</label>
          {selected ? (
            <div className="flex items-start justify-between gap-3 rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-3.5">
              <div className="min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold text-white truncate">{selected.address}</span>
                  <span
                    className={
                      "shrink-0 rounded-full text-[10px] uppercase tracking-wider px-2 py-0.5 font-semibold " +
                      statusChipClass(selected.status)
                    }
                  >
                    {selected.status}
                  </span>
                </div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {[selected.city, selected.county].filter(Boolean).join(", ")}
                  {selected.subdivision ? ` · ${selected.subdivision}` : ""}
                  {selected.parcel_id ? ` · parcel ${selected.parcel_id}` : ""}
                </div>
                <div className="text-xs text-slate-300 mt-1">
                  {[
                    selected.sqft ? `${selected.sqft.toLocaleString()} sf` : null,
                    selected.acres ? `${selected.acres.toFixed(2)} ac` : null,
                    selected.year_built && selected.year_built > 1800 && selected.year_built < 2100
                      ? `built ${selected.year_built}`
                      : null,
                    selected.bedrooms && selected.full_baths
                      ? `${selected.bedrooms}bd/${selected.full_baths}ba`
                      : null,
                    selected.owner ? `owner ${selected.owner.slice(0, 30)}` : null,
                    selected.list_price && selected.status === "Active"
                      ? `list ${formatMoney(selected.list_price)}`
                      : null,
                    selected.last_sale_price && selected.last_sale_date
                      ? `last sold ${String(selected.last_sale_date).slice(0, 10)} ${formatMoney(selected.last_sale_price)}`
                      : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelected(null);
                  setAddress("");
                  setExcluded([]);
                  setForced([]);
                }}
                className="shrink-0 text-xs text-slate-400 underline-offset-4 hover:text-white hover:underline"
              >
                × change
              </button>
            </div>
          ) : (
            <>
              <AddressTypeahead
                value={address}
                onChange={setAddress}
                onSelect={(m) => {
                  setSelected(m);
                  setExcluded([]);
                  setForced([]);
                }}
                placeholder='e.g. "509 Jefferson St Blacksburg" or "7423 Floyd Highway N"'
              />
              <p className="text-xs text-slate-500 mt-1.5">
                Live search across MLS + assessor parcels (12 counties: NRV core + extended). Pick from
                the dropdown to confirm the right property. You can also paste a parcel ID directly.
              </p>
            </>
          )}
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-slate-500">Brand</label>
            <select
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
              className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-white transition-colors focus:border-emerald-500/40 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
            >
              {brands.map((b) => (
                <option key={b.name} value={b.name} className="bg-ink-800 text-white">
                  {b.display_name} ({b.layout_style})
                </option>
              ))}
            </select>
            {selectedBrand && (
              <div className="mt-2.5 flex items-center gap-2">
                <span
                  className="size-3.5 rounded border border-white/15"
                  style={{ background: selectedBrand.primary }}
                />
                <span
                  className="size-3.5 rounded border border-white/15"
                  style={{ background: selectedBrand.secondary }}
                />
                <span
                  className="size-3.5 rounded border border-white/15"
                  style={{ background: selectedBrand.paper }}
                />
                <span className="text-xs text-slate-500">{selectedBrand.layout_style}</span>
              </div>
            )}
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-slate-500">Agent name (optional)</label>
            <input
              type="text"
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
              placeholder={selectedBrand?.agent_name || "Defaults to brand profile"}
              className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500 transition-colors focus:border-emerald-500/40 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
            />
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-slate-500">Force-include comps (optional)</label>
          <input
            type="text"
            value={comps}
            onChange={(e) => setComps(e.target.value)}
            placeholder='Comma-separated, e.g. "446 Good Neighbors, 877 Old Furnace"'
            className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500 transition-colors focus:border-emerald-500/40 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
          />
          <p className="text-xs text-slate-500 mt-1.5">
            Useful for outlier subjects where the auto comp set misses key recents.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-slate-500">Lookback (months)</label>
            <input
              type="number"
              min={3}
              max={60}
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-white transition-colors focus:border-emerald-500/40 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
            />
          </div>
          <div className="flex flex-col justify-center gap-2 pt-1">
            <label className="flex items-center gap-2.5 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={allowMultiPage}
                onChange={(e) => setAllowMultiPage(e.target.checked)}
                className="size-4 rounded border-white/20 bg-white/[0.03] text-emerald-400 accent-emerald-400 focus:ring-emerald-400/30"
              />
              Allow multi-page output
            </label>
            <label className="flex items-center gap-2.5 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={aiHygiene}
                onChange={(e) => setAiHygiene(e.target.checked)}
                className="size-4 rounded border-white/20 bg-white/[0.03] text-emerald-400 accent-emerald-400 focus:ring-emerald-400/30"
              />
              AI comp review
              <span className="text-xs text-slate-500">(needs API key)</span>
            </label>
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-white/10 pt-4">
          <p className="text-xs text-slate-500">
            Renders to <code className="rounded bg-white/[0.06] px-1.5 py-0.5 text-emerald-300">outputs/</code> on the file system.
          </p>
          <button
            type="submit"
            disabled={pending || !address}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-emerald-400 px-6 py-2.5 text-sm font-semibold text-ink-950 shadow-[0_0_28px_rgba(16,185,129,0.35)] transition-all duration-300 hover:bg-emerald-300 hover:shadow-[0_0_44px_rgba(16,185,129,0.5)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
          >
            {pending ? "Generating…" : "Generate CMA"}
          </button>
        </div>
      </form>
      </FadeIn>

      {selected && (
        <CompPreview
          address={selected.address}
          parcelId={selected.parcel_id || undefined}
          months={months}
          aiHygiene={aiHygiene}
          excluded={excluded}
          forced={forced}
          onExcludedChange={setExcluded}
          onForcedChange={setForced}
        />
      )}

      {result && (
        <FadeIn>
        <div
          className={
            "rounded-2xl border p-6 " +
            (result.ok
              ? "edge-light border-emerald-500/25 bg-ink-900/80"
              : "border-rose-400/30 bg-rose-500/10")
          }
        >
          {result.ok ? (
            <>
              <div className="flex items-center justify-between mb-5">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">Generated</div>
                  <div className="text-lg font-semibold text-white mt-1">{result.subject}</div>
                </div>
                <a
                  href={`/api/cma/pdf/${encodeURIComponent(result.pdfName ?? "")}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 rounded-full bg-emerald-400 px-5 py-2.5 text-sm font-semibold text-ink-950 shadow-[0_0_28px_rgba(16,185,129,0.35)] transition-all duration-300 hover:bg-emerald-300 hover:shadow-[0_0_44px_rgba(16,185,129,0.5)]"
                >
                  Open PDF →
                </a>
              </div>
              <dl className="grid sm:grid-cols-4 gap-4 text-sm">
                <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <dt className="text-[10px] uppercase tracking-wider text-slate-500">Value midpoint</dt>
                  <dd className="text-xl font-semibold tracking-tight text-white mt-1">{formatMoney(result.valueMid)}</dd>
                  <dd className="text-xs text-slate-500 mt-0.5">
                    {formatMoney(result.valueLow)} – {formatMoney(result.valueHigh)}
                  </dd>
                </div>
                <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <dt className="text-[10px] uppercase tracking-wider text-slate-500">Comps</dt>
                  <dd className="text-xl font-semibold tracking-tight text-white mt-1">{result.compCount}</dd>
                </div>
                <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <dt className="text-[10px] uppercase tracking-wider text-slate-500">Pages</dt>
                  <dd className="text-xl font-semibold tracking-tight text-white mt-1">{result.pages}</dd>
                </div>
                <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                  <dt className="text-[10px] uppercase tracking-wider text-slate-500">Elapsed</dt>
                  <dd className="text-xl font-semibold tracking-tight text-white mt-1">
                    {result.elapsedSeconds?.toFixed(1)}s
                  </dd>
                </div>
              </dl>
            </>
          ) : (
            <>
              <div className="font-semibold text-rose-300">
                {result.error?.toLowerCase().includes("locate")
                  ? "Subject not found"
                  : "Generation failed"}
              </div>
              <p className="text-sm text-rose-200/90 mt-2">{result.error}</p>
              {result.error?.toLowerCase().includes("locate") && (
                <p className="text-sm text-rose-200/70 mt-3">
                  Try typing again and picking a property from the dropdown — that uses the parcel ID,
                  which is more precise. Or paste the parcel ID directly into the address field if you
                  know it.
                </p>
              )}
              {result.stderr && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-xs text-rose-200/70">Show diagnostic output</summary>
                  <pre className="mt-2 overflow-x-auto rounded-lg border border-rose-400/20 bg-rose-950/40 p-3 text-xs text-rose-200/80">
                    {result.stderr}
                  </pre>
                </details>
              )}
            </>
          )}
        </div>
        </FadeIn>
      )}
    </div>
  );
}
