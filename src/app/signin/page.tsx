import Link from "next/link";
import type { Metadata } from "next";
import { Wordmark } from "@/components/compbird/brand";
import { Button, GrainOverlay } from "@/components/compbird/ui";
import { login } from "@/actions/auth";
import { safeAuthRedirect } from "@/lib/auth-redirect";

export const metadata: Metadata = {
  title: "Sign in", // layout template appends "· compbird"
  description: "Sign in to your compbird account.",
};

export const dynamic = "force-dynamic";

// Support inbox for the dead-end error path — same env override as the footer,
// so "contact support" is actionable, not a dangling instruction.
const CONTACT_EMAIL =
  process.env.NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL?.trim() || "hello@ratifyly.com";

const LOGIN_ERROR: Record<string, string> = {
  "1": "Email or password is incorrect.",
  throttled: "Too many attempts. Please wait a minute and try again.",
  noaccount: `That account isn't set up yet — email ${CONTACT_EMAIL}.`,
};

const inputCls =
  "w-full rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm text-foreground " +
  "placeholder:text-muted-foreground outline-none transition-colors focus:border-[var(--cb-ember)] " +
  "focus:ring-2 focus:ring-[var(--cb-ember)]/25";

export default async function CompbirdSignInPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const redirectTo = safeAuthRedirect(sp.redirect);
  const errorCode = typeof sp.error === "string" ? sp.error : "";
  const errorMsg = errorCode ? (LOGIN_ERROR[errorCode] ?? "Couldn't sign you in — try again.") : "";
  const resetDone = sp.reset === "1";
  const resetError = sp.resetError === "1";
  const joinHref = `/join?redirect=${encodeURIComponent(redirectTo)}`;

  return (
    <div className="cb-shell-paper relative min-h-screen overflow-hidden bg-background text-foreground">
      <GrainOverlay className="opacity-[0.25]" />
      <div
        aria-hidden
        className="cb-glow-ring pointer-events-none absolute -right-40 -top-48 h-[34rem] w-[34rem] opacity-40"
      />
      <div className="relative mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-5 py-12 sm:px-6">
        <Link href="/" aria-label="compbird home" className="mb-8 inline-flex">
          <Wordmark />
        </Link>

        <h1 className="font-display text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
          Sign in
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">Welcome back to the comp studio. Free: unlimited instant estimates · Pro: every comp and the full market read, $20/mo.</p>

        {errorMsg ? (
          <div
            id="signin-error"
            role="alert"
            className="mt-6 rounded-lg border border-[var(--negative)]/40 bg-[var(--negative)]/10 px-3.5 py-2.5 text-sm text-foreground"
          >
            {errorMsg}
          </div>
        ) : null}

        {resetDone ? (
          <div
            role="status"
            className="mt-6 rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm text-foreground"
          >
            Password updated — sign in.
          </div>
        ) : null}

        {resetError ? (
          <div
            role="alert"
            className="mt-6 rounded-lg border border-[var(--negative)]/40 bg-[var(--negative)]/10 px-3.5 py-2.5 text-sm text-foreground"
          >
            That reset link is invalid or expired.{" "}
            <Link href="/forgot-password" className="font-medium underline">
              Request a new one
            </Link>
            .
          </div>
        ) : null}

        <form action={login} className="mt-6 flex flex-col gap-4">
          <input type="hidden" name="redirect" value={redirectTo} />

          <div className="flex flex-col gap-1.5">
            <label htmlFor="email" className="text-xs font-medium text-muted-foreground">
              Email
            </label>
            <input id="email" name="email" type="email" required autoComplete="email" className={inputCls} />
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="password" className="text-xs font-medium text-muted-foreground">
                Password
              </label>
              <Link href="/forgot-password" className="text-xs text-muted-foreground hover:text-foreground">
                Forgot?
              </Link>
            </div>
            <input
              id="password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
              className={inputCls}
            />
          </div>

          <Button type="submit" className="mt-1 w-full justify-center">
            Sign in
          </Button>
        </form>

        <p className="mt-6 text-sm text-muted-foreground">
          New to compbird?{" "}
          <Link href={joinHref} className="font-medium text-[var(--cb-ember-text)] hover:underline">
            Create a free account
          </Link>
        </p>
      </div>
    </div>
  );
}
