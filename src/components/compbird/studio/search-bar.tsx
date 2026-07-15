"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Pill } from "@/components/compbird/ui";
import { searchProperties, isRateLimitError } from "@/lib/compbird/api";
import { sqft, titleCase, placeLabel } from "@/lib/compbird/format";
import type { PropertyMatch } from "@/lib/compbird/types";
import { cn } from "@/lib/utils/cn";

/**
 * Address typeahead. Debounced (~250ms) live search with an accessible listbox
 * dropdown, plus one-tap preset chips. Selection is handed up to the studio,
 * which fetches the dossier.
 *
 * CONCURRENT-LOOKUP GATING: while the studio has a profile lookup in flight
 * (`busy`), EVERY selection surface refuses new picks — preset chips,
 * suggestion rows, recents chips, and the Cmd/Ctrl-K palette all gate on the
 * same `pickBlocked` predicate (disabled + dimmed + aria-disabled). No
 * queueing: the escape hatch is Escape, which the studio wires to the
 * in-flight lookup's abort — then everything re-enables. The bar shows WHICH
 * subject is loading (`busySubject`) next to the spinner.
 */

/**
 * ONE predicate decides whether a selection surface accepts a pick while the
 * studio is busy — shared by the dropdown rows/preset chips here and the
 * recents chips + palette rows in recents.tsx, so the surfaces can never
 * drift apart again. Exported for the interaction test.
 */
export function pickBlocked(busy: boolean): boolean {
  return Boolean(busy);
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className} aria-hidden>
      <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.7" />
      <path
        d="m14 14 3.5 3.5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Spinner({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("animate-spin", className)} aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.25" fill="none" />
      <path
        d="M12 3a9 9 0 0 1 9 9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

/** Clamp the echoed query so a pasted blob can't blow out the empty panel. */
function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

function matchMeta(m: PropertyMatch): string {
  const parts: string[] = [];
  if (m.bedrooms != null) parts.push(`${m.bedrooms} bd`);
  if (m.sqft != null) parts.push(sqft(m.sqft));
  if (m.status) parts.push(titleCase(m.status));
  return parts.join(" · ");
}

