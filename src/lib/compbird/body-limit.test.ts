/**
 * Request-size guard (launch security review 2026-07).
 *
 * Contract under test: bodyTooLarge flags a declared Content-Length above the
 * cap and NEVER blocks a request with an absent/malformed header (best-effort
 * by design — the Caddy-layer max_size is the backstop for chunked bodies).
 *
 * Run with: npx tsx src/lib/compbird/body-limit.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { bodyTooLarge, MAX_JSON_BODY_BYTES } from "./body-limit";

function reqWith(contentLength: string | null) {
  return {
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-length" ? contentLength : null,
    },
  };
}

test("over-cap Content-Length is flagged", () => {
  assert.equal(bodyTooLarge(reqWith(String(MAX_JSON_BODY_BYTES + 1))), true);
  assert.equal(bodyTooLarge(reqWith("999999999")), true);
});

test("at or under the cap passes", () => {
  assert.equal(bodyTooLarge(reqWith(String(MAX_JSON_BODY_BYTES))), false);
  assert.equal(bodyTooLarge(reqWith("512")), false);
  assert.equal(bodyTooLarge(reqWith("0")), false);
});

test("absent or malformed header never blocks", () => {
  assert.equal(bodyTooLarge(reqWith(null)), false);
  assert.equal(bodyTooLarge(reqWith("")), false);
  assert.equal(bodyTooLarge(reqWith("not-a-number")), false);
});

test("custom cap is honored", () => {
  assert.equal(bodyTooLarge(reqWith("101"), 100), true);
  assert.equal(bodyTooLarge(reqWith("100"), 100), false);
});

test("a real Request object works through the same interface", () => {
  const r = new Request("http://localhost/api/x", {
    method: "POST",
    headers: { "content-length": String(MAX_JSON_BODY_BYTES * 2) },
  });
  assert.equal(bodyTooLarge(r), true);
});
