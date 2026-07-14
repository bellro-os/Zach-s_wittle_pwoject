import { Suspense } from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Wordmark } from "@/components/compbird/brand";
import { GrainOverlay } from "@/components/compbird/ui";
import { CompStudio } from "@/components/compbird/studio/comp-studio";
import { StudioAccountMenu, ProPitchBanner } from "@/components/compbird/studio/account-menu";
import { SubscribeToast } from "@/components/compbird/studio/subscribe-toast";
import { getActiveContext } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";

export const metadata: Metadata = {
  title: "Comp studio",
  description:
    "Price any home with appraisal-grade comparables and a live neighborhood market read — a bird's-eye view of value.",
};

// Resolves the account (tier + subscription) per-request, so it renders dynamically.
export const dynamic = "force-dynamic";

/** Compact plan label for the studio header chip. */
const PLAN_LABEL: Record<string, string> = {
  FREE: "Free plan",
  BETA: "Beta",
  SOLO: "Pro",
  TEAM: "Team",
  BROKERAGE: "Brokerage",
  ADMIN: "Admin",
};

/**
 * The live comp studio — compbird's working tool on the dark "instrument"
 * surface. A slim header brackets the studio; everything else is driven by the
 * client <CompStudio/>, which paints a sample dossier instantly and runs live
 * on demand.
 */
export default async function CompStudioPage() {
  // A free account is required to use the studio. The proxy already walls this
  // route; this is defense-in-depth so it never renders for an anonymous visitor
  // even if the middleware matcher is bypassed.
  const ctx = await getActiveContext();
  if (!ctx) redirect("/join?redirect=%2Fcomps");
  // ctx.account is the full Prisma row at runtime (the ActiveContext type narrows
  // it). Plan state keys off the TIER (via entitlements) — a comped/dev SOLO
  // account is Pro with no Stripe record; the Stripe subscription id ONLY
  // decides whether "Manage billing" exists.
  const acct = ctx.account as unknown as { tier: string; stripeSubscriptionId?: string | null };
  const plan = PLAN_LABEL[acct.tier] ?? "Account";
  const subscribed = Boolean(acct.stripeSubscriptionId);

  // The paywall line: Pro ("cma.evidence") sees everything, unmetered — no
  // banner at all. FREE sees unlimited estimates with the evidence redacted
  // server-side, so the only banner is a slim pitch naming what Pro adds.
  const evidence = canFeature(ctx.ent, "cma.evidence");
  return (
    <div className="cb-dark cb-shell-night min-h-screen bg-background text-foreground">
      {/* Stripe Checkout return toasts (?subscribed=1 / ?checkout=cancelled) */}
      <SubscribeToast />
      {/* studio header */}
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link
            href="/"
            className="rounded-md outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--cb-ember)]"
            aria-label="compbird home"
          >
            <Wordmark />
          </Link>
          <div className="flex items-center gap-4 sm:gap-5">
            <Link
              href="/"
              className="hidden items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground sm:inline-flex"
            >
              <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4" aria-hidden>
                <path
                  d="M13 8H3m0 0 4 4M3 8l4-4"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              Back to compbird
            </Link>
            <StudioAccountMenu plan={plan} pro={evidence} subscribed={subscribed} />
          </div>
        </div>
      </header>

      {/* studio body */}
      <main className="relative overflow-hidden">
        <GrainOverlay className="opacity-[0.3]" />
        <div
          aria-hidden
          className="cb-glow-ring pointer-events-none absolute -right-48 -top-56 h-[36rem] w-[36rem] opacity-50"
        />
        <div className="relative mx-auto w-full max-w-6xl px-5 py-12 sm:px-8 sm:py-16">
          {!evidence ? (
            <div className="mb-8">
              <ProPitchBanner />
            </div>
          ) : null}
          {/* Suspense: the studio reads useSearchParams so LIVE ?address= /
              ?parcelId= / ?demo=1 changes load a subject while mounted — Next
              requires the boundary. The page is force-dynamic, so the fallback
              never actually paints in practice. */}
          <Suspense fallback={null}>
            <CompStudio />
          </Suspense>
          <p className="mt-12 border-t border-border pt-6 text-xs leading-relaxed text-muted-foreground">
            compbird estimates are model-driven opinions of value based on public
            records and recent comparable sales — they are not appraisals, and no
            estimate here should be relied on as one. Verify property details
            independently before making decisions.
          </p>
        </div>
      </main>
    </div>
  );
}
