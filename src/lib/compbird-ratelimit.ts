// Per-IP rate limiting for the PUBLIC compbird API (`/api/compbird/*`).
//
// The compbird routes are an unauthenticated surface over the same MLS Bot
// engine the gated `/api/cma/*` routes use. Without a throttle, a single client
// could pin the Python spawn pool / warm worker with /generate or /profile calls
// (audit P0 #12). This module adds a lightweight FIXED-WINDOW counter keyed by
// `<surface>:<ipHash>` so each public endpoint gets its own per-IP budget.
//
// It deliberately reuses `getClientIp` from auth-ratelimit so IP extraction is
// consistent with the auth surfaces, but keeps a SEPARATE bucket map and a
// simpler counting model (every request counts) — the auth module's exponential
// lockout semantics are tuned for credential brute-forcing, not API pacing.
//
// Single-process app (see project memory: Docker/local single instance), so an
// in-memory Map is sufficient; counters reset on restart (acceptable).
//
// server-only (node:crypto). Do NOT import from Edge middleware.

import "server-only";
import { createHash } from "node:crypto";
import { getClientIp } from "@/lib/auth-ratelimit";

export { getClientIp };

/** A public compbird endpoint with its own per-IP budget. */
export type CompbirdSurface =
  | "compbird:generate"
  | "compbird:profile"
  | "compbird:preview"
  | "compbird:search"
  | "compbird:pdf"
  | "compbird:markets"
  | "compbird:streetview"
  | "compbird:lead"
  | "compbird:portfolio";

/** Fixed-window budget: at most `max` requests per `windowMs` per IP. */
interface Limit {
  max: number;
  windowMs: number;
}

// ─── default limits (tunable here; comments explain the reasoning) ──────────
//
// These default to sane, conservative values. The heavy endpoints that drive a
// Python spawn / warm-worker call (generate, profile, preview) are strictest;
// the cheap typeahead (search) and the static PDF stream are looser.
const MINUTE = 60 * 1000;

/** generate renders a branded PDF (seconds of CPU + headless Chrome). */
const GENERATE_LIMIT: Limit = { max: 5, windowMs: MINUTE }; // ~5/min/IP
/** profile is a full dossier lookup (warm worker or ~100s spawn). */
const PROFILE_LIMIT: Limit = { max: 10, windowMs: MINUTE }; // ~10/min/IP
/** preview computes a comp set + valuation (no PDF, but still a spawn). */
const PREVIEW_LIMIT: Limit = { max: 15, windowMs: MINUTE }; // ~15/min/IP
/** search is a cheap typeahead (in-Node index fast-path). */
const SEARCH_LIMIT: Limit = { max: 30, windowMs: MINUTE }; // ~30/min/IP
/** pdf streams an already-generated file from disk. */
const PDF_LIMIT: Limit = { max: 30, windowMs: MINUTE }; // ~30/min/IP
/** markets is process-cached (30 min); this only guards the rare cache-miss spawn. */
const MARKETS_LIMIT: Limit = { max: 20, windowMs: MINUTE }; // ~20/min/IP
/** streetview is a cheap, day-cached image proxy (one Google fetch on a miss). */
const STREETVIEW_LIMIT: Limit = { max: 30, windowMs: MINUTE }; // ~30/min/IP
/** lead appends a waitlist email to a file (cheap, but abuse-prone form post). */
const LEAD_LIMIT: Limit = { max: 5, windowMs: MINUTE }; // ~5/min/IP
/** portfolio POST enqueues up to 50 engine valuations per call — strictest budget. */
const PORTFOLIO_LIMIT: Limit = { max: 4, windowMs: MINUTE }; // ~4/min/IP

const LIMITS: Record<CompbirdSurface, Limit> = {
  "compbird:generate": GENERATE_LIMIT,
  "compbird:profile": PROFILE_LIMIT,
  "compbird:preview": PREVIEW_LIMIT,
  "compbird:search": SEARCH_LIMIT,
  "compbird:pdf": PDF_LIMIT,
  "compbird:markets": MARKETS_LIMIT,
  "compbird:streetview": STREETVIEW_LIMIT,
  "compbird:lead": LEAD_LIMIT,
  "compbird:portfolio": PORTFOLIO_LIMIT,
};

interface Window {
  /** Count of requests in the current window. */
  count: number;
  /** Window start timestamp (ms epoch). */
  windowStart: number;
  /** This window's budget length, so the GC sweep knows when it's fully stale. */
  windowMs: number;
}

// Keyed by `<surface>:<ipHash>`. Module-level so it survives across requests in
// the single Node process.
const windows = new Map<string, Window>();

/** Non-reversible IP hash so we never key on a raw address. */
function hashIp(ip: string): string {
  return createHash("sha256").update(ip).digest("hex").slice(0, 16);
}

export interface RateLimitResult {
  /** True when this request should be refused (over budget). */
  limited: boolean;
  /** Seconds until the window resets (only meaningful when limited). */
  retryAfterSeconds: number;
}

// ─── opportunistic GC ───────────────────────────────────────────────────────
// `windows` is unbounded: a public endpoint hit by many distinct IPs (or one
// attacker rotating `x-forwarded-for`) would grow it forever — a slow memory
// leak. A fully-elapsed window is dead weight, so we sweep stale entries at most
// once per minute (cheap, amortized). Deleting during Map iteration is safe.
let lastSweepAt = 0;
function sweepStale(now: number): void {
  if (now - lastSweepAt < MINUTE) return;
  lastSweepAt = now;
  for (const [key, w] of windows) {
    if (now - w.windowStart >= w.windowMs) windows.delete(key);
  }
}

/**
 * Count this request against the per-IP budget for `surface` and report whether
 * it is over the limit. Call ONCE at the top of the route handler. The request
 * is counted whether or not it ends up limited (so a flood keeps the window
 * pinned), matching standard fixed-window behavior.
 */
export function checkRateLimit(surface: CompbirdSurface, ip: string): RateLimitResult {
  const { max, windowMs } = LIMITS[surface];
  const key = `${surface}:${hashIp(ip)}`;
  const now = Date.now();
  sweepStale(now);
  let w = windows.get(key);

  if (!w || now - w.windowStart >= windowMs) {
    // Start a fresh window.
    w = { count: 0, windowStart: now, windowMs };
    windows.set(key, w);
  }

  w.count += 1;
  if (w.count > max) {
    const retryAfterSeconds = Math.max(1, Math.ceil((w.windowStart + windowMs - now) / 1000));
    return { limited: true, retryAfterSeconds };
  }
  return { limited: false, retryAfterSeconds: 0 };
}
