import { SectionShell, Eyebrow } from "@/components/compbird/ui";
import { Reveal, SpotlightCard } from "@/components/compbird/motion";
import { AerialMap, pointsFromProfile } from "@/components/compbird/graphics";
import { SAMPLE_PROFILE } from "@/lib/compbird/sample";
import { cn } from "@/lib/utils/cn";

/**
 * compbird — feature bento. Asymmetric tiles on a 3-col grid (one lead tile spans
 * two columns and two rows). Each tile is a SpotlightCard carrying a small,
 * hand-drawn line-art mark (currentColor + ember, no fills) so the grid reads as
 * a boutique instrument panel rather than a generic SaaS feature list.
 */

/* ── Line-art marks (stroke-only, ~28px, inherit currentColor) ──────────────── */

type MarkProps = { className?: string };

/** Three stacked comp cards aligned to a baseline — similarity-ranked stack. */
function MarkComparables({ className }: MarkProps) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={className} aria-hidden>
      <g stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
        <rect x="6.5" y="20" width="12" height="22" rx="1.6" />
        <rect x="18.5" y="13" width="12" height="29" rx="1.6" />
        <rect x="30.5" y="25" width="11" height="17" rx="1.6" />
      </g>
      {/* the subject baseline + the chosen comp, marked in ember */}
      <path
        d="M4 42h40"
        stroke="var(--cb-ember)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="24.5" cy="13" r="2.4" fill="var(--cb-ember)" />
      <path
        d="M11 14.5l3.2 3.2 4.6-6"
        stroke="var(--cb-ember)"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      />
    </svg>
  );
}

/** Tag with a per-square-foot tick — live unit price. */
function MarkPpsf({ className }: MarkProps) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={className} aria-hidden>
      <g stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
        <path d="M7 24.5 24 7.5h17v17L24 41.5 7 24.5Z" />
        <path d="M19 19.5h10M19 28.5h10M24 16v16" opacity="0.6" />
      </g>
      <circle cx="34" cy="14" r="2.2" fill="var(--cb-ember)" />
    </svg>
  );
}

/** Scatter of points with one outlier pulled aside — atypical-sale flag. */
function MarkAtypical({ className }: MarkProps) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={className} aria-hidden>
      <path
        d="M6 38 14 30l7 5 8-12"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g fill="currentColor">
        <circle cx="14" cy="30" r="2" />
        <circle cx="21" cy="35" r="2" />
        <circle cx="29" cy="23" r="2" />
      </g>
      {/* the flagged outlier, ringed in the negative tone */}
      <circle cx="38" cy="11" r="3" stroke="var(--negative)" strokeWidth="1.6" />
      <path
        d="M38 8.4v2.6M38 13.4h.01"
        stroke="var(--negative)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Document with a folded corner + bird mark — branded PDF. */
function MarkReport({ className }: MarkProps) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={className} aria-hidden>
      <g stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
        <path d="M12 6h17l8 8v28H12V6Z" />
        <path d="M29 6v8h8" />
        <path d="M17 26h14M17 32h10" opacity="0.6" strokeLinecap="round" />
      </g>
      {/* ember masthead tick */}
      <path d="M17 20h9" stroke="var(--cb-ember)" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/** Calendar leaf with a refresh arc — hourly MLS + daily county refresh. */
function MarkRefresh({ className }: MarkProps) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={className} aria-hidden>
      <g stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
        <rect x="8" y="11" width="32" height="29" rx="2.5" />
        <path d="M8 18h32" opacity="0.7" />
        <path d="M16 8v6M32 8v6" />
      </g>
      <path
        d="M30 30a6 6 0 1 1-1.8-4.3"
        stroke="var(--cb-ember)"
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M28.5 22.5v3.4h-3.4"
        stroke="var(--cb-ember)"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

/** State outline with a dropped pin — statewide coverage. */
function MarkCoverage({ className }: MarkProps) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={className} aria-hidden>
      <path
        d="M7 16l9-3 8 3 9-2 7 4-2 13-7 4-9-3-8 3-7-3 0-16Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M27 19c-3 0-5.4 2.4-5.4 5.4 0 3.7 5.4 8.6 5.4 8.6s5.4-4.9 5.4-8.6C32.4 21.4 30 19 27 19Z"
        stroke="var(--cb-ember)"
        strokeWidth="1.6"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="27" cy="24.4" r="1.9" fill="var(--cb-ember)" />
    </svg>
  );
}

/* ── Tile ───────────────────────────────────────────────────────────────────── */

