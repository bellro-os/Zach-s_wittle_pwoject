"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/compbird/ui";
import { cn } from "@/lib/utils/cn";
import {
  buildQueue,
  parseAddressLines,
  parseCsv,
  PORTFOLIO_CAP,
  type ParsedEntry,
} from "./csv";

/**
 * The run builder: paste addresses (one per line) and/or drop a CSV (first
 * column address, optional second column label). Both sources merge into one
 * deduped queue, hard-capped at 50 with a visible "+N trimmed" note, and the
 * Run button POSTs the whole queue at once.
 *
 * FREE accounts see the panel intact but inert behind the Pro upsell overlay —
 * the same visual boundary the studio's LockedPanel draws (the controls are
 * disabled AND the server 403s, so the overlay is honesty, not enforcement).
 */

/** Generic subject glyph — a stacked-parcels mark for the portfolio idea. */
function StackGlyph() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4" aria-hidden>
      <path
        d="M8 2 14 5 8 8 2 5l6-3Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="m2 8 6 3 6-3M2 11l6 3 6-3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function PortfolioInputPanel({
  pro,
  busy,
  onRun,
}: {
  /** Account may run portfolios (SOLO/Pro). FREE renders the upsell overlay. */
  pro: boolean;
  /** A run is being created / is in flight — the button parks. */
  busy: boolean;
  onRun: (items: ParsedEntry[]) => void;
}) {
  const [text, setText] = useState("");
  const [csvEntries, setCsvEntries] = useState<ParsedEntry[]>([]);
  const [csvName, setCsvName] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const queue = useMemo(
    () => buildQueue([...parseAddressLines(text), ...csvEntries]),
    [text, csvEntries],
  );

  function onFile(file: File | null) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const parsed = parseCsv(String(reader.result ?? ""));
      if (!parsed.length) {
        toast.error("No addresses found in that CSV — first column should be the address.");
        return;
      }
      setCsvEntries(parsed);
      setCsvName(file.name);
    };
    reader.onerror = () => toast.error("Couldn't read that file.");
    reader.readAsText(file);
  }

  function clearCsv() {
    setCsvEntries([]);
    setCsvName(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  const disabled = !pro || busy;
  const count = queue.items.length;

  return (
    <div className="relative overflow-hidden rounded-2xl border border-border bg-card/70 p-5 sm:p-7">
      <div className={cn(!pro && "pointer-events-none select-none blur-[2px]")} aria-hidden={!pro}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="cb-eyebrow text-muted-foreground">Build the run</span>
          <span className="text-xs text-muted-foreground">up to {PORTFOLIO_CAP} properties</span>
        </div>

        <label htmlFor="cb-portfolio-addresses" className="sr-only">
          Addresses, one per line
        </label>
        <textarea
          id="cb-portfolio-addresses"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={disabled}
          rows={7}
          placeholder={"one address per line — up to 50\n509 Jefferson St, Blacksburg, VA\n1203 Walnut Ridge Rd, Christiansburg, VA"}
          spellCheck={false}
          className="font-data mt-4 w-full resize-y rounded-xl border border-border bg-background/60 px-4 py-3 text-sm text-foreground outline-none transition-colors placeholder:font-sans placeholder:text-muted-foreground focus:border-[var(--cb-ember)]/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:opacity-60"
        />

        {/* CSV path */}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            disabled={disabled}
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            disabled={disabled}
            onClick={() => fileRef.current?.click()}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3.5 py-2 text-xs font-medium text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
          >
            <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5" aria-hidden>
              <path
                d="M8 10V2m0 0L5 5m3-3 3 3M3 11v2a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-2"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Upload CSV
          </button>
          <span className="text-xs text-muted-foreground">
            first column address · optional second column label
          </span>
        </div>

        {/* CSV parse preview */}
        {csvName && csvEntries.length ? (
          <div className="mt-3 rounded-xl border border-border bg-background/50 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-medium text-foreground">
                {csvName} — {csvEntries.length} {csvEntries.length === 1 ? "address" : "addresses"} parsed
              </span>
              <button
                type="button"
                onClick={clearCsv}
                disabled={disabled}
                className="text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
              >
                Remove
              </button>
            </div>
            <ul className="mt-2 flex flex-col gap-1">
              {csvEntries.slice(0, 3).map((e, i) => (
                <li key={i} className="flex items-baseline gap-2 truncate text-xs text-muted-foreground">
                  <span aria-hidden className="h-px w-2.5 shrink-0 translate-y-[-0.2em] bg-[var(--cb-ember)]/70" />
                  <span className="truncate">
                    {e.address}
                    {e.label ? <span className="text-foreground/70"> — {e.label}</span> : null}
                  </span>
                </li>
              ))}
              {csvEntries.length > 3 ? (
                <li className="pl-[1.125rem] text-xs text-muted-foreground">
                  +{csvEntries.length - 3} more
                </li>
              ) : null}
            </ul>
          </div>
        ) : null}

        {/* queue summary + run */}
        <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-border pt-4">
          <Button
            size="md"
            disabled={disabled || count === 0}
            onClick={() => onRun(queue.items)}
            arrow
          >
            {busy ? "Starting run…" : "Run portfolio"}
          </Button>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {count === 0 ? (
              "No addresses yet."
            ) : (
              <>
                <span className="font-data text-foreground">{count}</span>{" "}
                {count === 1 ? "property" : "properties"} ready
                {queue.duplicates > 0 ? ` · ${queue.duplicates} duplicate${queue.duplicates === 1 ? "" : "s"} collapsed` : ""}
                {queue.trimmed > 0 ? (
                  <span className="text-[var(--negative-foreground)]">
                    {" "}
                    · +{queue.trimmed} over the limit trimmed
                  </span>
                ) : null}
              </>
            )}
          </p>
        </div>
      </div>

      {/* ── Pro upsell overlay (FREE accounts) ──────────────────────────── */}
      {!pro ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3.5 bg-background/60 px-6 py-8 text-center backdrop-blur-[2px]">
          <span
            className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] text-[var(--cb-ember-text)]"
            aria-hidden
          >
            <StackGlyph />
          </span>
          <div className="flex flex-col gap-1">
            <span className="cb-eyebrow text-muted-foreground">Portfolio comping</span>
            <p className="text-sm font-medium text-foreground">
              Portfolio comping is part of Pro — $20/mo
            </p>
            <p className="text-xs text-muted-foreground">
              Up to 50 properties per run · estimates, ranges, confidence, CSV export
            </p>
          </div>
          <Button size="sm" href="/pricing">
            See pricing
          </Button>
          <Link
            href="/comps"
            className="text-xs text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            or comp one property free in the studio
          </Link>
        </div>
      ) : null}
    </div>
  );
}
