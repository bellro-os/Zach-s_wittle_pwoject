"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { Button, Eyebrow } from "@/components/compbird/ui";

/**
 * First-run onboarding — shown ONCE, over the already-painted studio (the
 * sample report renders underneath; this never gates it). Three tight beats,
 * then out of the way. Any dismissal (Escape, backdrop, the button) writes the
 * flag, so nobody sees it twice. If localStorage is unavailable, we simply
 * never show it — an onboarding card must never wall the tool.
 */

const ONBOARDED_KEY = "cb-onboarded";

const BEATS: Array<{ title: string; body: ReactNode }> = [
  {
    title: "Search any Virginia address",
    body: "Street address in, live comparables out — about two seconds.",
  },
  {
    title: "Tune it",
    body: "Exclude or pin comps, adjust sqft and condition. The value recomputes as you work.",
  },
  {
    title: "Download when it counts",
    body: (
      <>
        Free runs 2 branded PDFs a month. Pro is $20/mo — unlimited,
        watermark-free.{" "}
        <Link
          href="/pricing"
          className="text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
        >
          See pricing
        </Link>
      </>
    ),
  },
];

export function FirstRun() {
  const [open, setOpen] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  // Client-only check — the flag lives in localStorage, so first paint (and
  // SSR) is always closed and there's no hydration mismatch.
  useEffect(() => {
    try {
      if (window.localStorage.getItem(ONBOARDED_KEY) !== "1") setOpen(true);
    } catch {
      /* storage unavailable — never show, never wall the studio */
    }
  }, []);

  const dismiss = useCallback(() => {
    try {
      window.localStorage.setItem(ONBOARDED_KEY, "1");
    } catch {
      /* best effort — the card still closes */
    }
    setOpen(false);
    restoreRef.current?.focus?.();
  }, []);

  // On open: remember where focus was, then move it to the primary action.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    cardRef.current?.querySelector<HTMLElement>("button")?.focus();
  }, [open]);

  // Escape dismisses; Tab is trapped inside the card while open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        dismiss();
        return;
      }
      if (e.key !== "Tab") return;
      const card = cardRef.current;
      if (!card) return;
      const focusables = Array.from(
        card.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const current = document.activeElement;
      if (e.shiftKey && (current === first || !card.contains(current))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (current === last || !card.contains(current))) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, dismiss]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Welcome to the comp studio"
    >
      {/* backdrop — clicking it dismisses; the studio stays painted beneath */}
      <div
        className="absolute inset-0 bg-background/70 backdrop-blur-sm"
        onClick={dismiss}
        aria-hidden
      />

      <div
        ref={cardRef}
        className="relative w-full max-w-md rounded-2xl border border-border bg-popover p-6 shadow-[0_24px_80px_-24px_rgba(0,0,0,0.8)] sm:p-7"
      >
        <Eyebrow>First run</Eyebrow>
        <h2 className="font-display mt-3 text-xl font-bold leading-snug tracking-tight text-foreground text-balance">
          Three moves from address to PDF.
        </h2>

        <ol className="mt-5 flex flex-col gap-4">
          {BEATS.map((beat, i) => (
            <li key={beat.title} className="flex gap-3.5">
              <span
                className="font-data mt-0.5 shrink-0 text-xs text-[var(--cb-ember-text)]"
                aria-hidden
              >
                0{i + 1}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">
                  {beat.title}
                </span>
                <span className="mt-0.5 block text-sm leading-relaxed text-muted-foreground">
                  {beat.body}
                </span>
              </span>
            </li>
          ))}
        </ol>

        <div className="mt-6">
          <Button onClick={dismiss} className="w-full sm:w-auto">
            Start pricing
          </Button>
        </div>
      </div>
    </div>
  );
}
