/**
 * Unit test for `retainExcludedComps` (comps-table.tsx) — the excluded-row
 * retention helper. FIX (2026-07): excluded comps must dim IN PLACE, not jump
 * to the bottom. The engine drops an excluded comp from the response entirely
 * and backfills the set, so the helper re-seats the dropped row from the
 * per-subject cache at the displayed index it FIRST appeared at; live rows
 * keep the engine's order around it and backfilled new comps take the
 * remaining slots.
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/comps-table.retain.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileComp } from "@/lib/compbird/types";
import { retainExcludedComps, compKey, type CachedComp } from "./comps-table";

/** Minimal honest fixture — the helper only reads `address` (via compKey). */
function comp(address: string, extra?: Partial<ProfileComp>): ProfileComp {
  return { address, ...extra } as ProfileComp;
}

const addresses = (rows: ProfileComp[]) => rows.map((r) => r.address);

test("no exclusions: passes the engine array through untouched (same reference) while caching first-seen slots", () => {
  const cache = new Map<string, CachedComp>();
  const comps = [comp("A"), comp("B"), comp("C")];
  const out = retainExcludedComps(comps, undefined, cache);
  assert.equal(out, comps, "referential pass-through keeps the memo fast path");
  assert.deepEqual(
    [...cache.entries()].map(([k, v]) => [k, v.order]),
    [["A", 0], ["B", 1], ["C", 2]],
    "every live comp is cached at its first-seen index",
  );
  // Empty set behaves like undefined.
  assert.equal(retainExcludedComps(comps, new Set(), cache), comps);
});

test("position retention across TWO recomputes: each excluded row dims in place; backfills take the remaining slots", () => {
  const cache = new Map<string, CachedComp>();

  // ── Initial response: A B C D E ───────────────────────────────────────────
  const first = [comp("A"), comp("B"), comp("C"), comp("D"), comp("E")];
  assert.deepEqual(addresses(retainExcludedComps(first, new Set(), cache)), [
    "A", "B", "C", "D", "E",
  ]);

  // ── Recompute 1: user excludes C (index 2); engine drops it + backfills F ─
  const second = [comp("A"), comp("B"), comp("D"), comp("E"), comp("F")];
  const out1 = retainExcludedComps(second, new Set(["C"]), cache);
  assert.deepEqual(
    addresses(out1),
    ["A", "B", "C", "D", "E", "F"],
    "C stays at its original index 2; live rows keep engine order; backfill F takes the freed slot at the end",
  );
  assert.equal(out1.indexOf(out1.find((c) => compKey(c) === "C")!), 2);

  // ── Recompute 2: user ALSO excludes E (first seen at index 4);
  //    engine returns A B D F G ───────────────────────────────────────────────
  const third = [comp("A"), comp("B"), comp("D"), comp("F"), comp("G")];
  const out2 = retainExcludedComps(third, new Set(["C", "E"]), cache);
  assert.deepEqual(
    addresses(out2),
    ["A", "B", "C", "D", "E", "F", "G"],
    "both excluded rows hold their original slots across the second recompute",
  );

  // ── Re-include C: it comes back LIVE from the engine, E stays dimmed in place
  const fourth = [comp("A"), comp("B"), comp("C"), comp("D"), comp("F")];
  const out3 = retainExcludedComps(fourth, new Set(["E"]), cache);
  assert.deepEqual(addresses(out3), ["A", "B", "C", "D", "E", "F"]);
});

test("original slot beyond the shrunken set: the excluded row clamps to the end instead of leaving a gap", () => {
  const cache = new Map<string, CachedComp>();
  const first = [comp("A"), comp("B"), comp("C"), comp("D")];
  retainExcludedComps(first, new Set(), cache);

  // Exclude the LAST row (index 3) and shrink the live set to two rows.
  const second = [comp("A"), comp("B")];
  const out = retainExcludedComps(second, new Set(["D"]), cache);
  assert.deepEqual(addresses(out), ["A", "B", "D"], "no phantom slots — D seats after the live rows run out");
});

test("an excluded key still present in the live set is not duplicated and keeps its live position", () => {
  const cache = new Map<string, CachedComp>();
  const first = [comp("A"), comp("B"), comp("C")];
  retainExcludedComps(first, new Set(), cache);

  // Engine still returned B (e.g. the recompute hasn't landed yet).
  const out = retainExcludedComps(first, new Set(["B"]), cache);
  assert.deepEqual(addresses(out), ["A", "B", "C"]);
  assert.equal(out, first, "no re-seating needed ⇒ pass-through reference");
});

test("recomputes refresh the cached payload but never rewrite the first-seen slot", () => {
  const cache = new Map<string, CachedComp>();
  retainExcludedComps([comp("A"), comp("B", { similarity: 70 })], new Set(), cache);

  // B comes back rescored — and in a different engine position.
  const rescored = comp("B", { similarity: 91 });
  retainExcludedComps([rescored, comp("A")], new Set(), cache);
  assert.equal(cache.get("B")!.comp, rescored, "payload refreshed to the latest engine row");
  assert.equal(cache.get("B")!.order, 1, "first-seen slot is sticky");
  assert.equal(cache.get("A")!.order, 0);

  // Excluding B now re-seats the FRESH payload at the ORIGINAL slot.
  const out = retainExcludedComps([comp("A"), comp("C")], new Set(["B"]), cache);
  assert.deepEqual(addresses(out), ["A", "B", "C"]);
  assert.equal(out[1], rescored);
});

test("an excluded key the cache has never seen is ignored (parity with the old behavior)", () => {
  const cache = new Map<string, CachedComp>();
  const comps = [comp("A"), comp("B")];
  const out = retainExcludedComps(comps, new Set(["ghost"]), cache);
  assert.equal(out, comps);
});
