/**
 * Redirect-flip tests (signed-in hub becomes the default post-auth landing).
 *
 * Contract under test (auth-redirect.ts):
 *  - the no-param DEFAULT is now "/home" (was "/comps"): an undefined / junk /
 *    off-allowlist target falls back to the hub;
 *  - "/home" is an ADMITTED path (bare and, defensively, without query cruft);
 *  - an EXPLICIT whitelisted target is still honored verbatim — the address-first
 *    arrival intent (?address=) survives and lands on the priced report /comps,
 *    NOT the hub, so the priced-report flow never regresses.
 *
 * The repo has no test runner — plain node:test, run with:
 *   npx tsx src/lib/auth-redirect.home.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { safeAuthRedirect } from "./auth-redirect";

test("no-param default is /home (the signed-in hub)", () => {
  assert.equal(safeAuthRedirect(undefined), "/home");
  assert.equal(safeAuthRedirect(""), "/home");
  assert.equal(safeAuthRedirect("   "), "/home");
});

test("off-allowlist / open-redirect attempts fall back to /home", () => {
  assert.equal(safeAuthRedirect("https://evil.example/phish"), "/home");
  assert.equal(safeAuthRedirect("//evil.example"), "/home");
  assert.equal(safeAuthRedirect("/not-a-real-app-path"), "/home");
});

test("/home is admitted (bare and with only-junk query stripped)", () => {
  assert.equal(safeAuthRedirect("/home"), "/home");
  // Non-whitelisted query keys are dropped, so a bare-ish /home stays /home.
  assert.equal(safeAuthRedirect("/home?foo=bar"), "/home");
});

test("explicit address-first target is honored → priced report on /comps, not the hub", () => {
  // The value survives; URLSearchParams re-encodes the space as "+" (standard
  // application/x-www-form-urlencoded). The point is the address rides through
  // to /comps rather than being dropped or bounced to the hub.
  const out = safeAuthRedirect("/comps?address=X%20St");
  assert.equal(out, "/comps?address=X+St");
  assert.equal(new URL(out, "https://compbird.test").searchParams.get("address"), "X St");
  // parcelId + intent likewise survive to /comps.
  assert.equal(
    safeAuthRedirect("/comps?parcelId=230322&intent=price"),
    "/comps?parcelId=230322&intent=price",
  );
});

test("other admitted app paths still round-trip", () => {
  assert.equal(safeAuthRedirect("/portfolio"), "/portfolio");
  assert.equal(safeAuthRedirect("/account"), "/account");
  assert.equal(safeAuthRedirect("/comps"), "/comps");
});
