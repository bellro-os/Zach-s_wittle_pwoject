/**
 * Production security-header baseline (launch security review 2026-07, P1).
 * Pure module — imported by next.config.ts (headers()) and unit-tested
 * directly. NO "server-only" import here: next.config runs outside the React
 * server graph and the test runner imports this file under plain tsx.
 *
 * CSP allowances, documented (everything else is 'self'):
 *   - script-src: 'unsafe-inline' — Next.js emits inline bootstrap/RSC-payload
 *     scripts (a nonce pipeline is a follow-up, not a launch blocker);
 *     connect.facebook.net + www.googletagmanager.com — the Meta pixel and
 *     Google Ads gtag loaders (src/components/marketing/pixels.tsx).
 *   - style-src: 'unsafe-inline' — Tailwind/Next inline style tags + Leaflet's
 *     inline positioning styles.
 *   - img-src: *.tile.openstreetmap.org — Leaflet map tiles
 *     (src/components/geo/leaflet-map.tsx); facebook.com/google endpoints —
 *     pixel/conversion beacons; data:/blob: — Leaflet marker icons and inline
 *     SVG data URIs.
 *   - connect-src: pixel/analytics beacons (Meta + Google). Street View images
 *     are proxied same-origin via /api/compbird/streetview, so maps.googleapis
 *     is deliberately NOT allowed from the browser.
 *   - frame-src: td.doubleclick.net / googletagmanager — gtag conversion
 *     iframes.
 *   - In dev, script-src adds 'unsafe-eval' (React Refresh) and connect-src
 *     adds ws:/wss: (HMR socket).
 */

export interface Header {
  key: string;
  value: string;
}

/** Content-Security-Policy value. Exported for the unit test. */
export function contentSecurityPolicy(isDev: boolean): string {
  const script = [
    "'self'",
    "'unsafe-inline'",
    ...(isDev ? ["'unsafe-eval'"] : []),
    "https://connect.facebook.net",
    "https://www.googletagmanager.com",
  ].join(" ");
  const connect = [
    "'self'",
    ...(isDev ? ["ws:", "wss:"] : []),
    "https://www.facebook.com",
    "https://connect.facebook.net",
    "https://www.google-analytics.com",
    "https://www.googletagmanager.com",
    "https://googleads.g.doubleclick.net",
    "https://www.google.com",
  ].join(" ");
  const img = [
    "'self'",
    "data:",
    "blob:",
    "https://*.tile.openstreetmap.org",
    "https://tile.openstreetmap.org",
    "https://www.facebook.com",
    "https://www.google.com",
    "https://googleads.g.doubleclick.net",
    "https://www.googletagmanager.com",
  ].join(" ");

  return [
    `default-src 'self'`,
    `script-src ${script}`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src ${img}`,
    `font-src 'self' data:`,
    `connect-src ${connect}`,
    `frame-src 'self' https://td.doubleclick.net https://www.googletagmanager.com`,
    `worker-src 'self' blob:`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    `frame-ancestors 'self'`,
  ].join("; ");
}

/**
 * The full header set applied to every route. HSTS ships only in production —
 * browsers ignore it over http anyway, and pinning localhost to https during
 * dev is a foot-gun.
 */
export function securityHeaders(isDev: boolean): Header[] {
  const headers: Header[] = [
    { key: "Content-Security-Policy", value: contentSecurityPolicy(isDev) },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "SAMEORIGIN" },
    // Also trims the path (e.g. a /reset-password/<token> URL) from any
    // cross-origin request the reset page might trigger.
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=(), payment=()",
    },
  ];
  if (!isDev) {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=15552000; includeSubDomains",
    });
  }
  return headers;
}
