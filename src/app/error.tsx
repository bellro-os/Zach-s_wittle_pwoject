"use client";

import { useEffect } from "react";
import { Wordmark } from "@/components/compbird/brand";
import { Button, GrainOverlay } from "@/components/compbird/ui";

/**
 * Route-segment error boundary for the whole app. A plain client component —
 * no server imports — styled to match the compbird paper surface.
 *
 * NEXT_PUBLIC_ env vars are inlined at build time, so reading it directly here
 * is safe in a client component; the fallback covers unset local builds.
 */
const CONTACT_EMAIL =
  process.env.NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL || "hello@ratifyly.com";

export default function CompbirdError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="cb-shell-paper relative min-h-screen overflow-hidden bg-background text-foreground">
      <GrainOverlay className="opacity-[0.25]" />
      <div
        aria-hidden
        className="cb-glow-ring pointer-events-none absolute -right-40 -top-48 h-[34rem] w-[34rem] opacity-40"
      />
      <div className="relative mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-5 py-12 sm:px-6">
        <a href="/" aria-label="compbird home" className="mb-8 inline-flex">
          <Wordmark />
        </a>

        <h1 className="font-display text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
          Something broke mid-flight.
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          An unexpected error interrupted the report. Your work is safe — retry,
          or head back to the studio.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button onClick={reset}>Try again</Button>
          <Button href="/comps" variant="ghost">
            Back to the studio
          </Button>
        </div>

        <p className="mt-6 text-xs text-muted-foreground">
          Still stuck?{" "}
          <a
            href={`mailto:${CONTACT_EMAIL}`}
            className="font-medium text-[var(--cb-ember-text)] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            {CONTACT_EMAIL}
          </a>
        </p>
      </div>
    </div>
  );
}
