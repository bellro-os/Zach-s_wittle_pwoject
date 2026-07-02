import { Marquee } from "@/components/compbird/ui";
import { Reveal } from "@/components/compbird/motion";

/**
 * TrustStrip — a slim data-provenance band that sits directly under the hero on
 * the paper surface. Not a section in its own right: a quiet credibility strip
 * (thin border-y, py-6) that names what the number is built on. The lead line
 * stacks above the source marquee on mobile and sits beside it from `lg` up.
 */

const SOURCES = [
  "Statewide MLS",
  "133 Virginia jurisdictions",
  "Statewide assessor parcels",
  "Recorded deed history",
  "Geocoded comps",
  "Hourly MLS sync",
  "Daily county refresh",
];

export function TrustStrip() {
  return (
    <div className="relative border-y border-border bg-background">
      <Reveal>
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-5 py-6 sm:px-8 lg:flex-row lg:items-center lg:gap-10">
          {/* lead — sits above the marquee on mobile, beside it on desktop */}
          <p className="shrink-0 text-sm leading-snug text-muted-foreground lg:max-w-xs">
            The number is only as good as the data behind it.
          </p>

          {/* fade-edged marquee of sources; ember dot separators come from <Marquee> */}
          <div
            className="relative min-w-0 flex-1"
            style={{
              WebkitMaskImage:
                "linear-gradient(to right, transparent, black 4%, black 96%, transparent)",
              maskImage:
                "linear-gradient(to right, transparent, black 4%, black 96%, transparent)",
            }}
          >
            <Marquee items={SOURCES} />
          </div>
        </div>
      </Reveal>
    </div>
  );
}
