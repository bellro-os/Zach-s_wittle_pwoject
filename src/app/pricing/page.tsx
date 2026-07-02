import type { Metadata } from "next";
import Link from "next/link";
import { Nav } from "@/components/compbird/nav";
import { Footer } from "@/components/compbird/footer";
import { SectionShell, Eyebrow, Button, Card, GrainOverlay } from "@/components/compbird/ui";

export const metadata: Metadata = {
  title: "Pricing", // layout template appends "· compbird"
  description:
    "Start free with the full comp studio and two report downloads a month. Pro is $20/mo for unlimited, whitelabeled reports with market analytics.",
};

/* Honest split: Free is the whole studio with a download cap; Pro removes the
   cap and dresses the report in the agent's brand. The layout is deliberately
   asymmetric — Pro carries the dark instrument slab. */

const FREE_FEATURES = [
  "Full comp studio — price any address in coverage",
  "Live comp tuning: swap, weight, and re-run in seconds",
  "Market cards on screen for every report",
  "2 report downloads a month, watermarked",
];

const PRO_FEATURES = [
  "Unlimited report downloads",
  "No watermark — your name and branding on every page",
  "Statewide off-MLS sales coverage in the comp pool",
  "Market analytics printed inside the report",
];

const FAQ: { q: string; a: string }[] = [
  {
    q: "What counts as a download?",
    a: "A rendered PDF report. If a render fails, it never counts against your two — only finished documents do.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes. Manage or cancel Pro from the billing portal in the studio's account menu; access runs to the end of the paid period.",
  },
  {
    q: "Where does compbird work today?",
    a: "Virginia and D.C. Deep live MLS runs in the New River Valley core, backed by recorded sales across 130 localities.",
  },
];

function FeatureList({ items }: { items: string[] }) {
  return (
    <ul className="mt-7 space-y-3.5">
      {items.map((f) => (
        <li key={f} className="flex gap-3 text-sm leading-relaxed">
          <span className="mt-2.5 h-px w-4 shrink-0 bg-[var(--cb-ember)]" aria-hidden />
          <span className="text-foreground/85">{f}</span>
        </li>
      ))}
    </ul>
  );
}

export default function PricingPage() {
  return (
    <div className="cb-shell-paper min-h-screen bg-background">
      <Nav />
      <main>
        <SectionShell className="pb-24 pt-16 sm:pb-28 sm:pt-24" width="wide">
          <div className="max-w-2xl">
            <Eyebrow>Pricing</Eyebrow>
            <h1 className="font-display mt-6 text-4xl font-bold tracking-tight text-foreground text-balance sm:text-5xl">
              Free to price. $20 when the report has to leave the building.
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted-foreground">
              Every account gets the whole studio — the same engine, the same comps.
              Pro is for agents who hand the report to a client.
            </p>
          </div>

          {/* ── plans: light Free panel · dark Pro slab ── */}
          <div className="mt-14 grid gap-6 lg:grid-cols-[0.85fr_1.15fr] lg:items-stretch">
            <Card className="flex flex-col p-8 sm:p-10">
              <span className="cb-eyebrow text-muted-foreground">Free</span>
              <div className="mt-5 flex items-baseline gap-2">
                <span className="font-data text-5xl font-semibold tracking-tight text-foreground">$0</span>
                <span className="text-sm text-muted-foreground">no card required</span>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                The full studio, on screen. Downloads are the only meter.
              </p>
              <FeatureList items={FREE_FEATURES} />
              <div className="mt-auto pt-9">
                <Button href="/join" variant="ghost" className="w-full justify-center">
                  Start free
                </Button>
              </div>
            </Card>

            <div className="cb-dark relative flex flex-col overflow-hidden rounded-2xl border border-border bg-card p-8 sm:p-10">
              <GrainOverlay className="opacity-30" />
              <div
                aria-hidden
                className="cb-glow-ring pointer-events-none absolute -right-24 -top-24 h-64 w-64 opacity-50"
              />
              <div className="relative flex grow flex-col">
                <div className="flex items-center justify-between gap-4">
                  <span className="cb-eyebrow text-[var(--cb-ember-text)]">Pro</span>
                  <span className="text-xs text-muted-foreground">for client-facing reports</span>
                </div>
                <div className="mt-5 flex items-baseline gap-2">
                  <span className="font-data text-5xl font-semibold tracking-tight text-foreground">$20</span>
                  <span className="text-sm text-muted-foreground">per month</span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  Everything in Free, plus:
                </p>
                <FeatureList items={PRO_FEATURES} />
                <div className="mt-auto pt-9">
                  <Button href="/join?redirect=%2Fcomps" className="w-full justify-center" arrow>
                    Start free, upgrade in the studio
                  </Button>
                  <p className="mt-3.5 text-xs leading-relaxed text-muted-foreground">
                    There&rsquo;s no checkout on this page on purpose — create a free
                    account, and when you need Pro, upgrade from the account menu
                    inside the studio. Billing is handled by Stripe.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* ── the fine print, plainly ── */}
          <div className="mt-20 max-w-3xl">
            <span className="cb-eyebrow text-muted-foreground">The fine print, plainly</span>
            <dl className="mt-6 divide-y divide-border border-y border-border">
              {FAQ.map((item) => (
                <div key={item.q} className="grid gap-2 py-5 sm:grid-cols-[15rem_1fr] sm:gap-8">
                  <dt className="text-sm font-semibold text-foreground">{item.q}</dt>
                  <dd className="text-sm leading-relaxed text-muted-foreground">{item.a}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-6 text-xs text-muted-foreground">
              Estimates are model-driven opinions of value — not appraisals. Full details in the{" "}
              <Link href="/terms" className="underline underline-offset-2 hover:text-foreground">
                terms
              </Link>
              .
            </p>
          </div>
        </SectionShell>
      </main>
      <Footer />
    </div>
  );
}
