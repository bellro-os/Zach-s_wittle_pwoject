"use client";

import { useEffect, useState } from "react";
import { Eyebrow } from "@/components/compbird/ui";
import {
  readRecents,
  hasTuning,
  keyOf,
  entryHref,
  type RecentEntry,
} from "@/components/compbird/studio/recents";

/**
 * The hub's recent-properties row — a jump-back list built from the SAME
 * localStorage store the studio writes. It reuses recents.tsx's readers
 * verbatim (readRecents / hasTuning / keyOf / entryHref); no storage logic is
 * forked here. Up to six real <a> cards (ctrl/cmd/middle-click opens a new tab),
 * each carrying the ?parcelId=&address= deep link the studio consumes, badged
 * "tuned" when a saved tuning record exists for that subject.
 *
 * Recents are client-only (localStorage), so this paints empty on the server
 * and fills after mount — no SSR/hydration divergence. When there's nothing yet,
 * it renders a first-run empty state that points the agent back at the search.
 */
const RECENTS_SHOWN = 6;
const RECENTS_CHANGED_EVENT = "cb-recents-changed";
const TUNING_CHANGED_EVENT = "cb-tuning-changed";

export function PortalRecents() {
  const [recents, setRecents] = useState<RecentEntry[]>([]);
  const [tunedKeys, setTunedKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    const refresh = () => {
      const rows = readRecents().slice(0, RECENTS_SHOWN);
      setRecents(rows);
      const tuned = new Set<string>();
      for (const r of rows) if (hasTuning(r)) tuned.add(keyOf(r));
      setTunedKeys(tuned);
    };
    refresh();
    // Same event contract as the studio's Recents: same-tab writes announce on
    // the custom events, other tabs arrive via "storage".
    window.addEventListener(RECENTS_CHANGED_EVENT, refresh);
    window.addEventListener(TUNING_CHANGED_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(RECENTS_CHANGED_EVENT, refresh);
      window.removeEventListener(TUNING_CHANGED_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  if (recents.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-card/40 px-6 py-10 text-center">
        <p className="font-display text-lg font-semibold tracking-tight text-foreground">
          Price your first home
        </p>
        <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">
          Search an address above and it lands here — jump straight back to any
          property you&rsquo;ve priced.
        </p>
      </div>
    );
  }

  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {recents.map((r) => (
        <li key={keyOf(r)} className="h-full">
          <a
            href={entryHref(r)}
            title={r.address}
            className="group flex h-full items-start justify-between gap-3 rounded-xl border border-border bg-card/60 px-4 py-3 transition-colors hover:border-[var(--cb-ember)]/40 hover:bg-card focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-foreground">
                {r.address.split(",")[0]}
              </span>
              <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                {r.address.split(",").slice(1).join(",").trim() || "View report"}
              </span>
            </span>
            {tunedKeys.has(keyOf(r)) ? (
              <span className="font-data mt-0.5 shrink-0 rounded border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] px-1 py-px text-[9px] uppercase tracking-[0.1em] text-[var(--cb-ember-text)]">
                tuned
              </span>
            ) : null}
          </a>
        </li>
      ))}
    </ul>
  );
}
