import { Eyebrow, GrainOverlay } from "@/components/compbird/ui";
import { Reveal, MagneticButton } from "@/components/compbird/motion";
import { AerialMap, pointsFromProfile } from "@/components/compbird/graphics";
import { SAMPLE_PROFILE } from "@/lib/compbird/sample";
import { usd, ppsf, pct } from "@/lib/compbird/format";

const v = SAMPLE_PROFILE.valuation;
const f = SAMPLE_PROFILE.facts;

export function Hero() {
  return (
    <section className="relative overflow-hidden px-5 pb-20 pt-10 sm:px-8 sm:pb-28">
      <GrainOverlay className="opacity-[0.35]" />
      {/* ember glow bleed top-right */}
      <div
        aria-hidden
        className="cb-glow-ring pointer-events-none absolute -right-40 -top-40 h-[34rem] w-[34rem] opacity-70"
      />

      <div className="relative mx-auto grid max-w-6xl items-center gap-14 lg:grid-cols-[1.05fr_0.95fr]">
        {/* ── copy ── */}
        <div className="cb-grid relative">
          <Reveal>
            <Eyebrow>Instant CMAs for real estate agents</Eyebrow>
          </Reveal>
          <Reveal delay={0.05}>
            <h1 className="font-display mt-6 text-[2.35rem] font-bold leading-[1.07] tracking-tight text-foreground text-balance sm:text-6xl sm:leading-[1.02]">
              A bird&rsquo;s-eye view of what every home is{" "}
              <span className="text-[var(--cb-ember-text)]">really worth.</span>
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground text-balance">
              compbird builds appraisal-grade comparables and live neighborhood market
              reports in seconds — from statewide assessor parcels joined to live
              listings, not a guess.
            </p>
          </Reveal>

          <Reveal delay={0.18}>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <MagneticButton href="/comps">Price a property</MagneticButton>
              <a
                href="/comps?demo=1"
                className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-6 py-3 text-[0.95rem] font-semibold text-foreground backdrop-blur transition-all duration-300 hover:border-[var(--cb-ember)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
              >
                See a sample report
              </a>
            </div>
          </Reveal>

          <Reveal delay={0.22}>
            <p className="mt-4 text-sm text-muted-foreground">
              Free account · instant value estimates · no card required.{" "}
              <span className="text-muted-foreground">
                Pro unlocks every comp and the full market read — $20/mo.
              </span>
            </p>
          </Reveal>

          <Reveal delay={0.26}>
            <dl className="mt-12 grid max-w-lg grid-cols-1 gap-5 border-t border-border pt-7 min-[420px]:grid-cols-3 min-[420px]:gap-6">
              {[
                { k: "Statewide", v: "assessor parcels" },
                { k: "~2s", v: "to six comps" },
                { k: "5 methods", v: "cross-checked" },
              ].map((s) => (
                <div key={s.v}>
                  <dt className="font-data text-2xl font-medium text-foreground">{s.k}</dt>
                  <dd className="mt-1 text-xs leading-snug text-muted-foreground">{s.v}</dd>
                </div>
              ))}
            </dl>
          </Reveal>

          <Reveal delay={0.3}>
            <p className="mt-6 max-w-lg text-xs leading-relaxed text-muted-foreground">
              Estimates are model-driven opinions of value — not appraisals.
            </p>
          </Reveal>
        </div>

        {/* ── aerial visual ── */}
        <Reveal delay={0.15} y={32}>
          <div className="relative">
            <AerialMap points={pointsFromProfile(SAMPLE_PROFILE)} height={420} />

            {/* floating valuation card */}
            <div className="absolute bottom-4 left-4 right-4 rounded-xl border border-border bg-card/90 p-4 backdrop-blur-md sm:left-4 sm:right-auto sm:w-72">
              <div className="flex items-center justify-between">
                <span className="cb-eyebrow text-muted-foreground">Estimated value</span>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card/60 px-2 py-0.5 text-[0.7rem] font-medium text-muted-foreground">
                  {pct(v?.divergence_pct)} spread
                </span>
              </div>
              <div className="font-data mt-1 text-3xl font-semibold tracking-tight text-foreground">
                {usd(v?.mid)}
              </div>
              <div className="mt-1.5 font-data text-xs text-muted-foreground">
                {usd(v?.low)} – {usd(v?.high)} · {ppsf(v?.comp_ppsf)}/sqft
              </div>
              <div className="mt-3 truncate border-t border-border pt-2 text-xs text-muted-foreground">
                {f?.address}
              </div>
            </div>

            {/* legend */}
            <div className="absolute right-4 top-4 flex items-center gap-3 rounded-full border border-border bg-card/85 px-3 py-1.5 text-[0.7rem] text-muted-foreground backdrop-blur">
              <span className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-[var(--cb-ember)]" /> Subject
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-foreground/70" /> Comps
              </span>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
