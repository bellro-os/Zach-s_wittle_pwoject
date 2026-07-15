import Link from "next/link";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Wordmark } from "@/components/compbird/brand";
import { Eyebrow, GrainOverlay } from "@/components/compbird/ui";
import { StudioAccountMenu } from "@/components/compbird/studio/account-menu";
import { PortfolioStudio } from "@/components/compbird/portfolio/portfolio-studio";
import { getActiveContext } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";

export const metadata: Metadata = {
  title: "Portfolio",
  description:
    "Comp an entire portfolio at once — up to 50 properties per run, each with an estimate, range, and confidence read.",
};

// Resolves the account (tier + subscription) per-request, so it renders dynamically.
export const dynamic = "force-dynamic";

/** Compact plan label for the header chip — mirrors the comp studio's map. */
const PLAN_LABEL: Record<string, string> = {
  FREE: "Free plan",
  BETA: "Beta",
  SOLO: "Pro",
  TEAM: "Team",
  BROKERAGE: "Brokerage",
  ADMIN: "Admin",
};

/**
 * The portfolio page — batch comping on the dark instrument surface. Same
 * shell as the comp studio (slim header, grain, glow ring); the client
 * <PortfolioStudio/> owns the input → poll → results loop.
 */
export default async function PortfolioPage() {
  // Same wall as /comps: an account is required. The proxy matcher only covers
  // /comps, so this server-side redirect IS the wall here.
  const ctx = await getActiveContext();
  if (!ctx) redirect("/join?redirect=%2Fportfolio");

  const acct = ctx.account as unknown as { tier: string; stripeSubscriptionId?: string | null };
  const plan = PLAN_LABEL[acct.tier] ?? "Account";
  const subscribed = Boolean(acct.stripeSubscriptionId);

  // Pro state keys off the same server-side entitlement check the comp studio
  // uses ("cma.evidence" = the SOLO/Pro marker — the tier that carries
  // "cma.portfolio"). FREE renders the page with the input parked behind the
  // upsell; the API 403s independently, so this is presentation, not the gate.
  const pro = canFeature(ctx.ent, "cma.evidence");

  return (
    <div className="cb-dark cb-shell-night min-h-screen bg-background text-foreground">
      {/* studio header */}
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link
            href="/"
            className="rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--cb-ember)]"
            aria-label="compbird home"
          >
            <Wordmark />
          </Link>
          <div className="flex items-center gap-4 sm:gap-5">
            <Link
              href="/comps"
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
              Comp studio
            </Link>
            <StudioAccountMenu plan={plan} pro={pro} subscribed={subscribed} />
          </div>
        </div>
      </header>

      {/* page body */}
      <main className="relative overflow-hidden">
        <GrainOverlay className="opacity-[0.3]" />
        <div
          aria-hidden
          className="cb-glow-ring pointer-events-none absolute -right-48 -top-56 h-[36rem] w-[36rem] opacity-50"
        />
        <div className="relative mx-auto w-full max-w-6xl px-5 py-12 sm:px-8 sm:py-16">
          <div className="mb-8 flex flex-col gap-3">
            <Eyebrow>Portfolio</Eyebrow>
            <h1 className="font-display text-3xl tracking-tight text-foreground sm:text-4xl">
              Comp an entire portfolio at once.
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Paste up to 50 addresses — or drop a CSV — and get an estimate,
              range, and confidence read on every property in one run, with the
              whole portfolio totaled at the bottom.
            </p>
          </div>

          <PortfolioStudio pro={pro} />

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
