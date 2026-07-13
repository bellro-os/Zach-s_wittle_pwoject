/**
 * Regression test for the what-if carry-over leak: subject overrides + report
 * config set on one subject were surviving onto the next subject's report
 * (observed live: Edited badges + 4→6 bd / 3→4 full-bath adjustments from a
 * previous subject rendered on a different subject), because select()'s
 * success path applied a resolved profile with no staleness check and the
 * override refs were written before any guard.
 *
 * The fix routes every subject-change path through one shared reset and stamps
 * all async work with a subject epoch inside `createSubjectSession` (exported
 * from comp-studio.tsx). This test drives that session through the exact
 * scenario: subject A → edit overrides → switch to subject B, asserting the
 * overrides/reportConfig are empty on B and that A's stale responses/edits are
 * refused.
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/comp-studio.leak.test.ts
 *
 * A tiny module hook stubs the one CSS import (leaflet's) that rides the
 * studio's component graph so the module loads under plain Node.
 */
import { createRequire, register } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileResult } from "@/lib/compbird/types";
import type { SubjectSession } from "./comp-studio";

// leaflet/dist/leaflet.css is statically imported by leaflet-map.tsx (inert on
// the Next server, unloadable under Node) — stub every .css module to an empty
// export, on BOTH loader paths (tsx may pull the graph through either),
// registered BEFORE comp-studio is (dynamically) imported below.
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
// CJS side: require.extensions is process-global, so registering a no-op .css
// handler here covers every module in the graph.
(createRequire(import.meta.url).extensions as Record<string, unknown>)[".css"] = () => {};

/** Import the real module AFTER the css hook is registered. */
async function loadCreateSession(): Promise<() => SubjectSession> {
  const mod = await import("./comp-studio");
  return mod.createSubjectSession;
}

/**
 * Minimal profile stand-in: the session stores the base opaquely (it never
 * reads into it), so a skeletal object is an honest fixture here.
 */
function fakeProfile(address: string, mid: number): ProfileResult {
  return {
    ok: true,
    facts: { address, parcel_id: `P-${address}` },
    comps: [],
    valuation: { mid },
  } as unknown as ProfileResult;
}

test("subject A → edit overrides → switch to B: overrides + reportConfig are empty and A's stale response is dropped", async () => {
  const createSubjectSession = await loadCreateSession();
  const s = createSubjectSession();

  // ── Subject A resolves and the agent edits it ────────────────────────────
  const epochA = s.beginSubjectChange();
  assert.equal(s.armSubject(epochA, { address: "A" }, fakeProfile("A", 400_000)), true);
  // The live sighting's edits: 4→6 bedrooms, 3→4 full baths + a custom summary.
  assert.equal(s.setOverrides(s.epoch(), { bedrooms: 6, full_baths: 4 }), true);
  assert.equal(s.setReportConfig(s.epoch(), { execText: "Agent-written summary." }), true);
  assert.deepEqual(s.overrides(), { bedrooms: 6, full_baths: 4 });
  assert.deepEqual(s.reportConfig(), { execText: "Agent-written summary." });

  // ── The user switches to subject B ───────────────────────────────────────
  const epochB = s.beginSubjectChange();

  // THE LEAK ASSERTIONS: nothing subject-scoped survives the switch.
  assert.deepEqual(s.overrides(), {}, "what-if overrides must not carry over");
  assert.deepEqual(s.reportConfig(), {}, "report config must not carry over");
  assert.equal(s.subject(), null, "subject disarmed during the switch");
  assert.equal(s.base(), null, "engine base dropped with its subject");
  assert.equal(s.isStale(epochA), true, "everything stamped for A is now stale");

  // ── A's profile response resolves LATE (the race that caused the sighting):
  // it must be refused, never re-arming the old subject under B's report. ────
  assert.equal(
    s.armSubject(epochA, { address: "A" }, fakeProfile("A", 400_000)),
    false,
    "a stale profile response must be discarded",
  );
  assert.equal(s.subject(), null);
  assert.equal(s.base(), null);

  // ── B's own response still lands normally, on a clean slate ──────────────
  assert.equal(s.armSubject(epochB, { address: "B" }, fakeProfile("B", 250_000)), true);
  assert.deepEqual(s.subject(), { address: "B" });
  assert.deepEqual(s.overrides(), {}, "B starts with no inherited edits");
  assert.deepEqual(s.reportConfig(), {}, "B starts with no inherited narrative");
});

test("straggler override/report-config edits stamped for the previous subject are refused", async () => {
  const createSubjectSession = await loadCreateSession();
  const s = createSubjectSession();

  const epochA = s.beginSubjectChange();
  s.armSubject(epochA, { address: "A" }, fakeProfile("A", 400_000));
  const editEpoch = s.epoch(); // an edit in flight, stamped while A was live

  const epochB = s.beginSubjectChange();
  s.armSubject(epochB, { address: "B" }, fakeProfile("B", 250_000));

  // The late edit (e.g. a callback surviving A's editor teardown) is dropped.
  assert.equal(s.setOverrides(editEpoch, { bedrooms: 6 }), false);
  assert.equal(s.setReportConfig(editEpoch, { execText: "stale" }), false);
  assert.deepEqual(s.overrides(), {}, "stale override edit must not be recorded");
  assert.deepEqual(s.reportConfig(), {}, "stale config edit must not be recorded");

  // A current-epoch edit for B works as normal.
  assert.equal(s.setOverrides(s.epoch(), { sqft: 2400 }), true);
  assert.deepEqual(s.overrides(), { sqft: 2400 });
});

test("engineMid baseline semantics: the base is set once per subject and a stale disarm cannot clear the new subject", async () => {
  const createSubjectSession = await loadCreateSession();
  const s = createSubjectSession();

  const epochA = s.beginSubjectChange();
  const baseA = fakeProfile("A", 400_000);
  s.armSubject(epochA, { address: "A" }, baseA);
  assert.equal(s.base(), baseA, "base = the first (unmodified) engine result for A");

  // Switch to B; A's failure path (sample fallback) fires late — its disarm
  // must not knock out B's armed subject.
  const epochB = s.beginSubjectChange();
  const baseB = fakeProfile("B", 250_000);
  s.armSubject(epochB, { address: "B" }, baseB);
  assert.equal(s.disarm(epochA), false, "stale disarm refused");
  assert.equal(s.base(), baseB, "B keeps its own untouched base");

  // The current subject CAN disarm (live-lookup failure → sample fallback).
  assert.equal(s.disarm(epochB), true);
  assert.equal(s.base(), null);
  assert.equal(s.subject(), null);
});
