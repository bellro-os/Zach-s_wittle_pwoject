"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/compbird/ui";
import { startSubscription, openBillingPortal } from "@/lib/compbird/api";
import { logout } from "@/actions/auth";

/**
 * The studio's account affordance: the plan Pill plus — when not subscribed —
 * an always-visible Upgrade ($20/mo) button (the upgrade CTA never hides in a
 * menu). Secondary actions (Manage billing, Sign out) live in a compact
 * dropdown behind a circular avatar trigger. `subscribed` is true when the
 * account has an active Stripe subscription.
 */
export function StudioAccountMenu({
  plan,
  subscribed,
}: {
  plan: string;
  subscribed: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close on click-outside (without stealing focus from whatever was clicked)
  // and on Escape (returning focus to the trigger, per the menu-button pattern).
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  /** Close the menu and hand focus back to the avatar trigger. */
  function closeMenu() {
    setOpen(false);
    triggerRef.current?.focus();
  }

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

  const itemCls =
    "block w-full rounded-md px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:bg-[var(--cb-tint)] hover:text-foreground disabled:opacity-50";

  return (
    <div className="flex items-center gap-3">
      <Pill tone={subscribed ? "ember" : "neutral"}>{plan}</Pill>

      {!subscribed ? (
        <button
          type="button"
          onClick={() => go(startSubscription, "Could not start checkout.")}
          disabled={busy}
          className="inline-flex items-center rounded-full bg-[var(--cb-ember)] px-3 py-1.5 text-xs font-semibold text-[var(--cb-on-ember)] transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          Upgrade to Pro · $20/mo
        </button>
      ) : null}

      <div ref={rootRef} className="relative">
        <button
          ref={triggerRef}
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Account menu"
          onClick={() => setOpen((v) => !v)}
          className="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-card/60 text-xs font-semibold text-foreground transition-colors hover:border-[var(--cb-ember)]/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
        >
          {(plan.trim().charAt(0) || "A").toUpperCase()}
        </button>

        {open ? (
          <div
            role="menu"
            aria-label="Account"
            className="absolute right-0 top-full z-50 mt-2 w-44 rounded-lg border border-border bg-card p-1 shadow-xl"
          >
            {subscribed ? (
              <button
                type="button"
                role="menuitem"
                disabled={busy}
                onClick={() => {
                  closeMenu();
                  void go(openBillingPortal, "Could not open billing.");
                }}
                className={itemCls}
              >
                Manage billing
              </button>
            ) : null}
            {/* Sign-out stays a server-action form post (clears the session
                cookie on the server) — the menu only wraps it. No onSubmit
                close: unmounting the form mid-dispatch could cancel the action,
                and logout navigates away regardless. */}
            <form action={logout}>
              <input type="hidden" name="redirect" value="/" />
              <button type="submit" role="menuitem" className={itemCls}>
                Sign out
              </button>
            </form>
          </div>
        ) : null}
      </div>
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
