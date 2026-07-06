"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/compbird/ui";
import { startSubscription } from "@/lib/compbird/api";

/**
 * The paywall's VISUAL boundary — a panel-sized container that stands in for a
 * Pro-only evidence panel (comps, market read) on a locked live report.
 *
 * The data is already gone: the server redacted it before the response shipped
 * (src/lib/compbird/redact.ts), so the blurred shapes beneath the overlay are
 * GENERIC placeholders — fake rows and bars, never real figures. There is
 * nothing behind the blur to un-blur.
 */

function LockGlyph() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4" aria-hidden>
      <rect
        x="3.25"
        y="7"
        width="9.5"
        height="6.25"
        rx="1.5"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M5.5 7V4.9a2.5 2.5 0 0 1 5 0V7"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Generic table-ish rows + a bar run — reads as "evidence", carries none. */
function PlaceholderShapes() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2.5">
        {[88, 72, 81, 64, 76].map((w, i) => (
          <div key={i} className="flex items-center gap-3">
            <div
              className="h-3 rounded-full bg-secondary/80"
              style={{ width: `${w}%` }}
            />
            <div className="h-3 w-12 shrink-0 rounded-full bg-secondary/50" />
          </div>
        ))}
      </div>
      <div className="flex items-end gap-2.5">
        {[22, 34, 28, 44, 38, 52, 47, 60].map((h, i) => (
          <div
            key={i}
            className="w-full rounded-t-sm bg-secondary/60"
            style={{ height: `${h}px` }}
          />
        ))}
      </div>
    </div>
  );
}

export function LockedPanel({
  title,
  teaser,
  subscribed = false,
  children,
}: {
  /** Panel identity, e.g. "Comparable sales". */
  title: string;
  /** One-line hook built from the redacted summary, e.g. "6 comparable sales found · nearest 0.8 mi". */
  teaser: string;
  /**
   * True when the viewer already has an active subscription (a locked payload
   * should then never occur — webhook lag at worst); hides the checkout CTA.
   */
  subscribed?: boolean;
  /** Optional custom placeholder skeleton; defaults to generic rows + bars. */
  children?: React.ReactNode;
}) {
  const [busy, setBusy] = useState(false);

  // Same navigate-on-success / toast-on-error contract as the account menu:
  // startSubscription() redirects to Stripe Checkout when it works, so busy is
  // only reset on failure.
  function onUnlock() {
    if (busy) return;
    setBusy(true);
    startSubscription().catch((e) => {
      toast.error(e instanceof Error ? e.message : "Could not start checkout.");
      setBusy(false);
    });
  }

  return (
    <div className="relative min-h-[16rem] overflow-hidden rounded-2xl border border-border bg-card/70 p-5 sm:p-7">
      {/* blurred placeholder — inert, invisible to AT, generic shapes only */}
      <div aria-hidden className="pointer-events-none select-none blur-sm">
        <span className="cb-eyebrow text-muted-foreground">{title}</span>
        <div className="mt-5">{children ?? <PlaceholderShapes />}</div>
      </div>

      {/* unlock overlay */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3.5 bg-background/60 px-6 py-8 text-center backdrop-blur-[2px]">
        <span
          className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] text-[var(--cb-ember-text)]"
          aria-hidden
        >
          <LockGlyph />
        </span>
        <div className="flex flex-col gap-1">
          <span className="cb-eyebrow text-muted-foreground">{title}</span>
          <p className="text-sm font-medium text-foreground">{teaser}</p>
        </div>
        {!subscribed ? (
          <>
            <Button size="sm" onClick={onUnlock} disabled={busy}>
              {busy ? "Opening checkout…" : "Unlock with Pro · $20/mo"}
            </Button>
            <span className="text-xs text-muted-foreground">
              cancel anytime ·{" "}
              <Link
                href="/pricing"
                className="underline underline-offset-4 transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
              >
                see pricing
              </Link>
            </span>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            Included in your plan — refresh to load.
          </p>
        )}
      </div>
    </div>
  );
}
