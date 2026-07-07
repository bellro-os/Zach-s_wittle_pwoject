import { SectionShell, Eyebrow, GrainOverlay } from "@/components/compbird/ui";
import { Reveal, CountUp } from "@/components/compbird/motion";
import { ContourField } from "@/components/compbird/graphics";
import { CoverageTabs } from "./coverage-tabs";

/**
 * Coverage — depth-first footprint. Statewide assessor parcels joined to live
 * MLS where it runs deep; MLS syncs hourly and county records refresh daily.
 * Dark "instrument" stat slab + a marquee of the Virginia jurisdictions the
 * engine already reads.
 */

/* Big stats. Numeric ones animate via CountUp; non-numeric render as plain
   mono figures so the row stays visually consistent. */
const STATS: Array<
  | { kind: "num"; to: number; prefix?: string; suffix?: string; label: string }
  | { kind: "text"; value: string; label: string }
> = [
  { kind: "num", to: 133, label: "Virginia jurisdictions mapped" },
  { kind: "num", to: 9, suffix: "+", label: "jurisdictions live on deep MLS" },
  { kind: "text", value: "Hourly", label: "MLS sync · daily county refresh" },
  { kind: "text", value: "Statewide", label: "assessor parcels" },
];

/* Real Virginia places the graph already covers — New River Valley core out to
   the metros, west → east. The static fallback marquee when the live feed is
   unavailable. */
const PLACES = [
  "Blacksburg",
  "Roanoke",
  "Christiansburg",
  "Radford",
  "Salem",
  "Montgomery County",
  "Floyd",
  "Pulaski",
  "Giles",
  "Wytheville",
  "Abingdon",
  "Bristol",
  "Lynchburg",
  "Charlottesville",
  "Richmond",
  "Fairfax",
  "Loudoun",
  "Arlington",
  "Alexandria",
  "Virginia Beach",
  "Norfolk",
];

/* Expansion markets in rollout order — the COMING NEXT tab. Deep-MLS rings out
   from the New River Valley core; these are roadmap, never claimed as live. */
const COMING_NEXT = [
  "Wytheville",
  "Abingdon",
  "Bristol",
  "Lynchburg",
  "Charlottesville",
  "Richmond",
  "Fairfax",
  "Loudoun",
  "Arlington",
  "Alexandria",
  "Virginia Beach",
  "Norfolk",
];

export function Coverage() {
  return (
    <SectionShell id="coverage" className="py-24 sm:py-32" width="wide">
      <div className="grid gap-14 lg:grid-cols-[0.92fr_1.08fr] lg:items-end">
        {/* ── lede ── */}
        <div>
          <Reveal>
            <Eyebrow>Coverage</Eyebrow>
          </Reveal>
          <Reveal delay={0.05}>
            <h2 className="font-display mt-6 text-4xl font-bold tracking-tight text-foreground text-balance sm:text-5xl">
              Built on Virginia. Expanding out.
            </h2>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground text-balance">
              We went deep before we went wide. The parcel graph spans all 133
              Virginia jurisdictions — every lot joined to its county or city assessor
              record, so a valuation knows the structure, the last deed, and the street
              it sits on, not just an address.
            </p>
          </Reveal>
          <Reveal delay={0.18}>
            <p className="mt-5 max-w-xl leading-relaxed text-muted-foreground">
              Deep live MLS runs in about nine jurisdictions today — the New River
              Valley core — and widens as each market&rsquo;s feed comes online.
              Recorded closed sales from public records back the comp pool across
              130 Virginia and D.C. localities, so rural valuations lean on nearby
              sales even before a market&rsquo;s feed lands. Listings sync hourly and
              county records refresh daily.
            </p>
          </Reveal>
        </div>

        {/* ── dark stat slab ── */}
        <Reveal delay={0.1} y={32}>
          <div className="cb-dark relative overflow-hidden rounded-3xl border border-border bg-card p-8 sm:p-10">
            {/* contour = the section's LEAD tile only (rule in compbird.css) */}
            <ContourField className="cb-contour-accent" />
            <GrainOverlay className="opacity-30" />
            {/* ember glow bleed — section accent = the named medium stop */}
            <div
              aria-hidden
              className="cb-glow-ring pointer-events-none absolute -right-28 -top-28 h-72 w-72 opacity-[var(--cb-glow-medium)]"
            />

            <div className="relative">
              <span className="cb-eyebrow text-muted-foreground">
                The footprint, in figures
              </span>

              <dl className="mt-7 grid grid-cols-2 gap-x-6 gap-y-9 sm:gap-y-10">
                {STATS.map((s, i) => (
                  <Reveal key={s.label} delay={0.14 + i * 0.08}>
                    <div>
                      <dt className="font-data text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
                        {s.kind === "num" ? (
                          <CountUp
                            to={s.to}
                            prefix={s.prefix}
                            suffix={s.suffix}
                            duration={1.6}
                          />
                        ) : (
                          <span className="font-data tabular-nums">{s.value}</span>
                        )}
                      </dt>
                      <dd className="mt-2 text-sm leading-snug text-muted-foreground">
                        {s.label}
                      </dd>
                    </div>
                  </Reveal>
                ))}
              </dl>

              <p className="mt-9 border-t border-border pt-5 text-sm leading-relaxed text-muted-foreground">
                Coverage is the constraint, not the claim — a market is only live here
                once its MLS and parcel layers are fully joined and verified.
              </p>
            </div>
          </div>
        </Reveal>
      </div>

      {/* ── coverage footprint: LIVE NOW vs COMING NEXT (static marquee until
             the live feed answers — see CoverageTabs) ── */}
      <Reveal delay={0.12}>
        <div className="mt-16 sm:mt-20">
          <CoverageTabs places={PLACES} coming={COMING_NEXT} />
        </div>
      </Reveal>
    </SectionShell>
  );
}
