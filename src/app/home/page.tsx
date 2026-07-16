import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Eyebrow, GrainOverlay, Pill } from "@/components/compbird/ui";
import { AppHeader } from "@/components/compbird/studio/app-header";
import { PortalSearch } from "@/components/compbird/home/portal-search";
import { ToolLauncher } from "@/components/compbird/home/tool-launcher";
import { PortalRecents } from "@/components/compbird/home/portal-recents";
import { MarketSnapshot } from "@/components/compbird/home/market-snapshot";
import { PortalUpgradeButton } from "@/components/compbird/home/upgrade-button";
import { getActiveContext, monthlyUsage } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";
import { engineMarkets } from "@/lib/cma/engine";
import type { NeighborhoodMarket } from "@/lib/compbird/types";

export const metadata: Metadata = {
  title: "Home",
  description:
    "Your compbird home base — price any home, comp a portfolio, and read the neighborhoods you sell in.",
};

// Resolves the account (tier + subscription) and live markets per-request.
export const dynamic = "force-dynamic";

/** Compact plan label — mirrors the comp studio / portfolio header maps. */
const PLAN_LABEL: Record<string, string> = {
  FREE: "Free plan",
  BETA: "Beta",
  SOLO: "Pro",
  TEAM: "Team",
  BROKERAGE: "Brokerage",
  ADMIN: "Admin",
};

/**
 * The signed-in HUB — the default post-login destination. It surfaces every
 * tool from one place on the same dark "instrument" surface as the studio:
 * the instant-CMA search (hero action), the tool grid, recent properties, a
 * live neighborhood snapshot, and an account strip. Server component: the shell
 * is RSC; only the search, recents, tool grid, and upgrade CTA are client.
 */
export default async function HomePage() {
  const ctx = await getActiveContext();
  if (!ctx) redirect("/signin?redirect=%2Fhome");

  const acct = ctx.account as unknown as { tier: string; stripeSubscriptionId?: string | null };
  const plan = PLAN_LABEL[acct.tier] ?? "Account";
  const subscribed = Boolean(acct.stripeSubscriptionId);
  const pro = canFeature(ctx.ent, "cma.evidence");

  // Live neighborhood cards — the SAME engine call the landing's /markets route
  // uses. engineMarkets never throws (soft-fails to []); we also guard so a
  // cold engine simply omits the snapshot section.
  let markets: NeighborhoodMarket[] = [];
  try {
    const res = await engineMarkets();
    if (Array.isArray(res.body?.markets)) markets = res.body.markets;
  } catch {
    /* cold engine — omit the snapshot, never break the hub */
  }

  // This-month generate usage (optional context for the account strip). Counts
  // the account's UsageEvent rows for the metered feature; best-effort.
  let usageThisMonth: number | null = null;
  try {
    usageThisMonth = await monthlyUsage("cma.generate", ctx.account.id);
  } catch {
    usageThisMonth = null;
  }

  const firstName = (ctx.account.name ?? "").trim().split(/\s+/)[0] || null;

  return (
    <div className="cb-dark cb-shell-night min-h-screen bg-background text-foreground">
      <AppHeader
        plan={plan}
        pro={pro}
        subscribed={subscribed}
        name={ctx.account.name}
        active="home"
      />

      <main className="relative overflow-hidden">
        <GrainOverlay className="opacity-[0.3]" />
        <div
          aria-hidden
          className="cb-glow-ring pointer-events-none absolute -right-48 -top-56 h-[36rem] w-[36rem] opacity-50"
        />
        <div className="relative mx-auto w-full max-w-6xl px-5 py-12 sm:px-8 sm:py-16">
          {/* ── hero: welcome + instant-CMA search ── */}
          <section className="flex flex-col gap-6">
            <div className="flex flex-col gap-3">
              <Eyebrow>Home</Eyebrow>
              <h1 className="font-display text-3xl tracking-tight text-foreground sm:text-4xl">
                {firstName ? `Welcome back, ${firstName}.` : "Welcome back."}
              </h1>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                Price any home in seconds, or pick up where you left off. Enter an
                address to run a fresh CMA.
              </p>
            </div>
            <PortalSearch />
          </section>

          {/* ── tools ── */}
          <section className="mt-14">
            <div className="mb-5 flex items-center gap-3">
              <Eyebrow>Your tools</Eyebrow>
            </div>
            <ToolLauncher pro={pro} />
          </section>

          {/* ── recents ── */}
          <section className="mt-14">
            <div className="mb-5 flex items-center gap-3">
              <Eyebrow>Recent properties</Eyebrow>
            </div>
            <PortalRecents />
          </section>

          {/* ── live market snapshot (hidden when the engine has no data) ── */}
          {markets.length > 0 ? (
            <section className="mt-14">
              <div className="mb-5 flex items-center gap-3">
                <Eyebrow>Neighborhood snapshot</Eyebrow>
                <Pill tone="ember">
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--cb-ember)]" aria-hidden />
                  Live data
                </Pill>
              </div>
              <MarketSnapshot markets={markets} />
            </section>
          ) : null}

          {/* ── account strip ── */}
          <section className="mt-14">
            <div className="flex flex-col gap-4 rounded-2xl border border-border bg-card/60 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3">
                <Pill tone={pro ? "ember" : "neutral"}>{plan}</Pill>
                {usageThisMonth != null ? (
                  <span className="text-xs text-muted-foreground">
                    <span className="font-data text-foreground">{usageThisMonth}</span>{" "}
                    report{usageThisMonth === 1 ? "" : "s"} generated this month
                  </span>
                ) : null}
              </div>
              {!pro ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-xs text-muted-foreground">
                    Unlock every comp, the full market read, and branded reports.
                  </span>
                  <PortalUpgradeButton />
                </div>
              ) : null}
            </div>
          </section>

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