interface Feature {
  title: string;
  body: string;
  Mark: (p: MarkProps) => React.ReactElement;
  span: string;
  /** Lead tile gets larger type + a faint contour wash. */
  lead?: boolean;
}

const FEATURES: Feature[] = [
  {
    title: "Appraisal-grade comparables",
    body: "Every comp is ranked by true similarity — size, age, lot, distance and recency — then weighted, not cherry-picked. Six defensible sales, located in about a second, the way an appraiser would choose them.",
    Mark: MarkComparables,
    span: "sm:col-span-2 lg:row-span-2",
    lead: true,
  },
  {
    title: "Live price-per-sqft",
    body: "The neighborhood unit price, recomputed as sales close — never a quarter behind.",
    Mark: MarkPpsf,
    span: "",
  },
  {
    title: "Atypical-sale detection",
    body: "Auctions, distress and off-market outliers are flagged and down-weighted, so they inform the number without dragging it.",
    Mark: MarkAtypical,
    span: "",
  },
  {
    title: "Branded PDF reports",
    body: "Export a clean, presentation-ready dossier under your own name — figures, comps and the map, on one page.",
    Mark: MarkReport,
    span: "sm:col-span-2 lg:col-span-1",
  },
  {
    title: "Freshly synced data",
    body: "MLS listings re-sync hourly and county records refresh daily, so the value you defend is current — never a quarter behind.",
    Mark: MarkRefresh,
    span: "",
  },
  {
    title: "Statewide coverage",
    body: "One graph spanning every Virginia jurisdiction — statewide assessor parcels joined to live listings.",
    Mark: MarkCoverage,
    span: "",
  },
];

function Tile({ feature, index }: { feature: Feature; index: number }) {
  const { title, body, Mark, span, lead } = feature;
  return (
    <Reveal delay={Math.min(index, 4) * 0.06} className={cn("h-full", span)}>
      <SpotlightCard className="group relative flex h-full flex-col overflow-hidden p-6 sm:p-7">
        {lead ? (
          <span
            aria-hidden
            className="pointer-events-none absolute -right-10 -top-10 h-44 w-44 rounded-full bg-[var(--cb-tint)] blur-2xl"
          />
        ) : null}

        <span
          className={cn(
            "relative inline-flex items-center justify-center rounded-xl border border-border bg-background/40 text-foreground transition-colors duration-300 group-hover:border-[var(--cb-ember)]/40 group-hover:text-foreground",
            lead ? "h-14 w-14" : "h-12 w-12",
          )}
        >
          <Mark className={cn(lead ? "h-8 w-8" : "h-7 w-7")} />
        </span>

        <h3
          className={cn(
            "font-display relative mt-6 font-semibold tracking-tight text-foreground",
            lead ? "text-2xl sm:text-[1.7rem]" : "text-lg",
          )}
        >
          {title}
        </h3>
        <p
          className={cn(
            "relative mt-2.5 text-muted-foreground text-pretty",
            lead ? "max-w-md text-base leading-relaxed" : "text-sm leading-relaxed",
          )}
        >
          {body}
        </p>

        {lead ? (
          <>
            {/* the claim, pictured: subject + six ranked comps on the brand's
                aerial motif — static and purely decorative */}
            <div aria-hidden className="pointer-events-none relative mt-auto pt-7">
              <AerialMap
                points={pointsFromProfile(SAMPLE_PROFILE)}
                height={216}
                animate={false}
              />
            </div>
            <span className="relative mt-5 block">
              <span className="cb-eyebrow text-[var(--cb-ember-text)]">
                Similarity-ranked, recency-weighted
              </span>
            </span>
          </>
        ) : null}
      </SpotlightCard>
    </Reveal>
  );
}

/* ── Section ─────────────────────────────────────────────────────────────────── */

export function FeaturesBento() {
  return (
    <SectionShell className="py-24 sm:py-32" id="features">
      <Reveal>
        <Eyebrow>Built for precision</Eyebrow>
      </Reveal>
      <Reveal delay={0.06}>
        <h2 className="font-display mt-6 max-w-2xl text-4xl font-bold tracking-tight text-foreground text-balance sm:text-5xl">
          Everything you need to defend a number.
        </h2>
      </Reveal>

      <div className="mt-14 grid grid-cols-1 gap-4 sm:grid-cols-2 sm:gap-5 lg:grid-cols-3">
        {FEATURES.map((feature, i) => (
          <Tile key={feature.title} feature={feature} index={i} />
        ))}
      </div>
    </SectionShell>
  );
}
