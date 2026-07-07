"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils/cn";
import { Wordmark } from "./brand";

const LINKS = [
  { label: "Accuracy", href: "/#accuracy" },
  { label: "Market reports", href: "/#markets" },
  { label: "How it works", href: "/#how" },
  { label: "Coverage", href: "/#coverage" },
  { label: "Pricing", href: "/pricing" },
];

const focusRing =
  "rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]";

function CtaLink({ className, onClick }: { className?: string; onClick?: () => void }) {
  return (
    <Link
      href="/comps"
      onClick={onClick}
      className={cn(
        "group inline-flex items-center justify-center gap-2 rounded-full bg-[var(--cb-ember)] px-4 py-2 text-sm font-semibold text-[var(--cb-on-ember)] shadow-[0_8px_30px_-10px_var(--cb-glow)] transition-all duration-300 hover:bg-[var(--cb-ember-deep)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
        className,
      )}
    >
      Price a property
      <svg className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M3 8h10m0 0L9 4m4 4-4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </Link>
  );
}

export function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 16);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Keyboard dismissal for the mobile disclosure: Escape closes the panel and
  // hands focus back to the toggle, per the disclosure pattern.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="sticky top-0 z-50 w-full">
      <div
        className={cn(
          "mx-auto flex max-w-6xl items-center justify-between gap-6 px-5 transition-all duration-300 sm:px-8",
          scrolled || open
            ? "my-2 rounded-2xl border border-border bg-card/80 py-2.5 backdrop-blur-xl md:rounded-full"
            : "my-0 border border-transparent py-4",
        )}
      >
        <Link href="/" aria-label="compbird home" className={cn("shrink-0", focusRing)}>
          <Wordmark />
        </Link>

        <nav aria-label="Primary" className="hidden items-center gap-7 md:flex">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className={cn(
                "px-1 py-0.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                focusRing,
              )}
            >
              {l.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          {/* compbird's OWN auth pages (not the host /login|/signup) — both land
              back in the studio after auth, keeping the funnel on-brand. */}
          <Link
            href="/signin?redirect=%2Fcomps"
            className={cn(
              "hidden px-1 py-0.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground md:inline-flex",
              focusRing,
            )}
          >
            Sign in
          </Link>
          <Link
            href="/join?redirect=%2Fcomps"
            className={cn(
              "hidden items-center justify-center rounded-full border border-border bg-card/60 px-4 py-2 text-sm font-semibold text-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground md:inline-flex",
              focusRing,
            )}
          >
            Sign up free
          </Link>
          <CtaLink className="hidden md:inline-flex" />
          {/* mobile disclosure */}
          <button
            ref={menuButtonRef}
            type="button"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="cb-mobile-menu"
            onClick={() => setOpen((v) => !v)}
            className={cn(
              "inline-flex h-10 w-10 items-center justify-center rounded-full border border-border text-foreground md:hidden",
              focusRing,
            )}
          >
            <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden>
              {open ? (
                <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              ) : (
                <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* mobile menu panel */}
      {open ? (
        <div className="px-5 sm:px-8 md:hidden">
          <div
            id="cb-mobile-menu"
            className="mx-auto mt-1 max-w-6xl rounded-2xl border border-border bg-card/95 p-3 backdrop-blur-xl"
          >
            {/* Same "Primary" label is safe: the desktop nav is display:none
                here, so only one primary landmark is exposed at a time. */}
            <nav aria-label="Primary" className="flex flex-col">
              {LINKS.map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "rounded-lg px-3 py-3 text-base font-medium text-foreground transition-colors hover:bg-secondary",
                    focusRing,
                  )}
                >
                  {l.label}
                </a>
              ))}
            </nav>
            <CtaLink className="mt-2 w-full" onClick={() => setOpen(false)} />
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Link
                href="/signin?redirect=%2Fcomps"
                onClick={() => setOpen(false)}
                className={cn(
                  "inline-flex items-center justify-center rounded-full border border-border bg-card/60 px-4 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-secondary",
                  focusRing,
                )}
              >
                Sign in
              </Link>
              <Link
                href="/join?redirect=%2Fcomps"
                onClick={() => setOpen(false)}
                className={cn(
                  "inline-flex items-center justify-center rounded-full border border-border bg-card/60 px-4 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-secondary",
                  focusRing,
                )}
              >
                Sign up free
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