export function SearchBar({
  presets,
  onSelect,
  busy = false,
  busySubject = null,
}: {
  presets: PropertyMatch[];
  onSelect: (match: PropertyMatch) => void;
  /** The studio is mid-fetch — every selection surface gates on this. */
  busy?: boolean;
  /** The subject the in-flight lookup is FOR — named in the busy notice. */
  busySubject?: string | null;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PropertyMatch[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(-1);
  const [failed, setFailed] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  // Debounced search.
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setLoading(false);
      setFailed(false);
      setRateLimited(false);
      return;
    }
    setLoading(true);
    const ctrl = new AbortController();
    const id = window.setTimeout(async () => {
      try {
        const matches = await searchProperties(term, 8, ctrl.signal);
        setResults(matches);
        setFailed(false);
        setRateLimited(false);
        setOpen(true);
        setActive(-1);
      } catch (err) {
        // The request errored (network/server). Aborts are expected on each
        // keystroke and shouldn't read as a failure to the user.
        setResults([]);
        if (!ctrl.signal.aborted) {
          setRateLimited(isRateLimitError(err));
          setFailed(true);
          setOpen(true);
        }
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => {
      ctrl.abort();
      window.clearTimeout(id);
    };
  }, [q]);

  // Close on outside click.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function choose(m: PropertyMatch) {
    // Belt-and-braces behind the disabled rows/chips: no pick starts while a
    // lookup is in flight (Escape cancels it, then this re-enables).
    if (pickBlocked(busy)) return;
    setQ("");
    setResults([]);
    setOpen(false);
    setActive(-1);
    setFailed(false);
    setRateLimited(false);
    onSelect(m);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    // Escape always dismisses the popover — including the no-results / error
    // panel, which has no options for the branch below to walk.
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open || results.length === 0) {
      if (e.key === "ArrowDown" && results.length) setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + results.length) % results.length);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(results[active]);
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <label htmlFor={`${listId}-input`} className="sr-only">
        Search by address or parcel
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground">
          <SearchIcon className="h-5 w-5" />
        </span>
        <input
          id={`${listId}-input`}
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search any address or parcel"
          aria-label="Search a property address"
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-opt-${active}` : undefined}
          className="font-data w-full rounded-2xl border border-border bg-card/80 py-4 pl-12 pr-12 text-base text-foreground shadow-[0_8px_30px_-18px_var(--cb-glow)] outline-none backdrop-blur transition-colors placeholder:font-sans placeholder:text-muted-foreground focus:border-[var(--cb-ember)] focus:ring-2 focus:ring-[var(--cb-ember)]/25"
        />
        {loading || busy ? (
          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[var(--cb-ember)]">
            <Spinner className="h-5 w-5" />
          </span>
        ) : null}
      </div>

      {/* busy notice — WHICH subject the in-flight lookup is for, and the
          escape hatch. Same idiom as the input spinner / dimmed chips. */}
      {busy && busySubject ? (
        <p
          role="status"
          aria-live="polite"
          className="mt-3 flex items-center gap-2 text-xs text-muted-foreground"
        >
          <Spinner className="h-3.5 w-3.5 shrink-0 text-[var(--cb-ember)]" />
          <span className="truncate">
            Pricing <span className="font-medium text-foreground">{busySubject}</span>…
          </span>
          <span className="shrink-0 text-muted-foreground">Esc to cancel</span>
        </p>
      ) : null}

      {/* Screen-reader narration of the async result set — the listbox popping
          open is invisible to AT until focus moves into it. Failure states are
          narrated too: the error panel below is otherwise silent for AT. */}
      <p aria-live="polite" role="status" className="sr-only">
        {open && results.length > 0
          ? `${results.length} matching propert${results.length === 1 ? "y" : "ies"}. Use the arrow keys to review.`
          : open && !loading && q.trim().length >= 2
            ? rateLimited
              ? "Searching too fast — wait a few seconds and try again."
              : failed
                ? "Search is unavailable right now. Try again in a moment."
                : "No matching properties."
            : ""}
      </p>

      {/* preset chips */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="cb-eyebrow mr-1 text-muted-foreground">Try</span>
        {presets.map((p) => (
          <button
            key={p.parcel_id}
            type="button"
            onClick={() => choose(p)}
            disabled={pickBlocked(busy)}
            aria-disabled={pickBlocked(busy) || undefined}
            className="group inline-flex min-h-[40px] items-center gap-2 rounded-full border border-border bg-card/60 px-3.5 py-2 text-xs text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--cb-ember)]/70" aria-hidden />
            {p.address.split(",")[0]}
          </button>
        ))}
      </div>

      {/* results dropdown */}
      {open && results.length > 0 ? (
        <ul
          id={listId}
          role="listbox"
          aria-label="Matching properties"
          className="absolute z-30 mt-2 max-h-[22rem] w-full overflow-auto rounded-2xl border border-border bg-popover/95 p-1.5 shadow-[0_24px_60px_-24px_rgba(0,0,0,0.7)] backdrop-blur-md"
        >
          {results.map((m, i) => (
            <li key={`${m.parcel_id}-${i}`} role="presentation">
              <button
                id={`${listId}-opt-${i}`}
                role="option"
                aria-selected={i === active}
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(m)}
                disabled={pickBlocked(busy)}
                aria-disabled={pickBlocked(busy) || undefined}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors disabled:opacity-50",
                  i === active && !busy ? "bg-secondary/70" : "hover:bg-secondary/50",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">
                    {m.address}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {placeLabel(m.city, m.county)}
                    {matchMeta(m) ? ` — ${matchMeta(m)}` : ""}
                  </span>
                </span>
                <Pill tone={m.source === "mls" ? "ember" : "neutral"} className="shrink-0">
                  {m.source.toUpperCase()}
                </Pill>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {open && !loading && q.trim().length >= 2 && results.length === 0 ? (
        <div className="absolute z-30 mt-2 w-full rounded-2xl border border-border bg-popover/95 p-4 text-sm text-muted-foreground shadow-lg backdrop-blur-md">
          {rateLimited ? (
            "You're searching a little fast — give it a few seconds and try again."
          ) : failed ? (
            "Search is unavailable right now. Try again in a moment."
          ) : (
            <>
              No matches for “{truncate(q.trim(), 80)}”. Try a street address or
              parcel id.
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
