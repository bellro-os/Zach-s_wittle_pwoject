// Login throttling for the auth surfaces (shared-password sign-in and the
// client portal access-code login).
//
// Design:
//  - In-memory attempt counter keyed by `<surface>:<ipHash>`. The app runs as a
//    single instance (see project memory: Docker/local single process), so an
//    in-memory Map is sufficient and avoids a DB round-trip on every attempt.
//  - Sliding lockout with exponential backoff: after FREE_ATTEMPTS failures in
//    the window, each further failure extends a lockout whose duration grows
//    with the number of failures (capped). A SUCCESSFUL login clears the bucket.
//  - The caller never learns *which* factor failed — these helpers only answer
//    "are you currently throttled" and "record an outcome". The throttle message
//    is intentionally generic.
//
// This module is server-only (uses node:crypto). Do NOT import it from the Edge
// middleware.

import { createHash } from "node:crypto";
import { headers } from "next/headers";

/** Failures allowed inside the window before lockouts start. */
const FREE_ATTEMPTS = 5;
/** Rolling window for counting failures (ms). */
const WINDOW_MS = 15 * 60 * 1000; // 15 minutes
/** Base lockout once free attempts are exhausted (ms). */
const BASE_LOCKOUT_MS = 30 * 1000; // 30 seconds
/** Hard cap on a single lockout (ms). */
const MAX_LOCKOUT_MS = 15 * 60 * 1000; // 15 minutes

interface Bucket {
  /** Count of failures within the current window. */
  failures: number;
  /** Timestamp of the first failure in the current window (ms epoch). */
  windowStart: number;
  /** Locked until this timestamp (ms epoch); 0 when not locked. */
  lockedUntil: number;
}

// Keyed by `<surface>:<ipHash>`. Module-level so it survives across requests
// within the single Node process. Reset on server restart (acceptable).
const buckets = new Map<string, Bucket>();

/** Identifies a login surface for separate counters. */
export type AuthSurface = "login" | "portal" | "signup";

/**
 * Hash the client IP so we never persist or key on a raw address. Cheap,
 * non-reversible, and stable for a given IP within the process lifetime.
 */
function hashIp(ip: string): string {
  return createHash("sha256").update(ip).digest("hex").slice(0, 16);
}

/**
 * Best-effort client IP from request headers. Falls back to a constant so that
 * a missing/forged header still throttles (shared bucket) rather than bypassing.
 *
 * Trust model: we sit behind a Caddy reverse proxy that terminates every public
 * request. A client can send ARBITRARY `x-forwarded-for` AND `x-real-ip` header
 * values — both reach us verbatim unless our edge overwrites them. The ONLY value
 * we can trust is the hop OUR proxy appends: Caddy appends the real peer address
 * as the LAST (right-most) entry of `x-forwarded-for`. Any header value a client
 * supplies (including a forged `x-real-ip`, or extra left-most `x-forwarded-for`
 * entries) is attacker-controlled and trivially rotated to defeat a per-IP
 * throttle, so we must NOT key on it.
 *
 * Therefore:
 *   1. Take the LAST (right-most) entry of `x-forwarded-for` — the address Caddy
 *      actually saw and appended. This is the trusted proxy position.
 *   2. Only if `x-forwarded-for` is absent entirely (e.g. a non-proxied local
 *      request) fall back to `x-real-ip`.
 * Never trust the FIRST x-forwarded-for entry, and never prefer a raw,
 * client-settable `x-real-ip` over the proxy-appended hop.
 */
export async function getClientIp(): Promise<string> {
  try {
    const h = await headers();
    const xff = h.get("x-forwarded-for");
    if (xff) {
      const parts = xff
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean);
      const last = parts[parts.length - 1];
      if (last) return last;
    }
    // No XFF at all — not proxied (or a misconfigured edge). x-real-ip is the
    // best remaining signal; it is only reachable when XFF is absent.
    const real = h.get("x-real-ip");
    if (real?.trim()) return real.trim();
  } catch {
    // headers() throws outside a request scope — fall through to the constant.
  }
  return "unknown";
}

