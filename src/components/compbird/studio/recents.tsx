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

/**
 * Session recents: every successful live selection lands in
 * localStorage["cb-recents"] (via pushRecent, called from the studio's select
 * success path). Two surfaces read it:
 *
 *  1. a quiet "Recent" chip row under the preset "Try" chips — up to five,
 *     newest first, one "Clear all";
 *  2. a Cmd/Ctrl-K palette — centered, filter-as-you-type, arrow keys + Enter
 *     re-run the selection. Hand-rolled, no deps.
 *
 * Same-tab writers announce themselves on a custom window event; the "storage"
 * event covers other tabs. All storage access is wrapped — a blocked
 * localStorage degrades to "no recents", never a crash.
 */

const RECENTS_KEY = "cb-recents";
const RECENTS_CAP = 10;
const CHANGED_EVENT = "cb-recents-changed";

export interface RecentEntry {
  address: string;
  parcel_id: string;
  at: number;
}

/** Dedupe identity: parcel where we have one, address otherwise. */
function keyOf(e: Pick<RecentEntry, "address" | "parcel_id">): string {
  return e.parcel_id || e.address;
}

function readRecents(): RecentEntry[] {
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
 * ten, newest first. Called from the studio's select() success path.
 */
export function pushRecent(entry: { address: string; parcel_id: string }) {
  const address = entry.address.trim();
  if (!address) return;
  const fresh: RecentEntry = {
    address,
    parcel_id: entry.parcel_id.trim(),
    at: Date.now(),
  };
  const next = [
    fresh,
    ...readRecents().filter((e) => keyOf(e) !== keyOf(fresh)),
  ].slice(0, RECENTS_CAP);
  writeRecents(next);
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
}: {
  /** Re-runs the studio's select() for a stored entry. */
  onPick: (match: { address: string; parcel_id: string }) => void;
  /** The studio is mid-fetch — chips disable, matching the preset chips. */
  busy?: boolean;
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
      close();
      onPick({ address: r.address, parcel_id: r.parcel_id });
    },
    [close, onPick],
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
            <button
              key={keyOf(r)}
              type="button"
              onClick={() => onPick({ address: r.address, parcel_id: r.parcel_id })}
              disabled={busy}
              title={r.address}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-full border border-border bg-card/60 px-3.5 py-2 text-xs text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:opacity-50"
            >
              <span
                className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60"
                aria-hidden
              />
              {r.address.split(",")[0]}
            </button>
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

            {filtered.length > 0 ? (
              <ul
                id={`${listId}-list`}
                role="listbox"
                aria-label="Recent properties"
                className="max-h-72 overflow-auto p-1.5"
              >
                {filtered.map((r, i) => (
                  <li key={keyOf(r)} role="presentation">
                    <button
                      id={`${listId}-opt-${i}`}
                      role="option"
                      aria-selected={i === activeIdx}
                      type="button"
                      onMouseEnter={() => setActive(i)}
                      onClick={() => pick(r)}
                      className={cn(
                        "flex w-full items-baseline gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                        i === activeIdx ? "bg-secondary/70" : "hover:bg-secondary/50",
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                        {r.address}
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {ago(r.at)}
                      </span>
                    </button>
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
