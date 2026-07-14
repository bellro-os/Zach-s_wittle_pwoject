/**
 * Request-size guard for the JSON POST routes (launch security review 2026-07).
 *
 * Next.js route handlers have NO default body-size limit, and the production
 * edge in front of the app (Railway's proxy for the launch deploy) exposes no
 * user-configurable request-size cap — so this app-layer gate is the PRIMARY
 * control, not a convenience. Without it, `await req.json()` on an unbounded
 * body is a free memory-pressure lever. Every legitimate compbird payload is
 * tiny (the largest — a 50-item portfolio run of 200-char addresses — is well
 * under 64 KB), so anything approaching a megabyte is garbage by construction.
 *
 * Best-effort by design: the check reads the Content-Length header, which
 * browsers and every standard HTTP client always send for a sized body. A
 * chunked request without the header still lands in `req.json()`'s parse (and
 * the per-field caps in validate.ts). On a proxy that CAN cap bodies (the
 * legacy Caddy stack: `request_body max_size`) add the backstop there too.
 * Pure module — no server-only import — so it unit-tests under plain tsx.
 */

/** 1 MB — orders of magnitude above any legitimate compbird JSON payload. */
export const MAX_JSON_BODY_BYTES = 1_000_000;

/**
 * True when the declared Content-Length exceeds the cap → respond 413 before
 * reading the body. Absent/malformed header ⇒ false (never block a legitimate
 * request over a missing header).
 */
export function bodyTooLarge(
  req: { headers: { get(name: string): string | null } },
  maxBytes: number = MAX_JSON_BODY_BYTES,
): boolean {
  const raw = req.headers.get("content-length");
  if (!raw) return false;
  const n = Number(raw);
  return Number.isFinite(n) && n > maxBytes;
}

/** Shared 413 body so the four JSON routes answer identically. */
export const BODY_TOO_LARGE_RESPONSE = {
  ok: false as const,
  error: "Request body too large.",
};
