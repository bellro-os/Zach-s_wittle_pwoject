import Link from "next/link";
import type { Metadata } from "next";
import { Wordmark } from "@/components/compbird/brand";
import { Button, GrainOverlay } from "@/components/compbird/ui";
import { signup } from "@/actions/auth";

export const metadata: Metadata = {
  title: "Create your free account", // layout template appends "· compbird"
  description:
    "Create a free compbird account for instant property value estimates — unlimited lookups, no card required. Pro unlocks every comp and the full market read.",
  alternates: { canonical: "/join" },
};

export const dynamic = "force-dynamic";

/** Only honor internal compbird redirect targets (no open-redirect). */
function safeRedirect(raw: string | string[] | undefined): string {
  const v = typeof raw === "string" ? raw.trim() : "";
  return /^\/(?:comps(?:\/[A-Za-z0-9._~-]*)?)?$/.test(v) ? v || "/comps" : "/comps";
}

const SIGNUP_ERROR: Record<string, string> = {
  email: "Enter a valid email address.",
  weak: "Password must be at least 8 characters.",
  exists: "That email already has an account — sign in instead.",
  throttled: "Too many attempts. Please wait a minute and try again.",
  company: "Please add a name for your account.",
};

const inputCls =
  "w-full rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm text-foreground " +
  "placeholder:text-muted-foreground outline-none transition-colors focus:border-[var(--cb-ember)] " +
  "focus:ring-2 focus:ring-[var(--cb-ember)]/25";

export default async function CompbirdJoinPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const redirectTo = safeRedirect(sp.redirect);
  const errorCode = typeof sp.error === "string" ? sp.error : "";
  const errorMsg = errorCode ? (SIGNUP_ERROR[errorCode] ?? "Something went wrong — try again.") : "";
  const email = typeof sp.email === "string" ? sp.email : "";
  const name = typeof sp.name === "string" ? sp.name : "";
  const signinHref = `/signin?redirect=${encodeURIComponent(redirectTo)}`;
  // Field-level error association (generic/throttled errors stay at the form level).
  const emailError = errorCode === "email" || errorCode === "exists";
  const passwordError = errorCode === "weak";

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
          Create your free account
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Instant value estimates, unlimited lookups — free. No card required.
        </p>

        {errorMsg ? (
          <div
            id="join-error"
            role="alert"
            className="mt-6 rounded-lg border border-[var(--negative)]/40 bg-[var(--negative)]/10 px-3.5 py-2.5 text-sm text-foreground"
          >
            {errorMsg}
          </div>
        ) : null}

        <form action={signup} className="mt-6 flex flex-col gap-4">
          <input type="hidden" name="redirect" value={redirectTo} />

          <div className="flex flex-col gap-1.5">
            <label htmlFor="name" className="text-xs font-medium text-muted-foreground">
              Name <span className="text-muted-foreground/60">(optional)</span>
            </label>
            <input id="name" name="name" type="text" autoComplete="name" defaultValue={name} className={inputCls} />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="email" className="text-xs font-medium text-muted-foreground">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="email"
              defaultValue={email}
              aria-invalid={emailError || undefined}
              aria-describedby={emailError ? "join-error" : undefined}
              className={inputCls}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="password" className="text-xs font-medium text-muted-foreground">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              aria-invalid={passwordError || undefined}
              aria-describedby={passwordError ? "join-error password-hint" : "password-hint"}
              className={inputCls}
            />
            <span id="password-hint" className="text-xs text-muted-foreground">
              At least 8 characters.
            </span>
          </div>

          <Button type="submit" className="mt-1 w-full justify-center">
            Create free account
          </Button>
        </form>

        <p className="mt-6 text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href={signinHref} className="font-medium text-[var(--cb-ember-text)] hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
