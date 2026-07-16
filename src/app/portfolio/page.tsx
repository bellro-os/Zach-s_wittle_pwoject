import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Eyebrow, GrainOverlay } from "@/components/compbird/ui";
import { AppHeader } from "@/components/compbird/studio/app-header";
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
      <AppHeader
        plan={plan}
        pro={pro}
        subscribed={subscribed}
        name={ctx.account.name}
        active="portfolio"
      />

      {/* page body */}
      <main className="relative overflow-hidden">
        <GrainOverlay className="opacity-[0.3]" />
        <div
          aria-hidden
          className="cb-glow-ring pointer-events-none absolute -right-48 -top-56 h-[36rem] w-[36rem] opacity-50"
        />
        <div className="relative mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-12">
          {/* Workspace header — a tool, not a landing page. */}
          <div className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-border pb-6">
            <div className="flex flex-col gap-2">
              <Eyebrow>Portfolio</Eyebrow>
              <h1 className="font-display text-2xl tracking-tight text-foreground sm:text-[1.75rem]">
                Portfolio
              </h1>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                Value up to 50 properties in one run — estimate, range, and
                confidence on each, with the whole book totaled.
              </p>
            </div>
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
