"use client";

import { useEffect, useRef, useState } from "react";

export interface PropertyMatch {
  source: "mls" | "parcel";
  address: string;
  city: string;
  county: string;
  parcel_id: string;
  acres?: number | null;
  sqft?: number | null;
  year_built?: number | null;
  bedrooms?: number | null;
  full_baths?: number | null;
  half_baths?: number | null;
  owner?: string | null;
  subdivision?: string | null;
  last_sale_price?: number | null;
  last_sale_date?: string | null;
  status: string;
  list_price?: number | null;
  listing_id?: string | null;
}

interface Props {
  value: string;
  onChange: (s: string) => void;
  onSelect: (m: PropertyMatch | null) => void;
  placeholder?: string;
  disabled?: boolean;
}

function formatSummary(m: PropertyMatch): string {
  const bits: string[] = [];
  if (m.sqft) bits.push(`${m.sqft.toLocaleString()} sf`);
  if (m.acres) bits.push(`${m.acres.toFixed(2)} ac`);
  if (m.year_built && m.year_built > 1800 && m.year_built < 2100) bits.push(`built ${m.year_built}`);
  if (m.bedrooms && m.full_baths) bits.push(`${m.bedrooms}bd/${m.full_baths}ba`);
  if (m.owner) bits.push(`owner ${m.owner.slice(0, 24)}`);
  return bits.join(" · ");
}

function statusClass(status: string): string {
  const s = status.toLowerCase();
  if (s === "active") return "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (s === "closed") return "border border-white/10 bg-white/[0.06] text-slate-300";
  if (s === "pending") return "border border-amber-400/30 bg-amber-400/10 text-amber-300";
  return "border border-white/10 bg-white/[0.04] text-slate-400"; // off-market
}

export function AddressTypeahead({ value, onChange, onSelect, placeholder, disabled }: Props) {
  const [results, setResults] = useState<PropertyMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [touched, setTouched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!touched) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = value.trim();
    if (q.length < 2) {
      setResults([]);
      setLoading(false);
      setOpen(false);
      return;
    }
    setLoading(true);
    debounceRef.current = setTimeout(async () => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const res = await fetch(`/api/properties/search?q=${encodeURIComponent(q)}`, {
          signal: ctrl.signal,
          cache: "no-store",
        });
        const data = await res.json();
        setResults(Array.isArray(data.matches) ? data.matches : []);
        setOpen(true);
        setHighlight(0);
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setResults([]);
        }
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [value, touched]);

  // Close dropdown on outside click.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  function commit(m: PropertyMatch) {
    onSelect(m);
    onChange(m.address);
    setOpen(false);
    setTouched(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      if (results[highlight]) {
        e.preventDefault();
        commit(results[highlight]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => {
          setTouched(true);
          onSelect(null);
          onChange(e.target.value);
        }}
        onFocus={() => {
          if (results.length > 0) setOpen(true);
        }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500 transition-colors focus:border-emerald-500/40 focus:outline-none focus:ring-2 focus:ring-emerald-400/30"
      />
      {loading && (
        <div className="absolute right-3 top-3 text-xs text-emerald-300/80">searching…</div>
      )}
      {open && (
        <div className="absolute z-20 left-0 right-0 mt-2 max-h-96 overflow-y-auto rounded-xl border border-white/10 bg-ink-800/95 shadow-2xl shadow-black/60 backdrop-blur-xl">
          {results.length === 0 ? (
            <div className="px-3.5 py-3 text-sm text-slate-400">
              No matches for {JSON.stringify(value.trim())}. Try a parcel ID, or fewer words.
            </div>
          ) : (
            results.map((m, i) => (
              <button
                key={`${m.source}-${m.county}-${m.parcel_id || m.listing_id || i}`}
                type="button"
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  commit(m);
                }}
                className={
                  "w-full text-left px-3.5 py-2.5 border-b border-white/8 last:border-0 transition-colors " +
                  (i === highlight ? "bg-emerald-500/10" : "hover:bg-white/[0.04]")
                }
              >
                <div className="flex items-baseline justify-between gap-3">
                  <div className="font-medium text-white truncate">{m.address || "(no address)"}</div>
                  <span
                    className={
                      "shrink-0 rounded-full text-[10px] uppercase tracking-wider px-2 py-0.5 font-semibold " +
                      statusClass(m.status)
                    }
                  >
                    {m.status}
                  </span>
                </div>
                <div className="text-xs text-slate-400 truncate">
                  {[m.city, m.county].filter(Boolean).join(", ")}
                  {m.subdivision ? ` · ${m.subdivision}` : ""}
                </div>
                <div className="text-xs text-slate-500 mt-0.5 truncate">{formatSummary(m)}</div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
