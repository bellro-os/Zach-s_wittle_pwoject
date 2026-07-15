"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils/cn";
import { pickBlocked } from "./search-bar";
import type { LookupSelection } from "./subject-preview";

/**
 * Session recents: every successful live selection lands in
 * localStorage["cb-recents"] (via pushRecent, called from the studio's select
 * success path) — identity PLUS a facts snapshot from the RESOLVED profile,
 * so a re-pick hands select() a full LookupSelection and the wave-2 instant
 * preview paints (subject-preview.tsx, untouched). Two surfaces read it:
 *
 *  1. a quiet "Recent" chip row under the preset "Try" chips — up to five,
 *     newest first, one "Clear all";
 *  2. a Cmd/Ctrl-K palette — centered, filter-as-you-type, arrow keys + Enter
 *     re-run the selection. Hand-rolled, no deps.
 *
 * Both surfaces build their selection through ONE exported `toSelection`, so
 * chip row and palette can never drift apart (asserted structurally in
 * recents.persistence.test.ts).
 *
 * Same-tab writers announce themselves on a custom window event; the "storage"
 * event covers other tabs. All storage access is wrapped — a blocked
 * localStorage degrades to "no recents", never a crash.
 */

const RECENTS_KEY = "cb-recents";
const RECENTS_CAP = 10;
const CHANGED_EVENT = "cb-recents-changed";

/**
 * The record facts captured at the moment a subject RESOLVES (from the
 * profile's ProfileFacts — the truth source, richer than the search match).
 * Field names mirror PropertyMatch so an entry converts 1:1 into the
 * LookupSelection the studio's select() accepts; parcel_id is NOT here — it
 * is identity, stored on the entry itself. Every field nullable: null means
 * "not on record", never invented.
 */
export interface RecentFacts {
  sqft: number | null;
  bedrooms: number | null;
  full_baths: number | null;
  half_baths: number | null;
  acres: number | null;
  year_built: number | null;
  status: string | null;
  city: string | null;
  county: string | null;
  subdivision: string | null;
}

export interface RecentEntry {
  address: string;
  parcel_id: string;
  at: number;
  /**
   * Schema v2, OPTIONAL: the resolved-facts snapshot powering the instant
   * re-pick preview. Entries persisted before this field existed simply lack
   * it — they load as identity-only rows (plain skeleton path on re-pick),
   * never dropped, never wiped. Size: ~200B/entry × the existing cap of ten
   * ≈ 2KB worst case, well inside any localStorage budget.
   */
  facts?: RecentFacts;
}

/* ── facts sanitation (storage may hold anything) ──────────────────────────── */

const factNum = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
const factStr = (v: unknown): string | null => {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t ? t : null;
};

/**
 * Normalize an unknown `facts` blob field-by-field (junk values → null).
 * Returns undefined for a non-object OR an all-null result: an empty snapshot
 * is stored as NO snapshot, so "identity-only" stays the single no-facts shape
 * on both the old and new schema.
 */
function sanitizeFacts(raw: unknown): RecentFacts | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const o = raw as Record<string, unknown>;
  const facts: RecentFacts = {
    sqft: factNum(o.sqft),
    bedrooms: factNum(o.bedrooms),
    full_baths: factNum(o.full_baths),
    half_baths: factNum(o.half_baths),
    acres: factNum(o.acres),
    year_built: factNum(o.year_built),
    status: factStr(o.status),
    city: factStr(o.city),
    county: factStr(o.county),
    subdivision: factStr(o.subdivision),
  };
  return Object.values(facts).some((v) => v !== null) ? facts : undefined;
}

/** Dedupe identity: parcel where we have one, address otherwise. */
function keyOf(e: Pick<RecentEntry, "address" | "parcel_id">): string {
  return e.parcel_id || e.address;
}

/**
 * Read + MIGRATE: accepts both stored shapes. v1 entries (identity only) pass
 * through with no `facts`; v2 entries get their snapshot sanitized (a
 * malformed snapshot is dropped, the entry itself is KEPT). Only an entry
 * missing its identity fields is filtered. Read-only — never rewrites storage.
 * Exported for recents.persistence.test.ts.
 */
