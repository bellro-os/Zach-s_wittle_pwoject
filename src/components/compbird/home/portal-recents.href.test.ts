/**
 * Href-building tests for the hub's recent-properties row (PortalRecents).
 *
 * PortalRecents renders each stored recent as a REAL anchor to the studio's
 * ?parcelId=&address= deep-link contract, keyed + badged through the SAME
 * exported helpers the studio's own recents surfaces use (entryHref / keyOf) —
 * never a fork. This asserts that reuse holds:
 *  - entryHref carries parcelId (when present) AND address, encoded;
 *  - address-only entries (no parcel) still build a valid /comps?address= href;
 *  - keyOf prefers parcel_id, falling back to address (the dedupe identity).
 *
 * Same module-hook idiom as recents.persistence.test.ts: stub CSS imports and a
 * minimal window/localStorage so recents.tsx's client module loads under plain
 * Node. Run with:
 *   npx tsx src/components/compbird/home/portal-recents.href.test.ts
 */
import { createRequire, register } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";

register(
  "data:text/javascript," +
    encodeURIComponent(
      `export async function load(url, context, next) {
        if (url.split("?")[0].endsWith(".css")) {
          return { format: "module", source: "export default {};", shortCircuit: true };
        }
        return next(url, context);
      }`,
    ),
);
(createRequire(import.meta.url).extensions as Record<string, unknown>)[".css"] = () => {};

/* ── window/localStorage stub (recents.tsx helpers touch window) ───────────── */
const mem = new Map<string, string>();
(globalThis as Record<string, unknown>).window = {
  localStorage: {
    getItem: (k: string) => (mem.has(k) ? (mem.get(k) as string) : null),
    setItem: (k: string, v: string) => {
      mem.set(k, String(v));
    },
    removeItem: (k: string) => {
      mem.delete(k);
    },
  },
  dispatchEvent: () => true,
  addEventListener: () => {},
  removeEventListener: () => {},
};

async function loadRecents() {
  return await import("../studio/recents");
}

test("entryHref carries parcelId + address (encoded) on the /comps deep-link contract", async () => {
  const { entryHref } = await loadRecents();
  const href = entryHref({ address: "123 Main St, Blacksburg, VA", parcel_id: "230322" });
  const url = new URL(href, "https://compbird.test");
  assert.equal(url.pathname, "/comps");
  assert.equal(url.searchParams.get("parcelId"), "230322");
  assert.equal(url.searchParams.get("address"), "123 Main St, Blacksburg, VA");
});

test("address-only entries (no parcel) still build a valid /comps?address= href", async () => {
  const { entryHref } = await loadRecents();
  const href = entryHref({ address: "500 Draper Rd", parcel_id: "" });
  const url = new URL(href, "https://compbird.test");
  assert.equal(url.pathname, "/comps");
  assert.equal(url.searchParams.get("parcelId"), null);
  assert.equal(url.searchParams.get("address"), "500 Draper Rd");
});

test("keyOf is the dedupe identity: parcel_id preferred, address fallback", async () => {
  const { keyOf } = await loadRecents();
  assert.equal(keyOf({ address: "1 A St", parcel_id: "P1" }), "P1");
  assert.equal(keyOf({ address: "2 B St", parcel_id: "" }), "2 B St");
});
