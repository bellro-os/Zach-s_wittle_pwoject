"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils/cn";

/* Marketing-surface motion primitives. Deliberately framer-motion-FREE: these
   ship on the landing + pricing pages, so they use only IntersectionObserver +
   CSS transitions / rAF (≈42KB of framer stays out of the marketing bundle; the
   studio's valuation-panel still uses framer in its own auth-gated chunk).
   prefers-reduced-motion is honored everywhere. */

// CSS easing that matches the old framer cubic-bezier [0.16, 1, 0.3, 1].
const EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

/* Local replacement for framer's useReducedMotion (SSR-safe: false until mount). */
function usePrefersReducedMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setReduce(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
  return reduce;
}

/* ── Reveal: fade + rise on scroll into view ───────────────────────────────── */
export function Reveal({
  children,
  delay = 0,
  y = 24,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = usePrefersReducedMotion();
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (reduce) {
      setShown(true);
      return;
    }
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setShown(true);
          io.disconnect();
        }
      },
      { rootMargin: "-80px 0px", threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduce]);

  return (
    <div
      ref={ref}
      className={className}
      style={
        reduce
          ? undefined
          : {
              opacity: shown ? 1 : 0,
              transform: shown ? "none" : `translateY(${y}px)`,
              transition: `opacity 0.7s ${EASE} ${delay}s, transform 0.7s ${EASE} ${delay}s`,
              willChange: "opacity, transform",
            }
      }
    >
      {children}
    </div>
  );
}

/* ── CountUp: animate a number when it scrolls into view ────────────────────── */
export function CountUp({
  to,
  prefix = "",
  suffix = "",
  decimals = 0,
  duration = 1.8,
  className,
}: {
  to: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduce = usePrefersReducedMotion();
  const [value, setValue] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduce) {
      setValue(to);
      return;
    }
    let raf = 0;
    let start = 0;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        io.disconnect();
        const step = (ts: number) => {
          if (!start) start = ts;
          const t = Math.min((ts - start) / (duration * 1000), 1);
          // easeOutExpo — visually equivalent to the old [0.16,1,0.3,1] for a counter.
          const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
          setValue(to * eased);
          if (t < 1) raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);
      },
      { rootMargin: "-60px 0px", threshold: 0 },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [reduce, to, duration]);

  return (
    <span ref={ref} className={cn("font-data tabular-nums", className)}>
      {prefix}
      {value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
      {suffix}
    </span>
  );
}

/* ── MagneticButton: cursor-attracted primary CTA ──────────────────────────── */
export function MagneticButton({
  children,
  href,
  className,
  onClick,
}: {
  children: React.ReactNode;
  href?: string;
  className?: string;
  onClick?: () => void;
}) {
  const ref = useRef<HTMLAnchorElement>(null);
  const reduce = usePrefersReducedMotion();

  function onMove(e: React.MouseEvent) {
    if (reduce) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - (r.left + r.width / 2)) * 0.25;
    const y = (e.clientY - (r.top + r.height / 2)) * 0.35;
    el.style.transform = `translate(${x}px, ${y}px)`;
  }
  function reset() {
    const el = ref.current;
    if (el) el.style.transform = "translate(0,0)";
  }

  return (
    <a
      ref={ref}
      href={href}
      onClick={onClick}
      onMouseMove={onMove}
      onMouseLeave={reset}
      className={cn(
        "group inline-flex select-none items-center justify-center gap-2 rounded-full bg-[var(--cb-ember)] px-6 py-3 text-[0.95rem] font-semibold text-[var(--cb-on-ember)] shadow-[0_10px_36px_-8px_var(--cb-glow)] transition-[background,box-shadow] duration-300 will-change-transform hover:bg-[var(--cb-ember-deep)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]",
        className,
      )}
    >
      {children}
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
    </a>
  );
}

/* ── SpotlightCard: ember radial highlight follows the cursor ───────────────── */
export function SpotlightCard({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  }
  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      className={cn(
        "cb-spot rounded-2xl border border-border bg-card/80 backdrop-blur-sm transition-colors duration-300 hover:border-[var(--cb-ember)]/30",
        className,
      )}
    >
      {children}
    </div>
  );
}
