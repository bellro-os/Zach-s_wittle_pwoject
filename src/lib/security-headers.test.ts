/**
 * Security-header baseline (launch security review 2026-07, P1 fix).
 *
 * Contract under test: securityHeaders() ships the full baseline (CSP, nosniff,
 * frame, referrer, permissions; HSTS in prod only) and the CSP keeps exactly
 * the documented third-party allowances — OSM tiles for Leaflet, the Meta /
 * Google pixel origins — without ever weakening object-src / base-uri /
 * frame-ancestors, and with the dev-only relaxations ('unsafe-eval', ws:)
 * absent from the production policy.
 *
 * Run with: npx tsx src/lib/security-headers.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { securityHeaders, contentSecurityPolicy } from "./security-headers";

function headerMap(isDev: boolean): Map<string, string> {
  return new Map(securityHeaders(isDev).map((h) => [h.key, h.value]));
}

function directive(csp: string, name: string): string {
  const d = csp.split(";").map((s) => s.trim()).find((s) => s.startsWith(`${name} `) || s === name);
  assert.ok(d, `CSP is missing the ${name} directive`);
  return d!;
}

test("production ships the full baseline including HSTS", () => {
  const h = headerMap(false);
  for (const key of [
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "Strict-Transport-Security",
  ]) {
    assert.ok(h.has(key), `missing ${key}`);
  }
  assert.equal(h.get("X-Content-Type-Options"), "nosniff");
  assert.equal(h.get("X-Frame-Options"), "SAMEORIGIN");
  assert.match(h.get("Strict-Transport-Security")!, /max-age=\d{7,}/);
});

test("dev omits HSTS (no localhost https pinning)", () => {
  assert.equal(headerMap(true).has("Strict-Transport-Security"), false);
});

test("prod CSP locks the dangerous directives", () => {
  const csp = contentSecurityPolicy(false);
  assert.equal(directive(csp, "object-src"), "object-src 'none'");
  assert.equal(directive(csp, "base-uri"), "base-uri 'self'");
  assert.equal(directive(csp, "form-action"), "form-action 'self'");
  assert.equal(directive(csp, "frame-ancestors"), "frame-ancestors 'self'");
  assert.equal(directive(csp, "default-src"), "default-src 'self'");
});

test("prod CSP has no dev relaxations", () => {
  const csp = contentSecurityPolicy(false);
  assert.ok(!csp.includes("'unsafe-eval'"), "prod must not allow eval");
  assert.ok(!/\bws:/.test(csp), "prod must not allow ws:");
});

test("dev CSP allows React Refresh + HMR", () => {
  const csp = contentSecurityPolicy(true);
  assert.ok(directive(csp, "script-src").includes("'unsafe-eval'"));
  assert.ok(directive(csp, "connect-src").includes("ws:"));
});

test("documented allowances: OSM tiles (Leaflet) and pixel origins", () => {
  const csp = contentSecurityPolicy(false);
  assert.ok(directive(csp, "img-src").includes("https://*.tile.openstreetmap.org"));
  const script = directive(csp, "script-src");
  assert.ok(script.includes("https://connect.facebook.net"));
  assert.ok(script.includes("https://www.googletagmanager.com"));
  // Street View is proxied same-origin — the browser must NOT talk to Google Maps.
  assert.ok(!csp.includes("maps.googleapis.com"), "streetview stays proxied server-side");
});

test("script-src is limited to self + inline + the two pixel loaders", () => {
  const sources = directive(contentSecurityPolicy(false), "script-src")
    .split(/\s+/)
    .slice(1)
    .sort();
  assert.deepEqual(sources, [
    "'self'",
    "'unsafe-inline'",
    "https://connect.facebook.net",
    "https://www.googletagmanager.com",
  ]);
});
