import Link from "next/link";
import { cn } from "@/lib/utils/cn";

/**
 * compbird server-safe primitives (no hooks → usable in server components).
 * Client-only motion lives in ./motion.tsx. All colors are token-driven so the
 * same component reads correctly on the paper and instrument surfaces.
 */

/* ── Section scaffold ──────────────────────────────────────────────────────── */
export function SectionShell({
  children,
  className,
  width = "default",
  id,
}: {
  children: React.ReactNode;
  className?: string;
  width?: "default" | "wide" | "narrow";
  id?: string;
}) {
  const max =
    width === "wide" ? "max-w-7xl" : width === "narrow" ? "max-w-3xl" : "max-w-6xl";
  return (
    <section id={id} className={cn("relative px-5 sm:px-8", className)}>
      <div className={cn("mx-auto w-full", max)}>{children}</div>
    </section>
  );
}

/* ── Eyebrow (uppercase micro-label, optional ember tick) ──────────────────── */
export function Eyebrow({
  children,
  className,
  tick = true,
}: {
  children: React.ReactNode;
  className?: string;
  tick?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      {tick ? <span className="h-px w-7 bg-[var(--cb-ember)]" aria-hidden /> : null}
      <span className="cb-eyebrow text-[var(--cb-ember-text)]">{children}</span>
    </span>
  );
}

/* ── Pill / tag ────────────────────────────────────────────────────────────── */
export function Pill({
  children,
  className,
  tone = "neutral",
}: {
  children: React.ReactNode;
  className?: string;
  tone?: "neutral" | "ember" | "positive" | "negative";
}) {
  const tones = {
    neutral: "border-border bg-secondary/60 text-muted-foreground",
    ember: "border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] text-[var(--cb-ember-text)]",
    positive: "border-[var(--positive)]/30 bg-[var(--positive-tint)] text-[var(--positive)]",
    negative: "border-[var(--negative)]/30 bg-[var(--negative-tint)] text-[var(--negative)]",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ── Button (anchor / link / button) ───────────────────────────────────────── */
type ButtonProps = {
  children: React.ReactNode;
  href?: string;
  variant?: "primary" | "ghost" | "quiet";
  size?: "sm" | "md" | "lg";
  className?: string;
  type?: "button" | "submit";
  onClick?: () => void;
  disabled?: boolean;
  arrow?: boolean;
};

function buttonClasses(variant: string, size: string, className?: string) {
  const sizes: Record<string, string> = {
    sm: "px-3.5 py-2 text-[0.8rem]",
    md: "px-5 py-2.5 text-sm",
    lg: "px-6 py-3 text-[0.95rem]",
  };
  const variants: Record<string, string> = {
    primary:
      "bg-[var(--cb-ember)] text-[var(--cb-on-ember)] shadow-[0_8px_30px_-8px_var(--cb-glow)] hover:bg-[var(--cb-ember-deep)] hover:shadow-[0_12px_40px_-8px_var(--cb-glow)]",
    ghost:
      "border border-border bg-card/60 text-foreground backdrop-blur hover:border-[var(--cb-ember)]/40 hover:bg-card",
    quiet:
      "text-muted-foreground hover:text-foreground",
  };
  return cn(
    "group inline-flex select-none items-center justify-center gap-2 rounded-full font-semibold transition-all duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)] disabled:cursor-not-allowed disabled:opacity-50",
    sizes[size],
    variants[variant],
    className,
  );
}

function Arrow() {
  return (
    <svg
      className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5"
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
  );
}

export function Button({
  children,
  href,
  variant = "primary",
  size = "md",
  className,
  type = "button",
  onClick,
  disabled,
  arrow = false,
}: ButtonProps) {
  const cls = buttonClasses(variant, size, className);
  const inner = (
    <>
      {children}
      {arrow ? <Arrow /> : null}
    </>
  );
  if (href) {
    const external = href.startsWith("http") || href.startsWith("#");
    if (external) {
      return (
        <a href={href} className={cls}>
          {inner}
        </a>
      );
    }
    return (
      <Link href={href} className={cls}>
        {inner}
      </Link>
    );
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={cls}>
      {inner}
    </button>
  );
}

/* ── Card ──────────────────────────────────────────────────────────────────── */
export function Card({
  children,
  className,
  as: As = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "div" | "article" | "li";
}) {
  return (
    <As
      className={cn(
        "rounded-2xl border border-border bg-card/80 backdrop-blur-sm",
        className,
      )}
    >
      {children}
    </As>
  );
}

/* ── Stat (label + mono figure + optional delta) ───────────────────────────── */
export function Stat({
  label,
  value,
  delta,
  deltaTone = "positive",
  className,
}: {
  label: string;
  value: React.ReactNode;
  delta?: string;
  deltaTone?: "positive" | "negative" | "neutral";
  className?: string;
}) {
  const tone =
    deltaTone === "positive"
      ? "text-[var(--positive)]"
      : deltaTone === "negative"
        ? "text-[var(--negative)]"
        : "text-muted-foreground";
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="cb-eyebrow text-muted-foreground">{label}</span>
      <span className="font-data text-2xl font-medium tracking-tight text-foreground">
        {value}
      </span>
      {delta ? <span className={cn("font-data text-xs", tone)}>{delta}</span> : null}
    </div>
  );
}

/* ── Tick rule (ember section marker) ──────────────────────────────────────── */
export function TickRule({ className }: { className?: string }) {
  return <div className={cn("cb-tick", className)} aria-hidden />;
}

/* ── Grain overlay (drop into a relative parent) ───────────────────────────── */
export function GrainOverlay({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("pointer-events-none absolute inset-0 cb-grain", className)}
    />
  );
}

/* ── Marquee (CSS-driven, server-safe) ─────────────────────────────────────── */
export function Marquee({
  items,
  className,
}: {
  items: string[];
  className?: string;
}) {
  const doubled = [...items, ...items];
  return (
    <div
      className={cn("group relative flex overflow-hidden", className)}
      role="img"
      aria-label={items.join(", ")}
    >
      <div
        className="cb-marquee-track flex shrink-0 items-center gap-10 pr-10"
        data-cb-anim
        aria-hidden
      >
        {doubled.map((it, i) => (
          <span
            key={i}
            className="flex items-center gap-10 whitespace-nowrap text-sm font-medium text-muted-foreground"
          >
            {it}
            <span className="h-1 w-1 rounded-full bg-[var(--cb-ember)]/60" aria-hidden />
          </span>
        ))}
      </div>
    </div>
  );
}
