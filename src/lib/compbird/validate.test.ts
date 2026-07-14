/**
 * Bounds suite for the public-route clamp layer (July-audit batch-2 debt).
 * Every numeric/size input a compbird route forwards to the engine or DB goes
 * through one of these functions; the contract under test, per the validate.ts
 * idiom:
 *
 *   - tuning knobs / identity strings / lists → CLAMPED, never rejected;
 *     garbage degrades to `undefined` (= engine default / absent);
 *   - subject facts, coordinates, and structurally invalid portfolio items →
 *     a terse error the route turns into a 400 (never a 500).
 *
 * The repo has no test runner — plain `node:test`, run with:
 *
 *   npx tsx src/lib/compbird/validate.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  clampInt,
  capString,
  capStringList,
  subjectOverridesError,
  parseLatLng,
  COMPBIRD_BOUNDS,
  STRING_CAPS,
  LIST_CAPS,
} from "./validate";
import { parsePortfolioItems, PORTFOLIO_MAX_ITEMS } from "./portfolio";

/* ── clampInt — months / nComps / search limit ─────────────────────────────── */

test("clampInt: in-range values pass through untouched", () => {
  assert.equal(clampInt(24, COMPBIRD_BOUNDS.months), 24);
  assert.equal(clampInt(6, COMPBIRD_BOUNDS.nComps), 6);
  assert.equal(clampInt("12", COMPBIRD_BOUNDS.searchLimit), 12); // numeric string ok
});

test("clampInt: over-cap clamps to max, under-min clamps to min", () => {
  assert.equal(clampInt(999999, COMPBIRD_BOUNDS.months), COMPBIRD_BOUNDS.months.max);
  assert.equal(clampInt(-5, COMPBIRD_BOUNDS.months), COMPBIRD_BOUNDS.months.min);
  assert.equal(clampInt(10_000, COMPBIRD_BOUNDS.nComps), COMPBIRD_BOUNDS.nComps.max);
  assert.equal(clampInt(0, COMPBIRD_BOUNDS.searchLimit), COMPBIRD_BOUNDS.searchLimit.min);
});

test("clampInt: non-integers round; garbage degrades to undefined (engine default)", () => {
  assert.equal(clampInt(5.6, COMPBIRD_BOUNDS.nComps), 6);
  assert.equal(clampInt("abc", COMPBIRD_BOUNDS.months), undefined);
  assert.equal(clampInt(NaN, COMPBIRD_BOUNDS.months), undefined);
  assert.equal(clampInt(Infinity, COMPBIRD_BOUNDS.months), undefined);
  assert.equal(clampInt(null, COMPBIRD_BOUNDS.months), undefined);
  assert.equal(clampInt({}, COMPBIRD_BOUNDS.months), undefined);
});

/* ── capString — address / parcelId / agent / run id ───────────────────────── */

test("capString: normal strings pass through trimmed", () => {
  assert.equal(
    capString("  509 Jefferson St, Blacksburg, VA  ", STRING_CAPS.address),
    "509 Jefferson St, Blacksburg, VA",
  );
});

test("capString: oversized strings truncate to the cap", () => {
  const big = "x".repeat(100_000);
  assert.equal(capString(big, STRING_CAPS.address)?.length, STRING_CAPS.address);
  assert.equal(capString(big, STRING_CAPS.runId)?.length, STRING_CAPS.runId);
});

test("capString: non-string / empty degrades to undefined (absent)", () => {
  assert.equal(capString(12345, STRING_CAPS.parcelId), undefined);
  assert.equal(capString({ evil: true }, STRING_CAPS.address), undefined);
  assert.equal(capString("   ", STRING_CAPS.address), undefined);
  assert.equal(capString(null, STRING_CAPS.address), undefined);
});

/* ── capStringList — excluded / forced / reportConfig.sections ─────────────── */

test("capStringList: a sane list passes through", () => {
  assert.deepEqual(capStringList(["a", "b"]), ["a", "b"]);
});

test("capStringList: item count and per-item length are capped", () => {
  const flood = Array.from({ length: 5000 }, (_, i) => `addr ${i} ` + "y".repeat(1000));
  const out = capStringList(flood)!;
  assert.equal(out.length, LIST_CAPS.maxItems);
  for (const s of out) assert.ok(s.length <= LIST_CAPS.maxLen);
});

test("capStringList: non-strings dropped, non-array degrades to undefined", () => {
  assert.deepEqual(capStringList(["ok", 42, null, "also ok"]), ["ok", "also ok"]);
  assert.equal(capStringList("not-an-array"), undefined);
  assert.equal(capStringList({ 0: "a" }), undefined);
});

/* ── subjectOverridesError — facts are REJECTED (route → 400), not clamped ── */

test("subjectOverridesError: plausible facts pass (null error)", () => {
  assert.equal(subjectOverridesError({ sqft: 2400, bedrooms: 4, year_built: 1998 }), null);
  assert.equal(subjectOverridesError(undefined), null); // absent = no overrides
});

test("subjectOverridesError: absurd/non-finite facts produce the 400-path error", () => {
  assert.match(subjectOverridesError({ sqft: 2 ** 53 })!, /sqft/);
  assert.match(subjectOverridesError({ sqft: Infinity })!, /sqft/);
  assert.match(subjectOverridesError({ year_built: -4 })!, /year_built/);
  assert.match(subjectOverridesError({ bedrooms: "lots" })!, /bedrooms/);
  assert.match(subjectOverridesError(["not", "an", "object"])!, /object/);
});

/* ── parseLatLng — streetview coordinates ──────────────────────────────────── */

test("parseLatLng: plausible coordinates pass through", () => {
  assert.deepEqual(parseLatLng("37.23", "-80.41"), { lat: 37.23, lng: -80.41 });
});

test("parseLatLng: both absent → null (graceful 404 contract)", () => {
  assert.equal(parseLatLng(null, null), null);
  assert.equal(parseLatLng("", ""), null);
});

test("parseLatLng: garbage/off-planet → error (route → 400)", () => {
  assert.ok("error" in parseLatLng("abc", "-80")!);
  assert.ok("error" in parseLatLng("Infinity", "-80")!);
  assert.ok("error" in parseLatLng("91", "-80")!); // lat beyond ±90
  assert.ok("error" in parseLatLng("37", "-181")!); // lng beyond ±180
});

/* ── parsePortfolioItems — the batch route's body ──────────────────────────── */

test("parsePortfolioItems: a sane batch passes with strings capped", () => {
  const r = parsePortfolioItems([
    { address: "509 Jefferson St, Blacksburg, VA", label: "  Rental 1  " },
    { parcelId: "230322" },
    { address: "x".repeat(10_000), label: "y".repeat(10_000) },
  ]);
  assert.ok(r.ok);
  if (r.ok) {
    assert.equal(r.items.length, 3);
    assert.equal(r.items[0].label, "Rental 1");
    assert.ok(r.items[2].address!.length <= LIST_CAPS.maxLen); // address capped
    assert.ok(r.items[2].label!.length <= 80); // label capped
  }
});

test("parsePortfolioItems: nonsensical shapes → error (route → 400)", () => {
  assert.equal(parsePortfolioItems("not an array").ok, false);
  assert.equal(parsePortfolioItems([]).ok, false); // empty run
  assert.equal(
    parsePortfolioItems(Array.from({ length: PORTFOLIO_MAX_ITEMS + 1 }, () => ({ address: "a" }))).ok,
    false, // over the 50 cap — contract says 1..50
  );
  assert.equal(parsePortfolioItems([{ label: "no identity" }]).ok, false);
  assert.equal(parsePortfolioItems([null]).ok, false);
});
