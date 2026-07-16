/**
 * The ONE post-auth redirect allowlist — shared by /join, /signin and the auth
 * server actions so the admitted targets can never drift apart again (the old
 * per-file copies disagreed: the action still only admitted /comps, so a
 * portfolio-intent signup silently landed in /comps).
 *
 * Admits INTERNAL app paths only: /home, /comps (with an optional suffix
 * segment), /portfolio, /account. Everything else — absolute URLs,
 * protocol-relative "//host" — falls back to "/home", so there is no open
 * redirect. The no-param DEFAULT is /home (the signed-in hub); an EXPLICIT
 * whitelisted target (e.g. /comps?address=…) is still honored verbatim, so the
 * address-first arrival intent lands on the priced report, not the hub.
 *
 * A query string is allowed but SANITIZED, not passed through: only the
 * whitelisted arrival-intent keys (demo / address / parcelId / intent)
 * survive, values are control-char-stripped and capped, and the result is
 * re-encoded deterministically (fixed key order via URLSearchParams). This is
 * what lets ?demo=1 and ?address= deep links survive the proxy's auth
 * bounce. Fragments are dropped.
 *
 * NOTE: the returned path may now CARRY a query — callers appending their own
 * marker (e.g. the ?signedup=1 conversion event) must use
 * withAuthRedirectParam() below instead of blindly appending "?".
 *
 * Edge-safe: pure string logic + URLSearchParams, no Node imports.
 */

const ALLOWED_PATH = /^\/(?:home|comps(?:\/[A-Za-z0-9._~-]*)?|portfolio|account)$/;

/** Arrival-intent params allowed to ride through the auth wall. */
const ALLOWED_QUERY_KEYS = ["demo", "address", "parcelId", "intent"] as const;

/** Hard cap on any single surviving query value. */
const MAX_QUERY_VALUE_LENGTH = 120;

/** Strip C0 control chars + DEL from a query value, then cap its length. */
function cleanQueryValue(value: string): string {
  let out = "";
  for (const ch of value) {
    const code = ch.charCodeAt(0);
    if (code < 0x20 || code === 0x7f) continue;
    out += ch;
    if (out.length >= MAX_QUERY_VALUE_LENGTH) break;
  }
  return out;
}

export function safeAuthRedirect(raw: string | string[] | undefined): string {
  const v = typeof raw === "string" ? raw.trim() : "";
  // Fragments never round-trip through a redirect param — drop them outright.
  const hashIdx = v.indexOf("#");
  const noHash = hashIdx === -1 ? v : v.slice(0, hashIdx);

  const qIdx = noHash.indexOf("?");
  const path = qIdx === -1 ? noHash : noHash.slice(0, qIdx);
  if (!ALLOWED_PATH.test(path)) return "/home";
  if (qIdx === -1) return path;

  const params = new URLSearchParams(noHash.slice(qIdx + 1));
  const kept = new URLSearchParams();
  for (const key of ALLOWED_QUERY_KEYS) {
    const value = params.get(key);
    if (value === null) continue;
    const clean = cleanQueryValue(value);
    if (clean) kept.set(key, clean);
  }
  const qs = kept.toString();
  return qs ? `${path}?${qs}` : path;
}

/**
 * Append a marker param (e.g. signedup=1) to a safeAuthRedirect() result
 * without clobbering a query it may already carry: "?" when bare, "&" when
 * the sanitized intent query survived.
 */
export function withAuthRedirectParam(target: string, key: string, value: string): string {
  const sep = target.includes("?") ? "&" : "?";
  return `${target}${sep}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}
