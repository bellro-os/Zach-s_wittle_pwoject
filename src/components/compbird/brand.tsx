import { cn } from "@/lib/utils/cn";

/**
 * compbird wordmark + mark.
 *
 * The mark is a "comp pin": a value marker dropped from a bird's-eye view, with
 * a soaring gull knocked out of its face. It reads two ways on purpose — a bird
 * in flight AND a map pin / valuation marker — which is exactly what compbird
 * does (an appraisal-grade comp, located from above).
 *
 * Construction is deliberately two-color and surface-aware:
 *   • the pin body is the ember (var(--cb-ember), or currentColor when ember=false)
 *   • the bird is punched out with var(--background), so it inverts cleanly on
 *     paper AND the dark Instrument surface with no extra props.
 *
 * Geometry lives on a tidy 32x32 box, mirror-symmetric about x=16, so optical
 * weight is even and the silhouette stays crisp from 24px (nav) up to footer
 * scale. Pure SVG, no runtime deps.
 */

/**
 * Default mark — comp pin with a soaring gull knocked out. The pin is a clean
 * teardrop (full-round shoulders, point at bottom); the bird is one continuous
 * wing-stroke so the negative space holds together at nav scale.
 */
function PinGull({ fill }: { fill: string }) {
  return (
    <>
      {/* Pin / teardrop body: round top, drawn-out point at the bottom. */}
      <path
        d="M16 2.5
           C 9.65 2.5 4.5 7.5 4.5 13.7
           C 4.5 21.2 13.2 27.2 15.3 29.2
           C 15.7 29.6 16.3 29.6 16.7 29.2
           C 18.8 27.2 27.5 21.2 27.5 13.7
           C 27.5 7.5 22.35 2.5 16 2.5
           Z"
        fill={fill}
      />
      {/* Soaring gull, knocked out with the surface color so it reads on
          paper and on the dark Instrument surface alike. Mirror-symmetric
          about x=16: outer wings sweep up, inner crook drops to the body. */}
      <path
        d="M16 17.6
           C 14.9 14.9 13 13.6 10.3 13.7
           C 8.9 13.75 7.7 13.2 6.7 12.0
           C 8.2 15.1 10.7 16.7 14 16.7
           C 12.2 17.6 11.1 19.2 10.7 21.5
           C 12.6 19.7 14.4 19.4 16 20.6
           C 17.6 19.4 19.4 19.7 21.3 21.5
           C 20.9 19.2 19.8 17.6 18 16.7
           C 21.3 16.7 23.8 15.1 25.3 12.0
           C 24.3 13.2 23.1 13.75 21.7 13.7
           C 19 13.6 17.1 14.9 16 17.6
           Z"
        fill="var(--background)"
      />
    </>
  );
}

/**
 * Alternate mark (internal) — an upswept gull with a tucked body and a small
 * tail point, no surrounding pin. Kept as a reusable variant for spots that
 * want a lighter, frameless bird. Not exported; promote here if ever needed.
 */
function UpsweptGull({ fill }: { fill: string }) {
  return (
    <>
      <path
        d="M16 6.2
           C 15 6.2 14.2 7 14 8.2
           C 13.4 11.7 11.6 13.9 8.6 14.7
           C 6.6 15.2 4.7 15.1 2.8 14.5
           C 5.2 17 8 18.4 11.2 18.8
           C 12.9 19 14 20.4 14.2 22.8
           L 16 27
           L 17.8 22.8
           C 18 20.4 19.1 19 20.8 18.8
           C 24 18.4 26.8 17 29.2 14.5
           C 27.3 15.1 25.4 15.2 23.4 14.7
           C 20.4 13.9 18.6 11.7 18 8.2
           C 17.8 7 17 6.2 16 6.2
           Z"
        fill={fill}
      />
      {/* comp-pin eye */}
      <circle cx="16" cy="10.8" r="1.5" fill="var(--background)" />
    </>
  );
}

export function CompbirdMark({
  className,
  ember = true,
  variant = "pin",
}: {
  className?: string;
  /** Fill the bird in ember (default). When false, uses currentColor. */
  ember?: boolean;
  /**
   * "pin" (default) — comp pin with a knocked-out gull (the primary mark).
   * "gull" — frameless upswept bird for lighter, badge-free placements.
   */
  variant?: "pin" | "gull";
}) {
  const fill = ember ? "var(--cb-ember)" : "currentColor";
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={cn("h-7 w-7", className)}
      role="img"
      aria-label="compbird"
    >
      {variant === "gull" ? <UpsweptGull fill={fill} /> : <PinGull fill={fill} />}
    </svg>
  );
}

export function Wordmark({
  className,
  markClassName,
  showMark = true,
}: {
  className?: string;
  markClassName?: string;
  showMark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      {showMark ? <CompbirdMark className={markClassName} /> : null}
      <span className="font-display text-[1.35rem] font-bold leading-none tracking-tight text-foreground">
        compbird
      </span>
    </span>
  );
}
