import Link from "next/link";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Wordmark } from "@/components/compbird/brand";
import { Button, Card, GrainOverlay, Pill } from "@/components/compbird/ui";
import { BillingButtons } from "@/components/compbird/account/billing-buttons";
import { changePassword, updateName } from "@/actions/account";
import { logout } from "@/actions/auth";
import { getActiveContext } from "@/lib/session";
import { db } from "@/lib/db";

export const metadata: Metadata = {
  title: "Account", // layout template appends "· compbird"
  description: "Manage your compbird profile, password, and plan.",
};

export const dynamic = "force-dynamic";

/** Plan label for the two-rung ladder (+ admin). */
const PLAN_LABEL: Record<string, string> = {
  FREE: "Free plan",
  SOLO: "Pro",
  ADMIN: "Admin",
};

const PW_ERROR: Record<string, string> = {
  "pw-current": "Your current password is incorrect.",
  "pw-weak": "New password must be at least 8 characters.",
  "pw-mismatch": "The new passwords don't match.",
  "pw-throttled": "Too many attempts. Please wait a minute and try again.",
};

const inputCls =
  "w-full rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm text-foreground " +
  "placeholder:text-muted-foreground outline-none transition-colors focus:border-[var(--cb-ember)] " +
  "focus:ring-2 focus:ring-[var(--cb-ember)]/25";

function SuccessNote({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <p
      id={id}
      role="status"
      className="mt-4 rounded-lg border border-[var(--positive)]/30 bg-[var(--positive-tint)] px-3.5 py-2.5 text-sm text-foreground"
    >
      {children}
    </p>
  );
}

/**
 * Account settings — profile, password, plan & billing, sign out. The proxy
 * only walls /comps, so this page MUST self-gate: no session → sign-in.
 */
