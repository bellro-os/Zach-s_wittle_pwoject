/**
 * Unit tests for the valuation panel's tuning cause-and-effect surface:
 *
 * PART A — per-method delta feedback (valuation-panel.tsx pure helpers):
 *   - computeMethodDeltas: changed / new / dropped / unchanged, by method name
 *   - advanceMethodDeltas: the previous-methods tracker the panel's ref
 *     delegates to verbatim — first sight never shows deltas, a same-subject
 *     recompute diffs, a SUBJECT-IDENTITY CHANGE CLEARS
 *   - largestMoverSentence / fmtDeltaChip: the aria-live narration + % chip copy
 *
 * PART B — actionable STANDARD tier (renderToStaticMarkup fixtures):
 *   - far/few comps  → the "Pin a closer comparable" chip (data-cb-action)
 *   - methods diverge → the "Review the comp set" chip
 *   - chips absent on HIGH, on locked payloads, and when the caller withholds
 *     the capability flags (the sample-report path)
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/valuation-panel.delta.test.ts
 *
 * Same module-hook idiom as comp-studio.leak.test.ts: stub any CSS import
 * riding the component graph so it loads under plain Node.
 */
import { createRequire, register } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Valuation } from "@/lib/compbird/types";

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

/** Import the real module AFTER the css hook is registered. */
async function loadPanel() {
  return await import("./valuation-panel");
}

type MethodRow = [name: string, value: number | null];

/** Valuation fixture — methods by [name, value], everything else honest defaults. */
function valuation(methods: MethodRow[], extra: Partial<Valuation> = {}): Valuation {
  return {
    mid: 450_000,
    low: 430_000,
    high: 470_000,
    comp_ppsf: 210,
    implied_subject_ppsf: null,
    divergence_pct: null,
    methods: methods.map(([name, value]) => ({ name, value, rationale: "" })),
    ...extra,
  };
}

function snap(rows: MethodRow[]) {
  return rows.map(([name, value]) => ({ name, value }));
}

/* ── PART A: method-delta computation ──────────────────────────────────────── */

test("computeMethodDeltas: changed / new / dropped / unchanged, keyed by method name", async () => {
  const { computeMethodDeltas } = await loadPanel();

  const prev = snap([
    ["Direct comparison", 443_200],
    ["$/sqft benchmark", 450_000],
    ["AI comparable read", 447_000],
    ["Assessment ratio", null],
  ]);
  const next = snap([
    ["Direct comparison", 451_800], // moved
    ["$/sqft benchmark", 450_000], // unchanged
    ["Assessment ratio", 449_000], // value appeared on an existing row
    ["Cost approach", 455_000], // brand-new method
    // "AI comparable read" left the list entirely
  ]);

  const d = computeMethodDeltas(prev, next);

  const moved = d.get("Direct comparison");
  assert.equal(moved?.kind, "changed");
  if (moved?.kind === "changed") {
    assert.equal(moved.from, 443_200);
    assert.equal(moved.to, 451_800);
    assert.ok(Math.abs(moved.pct - 1.9404) < 0.01, `pct ≈ +1.94, got ${moved.pct}`);
  }

  assert.equal(d.has("$/sqft benchmark"), false, "an unchanged method gets NO entry");
  assert.equal(d.get("Assessment ratio")?.kind, "new", "null → value reads as new, not a delta");
  assert.equal(d.get("Cost approach")?.kind, "new");

  const dropped = d.get("AI comparable read");
  assert.equal(dropped?.kind, "dropped");
  if (dropped?.kind === "dropped") assert.equal(dropped.from, 447_000);

  assert.equal(d.size, 4);

  // A surviving row whose value vanished also reads as dropped.
  const d2 = computeMethodDeltas(snap([["X", 400_000]]), snap([["X", null]]));
  assert.deepEqual(d2.get("X"), { kind: "dropped", from: 400_000 });
});

