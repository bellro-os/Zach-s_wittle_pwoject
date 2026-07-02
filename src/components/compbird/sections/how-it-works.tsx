import { SectionShell, Eyebrow, Card } from "@/components/compbird/ui";
import { Reveal } from "@/components/compbird/motion";

/**
 * "How it works" — three crisp moves from address to report. Server component
 * (no hooks); renders the client <Reveal> primitive for staggered entrance.
 * Icons are hand-drawn inline line-art, stroke=currentColor at ~28px.
 */

type Step = {
  index: string;
  title: string;
  body: string;
  icon: React.ReactNode;
};

/* ── hand-drawn line-art icons (28px, 1.5 stroke, currentColor) ─────────────── */
function iconProps() {
  return {
    width: 28,
    height: 28,
    viewBox: "0 0 28 28",
    fill: "none" as const,
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

/** 01 — magnifier scanning a parcel grid. */
function SearchIcon() {
  return (
    <svg {...iconProps()}>
      <circle cx="12" cy="12" r="7.5" />
      <path d="M17.4 17.4 23 23" />
      {/* parcel cross-hairs inside the lens */}
      <path d="M12 7.5v9M7.5 12h9" opacity={0.45} />
    </svg>
  );
}

/** 02 — sliders / faders for tuning the comp set. */
function TuneIcon() {
  return (
    <svg {...iconProps()}>
      <path d="M5 8h14M5 14h14M5 20h14" />
      <circle cx="9" cy="8" r="2" fill="var(--background)" />
      <circle cx="16" cy="14" r="2" fill="var(--background)" />
      <circle cx="11" cy="20" r="2" fill="var(--background)" />
    </svg>
  );
}

/** 03 — a document with a fold and ruled lines (the report). */
function ReportIcon() {
  return (
    <svg {...iconProps()}>
      <path d="M7 3.5h8l5 5V24a.5.5 0 0 1-.5.5h-12A.5.5 0 0 1 7 24V4a.5.5 0 0 1 0-.5Z" />
      <path d="M15 3.5V8a1 1 0 0 0 1 1h4" />
      <path d="M10.5 14h7M10.5 18h7M10.5 21.5h4" opacity={0.55} />
    </svg>
  );
}

const STEPS: Step[] = [
  {
    index: "01",
    title: "Search any address",
    body: "Type any Virginia address or parcel — compbird resolves it across live MLS and statewide assessor parcels.",
    icon: <SearchIcon />,
  },
  {
    index: "02",
    title: "Tune the comp set",
    body: "Include or exclude comparables and watch $/sqft and the valuation recompute live, comp by comp.",
    icon: <TuneIcon />,
  },
  {
    index: "03",
    title: "Export the report",
    body: "Generate a clean, branded PDF market report in seconds — ready to share with a client or carry into a listing.",
    icon: <ReportIcon />,
  },
];

export function HowItWorks() {
  return (
    <SectionShell id="how" className="py-24 sm:py-32">
      <Reveal>
        <Eyebrow>How it works</Eyebrow>
      </Reveal>
      <Reveal delay={0.05}>
        <h2 className="font-display mt-6 max-w-2xl text-4xl font-bold tracking-tight text-foreground text-balance sm:text-5xl">
          From address to report in three moves.
        </h2>
      </Reveal>

      <ol className="mt-14 grid gap-5 sm:mt-16 md:grid-cols-3">
        {STEPS.map((step, i) => (
          <li key={step.index} className="h-full">
            <Reveal delay={0.1 + i * 0.08} className="h-full">
              <Card className="group relative flex h-full flex-col gap-6 p-6 transition-colors duration-300 hover:border-[var(--cb-ember)]/40 sm:p-7">
                <div className="flex items-center justify-between">
                  <span
                    className="text-[var(--cb-ember)] grid h-12 w-12 place-items-center rounded-xl border border-[var(--cb-ember)]/25 bg-[var(--cb-tint)] transition-transform duration-300 group-hover:-translate-y-0.5"
                    aria-hidden
                  >
                    {step.icon}
                  </span>
                  <span className="font-data text-sm font-semibold tracking-[0.18em] text-[var(--cb-ember-text)]">
                    {step.index}
                  </span>
                </div>

                <div className="flex flex-col gap-2.5">
                  <h3 className="font-display text-xl font-semibold tracking-tight text-foreground">
                    {step.title}
                  </h3>
                  <p className="text-[0.95rem] leading-relaxed text-muted-foreground text-balance">
                    {step.body}
                  </p>
                </div>

                {/* hairline tick at the foot — subtle ember rhythm */}
                <span
                  aria-hidden
                  className="mt-auto h-px w-10 bg-[var(--cb-ember)]/40 transition-all duration-300 group-hover:w-16"
                />
              </Card>
            </Reveal>
          </li>
        ))}
      </ol>
    </SectionShell>
  );
}
