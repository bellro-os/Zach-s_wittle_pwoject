import { Eyebrow, SectionShell } from "@/components/compbird/ui";
import { Reveal, MagneticButton } from "@/components/compbird/motion";
import { ContourField } from "@/components/compbird/graphics";

/**
 * FinalCTA — the closing band. Deliberately NOT a second hero: a dark "instrument"
 * panel with a left-aligned, declarative finale paired with topographic terrain
 * (no ember headline word, no glow-ring + grain echo) that sends people straight
 * into the comp studio.
 */
export function FinalCTA() {
  return (
    <SectionShell className="py-24 sm:py-32" width="wide">
      <Reveal y={32}>
        <div className="cb-dark relative isolate overflow-hidden rounded-3xl border border-border bg-background px-6 py-20 sm:px-12 sm:py-24">
          {/* sole background treatment: topographic terrain, bled to the right —
              distinct from the glow-ring + grain on the other dark panels */}
          <ContourField className="opacity-[0.22] [mask-image:linear-gradient(to_left,black,transparent_72%)]" />

          {/* a single ember sightline rule — the accent, used as a fill, not a word */}
          <span
            aria-hidden
            className="absolute left-0 top-0 h-full w-1 bg-[var(--cb-ember)]/70"
          />

          <div className="relative grid items-center gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:gap-14">
            {/* ── left-aligned, declarative copy ── */}
            <div className="max-w-2xl">
              <Eyebrow>Price with confidence</Eyebrow>

              <h2 className="font-display mt-6 text-4xl font-bold leading-[1.04] tracking-tight text-foreground text-balance sm:text-[3.4rem]">
                Stop guessing. Start defending the number.
              </h2>

              <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground text-balance">
                Type an address and watch six appraisal-grade comps plot themselves —
                a defensible value range, the $/sqft math, and the neighborhood read,
                all from the property graph.
              </p>

              <div className="mt-10 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
                <MagneticButton href="/comps">Price a property</MagneticButton>
                <a
                  href="/comps?demo=1"
                  className="inline-flex items-center gap-2 rounded-full px-4 py-3 text-[0.95rem] font-semibold text-muted-foreground transition-colors duration-300 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
                >
                  See a sample report
                  <svg
                    className="h-4 w-4"
                    viewBox="0 0 16 16"
                    fill="none"
                    aria-hidden
                  >
                    <path
                      d="M3 8h10m0 0L9 4m4 4-4 4"
                      stroke="currentColor"
                      strokeWidth="1.7"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </a>
              </div>
            </div>

            {/* ── a single declarative figure, right of the copy ── */}
            <div className="hidden lg:block">
              <p className="font-display text-right text-[5.5rem] font-bold leading-none tracking-tight text-foreground/90">
                ~2s
              </p>
              <p className="mt-2 text-right text-sm leading-snug text-muted-foreground">
                from address to six comps and a defensible value range.
              </p>
            </div>
          </div>
        </div>
      </Reveal>
    </SectionShell>
  );
}