test("advanceMethodDeltas: first sight is silent; same-subject recompute diffs; subject change CLEARS", async () => {
  const { advanceMethodDeltas } = await loadPanel();

  // First sight of subject A — snapshot only, never a delta.
  const first = advanceMethodDeltas(null, "A", snap([["Direct comparison", 443_200]]));
  assert.equal(first.deltas, null, "the first valuation for a subject shows no deltas");

  // Same subject, values moved — the recompute story.
  const second = advanceMethodDeltas(first, "A", snap([["Direct comparison", 451_800]]));
  assert.equal(second.deltas?.get("Direct comparison")?.kind, "changed");

  // Same subject, nothing moved — no residual delta.
  const third = advanceMethodDeltas(second, "A", snap([["Direct comparison", 451_800]]));
  assert.equal(third.deltas, null, "an identical recompute clears the delta");

  // SUBJECT-IDENTITY CHANGE — the tracker resets; different values must NOT
  // read as a move (this is the panel's subjectKey-keyed ref reset).
  const fourth = advanceMethodDeltas(second, "B", snap([["Direct comparison", 300_000]]));
  assert.equal(fourth.deltas, null, "a new subject never inherits the old subject's deltas");
  assert.equal(fourth.key, "B");

  // ...and returning to work on B diffs against B's own snapshot.
  const fifth = advanceMethodDeltas(fourth, "B", snap([["Direct comparison", 310_000]]));
  assert.equal(fifth.deltas?.get("Direct comparison")?.kind, "changed");
});

test("largestMoverSentence + fmtDeltaChip: the shipped copy", async () => {
  const { computeMethodDeltas, largestMoverSentence, fmtDeltaChip } = await loadPanel();

  // Largest ABSOLUTE mover wins: A +1.94% vs B −4%.
  const both = computeMethodDeltas(
    snap([
      ["Direct comparison", 443_200],
      ["$/sqft benchmark", 400_000],
    ]),
    snap([
      ["Direct comparison", 451_800],
      ["$/sqft benchmark", 384_000],
    ]),
  );
  assert.equal(largestMoverSentence(both), "$/sqft benchmark moved down 4 percent.");

  // The spec's exemplar shape: +1.94% rounds to spoken "2".
  const up = computeMethodDeltas(
    snap([["Direct comparison", 443_200]]),
    snap([["Direct comparison", 451_800]]),
  );
  assert.equal(largestMoverSentence(up), "Direct comparison moved up 2 percent.");

  // Sub-1% moves speak one decimal, never "0 percent".
  const tiny = computeMethodDeltas(
    snap([["Direct comparison", 450_000]]),
    snap([["Direct comparison", 452_000]]),
  );
  assert.equal(largestMoverSentence(tiny), "Direct comparison moved up 0.4 percent.");

  // Only new/dropped (no value→value move) ⇒ nothing to narrate.
  const churn = computeMethodDeltas(snap([["Old method", 400_000]]), snap([["New method", 410_000]]));
  assert.equal(largestMoverSentence(churn), null);
  assert.equal(largestMoverSentence(null), null);

  // The row chip: signed, one decimal, magnitude clamped ≥ 0.1.
  assert.equal(fmtDeltaChip(1.94), "+1.9%");
  assert.equal(fmtDeltaChip(-0.02), "-0.1%", "a real move never prints ±0.0%");
  assert.equal(fmtDeltaChip(-12.34), "-12.3%");
});

/* ── PART B: STANDARD-tier action chips ────────────────────────────────────── */

const PIN = 'data-cb-action="pin-closer"';
const REVIEW = 'data-cb-action="review-comps"';

test("STANDARD far/few comps: only the 'Pin a closer comparable' chip, targeting the add-comp anchor", async () => {
  const { ValuationPanel, ADD_COMP_SECTION_ID } = await loadPanel();

  // 3 comps, nearest 2.2 mi — far AND few; methods agree (no divergence chip).
  const html = renderToStaticMarkup(
    createElement(ValuationPanel, {
      valuation: valuation([
        ["Direct comparison", 452_000],
        ["$/sqft benchmark", 448_000],
      ]),
      compCount: 3,
      nearestMi: 2.2,
      farthestMi: 3.1,
      subjectKey: "A",
      canPinComp: true,
      canReviewComps: true,
    }),
  );

  assert.ok(html.includes("Estimated range"), "far/few comps ⇒ STANDARD range hero");
  assert.ok(html.includes(PIN), "far/few ⇒ the pin chip");
  assert.ok(html.includes("Pin a closer comparable"), "shipped chip copy");
  assert.ok(!html.includes(REVIEW), "agreeing methods ⇒ no review chip");
  assert.equal(ADD_COMP_SECTION_ID, "cb-add-comp", "anchor id contract with report-view");
});