function bucketKey(surface: AuthSurface, ip: string): string {
  return `${surface}:${hashIp(ip)}`;
}

/** Lockout duration for the Nth failure past the free allotment (exponential, capped). */
function lockoutFor(failures: number): number {
  const over = Math.max(0, failures - FREE_ATTEMPTS);
  const ms = BASE_LOCKOUT_MS * 2 ** Math.max(0, over - 1);
  return Math.min(ms, MAX_LOCKOUT_MS);
}

export interface ThrottleState {
  /** True when the caller should be refused right now. */
  limited: boolean;
  /** Seconds until the caller may retry (only meaningful when limited). */
  retryAfterSeconds: number;
}

/**
 * Check (without mutating failure counts) whether this surface+IP is currently
 * locked out. Call this BEFORE doing the credential comparison.
 */
export function checkThrottle(surface: AuthSurface, ip: string): ThrottleState {
  const key = bucketKey(surface, ip);
  const b = buckets.get(key);
  const now = Date.now();
  if (!b) return { limited: false, retryAfterSeconds: 0 };

  // Window expired with no active lockout -> reset.
  if (b.lockedUntil <= now && now - b.windowStart > WINDOW_MS) {
    buckets.delete(key);
    return { limited: false, retryAfterSeconds: 0 };
  }
  if (b.lockedUntil > now) {
    return { limited: true, retryAfterSeconds: Math.ceil((b.lockedUntil - now) / 1000) };
  }
  return { limited: false, retryAfterSeconds: 0 };
}

/**
 * Record a FAILED login. Increments the windowed failure count and, once the
 * free allotment is exhausted, (re)arms an exponentially-growing lockout.
 * Returns the resulting throttle state so the caller can surface a retry hint.
 */
export function recordFailure(surface: AuthSurface, ip: string): ThrottleState {
  const key = bucketKey(surface, ip);
  const now = Date.now();
  let b = buckets.get(key);

  // Start a fresh window if none exists or the prior one fully elapsed.
  if (!b || (b.lockedUntil <= now && now - b.windowStart > WINDOW_MS)) {
    b = { failures: 0, windowStart: now, lockedUntil: 0 };
    buckets.set(key, b);
  }

  b.failures += 1;
  if (b.failures > FREE_ATTEMPTS) {
    const lock = lockoutFor(b.failures);
    b.lockedUntil = now + lock;
    return { limited: true, retryAfterSeconds: Math.ceil(lock / 1000) };
  }
  return { limited: false, retryAfterSeconds: 0 };
}

/** Record a SUCCESSFUL login — clears the bucket for this surface+IP. */
export function recordSuccess(surface: AuthSurface, ip: string): void {
  buckets.delete(bucketKey(surface, ip));
}

// --- Second throttle dimension --------------------------------------------
//
// The IP-keyed throttle above is defeated by IP rotation. These helpers add
// orthogonal buckets keyed by an arbitrary string so a single account can't be
// brute-forced (per-email login throttle) and signup can't be mass-abused
// (coarse global cap) regardless of how many source IPs an attacker uses.
//
// They reuse the SAME bucket store and exponential-backoff math; the only
// difference is the key is a caller-supplied literal instead of `<surface>:<ip>`.
// Suggested keys:
//   - "login:email:<lowercased-email>"  (per-account login attempts)
//   - "signup:global"                   (all signups, one shared window)

/** Check whether an arbitrary throttle key is currently locked out. */
export function checkThrottleKey(key: string): ThrottleState {
  const b = buckets.get(key);
  const now = Date.now();
  if (!b) return { limited: false, retryAfterSeconds: 0 };

  if (b.lockedUntil <= now && now - b.windowStart > WINDOW_MS) {
    buckets.delete(key);
    return { limited: false, retryAfterSeconds: 0 };
  }
  if (b.lockedUntil > now) {
    return { limited: true, retryAfterSeconds: Math.ceil((b.lockedUntil - now) / 1000) };
  }
  return { limited: false, retryAfterSeconds: 0 };
}

