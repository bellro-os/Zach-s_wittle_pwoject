"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Pill } from "@/components/compbird/ui";
import { searchProperties } from "@/lib/compbird/api";
import { sqft, titleCase, placeLabel } from "@/lib/compbird/format";
import type { PropertyMatch } from "@/lib/compbird/types";
import { cn } from "@/lib/utils/cn";

/**
 * Compact "add a comparable" typeahead. A trimmed-down sibling of the studio
 * SearchBar that reuses the same `/api/compbird/search` path (via
 * searchProperties), but instead of resolving a new subject it hands the picked
 * address UP so the studio force-includes it in the comp set (the engine's
 * `forced` list) and re-runs the live preview.
 *
 * Collapsed by default to a quiet "+ Add a comparable" affordance — the search
 * input only appears once the user reaches for it, so the tuning area doesn't
 * carry a permanently-open input. Pass `collapsible={false}` to pin the input
 * open (e.g. in a dedicated add flow).
 *
 * Live reports only — the studio passes a no-op / omits the affordance on sample
 * data, and `disabled` hard-stops typing as a belt-and-braces guard.
 */

function PlusIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className={className} aria-hidden>
      <path
        d="M10 4v12M4 10h12"
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

export function AddCompSearch({
  onAdd,
  disabled = false,
  busy = false,
  /** Addresses already pinned — surfaced as "Added" so the user can't double-add. */
  pinned,
  collapsible = true,
  dropUp = false,
}: {
  /** Hand the picked address up to force-include it as a comp. */
  onAdd: (address: string) => void;
  /** Not a live report (or a guard) — the control is inert. */
  disabled?: boolean;
  /** A recompute is in flight — reflected on the spinner. */
  busy?: boolean;
  pinned?: Set<string>;
  /** Collapse to a "+ Add a comparable" affordance until reached for (default). */
  collapsible?: boolean;
  /** Open the results ABOVE the input — for bottom-sticky mounts (table footer). */
  dropUp?: boolean;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PropertyMatch[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(-1);
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState(!collapsible);

  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const pinnedSet = pinned ?? EMPTY;

  // Reaching for the affordance opens the input ready to type.
  useEffect(() => {
    if (expanded && collapsible) inputRef.current?.focus();
  }, [expanded, collapsible]);

  // Debounced search — mirrors the studio SearchBar cadence (250ms).
  useEffect(() => {
    if (disabled) return;
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setLoading(false);
      setFailed(false);
      return;
    }
    setLoading(true);
    const ctrl = new AbortController();
    const id = window.setTimeout(async () => {
      try {
        const matches = await searchProperties(term, 8, ctrl.signal);
        setResults(matches);
        setFailed(false);
        setOpen(true);
        setActive(-1);
      } catch {
        // Aborts fire on every keystroke and shouldn't read as a failure.
        setResults([]);
        if (!ctrl.signal.aborted) {
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
  }, [q, disabled]);

  // Close on outside click; an untouched (empty) input also folds back to the
  // '+' affordance so the footer returns to its quiet state.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        if (collapsible) {
          setExpanded((was) => (was && inputRef.current?.value.trim() ? was : false));
        }
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [collapsible]);

  function choose(m: PropertyMatch) {
    setQ("");
    setResults([]);
    setOpen(false);
    setActive(-1);
    setFailed(false);
    if (collapsible) setExpanded(false); // added — fold back to the affordance
    onAdd(m.address);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
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
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  // Escape on an empty input (dropdown already closed) folds the affordance.
  function onInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (
      e.key === "Escape" &&
      collapsible &&
      !(open && results.length > 0) &&
      q.trim() === ""
    ) {
      setExpanded(false);
      return;
    }
    onKeyDown(e);
  }

  /* Collapsed: the quiet '+' affordance. */
  if (collapsible && !expanded) {
    return (
      <div ref={rootRef}>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setExpanded(true)}
          className="group inline-flex min-h-[40px] w-full items-center gap-2.5 rounded-xl border border-dashed border-border px-3.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/50 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
        >
          <span className="text-[var(--cb-ember)]">
            {busy ? <Spinner className="h-4 w-4" /> : <PlusIcon className="h-4 w-4" />}
          </span>
          Add a comparable
        </button>
      </div>
    );
  }

  return (
    <div ref={rootRef} className="relative">
      <label htmlFor={`${listId}-input`} className="sr-only">
        Add a comparable by address
      </label>
      <div className="relative">
        <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--cb-ember)]">
          <PlusIcon className="h-4.5 w-4.5" />
        </span>
        <input
          ref={inputRef}
          id={`${listId}-input`}
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
          onKeyDown={onInputKeyDown}
          disabled={disabled}
          placeholder="Add a comparable — search any address"
          aria-label="Add a comparable by address"
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-opt-${active}` : undefined}
          className="font-data w-full rounded-xl border border-border bg-card/70 py-2.5 pl-10 pr-10 text-sm text-foreground outline-none transition-colors placeholder:font-sans placeholder:text-muted-foreground focus:border-[var(--cb-ember)]/50 focus:ring-1 focus:ring-[var(--cb-ember)]/30 disabled:cursor-not-allowed disabled:opacity-50"
        />
        {loading || busy ? (
          <span className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[var(--cb-ember)]">
            <Spinner className="h-4 w-4" />
          </span>
        ) : null}
      </div>

      {/* results dropdown */}
      {open && results.length > 0 ? (
        <ul
          id={listId}
          role="listbox"
          aria-label="Properties to add as comparables"
          className={cn(
            "absolute z-30 max-h-[20rem] w-full overflow-auto rounded-2xl border border-border bg-popover/95 p-1.5 shadow-[0_24px_60px_-24px_rgba(0,0,0,0.7)] backdrop-blur-md",
            dropUp ? "bottom-full mb-2" : "mt-2",
          )}
        >
          {results.map((m, i) => {
            const already = pinnedSet.has(m.address);
            return (
              <li key={`${m.parcel_id}-${i}`} role="presentation">
                <button
                  id={`${listId}-opt-${i}`}
                  role="option"
                  aria-selected={i === active}
                  type="button"
                  disabled={already}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => choose(m)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-55",
                    i === active && !already ? "bg-secondary/70" : "hover:bg-secondary/50",
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
                  {already ? (
                    <Pill tone="ember" className="shrink-0">
                      Added
                    </Pill>
                  ) : (
                    <span className="shrink-0 text-[var(--cb-ember)]" aria-hidden>
                      <PlusIcon className="h-4 w-4" />
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {open && !loading && q.trim().length >= 2 && results.length === 0 ? (
        <div
          className={cn(
            "absolute z-30 w-full rounded-2xl border border-border bg-popover/95 p-4 text-sm text-muted-foreground shadow-lg backdrop-blur-md",
            dropUp ? "bottom-full mb-2" : "mt-2",
          )}
        >
          {failed
            ? "Search is unavailable right now. Try again in a moment."
            : `No matches for “${truncate(q.trim(), 80)}”. Try a street address.`}
        </div>
      ) : null}
    </div>
  );
}

const EMPTY: Set<string> = new Set();

export default AddCompSearch;