export default async function AccountPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const ctx = await getActiveContext();
  if (!ctx) redirect("/signin?redirect=%2Fcomps");

  const user = await db.authUser.findUnique({
    where: { id: ctx.session.userId },
    select: { name: true, email: true },
  });
  if (!user) redirect("/signin?redirect=%2Fcomps");

  // ctx.account is the full Prisma row at runtime (ActiveContext narrows the
  // type); the Stripe subscription id decides Upgrade vs. Manage billing.
  const acct = ctx.account as unknown as {
    tier: string;
    stripeSubscriptionId?: string | null;
    subscriptionStatus?: string | null;
  };
  const plan = PLAN_LABEL[acct.tier] ?? "Account";
  const subscribed = Boolean(acct.stripeSubscriptionId);
  const subStatus = acct.subscriptionStatus?.trim().replace(/_/g, " ") || "";

  const sp = await searchParams;
  const nameSaved = sp.saved === "1";
  const passwordSaved = sp.pw === "1";
  const errorCode = typeof sp.error === "string" ? sp.error : "";
  const pwError = errorCode ? (PW_ERROR[errorCode] ?? "Something went wrong — try again.") : "";

  return (
    <div className="cb-shell-paper relative min-h-screen overflow-hidden bg-background text-foreground">
      <GrainOverlay className="opacity-[0.25]" />
      <div
        aria-hidden
        className="cb-glow-ring pointer-events-none absolute -right-40 -top-48 h-[34rem] w-[34rem] opacity-40"
      />
      <div className="relative mx-auto w-full max-w-2xl px-5 py-12 sm:px-6 sm:py-16">
        <div className="flex items-center justify-between gap-4">
          <Link href="/" aria-label="compbird home" className="inline-flex">
            <Wordmark />
          </Link>
          <Link
            href="/comps"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
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
            Back to studio
          </Link>
        </div>

        <h1 className="font-display mt-10 text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
          Account
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Your profile, password, and plan — all in one place.
        </p>

        {/* ── Profile ── */}
        <section className="mt-10" aria-labelledby="profile-heading">
          <span id="profile-heading" className="cb-eyebrow text-muted-foreground">
            Profile
          </span>
          <Card className="mt-3 p-6 sm:p-7">
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Email</span>
              <p className="text-sm text-foreground">{user.email}</p>
              <p className="text-xs text-muted-foreground">
                Your email is your sign-in and can&rsquo;t be changed here.
              </p>
            </div>

            <form action={updateName} className="mt-6 flex flex-col gap-1.5">
              <label htmlFor="name" className="text-xs font-medium text-muted-foreground">
                Display name
              </label>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <input
                  id="name"
                  name="name"
                  type="text"
                  maxLength={80}
                  autoComplete="name"
                  defaultValue={user.name ?? ""}
                  placeholder="Your name"
                  className={inputCls}
                />
                <Button type="submit" size="sm" variant="ghost" className="shrink-0">
                  Save name
                </Button>
              </div>
              <span className="text-xs text-muted-foreground">
                Shown in the studio and on Pro report branding.
              </span>
            </form>
            {nameSaved ? <SuccessNote id="name-saved">Name updated.</SuccessNote> : null}
          </Card>
        </section>

        {/* ── Password ── */}
        <section className="mt-8" aria-labelledby="password-heading">
          <span id="password-heading" className="cb-eyebrow text-muted-foreground">
            Password
          </span>
          <Card className="mt-3 p-6 sm:p-7">
            {pwError ? (
              <div
                id="pw-error"
                role="alert"
                className="mb-5 rounded-lg border border-[var(--negative)]/40 bg-[var(--negative)]/10 px-3.5 py-2.5 text-sm text-foreground"
              >
                {pwError}
              </div>
            ) : null}

            <form
              action={changePassword}
              aria-describedby={pwError ? "pw-error" : undefined}
              className="flex flex-col gap-4"
            >
              <div className="flex flex-col gap-1.5">
                <label htmlFor="currentPassword" className="text-xs font-medium text-muted-foreground">
                  Current password
                </label>
                <input
                  id="currentPassword"
                  name="currentPassword"
                  type="password"
                  required
                  autoComplete="current-password"
                  aria-invalid={errorCode === "pw-current" || undefined}
                  aria-describedby={errorCode === "pw-current" ? "pw-error" : undefined}
                  className={inputCls}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label htmlFor="newPassword" className="text-xs font-medium text-muted-foreground">
                  New password
                </label>
                <input
                  id="newPassword"
                  name="newPassword"
                  type="password"
                  required
                  minLength={8}
                  autoComplete="new-password"
                  aria-invalid={errorCode === "pw-weak" || undefined}
                  aria-describedby={
                    errorCode === "pw-weak" ? "pw-error new-password-hint" : "new-password-hint"
                  }
                  className={inputCls}
                />
                <span id="new-password-hint" className="text-xs text-muted-foreground">
                  At least 8 characters.
                </span>
              </div>

              <div className="flex flex-col gap-1.5">
                <label htmlFor="confirmPassword" className="text-xs font-medium text-muted-foreground">
                  Confirm new password
                </label>
                <input
                  id="confirmPassword"
                  name="confirmPassword"
                  type="password"
                  required
                  minLength={8}
                  autoComplete="new-password"
                  aria-invalid={errorCode === "pw-mismatch" || undefined}
                  aria-describedby={errorCode === "pw-mismatch" ? "pw-error" : undefined}
                  className={inputCls}
                />
              </div>

              <div>
                <Button type="submit" size="sm">
                  Change password
                </Button>
              </div>
            </form>
            {passwordSaved ? <SuccessNote id="pw-saved">Password changed.</SuccessNote> : null}
          </Card>
        </section>

        {/* ── Plan & billing ── */}
        <section className="mt-8" aria-labelledby="billing-heading">
          <span id="billing-heading" className="cb-eyebrow text-muted-foreground">
            Plan &amp; billing
          </span>
          <Card className="mt-3 p-6 sm:p-7">
            <div className="flex flex-wrap items-center gap-3">
              <Pill tone={subscribed ? "ember" : "neutral"}>{plan}</Pill>
              {subStatus ? (
                <span className="text-xs text-muted-foreground">
                  Subscription status: {subStatus}
                </span>
              ) : null}
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {subscribed
                ? "Update your card, download invoices, or cancel any time — billing is handled by Stripe."
                : "The free plan includes unlimited instant value estimates. Pro is $20/mo for the evidence — every comp, market analytics, and unlimited watermark-free branded reports."}
            </p>
            <div className="mt-5">
              <BillingButtons subscribed={subscribed} />
            </div>
          </Card>
        </section>

        {/* ── Sign out ── */}
        <section className="mt-8" aria-labelledby="session-heading">
          <span id="session-heading" className="cb-eyebrow text-muted-foreground">
            Session
          </span>
          <Card className="mt-3 flex flex-wrap items-center justify-between gap-4 p-6 sm:p-7">
            <p className="text-sm text-muted-foreground">
              Signed in as <span className="text-foreground">{user.email}</span>.
            </p>
            <form action={logout}>
              <Button type="submit" variant="ghost" size="sm">
                Sign out
              </Button>
            </form>
          </Card>
        </section>
      </div>
    </div>
  );
}