/** Record a FAILED attempt against an arbitrary throttle key. */
export function recordFailureKey(key: string): ThrottleState {
  const now = Date.now();
  let b = buckets.get(key);

  if (!b || (b.lockedUntil <= now && now - b.windowStart > WINDOW_MS)) {
    b = { failures: 0, windowStart: now, lockedUntil: 0 };
    buckets.set(key, b);
  }

  b.failures += 1;
  if (b.failures > FREE_ATTEMPTS) {
    const lock = lockoutFor(b.failures);
    b.lockedUntil = now + lock;
    return { limited: true, retryAfterSeconds: Math.ceil(lock / 1000) };
  }
  return { limited: false, retryAfterSeconds: 0 };
}

/** Clear an arbitrary throttle key (e.g. on a successful login for that email). */
export function recordSuccessKey(key: string): void {
  buckets.delete(key);
}

/** Build the per-email login throttle key. */
export function loginEmailKey(email: string): string {
  return `login:email:${email.trim().toLowerCase()}`;
}

// --- Coarse global signup cap ----------------------------------------------
//
// A flat rolling counter of ALL signup attempts (success or failure) across the
// whole process, independent of source IP. This is a circuit-breaker against
// mass account creation when an attacker rotates IPs; it is deliberately set
// well above any plausible legitimate burst so normal sign-ups are never hit.

/** Total signup attempts permitted in the global window before refusing. */
const SIGNUP_GLOBAL_MAX = 30;
/** Rolling window for the global signup counter (ms). */
const SIGNUP_GLOBAL_WINDOW_MS = 10 * 60 * 1000; // 10 minutes

const SIGNUP_GLOBAL_KEY = "signup:global";

/**
 * Check the coarse global signup cap WITHOUT incrementing. Returns limited=true
 * once the rolling window is full. Call before creating an account.
 */
export function checkGlobalSignup(): ThrottleState {
  const b = buckets.get(SIGNUP_GLOBAL_KEY);
  const now = Date.now();
  if (!b) return { limited: false, retryAfterSeconds: 0 };
  if (now - b.windowStart > SIGNUP_GLOBAL_WINDOW_MS) {
    buckets.delete(SIGNUP_GLOBAL_KEY);
    return { limited: false, retryAfterSeconds: 0 };
  }
  if (b.failures >= SIGNUP_GLOBAL_MAX) {
    const retryAfter = Math.ceil((b.windowStart + SIGNUP_GLOBAL_WINDOW_MS - now) / 1000);
    return { limited: true, retryAfterSeconds: Math.max(1, retryAfter) };
  }
  return { limited: false, retryAfterSeconds: 0 };
}

/** Increment the coarse global signup counter (call on every signup attempt). */
export function recordGlobalSignupAttempt(): void {
  const now = Date.now();
  let b = buckets.get(SIGNUP_GLOBAL_KEY);
  if (!b || now - b.windowStart > SIGNUP_GLOBAL_WINDOW_MS) {
    b = { failures: 0, windowStart: now, lockedUntil: 0 };
    buckets.set(SIGNUP_GLOBAL_KEY, b);
  }
  b.failures += 1;
}

/** Human-friendly throttle copy with a rounded retry hint. */
export function throttleMessage(retryAfterSeconds: number): string {
  if (retryAfterSeconds >= 60) {
    const mins = Math.ceil(retryAfterSeconds / 60);
    return `Too many attempts. Please wait about ${mins} minute${mins === 1 ? "" : "s"} and try again.`;
  }
  const secs = Math.max(1, retryAfterSeconds);
  return `Too many attempts. Please wait ${secs} second${secs === 1 ? "" : "s"} and try again.`;
}
