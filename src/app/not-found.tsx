import Link from "next/link";
import type { Metadata } from "next";
import { Wordmark } from "@/components/compbird/brand";
import { Button, GrainOverlay } from "@/components/compbird/ui";

export const metadata: Metadata = {
  title: "Page not found", // layout template appends "· compbird"
};

export default function CompbirdNotFound() {
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
          404 — off the map.
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          That address doesn&apos;t resolve. Try the studio or head home.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button href="/comps">Open the studio</Button>
          <Button href="/" variant="ghost">
            Go home
          </Button>
        </div>
      </div>
    </div>
  );
}
