"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/compbird/ui";
import { startSubscription, openBillingPortal } from "@/lib/compbird/api";
import { logout } from "@/actions/auth";

/**
 * The studio's account affordance: shows the current plan, an Upgrade ($20/mo)
 * or Manage-billing action (Stripe Checkout / billing portal), and sign-out.
 * `subscribed` is true when the account has an active Stripe subscription.
 */
export function StudioAccountMenu({
  plan,
  subscribed,
}: {
  plan: string;
  subscribed: boolean;
}) {
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

  const linkCls =
    "text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50";

  return (
    <div className="flex items-center gap-3">
      <Pill tone={subscribed ? "ember" : "neutral"}>{plan}</Pill>

      {subscribed ? (
        <button
          type="button"
          onClick={() => go(openBillingPortal, "Could not open billing.")}
          disabled={busy}
          className={linkCls}
        >
          Manage billing
        </button>
      ) : (
        <button
          type="button"
          onClick={() => go(startSubscription, "Could not start checkout.")}
          disabled={busy}
          className="inline-flex items-center rounded-full bg-[var(--cb-ember)] px-3 py-1.5 text-xs font-semibold text-[var(--cb-on-ember)] transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          Upgrade to Pro · $20/mo
        </button>
      )}

      <form action={logout}>
        <input type="hidden" name="redirect" value="/" />
        <button type="submit" className={linkCls}>
          Sign out
        </button>
      </form>
    </div>
  );
}

/**
 * Persistent allowance banner for METERED plans, shown above the studio so the
 * monthly download cap is visible BEFORE a user spends a 2-minute render
 * discovering it. Unlimited plans never render this (the page skips it). The
 * plan label comes from the page (BETA is also metered — never say "Free plan"
 * to it), and the Pro upsell sentence renders only where Pro is a strict
 * upgrade (the FREE tier).
 */
export function QuotaBanner({
  used,
  limit,
  subscribed,
  plan,
  showUpsell = false,
}: {
  used: number;
  limit: number;
  subscribed: boolean;
  /** Resolved plan label for the copy (e.g. "Free plan", "Beta"). */
  plan: string;
  /** Pitch Pro in the banner — true only for the FREE tier. */
  showUpsell?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const left = Math.max(0, limit - used);
  const out = left === 0;

  return (
    <div
      role="status"
      className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 ${
        out
          ? "border-[var(--cb-ember)]/40 bg-[var(--cb-tint)]"
          : "border-border bg-card/60"
      }`}
    >
      <p className="text-sm text-foreground">
        {out ? (
          <>You&rsquo;ve used all {limit} report downloads this month.</>
        ) : (
          <>
            {plan} · <span className="font-data font-semibold">{left}</span> of{" "}
            <span className="font-data font-semibold">{limit}</span> report downloads
            left this month.
          </>
        )}{" "}
        {showUpsell ? (
          <span className="text-muted-foreground">
            Pro is unlimited, watermark-free, and statewide.
          </span>
        ) : null}
      </p>
      {!subscribed ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (busy) return;
            setBusy(true);
            startSubscription().catch((e) => {
              toast.error(e instanceof Error ? e.message : "Could not start checkout.");
              setBusy(false);
            });
          }}
          className="inline-flex items-center rounded-full bg-[var(--cb-ember)] px-4 py-1.5 text-xs font-semibold text-[var(--cb-on-ember)] transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          Upgrade to Pro · $20/mo
        </button>
      ) : null}
    </div>
  );
}
