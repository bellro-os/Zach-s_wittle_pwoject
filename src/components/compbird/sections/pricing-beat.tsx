import { SectionShell, Eyebrow, Button } from "@/components/compbird/ui";
import { Reveal } from "@/components/compbird/motion";

/**
 * PricingBeat — the landing arc's one price moment: a slim $0/$20 band between
 * Coverage and FinalCTA, reusing the pricing page's headline. A --cb-tint-band
 * wash, never dark (rhythm rule: Coverage owns the page's single ink slab).
 */
export function PricingBeat() {
  return (
    <SectionShell width="wide">
      <Reveal y={28}>
        <div className="relative overflow-hidden rounded-3xl border border-border bg-card px-6 py-12 sm:px-12 sm:py-14">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-[var(--cb-tint-band)]"
          />
          <div className="relative grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]">
            <div>
              <Eyebrow>Pricing</Eyebrow>
              <h2 className="font-display mt-5 max-w-xl text-3xl font-bold tracking-tight text-foreground text-balance sm:text-4xl">
                The estimate is free. The evidence is $20/mo.
              </h2>
            </div>

            <div className="flex flex-wrap items-center gap-x-10 gap-y-6 lg:justify-end">
              <div>
                <p className="font-data text-4xl font-semibold tracking-tight text-foreground">
                  $0
                </p>
                <p className="mt-1.5 max-w-[13rem] text-sm leading-snug text-muted-foreground">
                  Unlimited instant estimates — no card required.
                </p>
              </div>
              <div>
                <p className="font-data text-4xl font-semibold tracking-tight text-foreground">
                  $20
                </p>
                <p className="mt-1.5 max-w-[13rem] text-sm leading-snug text-muted-foreground">
                  Every comp, the market read, and the PDF — monthly.
                </p>
              </div>
              <Button href="/pricing" variant="ghost" arrow>
                See pricing
              </Button>
            </div>
          </div>
        </div>
      </Reveal>
    </SectionShell>
  );
}
