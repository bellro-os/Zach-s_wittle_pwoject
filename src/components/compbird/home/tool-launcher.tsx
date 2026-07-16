"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { cn } from "@/lib/utils/cn";
import { startSubscription } from "@/lib/compbird/api";

/**
 * The hub's tool grid — every signed-in surface in one place. Live tools are
 * real links; Portfolio locks to an inline upgrade for FREE accounts (the same
 * startSubscription() idiom the account menu / Pro pitch use, so FREE is never
 * dead-ended at a link that would only bounce). Two "Coming soon" cards make the
 * Phase-2 slots (Saved Reports, Market Reports) visible without being clickable.
 */

const cardBase =
  "group relative flex h-full flex-col gap-3 rounded-2xl border border-border bg-card/80 p-5 backdrop-blur-sm transition-colors";
const cardHover =
  "hover:border-[var(--cb-ember)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]";

function CardIcon({ children }: { children: React.ReactNode }) {
  return (
    <span
      aria-hidden
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-secondary/50 text-[var(--cb-ember-text)]"
    >
      {children}
    </span>
  );
}

function CardHead({ eyebrow, icon }: { eyebrow: string; icon: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <CardIcon>{icon}</CardIcon>
      <span className="cb-eyebrow text-muted-foreground">{eyebrow}</span>
    </div>
  );
}

function CardBody({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="mt-1">
      <h3 className="font-display text-lg font-semibold tracking-tight text-foreground">
        {title}
      </h3>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{desc}</p>
    </div>
  );
}

/* ── icons (inline, token-driven) ──────────────────────────────────────────── */
const iconStroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function StudioIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4.5 w-4.5" {...iconStroke}>
      <path d="M3 10a7 7 0 1 1 14 0 7 7 0 0 1-14 0Z" />
      <path d="M10 6v4l2.5 1.5" />
    </svg>
  );
}
function PortfolioIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4.5 w-4.5" {...iconStroke}>
      <path d="M3 5h14M3 10h14M3 15h9" />
    </svg>
  );
}
function AccountIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4.5 w-4.5" {...iconStroke}>
      <path d="M10 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />
      <path d="M4 16a6 6 0 0 1 12 0" />
    </svg>
  );
}
function ReportsIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4.5 w-4.5" {...iconStroke}>
      <path d="M5 3h7l3 3v11H5V3Z" />
      <path d="M12 3v3h3M7.5 11h5M7.5 14h5" />
    </svg>
  );
}
function MarketIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4.5 w-4.5" {...iconStroke}>
      <path d="M3 16V4M3 16h14M6 13l3-4 3 2 4-6" />
    </svg>
  );
}

function LinkCard({
  href,
  eyebrow,
  icon,
  title,
  desc,
}: {
  href: string;
  eyebrow: string;
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <Link href={href} className={cn(cardBase, cardHover)}>
      <CardHead eyebrow={eyebrow} icon={icon} />
      <CardBody title={title} desc={desc} />
    </Link>
  );
}

function ComingSoonCard({
  eyebrow,
  icon,
  title,
  desc,
}: {
  eyebrow: string;
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <div aria-disabled className={cn(cardBase, "cursor-default opacity-70")}>
      <div className="flex items-center justify-between gap-3">
        <CardIcon>{icon}</CardIcon>
        <span className="font-data rounded border border-border bg-secondary/60 px-1.5 py-px text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
          soon
        </span>
      </div>
      <CardBody title={title} desc={desc} />
    </div>
  );
}

/** Portfolio, locked for FREE — an inline upgrade instead of a dead /portfolio link. */
function PortfolioLockedCard() {
  const [busy, setBusy] = useState(false);
  return (
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
      className={cn(cardBase, cardHover, "text-left disabled:opacity-60")}
    >
      <div className="flex items-center justify-between gap-3">
        <CardIcon>
          <PortfolioIcon />
        </CardIcon>
        <span className="font-data inline-flex items-center gap-1 rounded border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] px-1.5 py-px text-[9px] uppercase tracking-[0.12em] text-[var(--cb-ember-text)]">
          <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" aria-hidden {...iconStroke}>
            <path d="M3.5 5.5V4a2.5 2.5 0 0 1 5 0v1.5M2.75 5.5h6.5v4.25h-6.5z" />
          </svg>
          Pro
        </span>
      </div>
      <CardBody
        title="Portfolio"
        desc="Comp up to 50 properties in one run — an estimate, range, and confidence read on each."
      />
      <span className="mt-auto inline-flex items-center gap-1.5 pt-1 text-xs font-semibold text-[var(--cb-ember-text)]">
        Upgrade to Pro · $20/mo
        <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden {...iconStroke}>
          <path d="M3 8h10m0 0L9 4m4 4-4 4" />
        </svg>
      </span>
    </button>
  );
}

export function ToolLauncher({ pro }: { pro: boolean }) {
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <li className="h-full">
        <LinkCard
          href="/comps"
          eyebrow="Price a home"
          icon={<StudioIcon />}
          title="Comp studio"
          desc="Price any address with appraisal-grade comps and a live neighborhood market read."
        />
      </li>
      <li className="h-full">
        {pro ? (
          <LinkCard
            href="/portfolio"
            eyebrow="Batch valuation"
            icon={<PortfolioIcon />}
            title="Portfolio"
            desc="Comp up to 50 properties in one run — an estimate, range, and confidence read on each."
          />
        ) : (
          <PortfolioLockedCard />
        )}
      </li>
      <li className="h-full">
        <LinkCard
          href="/account"
          eyebrow="Your plan"
          icon={<AccountIcon />}
          title="Account & billing"
          desc="Manage your plan, billing, and account details."
        />
      </li>
      <li className="h-full">
        <ComingSoonCard
          eyebrow="Coming soon"
          icon={<ReportsIcon />}
          title="Saved reports"
          desc="Every CMA you generate, saved and searchable — pick up right where you left off."
        />
      </li>
      <li className="h-full">
        <ComingSoonCard
          eyebrow="Coming soon"
          icon={<MarketIcon />}
          title="Market reports"
          desc="Full neighborhood analytics — momentum, supply, and velocity you can hand a client."
        />
      </li>
    </ul>
  );
}
