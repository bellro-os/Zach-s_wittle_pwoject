"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/compbird/ui";
import { openBillingPortal, startSubscription } from "@/lib/compbird/api";

/**
 * The /account billing affordance: subscribed accounts get "Manage billing"
 * (opens the Stripe customer portal), everyone else gets the Pro upgrade
 * (Stripe Checkout). Same navigate-away-on-success / toast-on-failure pattern
 * as the studio account menu.
 */
export function BillingButtons({ subscribed }: { subscribed: boolean }) {
  const [busy, setBusy] = useState(false);

  async function go(action: () => Promise<void>, fallback: string) {
    if (busy) return;
    setBusy(true);
    try {
      await action(); // navigates away on success
    } catch (e) {
      toast.error(e instanceof Error ? e.message : fallback);
      setBusy(false);
    }
  }

  if (subscribed) {
    return (
      <Button
        variant="ghost"
        size="sm"
        disabled={busy}
        onClick={() => void go(openBillingPortal, "Could not open billing.")}
      >
        Manage billing
      </Button>
    );
  }
  return (
    <Button
      size="sm"
      disabled={busy}
      onClick={() => void go(startSubscription, "Could not start checkout.")}
    >
      Upgrade to Pro · $20/mo
    </Button>
  );
}
