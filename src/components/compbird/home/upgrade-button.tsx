"use client";

import { useState } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils/cn";
import { startSubscription } from "@/lib/compbird/api";

/**
 * The hub account strip's upgrade CTA — the same startSubscription() Stripe
 * Checkout kick the account menu / Pro pitch use, so FREE always has a live path
 * to Pro from the hub (never a dead end). Errors surface as a toast; success
 * navigates away to Checkout.
 */
export function PortalUpgradeButton({ className }: { className?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      disabled={busy}
      aria-label="Upgrade to Pro · $20/mo"
      onClick={() => {
        if (busy) return;
        setBusy(true);
        startSubscription().catch((e) => {
          toast.error(e instanceof Error ? e.message : "Could not start checkout.");
          setBusy(false);
        });
      }}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full bg-[var(--cb-ember)] px-4 py-2 text-xs font-semibold text-[var(--cb-on-ember)] transition-opacity hover:opacity-90 disabled:opacity-50",
        className,
      )}
    >
      Upgrade to Pro · $20/mo
    </button>
  );
}
