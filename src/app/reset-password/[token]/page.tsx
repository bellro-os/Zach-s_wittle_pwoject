import Link from "next/link";
import type { Metadata } from "next";
import { Wordmark } from "@/components/compbird/brand";
import { Button, GrainOverlay } from "@/components/compbird/ui";
import { resetPassword } from "@/actions/auth";

export const metadata: Metadata = {
  title: "Choose a new password", // layout template appends "· compbird"
  description: "Choose a new password for your compbird account.",
};

export const dynamic = "force-dynamic";

const RESET_ERROR: Record<string, string> = {
  weak: "Password must be at least 8 characters.",
  mismatch: "Those passwords don't match.",
};

const inputCls =
  "w-full rounded-lg border border-border bg-card px-3.5 py-2.5 text-sm text-foreground " +
  "placeholder:text-muted-foreground outline-none transition-colors focus:border-[var(--cb-ember)] " +
  "focus:ring-2 focus:ring-[var(--cb-ember)]/25";

export default async function ResetPasswordPage({
  params,
  searchParams,
}: {
  params: Promise<{ token: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { token } = await params;
  const sp = await searchParams;
  const errorCode = typeof sp.error === "string" ? sp.error : "";
  const errorMsg = errorCode ? (RESET_ERROR[errorCode] ?? "Something went wrong — try again.") : "";

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
          Choose a new password
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Reset links work once and expire after 15 minutes.
        </p>

        {errorMsg ? (
          <div
            role="alert"
            className="mt-6 rounded-lg border border-[var(--negative)]/40 bg-[var(--negative)]/10 px-3.5 py-2.5 text-sm text-foreground"
          >
            {errorMsg}
          </div>
        ) : null}

        <form action={resetPassword} className="mt-6 flex flex-col gap-4">
          <input type="hidden" name="token" value={token} />

          <div className="flex flex-col gap-1.5">
            <label htmlFor="password" className="text-xs font-medium text-muted-foreground">
              New password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              className={inputCls}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="confirm" className="text-xs font-medium text-muted-foreground">
              Confirm new password
            </label>
            <input
              id="confirm"
              name="confirm"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              className={inputCls}
            />
          </div>

          <Button type="submit" className="mt-1 w-full justify-center">
            Set new password
          </Button>
        </form>

        <p className="mt-6 text-sm text-muted-foreground">
          Link expired?{" "}
          <Link href="/forgot-password" className="font-medium text-[var(--cb-ember-text)] hover:underline">
            Request a new one
          </Link>
        </p>
      </div>
    </div>
  );
}
