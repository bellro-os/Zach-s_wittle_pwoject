"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils/cn";
import type { ProfileComp } from "@/lib/compbird/types";

/**
 * The Match figure + its breakdown — the comp workshop's transparency layer.
 *
 * The trigger is the comps-table Match cell itself: integer score, tier word,
 * and a hairline ember bar. Tapping/clicking it opens the six-axis breakdown
 * (Location / Recency / Size / Lot / Age / Type) with the engine's own
 * plain-English reason per axis, any atypical/pending honesty flags, and the
 * invariant footnote (the overall is NOT the average of the bars — the price
 * axis and sale-type discounts live only in the overall).
 *
 * Presentation follows confidence-badge.tsx (same card surface, eyebrow,
 * hairline bullets), but the panel is PORTALED to <body> with fixed
 * positioning: the comps table scrolls in an `overflow-x-auto` region that
 * would clip an absolutely-positioned popover. Desktop gets an anchored
 * popover by the trigger; below `sm` it becomes a bottom sheet with a
 * backdrop. Keyboard/AT: real button semantics, aria-expanded/controls,
 * Escape closes and returns focus to the trigger.
 *
 * Null subscores (engine couldn't compute an axis — "sqft not recorded")
 * render an em-dash with their reason, never a zero: limited data is not a
 * poor match.
 */

/** Design-tier words for a 0–100 match score. */
export function matchTier(score: number): "Excellent" | "Strong" | "Fair" | "Weak" {
  if (score >= 85) return "Excellent";
  if (score >= 70) return "Strong";
  if (score >= 55) return "Fair";
  return "Weak";
}

/** Panel geometry once opened: anchored popover (desktop) or bottom sheet. */
type PanelMode =
  | { kind: "sheet" }
  | { kind: "popover"; style: React.CSSProperties };

const PANEL_WIDTH = 320; // Tailwind w-80
const PANEL_EST_HEIGHT = 380; // flip-above estimate; the panel scrolls if taller
const VIEWPORT_GUTTER = 8;