export function readRecents(): RecentEntry[] {
  try {
    const raw = window.localStorage.getItem(RECENTS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (e): e is RecentEntry =>
          !!e &&
          typeof e === "object" &&
          typeof (e as RecentEntry).address === "string" &&
          typeof (e as RecentEntry).parcel_id === "string" &&
          typeof (e as RecentEntry).at === "number",
      )
      .map((e) => {
        const facts = sanitizeFacts((e as { facts?: unknown }).facts);
        const entry: RecentEntry = {
          address: e.address,
          parcel_id: e.parcel_id,
          at: e.at,
        };
        if (facts) entry.facts = facts;
        return entry;
      })
      .slice(0, RECENTS_CAP);
  } catch {
    return [];
  }
}

function writeRecents(entries: RecentEntry[]) {
  try {
    if (entries.length === 0) window.localStorage.removeItem(RECENTS_KEY);
    else window.localStorage.setItem(RECENTS_KEY, JSON.stringify(entries));
  } catch {
    /* storage unavailable — recents just don't persist */
  }
  window.dispatchEvent(new Event(CHANGED_EVENT));
}

/**
 * Record a successful live selection. Deduped by parcel_id||address, capped at
 * ten, newest first. Called from the studio's select() success path with the
 * RESOLVED profile's facts snapshot — sanitized here, omitted when it carries
 * nothing. A re-resolve therefore UPGRADES an old identity-only entry in place
 * (same dedupe key, fresh enriched row).
 */
export function pushRecent(entry: {
  address: string;
  parcel_id: string;
  /** Snapshot of the resolved subject's record facts (see RecentFacts). */
  facts?: Partial<RecentFacts> | null;
}) {
  const address = entry.address.trim();
  if (!address) return;
  const facts = sanitizeFacts(entry.facts);
  const fresh: RecentEntry = {
    address,
    parcel_id: entry.parcel_id.trim(),
    at: Date.now(),
    ...(facts ? { facts } : {}),
  };
  const next = [
    fresh,
    ...readRecents().filter((e) => keyOf(e) !== keyOf(fresh)),
  ].slice(0, RECENTS_CAP);
  writeRecents(next);
}

/**
 * A stored entry as the LookupSelection handed to the studio's select():
 * identity always; the facts snapshot rides along when the entry carries one,
 * so buildSubjectPreview (subject-preview.tsx) returns a payload and the
 * instant fact preview paints on re-pick. Old identity-only entries yield an
 * identity-only selection — buildSubjectPreview returns null and the plain
 * skeleton path is preserved, exactly as before. THE single selection builder
 * for BOTH recents surfaces (chip row + Cmd-K palette rows); exported for
 * recents.persistence.test.ts.
 */
export function toSelection(e: RecentEntry): LookupSelection {
  const sel: LookupSelection = { address: e.address, parcel_id: e.parcel_id };
  const f = e.facts;
  if (!f) return sel;
  // PropertyMatch types city/county/status as non-nullable strings — set only
  // when known. The `?: number | null` fields carry null (= unknown) as-is.
  if (f.city != null) sel.city = f.city;
  if (f.county != null) sel.county = f.county;
  if (f.status != null) sel.status = f.status;
  sel.subdivision = f.subdivision;
  sel.sqft = f.sqft;
  sel.bedrooms = f.bedrooms;
  sel.full_baths = f.full_baths;
  sel.half_baths = f.half_baths;
  sel.acres = f.acres;
  sel.year_built = f.year_built;
  return sel;
}

/**
 * Deep-link href for a stored entry — the same ?parcelId=&address= contract
 * the studio's planDeepLink consumes (and select() mirrors back via
 * replaceState). Chips and palette rows render as REAL anchors carrying it,
 * so ctrl/cmd/middle-click opens the subject in a second tab; a plain
 * left-click preventDefaults and keeps the in-place select() path.
 */
function entryHref(e: Pick<RecentEntry, "address" | "parcel_id">): string {
  const qs = new URLSearchParams();
  if (e.parcel_id) qs.set("parcelId", e.parcel_id);
  qs.set("address", e.address);
  return `/comps?${qs.toString()}`;
}

