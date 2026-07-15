/**
 * The ONE post-auth redirect allowlist — shared by /join, /signin and the auth
 * server actions so the admitted targets can never drift apart again (the old
 * per-file copies disagreed: the action still only admitted /comps, so a
 * portfolio-intent signup silently landed in /comps).
 *
 * Admits INTERNAL app paths only: /comps (with an optional suffix segment),
 * /portfolio, /account. Everything else — absolute URLs, protocol-relative
 * "//host", paths carrying a query — falls back to "/comps", so there is no
 * open redirect and callers may safely append their own querystring
 * (e.g. the ?signedup=1 conversion marker).
 *
 * Edge-safe: pure string logic, no Node imports.
 */
export function safeAuthRedirect(raw: string | string[] | undefined): string {
  const v = typeof raw === "string" ? raw.trim() : "";
  return /^\/(?:comps(?:\/[A-Za-z0-9._~-]*)?|portfolio|account)$/.test(v) ? v : "/comps";
}