export function MatchPopover({
  comp,
  pinned = false,
  onOpen,
  className,
}: {
  comp: ProfileComp;
  /** The user pinned this comp in — the score wears a "Pinned" prefix. */
  pinned?: boolean;
  /** Fired when the breakdown opens — the comps table uses it to retire its one-time hint. */
  onOpen?: () => void;
  className?: string;
}) {
  const [mode, setMode] = useState<PanelMode | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const popId = useId();
  const headingId = useId();

  const sim = typeof comp.similarity === "number" ? comp.similarity : null;
  const open = mode !== null;

  const close = useCallback((focusTrigger: boolean) => {
    setMode(null);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  const openPanel = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    onOpen?.();
    // Same breakpoint as the table's `sm:` column collapse: phones get a sheet.
    if (window.matchMedia("(max-width: 639px)").matches) {
      setMode({ kind: "sheet" });
      return;
    }
    const r = trigger.getBoundingClientRect();
    const left = Math.max(
      VIEWPORT_GUTTER,
      Math.min(r.right - PANEL_WIDTH, window.innerWidth - PANEL_WIDTH - VIEWPORT_GUTTER),
    );
    const spaceBelow = window.innerHeight - r.bottom;
    const style: React.CSSProperties =
      spaceBelow < PANEL_EST_HEIGHT && r.top > spaceBelow
        ? { bottom: window.innerHeight - r.top + VIEWPORT_GUTTER, left }
        : { top: r.bottom + VIEWPORT_GUTTER, left };
    setMode({ kind: "popover", style });
  }, [onOpen]);

  // Global listeners while open: Escape closes (focus returns), pointer-down
  // outside closes, and a desktop popover closes on scroll/resize rather than
  // drifting away from its anchor.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close(true);
      }
    };
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t) || triggerRef.current?.contains(t)) return;
      close(false);
    };
    const onScrollOrResize = () => {
      if (mode?.kind === "popover") close(false);
    };
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("mousedown", onPointerDown, true);
    document.addEventListener("touchstart", onPointerDown, true);
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("mousedown", onPointerDown, true);
      document.removeEventListener("touchstart", onPointerDown, true);
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [open, mode, close]);

  // Move focus into the panel on open so Escape/AT reading starts there.
  useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);

  if (sim == null) return null;
  const tier = matchTier(sim);

  const panel = mode ? (
    <>
      {mode.kind === "sheet" ? (
        <div
          aria-hidden
          onClick={() => close(false)}
          className="fixed inset-0 z-[1100] bg-black/50 backdrop-blur-[2px]"
        />
      ) : null}
      <div
        ref={panelRef}
        id={popId}
        role="dialog"
        aria-modal={mode.kind === "sheet" || undefined}
        aria-labelledby={headingId}
        tabIndex={-1}
        style={mode.kind === "popover" ? mode.style : undefined}
        className={cn(
          "fixed z-[1101] border border-border bg-card text-left shadow-[0_16px_40px_-16px_rgba(0,0,0,0.55)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
          mode.kind === "sheet"
            ? "inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-2xl p-5 pb-[calc(1.5rem+env(safe-area-inset-bottom))]"
            : "w-80 max-h-[min(26rem,calc(100vh-2rem))] overflow-y-auto rounded-xl p-4",
        )}
      >
        {mode.kind === "sheet" ? (
          <span aria-hidden className="mx-auto mb-3 block h-1 w-10 rounded-full bg-border" />
        ) : null}

        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="cb-eyebrow text-muted-foreground">Why this match</span>
            <div id={headingId} className="mt-1 flex flex-wrap items-baseline gap-x-2">
              {pinned ? (
                <span className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-[var(--cb-ember-text)]">
                  Pinned
                </span>
              ) : null}
              <span className="font-data text-2xl font-semibold leading-none text-[var(--cb-ember-text)]">
                {sim}
              </span>
              <span className="text-sm font-medium text-foreground">{tier}</span>
            </div>
            <p className="mt-1 truncate text-xs text-muted-foreground" title={comp.address}>
              {comp.address}
            </p>
          </div>
          <button
            type="button"
            onClick={() => close(true)}
            aria-label="Close the match breakdown"
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)]"
          >
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden>
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {comp.subscores?.length ? (
          <ul className="mt-4 flex flex-col gap-3">
            {comp.subscores.map((s) => (
              <li key={s.key} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-xs font-medium text-foreground">
                    {s.label}
                    <span className="ml-1.5 font-normal text-muted-foreground">
                      {s.weight_pct}%
                    </span>
                  </span>
                  <span className="font-data text-xs text-foreground">
                    {s.score == null ? "—" : s.score}
                  </span>
                </div>
                <div className="h-[3px] w-full overflow-hidden rounded-full bg-border/50" aria-hidden>
                  {s.score != null ? (
                    <div
                      className="h-full rounded-full bg-[var(--cb-ember)]/80"
                      style={{ width: `${Math.max(0, Math.min(100, s.score))}%` }}
                    />
                  ) : null}
                </div>
                {s.reason ? (
                  <span className="text-[0.7rem] leading-snug text-muted-foreground">
                    {s.reason}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : comp.reasons?.length ? (
          // Older wire shape: overall + reasons but no per-axis bars.
          <ul className="mt-4 flex flex-col gap-1">
            {comp.reasons.map((r, i) => (
              <li key={i} className="flex items-baseline gap-2 text-xs text-foreground">
                <span aria-hidden className="h-px w-2.5 shrink-0 translate-y-[-0.2em] bg-[var(--cb-ember)]/70" />
                {r}
              </li>
            ))}
          </ul>
        ) : null}

        {comp.atypical_flags?.length ? (
          <ul className="mt-3 flex flex-col gap-1.5 border-t border-border pt-3">
            {comp.atypical_flags.map((f, i) => (
              <li
                key={i}
                className="flex items-baseline gap-2 text-[0.7rem] leading-snug text-[var(--negative-foreground)]"
              >
                <span aria-hidden className="h-1.5 w-1.5 shrink-0 translate-y-[-0.05em] rounded-full bg-[var(--negative)]/70" />
                {f}
              </li>
            ))}
          </ul>
        ) : null}

        <p className="mt-3 border-t border-border pt-3 text-[0.7rem] leading-snug text-muted-foreground">
          The overall score also weighs sale price and sale type — it is not just the
          average of these bars.
        </p>
      </div>
    </>
  ) : null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? popId : undefined}
        aria-label={`Match ${sim} — ${tier}${pinned ? " · pinned by you" : ""} — show the breakdown for ${comp.address}`}
        onClick={() => (open ? close(true) : openPanel())}
        className={cn(
          // Reads as tappable, not a static readout: pointer cursor, a hairline
          // border that warms to ember on hover/open (transparent placeholder so
          // nothing shifts), and the same quiet bg wash the row hover uses.
          "group inline-flex cursor-pointer flex-col items-end gap-1 rounded-md border border-transparent px-1.5 py-1 transition-colors hover:border-[var(--cb-ember)]/40 hover:bg-secondary/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
          open && "border-[var(--cb-ember)]/40 bg-secondary/50",
          className,
        )}
      >
        <span className="flex items-baseline gap-1 whitespace-nowrap leading-none">
          {pinned ? (
            <span className="text-[0.6rem] font-semibold uppercase tracking-[0.12em] text-[var(--cb-ember-text)]">
              Pinned ·
            </span>
          ) : null}
          <span className="font-data text-sm font-semibold text-foreground">{sim}</span>
          <span className="ml-0.5 text-[0.7rem] text-muted-foreground">{tier}</span>
          {/* disclosure chevron — the "there's more here" glyph; flips while open */}
          <svg
            viewBox="0 0 16 16"
            data-cb-match-glyph=""
            className={cn(
              "h-2.5 w-2.5 shrink-0 self-center text-muted-foreground transition-transform duration-200 motion-reduce:transition-none group-hover:text-foreground",
              open && "rotate-180",
            )}
            fill="none"
            aria-hidden
          >
            <path
              d="M4.5 6.25 8 9.75l3.5-3.5"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        {/* hairline ember bar — the score at a glance */}
        <span className="block h-0.5 w-14 overflow-hidden rounded-full bg-border/60" aria-hidden>
          <span
            className="block h-full rounded-full bg-[var(--cb-ember)]"
            style={{ width: `${Math.max(0, Math.min(100, sim))}%` }}
          />
        </span>
      </button>
      {panel ? createPortal(panel, document.body) : null}
    </>
  );
}
