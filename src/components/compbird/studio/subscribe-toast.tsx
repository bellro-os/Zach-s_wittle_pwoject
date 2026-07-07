"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { trackSubscribe } from "@/lib/marketing/track";

/**
 * Reads the Stripe Checkout return markers (`?subscribed=1` / `?checkout=cancelled`)
 * on the studio page and turns them into a toast. Renders nothing.
 *
 * The params are stripped via history.replaceState BEFORE toasting, so a manual
 * refresh (or React strict-mode's double effect run) never re-fires the toast.
 */
export function SubscribeToast() {
  const router = useRouter();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const subscribed = params.get("subscribed") === "1";
    const cancelled = params.get("checkout") === "cancelled";
    if (!subscribed && !cancelled) return;

    // Stripe Checkout session id (set by the checkout route's success_url) —
    // passed to the ad pixels as the event id so Meta dedups this browser
    // event against the webhook's server-side Conversions API copy.
    const checkoutSessionId = params.get("cs") ?? undefined;

    params.delete("subscribed");
    params.delete("checkout");
    params.delete("cs");
    const qs = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`,
    );

    if (subscribed) {
      trackSubscribe(checkoutSessionId);
      toast.success("Welcome to Pro — every comp, market analytics, and watermark-free branded reports are unlocked.");
      // The server render right after the Stripe redirect can beat the webhook
      // that flips the tier — refresh once shortly after so the header plan chip
      // updates without a manual reload. Deliberately NOT cleared on unmount:
      // strict-mode's mount→unmount→mount would otherwise drop the refresh
      // (the param strip above already guarantees this whole block runs once).
      window.setTimeout(() => router.refresh(), 2000);
    } else {
      toast("Checkout cancelled — you're still on the free plan.");
    }
  }, [router]);

  return null;
}