/** True for a click that should keep native anchor behavior (new tab/window). */
function isModifiedClick(e: React.MouseEvent): boolean {
  return e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0;
}

/** Compact relative timestamp for the palette rows. */
function ago(at: number): string {
  const s = Math.max(0, Math.floor((Date.now() - at) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="font-data rounded border border-border bg-secondary/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
      {children}
    </kbd>
  );
}

export function Recents({
  onPick,
  busy = false,
  busySubject = null,
}: {
  /**
   * Re-runs the studio's select() for a stored entry — identity plus the
   * resolved-facts snapshot when the entry carries one (toSelection), so the
   * re-pick paints the instant subject preview instead of the bare skeleton.
   */
  onPick: (selection: LookupSelection) => void;
  /**
   * The studio is mid-fetch — chips AND palette rows disable (same
   * `pickBlocked` gate as the search bar's chips/rows). Escape cancels the
   * lookup (studio-level listener), then everything re-enables.
   */
  busy?: boolean;
  /** The subject the in-flight lookup is FOR — named in the palette notice. */
  busySubject?: string | null;
}) {
  const [recents, setRecents] = useState<RecentEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [mac, setMac] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const listId = useId();

  // Load once on mount, then stay in sync: same-tab writes announce on the
  // custom event, other tabs arrive via the storage event.
  useEffect(() => {
    const refresh = () => setRecents(readRecents());
    refresh();
    setMac(/Mac|iPhone|iPad/i.test(window.navigator.userAgent));
    window.addEventListener(CHANGED_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(CHANGED_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  // Global Cmd/Ctrl-K — alive only while the studio is mounted. Ignored while
  // typing in inputs/textareas/contenteditable, EXCEPT the main search input
  // (the studio's one combobox), where switching subjects is exactly the point.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (
        (e.key === "k" || e.key === "K") &&
        (e.metaKey || e.ctrlKey) &&
        !e.altKey &&
        !e.shiftKey
      ) {
        const el = e.target instanceof HTMLElement ? e.target : null;
        const tag = el?.tagName;
        const typing =
          tag === "INPUT" || tag === "TEXTAREA" || Boolean(el?.isContentEditable);
        const isMainSearch =
          tag === "INPUT" && el?.getAttribute("role") === "combobox";
        if (typing && !isMainSearch) return;
        e.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // On open: remember focus, reset the filter, focus the palette input.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    setQ("");
    setActive(0);
    const id = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  const close = useCallback(() => {
    setOpen(false);
    restoreRef.current?.focus?.();
  }, []);

  const pick = useCallback(
    (r: RecentEntry) => {
      // Belt-and-braces behind the disabled rows: the palette's Enter path
      // lands here too, and no pick may start while a lookup is in flight.
      if (pickBlocked(busy)) return;
      close();
      onPick(toSelection(r));
    },
    [busy, close, onPick],
  );

  const clearAll = useCallback(() => writeRecents([]), []);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return recents;
    return recents.filter(
      (r) =>
        r.address.toLowerCase().includes(term) ||
        r.parcel_id.toLowerCase().includes(term),
    );
  }, [q, recents]);

  const activeIdx = filtered.length
    ? Math.min(active, filtered.length - 1)
    : -1;

  // One handler on the dialog container — the input's keys bubble here.
  function onPaletteKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (filtered.length) setActive((activeIdx + 1) % filtered.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (filtered.length)
        setActive((activeIdx - 1 + filtered.length) % filtered.length);
    } else if (e.key === "Enter") {
      if (activeIdx >= 0 && filtered[activeIdx]) {
        e.preventDefault();
        pick(filtered[activeIdx]);
      }
    }
  }

  const hintKey = mac ? "⌘K" : "Ctrl+K";

  return (
    <>
      {/* recent chip row — mirrors the preset "Try" row's language */}
      {recents.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="cb-eyebrow mr-1 text-muted-foreground">Recent</span>
          {recents.slice(0, 5).map((r) => (
            <a
              key={keyOf(r)}
              href={entryHref(r)}
              onClick={(e) => {
                // Modified/middle click: native anchor behavior — second tab.
                if (isModifiedClick(e)) return;
                e.preventDefault();
                if (pickBlocked(busy)) return;
                onPick(toSelection(r));
              }}
              aria-disabled={pickBlocked(busy) || undefined}
              title={r.address}
              className={cn(
                "inline-flex min-h-[40px] items-center gap-2 rounded-full border border-border bg-card/60 px-3.5 py-2 text-xs text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
                pickBlocked(busy) && "opacity-50",
              )}
            >
              <span
                className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60"
                aria-hidden
              />
              {r.address.split(",")[0]}
            </a>
          ))}
          <button
            type="button"
            onClick={clearAll}
            className="px-1 text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            Clear all
          </button>
          <span className="ml-auto hidden items-center gap-1.5 text-[11px] text-muted-foreground sm:inline-flex">
            <Kbd>{hintKey}</Kbd> to switch
          </span>
        </div>
      ) : null}

      {/* Cmd/Ctrl-K palette */}
      {open ? (
        <div className="fixed inset-0 z-50" onKeyDown={onPaletteKey}>
          <div
            className="absolute inset-0 bg-background/70 backdrop-blur-sm"
            onClick={close}
            aria-hidden
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Recent properties"
            className="relative mx-auto mt-[16vh] w-[min(34rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-border bg-popover/95 shadow-[0_24px_60px_-24px_rgba(0,0,0,0.7)] backdrop-blur-md"
          >
            <div className="border-b border-border">
              <input
                ref={inputRef}
                type="text"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setActive(0);
                }}
                placeholder="Jump back to a recent property"
                aria-label="Filter recent properties"
                aria-controls={`${listId}-list`}
                aria-activedescendant={
                  activeIdx >= 0 ? `${listId}-opt-${activeIdx}` : undefined
                }
                autoComplete="off"
                spellCheck={false}
                className="font-data w-full bg-transparent px-4 py-3.5 text-sm text-foreground outline-none placeholder:font-sans placeholder:text-muted-foreground"
              />
            </div>

            {/* busy notice — which subject is loading while the rows below are
                gated. Esc here closes the palette AND cancels the lookup (the
                studio's Escape listener), matching the hint. */}
            {busy && busySubject ? (
              <div
                role="status"
                aria-live="polite"
                className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs text-muted-foreground"
              >
                <span
                  className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--cb-ember)]"
                  aria-hidden
                />
                <span className="truncate">
                  Pricing{" "}
                  <span className="font-medium text-foreground">{busySubject}</span>…
                </span>
                <span className="shrink-0 text-muted-foreground">
                  Esc cancels
                </span>
              </div>
            ) : null}

            {filtered.length > 0 ? (
              <ul
                id={`${listId}-list`}
                role="listbox"
                aria-label="Recent properties"
                className="max-h-72 overflow-auto p-1.5"
              >
                {filtered.map((r, i) => (
                  <li key={keyOf(r)} role="presentation">
                    <a
                      id={`${listId}-opt-${i}`}
                      role="option"
                      aria-selected={i === activeIdx}
                      href={entryHref(r)}
                      onMouseEnter={() => setActive(i)}
                      onClick={(e) => {
                        // Modified/middle click: native anchor — second tab.
                        if (isModifiedClick(e)) return;
                        e.preventDefault();
                        pick(r); // busy-gated inside
                      }}
                      aria-disabled={pickBlocked(busy) || undefined}
                      className={cn(
                        "flex w-full items-baseline gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                        pickBlocked(busy) && "opacity-50",
                        i === activeIdx && !busy
                          ? "bg-secondary/70"
                          : "hover:bg-secondary/50",
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                        {r.address}
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {ago(r.at)}
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                {recents.length === 0
                  ? "Nothing recent yet — search an address and it lands here."
                  : "No recent properties match that."}
              </p>
            )}

            <div className="flex items-center gap-3 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Kbd>{"↑"}</Kbd>
                <Kbd>{"↓"}</Kbd> navigate
              </span>
              <span className="inline-flex items-center gap-1">
                <Kbd>Enter</Kbd> open
              </span>
              <span className="inline-flex items-center gap-1">
                <Kbd>Esc</Kbd> close
              </span>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