test("STANDARD diverging methods: only the 'Review the comp set' chip", async () => {
  const { ValuationPanel, COMPS_SECTION_ID } = await loadPanel();

  // Local, plentiful comps — but the methods spread 13% (> the 10% gate).
  const html = renderToStaticMarkup(
    createElement(ValuationPanel, {
      valuation: valuation([
        ["Direct comparison", 400_000],
        ["$/sqft benchmark", 460_000],
      ]),
      compCount: 6,
      nearestMi: 0.2,
      farthestMi: 0.6,
      subjectKey: "A",
      canPinComp: true,
      canReviewComps: true,
    }),
  );

  assert.ok(html.includes(REVIEW), "diverging methods ⇒ the review chip");
  assert.ok(html.includes("Review the comp set"), "shipped chip copy");
  assert.ok(!html.includes(PIN), "local + plentiful comps ⇒ no pin chip");
  assert.equal(COMPS_SECTION_ID, "cb-comp-set", "anchor id contract with report-view");
});

test("STANDARD with both drivers: both chips, pin first", async () => {
  const { ValuationPanel } = await loadPanel();

  const html = renderToStaticMarkup(
    createElement(ValuationPanel, {
      valuation: valuation([
        ["Direct comparison", 400_000],
        ["$/sqft benchmark", 460_000],
      ]),
      compCount: 3,
      nearestMi: 2.2,
      farthestMi: 3.1,
      subjectKey: "A",
      canPinComp: true,
      canReviewComps: true,
    }),
  );

  assert.ok(html.includes(PIN) && html.includes(REVIEW), "both drivers ⇒ both chips");
  assert.ok(html.indexOf(PIN) < html.indexOf(REVIEW), "pin-closer leads");
});

test("HIGH tier: mid hero, zero action chips", async () => {
  const { ValuationPanel } = await loadPanel();

  // Fallback-arm high gate: ≥5 comps, nearest ≤0.5, farthest ≤0.8, spread ≤10%.
  const html = renderToStaticMarkup(
    createElement(ValuationPanel, {
      valuation: valuation([
        ["Direct comparison", 452_000],
        ["$/sqft benchmark", 448_000],
      ]),
      compCount: 6,
      nearestMi: 0.2,
      farthestMi: 0.6,
      subjectKey: "A",
      canPinComp: true,
      canReviewComps: true,
    }),
  );

  assert.ok(html.includes("Estimated value"), "HIGH keeps the mid hero");
  assert.ok(!html.includes("data-cb-action"), "chips never render on HIGH");
});

test("locked and sample paths: chips absent even when the tier is STANDARD", async () => {
  const { ValuationPanel } = await loadPanel();

  // LOCKED — methods redacted to []; divergence survives and reads standard.
  // Even with the capability flags erroneously true, `locked` wins (defense
  // in depth — report-view also passes both flags false here).
  const lockedHtml = renderToStaticMarkup(
    createElement(ValuationPanel, {
      valuation: valuation([], { divergence_pct: 15 }),
      compCount: 4,
      nearestMi: 1.2,
      farthestMi: 2.0,
      locked: true,
      subjectKey: "A",
      canPinComp: true,
      canReviewComps: true,
    }),
  );
  assert.ok(lockedHtml.includes("Estimated range"), "locked standard still range-heroes");
  assert.ok(!lockedHtml.includes("data-cb-action"), "locked ⇒ no chips");

  // SAMPLE — report-view withholds both capability flags (the add-comp search
  // and live comp table don't exist there), so the chips stay hidden.
  const sampleHtml = renderToStaticMarkup(
    createElement(ValuationPanel, {
      valuation: valuation([
        ["Direct comparison", 452_000],
        ["$/sqft benchmark", 448_000],
      ]),
      compCount: 3,
      nearestMi: 2.2,
      farthestMi: 3.1,
      subjectKey: "sample",
      canPinComp: false,
      canReviewComps: false,
    }),
  );
  assert.ok(sampleHtml.includes("Estimated range"), "sample standard still range-heroes");
  assert.ok(!sampleHtml.includes("data-cb-action"), "sample ⇒ no chips");
});
