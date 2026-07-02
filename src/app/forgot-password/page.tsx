import Link from "next/link";
import type { Metadata } from "next";
import { Wordmark } from "@/components/compbird/brand";
import { Button, GrainOverlay } from "@/components/compbird/ui";
import { requestPasswordReset } from "@/actions/auth";

export const metadata: Metadata = {
  title: "Reset your password", // layout template appends "· compbird"
  description: "Request a password reset link for your compbird account.",
};

export const dynamic = "force-dynamic";

const FORGOT_ERROR: Record<string, string> = {
  throttled: "Too many attempts. Please wait a minute and try again.",
};

const inputCls =
  "w-full rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm text-foreground " +
  "placeholder:text-muted-foreground outline-none transition-colors focus:border-[var(--cb-ember)] " +
  "focus:ring-2 focus:ring-[var(--cb-ember)]/25";

export default async function ForgotPasswordPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const sent = sp.sent === "1";
  const errorCode = typeof sp.error === "string" ? sp.error : "";
  const errorMsg = errorCode ? (FORGOT_ERROR[errorCode] ?? "Something went wrong — try again.") : "";

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
          Reset your password
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Enter your account email and we&apos;ll send you a link to choose a new password.
        </p>

        {sent ? (
          <div
            role="status"
            className="mt-6 rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm text-foreground"
          >
            If that email has an account, a reset link is on its way.
            {process.env.NODE_ENV !== "production" ? (
              <span className="mt-1 block text-muted-foreground">
                Dev note: no email provider is configured — the link is printed in the server
                console.
              </span>
            ) : null}
          </div>
        ) : null}

        {errorMsg ? (
          <div
            role="alert"
            className="mt-6 rounded-lg border border-[var(--negative)]/40 bg-[var(--negative)]/10 px-3.5 py-2.5 text-sm text-foreground"
          >
            {errorMsg}
          </div>
        ) : null}

        <form action={requestPasswordReset} className="mt-6 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="email" className="text-xs font-medium text-muted-foreground">
              Email
            </label>
            <input id="email" name="email" type="email" required autoComplete="email" className={inputCls} />
          </div>

          <Button type="submit" className="mt-1 w-full justify-center">
            Send reset link
          </Button>
        </form>

        <p className="mt-6 text-sm text-muted-foreground">
          Remembered it?{" "}
          <Link href="/signin" className="font-medium text-[var(--cb-ember-text)] hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
