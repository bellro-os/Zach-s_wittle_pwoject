import Link from "next/link";
import { Wordmark } from "./brand";
import { TickRule } from "./ui";

// The monitored support inbox. Env-overridable so the compbird-branded inbox can
// be swapped in without a code change once it exists; the fallback is the parent
// company's monitored inbox (mail must never dead-end).
const CONTACT_EMAIL =
  process.env.NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL?.trim() || "hello@ratifyly.com";

const COLUMNS: { title: string; links: { label: string; href: string }[] }[] = [
  {
    title: "Product",
    links: [
      { label: "Comp studio", href: "/comps" },
      { label: "Pricing", href: "/pricing" },
      { label: "Market reports", href: "/#markets" },
      { label: "Accuracy", href: "/#accuracy" },
      { label: "Coverage", href: "/#coverage" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "How it works", href: "/#how" },
      { label: "Terms", href: "/terms" },
      { label: "Privacy", href: "/privacy" },
      { label: "Contact", href: `mailto:${CONTACT_EMAIL}` },
    ],
  },
];

export function Footer() {
  return (
    <footer className="relative mt-28 border-t border-border px-5 pb-12 pt-16 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-12 md:flex-row md:justify-between">
          <div className="max-w-sm">
            <Wordmark />
            <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
              A bird&rsquo;s-eye view of what every home is really worth — appraisal-grade
              comparables and live neighborhood market reports, in seconds.
            </p>
            <Link
              href="/comps"
              className="mt-6 inline-flex items-center gap-2 rounded-md text-sm font-semibold text-[var(--cb-ember-text)] hover:text-[var(--cb-ember-deep)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--cb-ember)]"
            >
              Price a property
              <span aria-hidden>→</span>
            </Link>
          </div>

          <div className="grid grid-cols-2 gap-12 sm:gap-20">
            {COLUMNS.map((col) => (
              <div key={col.title}>
                <span className="cb-eyebrow text-muted-foreground">{col.title}</span>
                <ul className="mt-4 space-y-3">
                  {col.links.map((l) => (
                    <li key={l.label}>
                      <Link
                        href={l.href}
                        className="rounded-md text-sm text-foreground/80 transition-colors hover:text-[var(--cb-ember-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
                      >
                        {l.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <TickRule className="mt-14" />
        <div className="mt-6 flex flex-col gap-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>© {2026} compbird · Built on statewide assessor parcels and live MLS.</p>
          <p className="max-w-md sm:text-right">
            Estimates are model-driven opinions of value — not appraisals.
          </p>
        </div>
      </div>
    </footer>
  );
}
