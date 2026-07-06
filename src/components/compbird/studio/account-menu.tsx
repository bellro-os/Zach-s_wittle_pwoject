"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
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
            <Link
              href="/account"
              role="menuitem"
              onClick={() => setOpen(false)}
              className={itemCls}
            >
              Account settings
            </Link>
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
 * Slim persistent Pro pitch for evidence-locked (FREE) accounts, shown above
 * the studio. Estimates are unlimited on Free — there is no quota to count —
 * so this banner names what Pro adds instead of metering anything. Pro
 * accounts never render it (the page skips it entirely).
 */
export function ProPitchBanner() {
  const [busy, setBusy] = useState(false);

  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card/60 px-4 py-3"
    >
      <p className="text-sm text-foreground">
        Estimates are free.{" "}
        <span className="text-muted-foreground">
          Every comp, the market read, and branded reports are Pro.
        </span>
      </p>
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
    </div>
  );
}
