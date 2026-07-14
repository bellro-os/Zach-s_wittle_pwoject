/**
 * Decorative-animation governor — "decorative animations must idle".
 *
 * compbird's ambient loops (the aerial-map scanline sweep, the subject-pin
 * radar pulse, the trust-strip/coverage marquees — everything tagged
 * `[data-cb-anim]` / `.cb-marquee-track`) are pure atmosphere: they carry no
 * information, so there is no reason to burn compositor frames when nobody is
 * watching. This module stamps `data-cb-anim-paused` on <html> whenever
 *
 *   1. the tab is hidden (visibilitychange), or
 *   2. the user has gone ~30s without any input,
 *
 * and lifts it again on the next interaction / return to the tab. A CSS rule
 * in compbird.css turns the attribute into `animation-play-state: paused` for
 * the decorative selectors ONLY — activity-tied motion (loading spinners,
 * skeleton shimmer, the recompute pulse) is untagged and never governed, and
 * `prefers-reduced-motion` handling is separate (a media query that sets
 * `animation: none` on the same selectors, which this attribute can't undo).
 *
 * The governor is deliberately DOM-agnostic (it takes a structural
 * `GovernorDocument`) so its state machine is unit-testable under plain Node:
 *
 *   npx tsx src/lib/compbird/idle-animations.test.ts
 *
 * Mounted once for the whole app by <AnimationGovernor /> in the root layout.
 */

/** Attribute stamped on <html> while decorative loops should hold their frame. */
export const ANIM_PAUSED_ATTR = "data-cb-anim-paused";

/** Settle decorative loops after this long without user input. */
export const IDLE_AFTER_MS = 30_000;

/** Any of these counts as "someone is actually looking at the page". */
export const ACTIVITY_EVENTS = [
  "pointermove",
  "pointerdown",
  "keydown",
  "wheel",
  "touchstart",
  "scroll",
] as const;

/**
 * The slice of `Document` the governor touches — `document` satisfies it
 * structurally; tests hand in a fake.
 */
export interface GovernorDocument {
  readonly hidden: boolean;
  readonly documentElement: {
    setAttribute(name: string, value: string): void;
    removeAttribute(name: string): void;
  };
  addEventListener(type: string, listener: () => void, options?: AddEventListenerOptions): void;
  removeEventListener(type: string, listener: () => void, options?: EventListenerOptions): void;
}

// Capture-phase + passive: scroll doesn't bubble from inner scrollers, and
// none of these listeners may ever block the interaction they observe.
const LISTEN: AddEventListenerOptions = { passive: true, capture: true };

/**
 * Start governing. Returns a cleanup that removes every listener, cancels the
 * idle timer, and lifts the pause attribute (used as a React effect cleanup).
 */
export function startAnimationGovernor(
  doc: GovernorDocument,
  idleAfterMs: number = IDLE_AFTER_MS,
): () => void {
  let idle = false;
  let pausedNow = false; // mirror of the attribute — apply() only touches the DOM on change
  let timer: ReturnType<typeof setTimeout> | null = null;

  const apply = () => {
    const shouldPause = doc.hidden || idle;
    if (shouldPause === pausedNow) return;
    pausedNow = shouldPause;
    if (shouldPause) doc.documentElement.setAttribute(ANIM_PAUSED_ATTR, "");
    else doc.documentElement.removeAttribute(ANIM_PAUSED_ATTR);
  };

  const armIdleTimer = () => {
    if (timer != null) clearTimeout(timer);
    timer = setTimeout(() => {
      idle = true;
      apply();
    }, idleAfterMs);
  };

  const onActivity = () => {
    idle = false;
    apply(); // resume immediately (no-op unless the paused state actually flips)
    armIdleTimer();
  };

  const onVisibilityChange = () => {
    if (doc.hidden) {
      // Pause now and stop the idle clock — hidden time isn't idle time.
      if (timer != null) clearTimeout(timer);
      timer = null;
      apply();
    } else {
      // Coming back to the tab counts as interaction.
      onActivity();
    }
  };

  doc.addEventListener("visibilitychange", onVisibilityChange);
  for (const type of ACTIVITY_EVENTS) doc.addEventListener(type, onActivity, LISTEN);
  armIdleTimer();
  apply();

  return () => {
    if (timer != null) clearTimeout(timer);
    timer = null;
    doc.removeEventListener("visibilitychange", onVisibilityChange);
    for (const type of ACTIVITY_EVENTS) doc.removeEventListener(type, onActivity, LISTEN);
    doc.documentElement.removeAttribute(ANIM_PAUSED_ATTR);
  };
}
