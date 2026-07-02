import { SectionShell, Eyebrow, Card, Pill } from "@/components/compbird/ui";
import { Reveal } from "@/components/compbird/motion";
import { RadialGauge } from "@/components/charts";
import { SAMPLE_PROFILE } from "@/lib/compbird/sample";
import { usd, pct, stripTags } from "@/lib/compbird/format";

/**
 * The flagship "extreme accuracy" section. Three independent valuation methods
 * are drawn as horizontal bars converging on a shared price scale; the consensus
 * line is the visible picture of triangulation. The tighter the methods cluster,
 * the higher the confidence — surfaced as a divergence readout + dial.
 */

const v = SAMPLE_PROFILE.valuation;

/* Scale endpoints come straight from the valuation range so bar lengths and the
   consensus line all share one domain. A little headroom keeps figures off the edge. */
const LOW = v?.low ?? 0;
const HIGH = v?.high ?? 0;
const MID = v?.mid ?? 0;
const FLOOR = LOW - (HIGH - LOW) * 0.18;
const CEIL = HIGH + (HIGH - LOW) * 0.18;
const SPAN = CEIL - FLOOR || 1;

/** Map a dollar value to a 0–100 position on the shared scale. */
function posOf(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 50;
  return Math.max(4, Math.min(96, ((value - FLOOR) / SPAN) * 100));
}

const methods = v?.methods ?? [];
const divergence = v?.divergence_pct ?? null;

/* Confidence inverts divergence: a tight (<= 5%) spread reads as high agreement.
   The dial stays in a believable 0–100 band even if divergence climbs. */
const confidence =
  divergence == null ? 90 : Math.max(40, Math.min(99, Math.round(100 - divergence * 4)));
const confidenceLabel =
  confidence >= 80 ? "high confidence" : confidence >= 62 ? "moderate" : "wide";

const beats: { n: string; title: string; body: string }[] = [
  {
    n: "01",
    title: "The comps are chosen, not scraped",
    body: "Candidates are ranked on distance, structure, recency, and condition — then atypical and distressed sales are flagged out before a single number is drawn. Six survivors, not sixty look-alikes.",
  },
  {
    n: "02",
    title: "Three methods, run independently",
    body: "A direct comp-plus-acreage adjustment, a straight $/sqft read, and an acreage-residual model each estimate the home on their own terms. No method gets to see the others, so they can't quietly agree.",
  },
  {
    n: "03",
    title: "Their spread is the confidence",
    body: "When three separate roads arrive at nearly the same address, the estimate holds. The gap between the high and low method becomes a published divergence — tight spread, high confidence.",
  },
];

const consensusPos = posOf(MID);

export function Accuracy() {
  return (
    <SectionShell id="accuracy" className="py-24 sm:py-32">
      <Reveal>
        <Eyebrow>Why the number holds up</Eyebrow>
      </Reveal>
      <Reveal delay={0.05}>
        <h2 className="font-display mt-6 max-w-3xl text-4xl font-bold tracking-tight text-foreground text-balance sm:text-5xl">
          Every estimate is triangulated, not guessed.
        </h2>
      </Reveal>
      <Reveal delay={0.1}>
        <p className="mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground text-balance">
          A single model can be confidently wrong. compbird locates value the way a
          careful appraiser does — by cross-reference, and by showing its work.
        </p>
      </Reveal>

      <div className="mt-14 grid items-start gap-10 lg:mt-16 lg:grid-cols-2 lg:gap-14">
        {/* ── LEFT: the three beats ── */}
        <ol className="flex flex-col">
          {beats.map((b, i) => (
            <li
              key={b.n}
              className={
                i === 0 ? "pb-8" : "border-t border-border py-8 last:pb-0"
              }
            >
              <Reveal delay={0.12 + i * 0.08}>
                <div className="flex gap-5">
                  <span
                    className="font-data mt-0.5 shrink-0 text-sm font-medium tabular-nums text-[var(--cb-ember-text)]"
                    aria-hidden
                  >
                    {b.n}
                  </span>
                  <div>
                    <h3 className="font-display text-xl font-semibold tracking-tight text-foreground">
                      {b.title}
                    </h3>
                    <p className="mt-2 max-w-md leading-relaxed text-muted-foreground">
                      {b.body}
                    </p>
                  </div>
                </div>
              </Reveal>
            </li>
          ))}
        </ol>

        {/* ── RIGHT: the convergence card ── */}
        <Reveal delay={0.18} y={32}>
          <Card className="overflow-hidden p-6 sm:p-7">
            <div className="flex items-start justify-between gap-4">
              <div>
                <span className="cb-eyebrow text-muted-foreground">Triangulated estimate</span>
                <h3 className="font-display mt-1.5 text-2xl font-semibold tracking-tight text-foreground">
                  How {usd(MID)} was derived
                </h3>
              </div>
              <Pill tone="neutral" className="shrink-0">
                {pct(divergence)} spread · {confidenceLabel}
              </Pill>
            </div>

            {/* convergence visual: three bars on a shared scale meeting at consensus */}
            <div
              className="relative mt-7 pt-10"
              role="img"
              aria-label={`Three valuation methods converging near ${usd(MID)} with a ${pct(divergence)} spread`}
            >
              {/* consensus line — the value all three methods bracket */}
              <div
                className="pointer-events-none absolute bottom-7 top-10 z-10 w-px bg-[var(--cb-ember)]"
                style={{ left: `${consensusPos}%` }}
                aria-hidden
              >
                <span className="absolute -top-2 left-1/2 h-2 w-2 -translate-x-1/2 rotate-45 bg-[var(--cb-ember)]" />
                <span className="absolute -top-8 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] px-2 py-0.5 font-data text-[0.7rem] font-medium text-[var(--cb-ember-text)]">
                  {usd(MID)}
                </span>
              </div>

              <div className="flex flex-col gap-5">
                {methods.map((m) => {
                  const p = posOf(m.value);
                  const fromLeft = p >= consensusPos;
                  return (
                    <div key={m.name}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-sm font-medium text-foreground">{m.name}</span>
                        <span className="font-data text-sm font-semibold tabular-nums text-foreground">
                          {usd(m.value)}
                        </span>
                      </div>

                      {/* the bar reaches from the scale floor toward its method value;
                          the dot lands on the value, near the consensus line */}
                      <div className="relative mt-2 h-2 rounded-full bg-secondary/60">
                        <div
                          className="absolute inset-y-0 left-0 rounded-full bg-foreground/25"
                          style={{ width: `${p}%` }}
                          aria-hidden
                        />
                        <span
                          className="absolute top-1/2 z-20 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--card)] bg-[var(--cb-ember)] shadow-[0_0_0_3px_var(--cb-tint)]"
                          style={{ left: `${p}%` }}
                          aria-hidden
                        />
                      </div>

                      <p
                        className={
                          "mt-2 max-w-[88%] text-xs leading-relaxed text-muted-foreground " +
                          (fromLeft ? "" : "ml-auto text-right")
                        }
                      >
                        {stripTags(m.rationale)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* confidence readout */}
            <div className="mt-7 flex items-center gap-5 border-t border-border pt-6">
              <RadialGauge
                value={confidence}
                size={88}
                color="var(--cb-ember)"
                label="agreement"
              />
              <div>
                <p className="text-sm leading-relaxed text-foreground">
                  Low divergence across independent methods.
                </p>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  The methods land within {pct(divergence)} of one another — a tight
                  cluster the engine reports as a high-confidence estimate.
                </p>
              </div>
            </div>
          </Card>
        </Reveal>
      </div>
    </SectionShell>
  );
}
