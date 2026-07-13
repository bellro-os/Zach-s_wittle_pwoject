/**
 * Fixture test: the ENGINE-computed confidence tier is AUTHORITATIVE.
 *
 * The engine (MLS Bot build_cma.confidence_signals, CMA_BLIND_ENSEMBLE=1)
 * computes the measured tier server-side from inputs it owns and ships it as
 * `valuation.confidence_tier`; the generated report's hero treatment is driven
 * by the SAME value. These tests pin the precedence contract in confidence.ts:
 * when the payload carries an engine tier, the client-side computation must
 * defer to it — even when the locally visible signals would read the other way
 * — so the studio badge can never contradict the downloaded report. Legacy /
 * sample payloads without the field keep the client-side gates.
 *
 * The repo has no test runner — plain `node:test`, run with:
 *
 *   npx tsx src/lib/compbird/confidence.engine-tier.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  computeConfidence,
  computeConfidenceFromSignals,
  type ConfidenceSignals,
} from "./confidence";

/** Signals that pass every client-side HIGH gate (ensemble arm). */
const highLookingSignals: ConfidenceSignals = {
  compCount: 6,
  nearestMi: 0.2,
  farthestMi: 0.6,
  methodValues: [500_000, 510_000],
  mid: 505_000,
  aiBlind: 505_000, // agreement 0% — well inside the 10% gate
  aiEnsemble: true,
  supplementalShare: 0,
};

/** Signals that read STANDARD client-side (far comps, methods diverge). */
const standardLookingSignals: ConfidenceSignals = {
  compCount: 6,
  nearestMi: 2.6,
  farthestMi: 11.2,
  methodValues: [450_000, 630_000],
  mid: 540_000,
};

test("sanity: the fixtures read as expected without an engine tier", () => {
  assert.equal(computeConfidenceFromSignals(highLookingSignals).tier, "high");
  assert.equal(computeConfidenceFromSignals(standardLookingSignals).tier, "standard");
});

test("engineTier=standard forces STANDARD even when client inputs look HIGH", () => {
  const conf = computeConfidenceFromSignals({ ...highLookingSignals, engineTier: "standard" });
  assert.equal(conf.tier, "standard");
});

test("engineTier=high is authoritative over a standard-looking payload", () => {
  const conf = computeConfidenceFromSignals({ ...standardLookingSignals, engineTier: "high" });
  assert.equal(conf.tier, "high");
});

test("null/absent engineTier keeps the client-side computation (legacy payloads)", () => {
  assert.equal(
    computeConfidenceFromSignals({ ...highLookingSignals, engineTier: null }).tier,
    "high",
  );
  assert.equal(
    computeConfidenceFromSignals({ ...standardLookingSignals, engineTier: null }).tier,
    "standard",
  );
});

test("computeConfidence reads valuation.confidence_tier off a profile-shaped body", () => {
  const highLookingProfile = {
    comps: [
      { distance_mi: 0.1 },
      { distance_mi: 0.2 },
      { distance_mi: 0.3 },
      { distance_mi: 0.4 },
      { distance_mi: 0.5 },
      { distance_mi: 0.6 },
    ],
    valuation: {
      mid: 505_000,
      methods: [{ value: 500_000 }, { value: 510_000 }],
      ai_blind: 505_000,
      ai_ensemble: true,
    },
  };
  // Sanity: reads HIGH client-side…
  assert.equal(computeConfidence(highLookingProfile).tier, "high");
  // …but the engine's tier wins when present.
  assert.equal(
    computeConfidence({
      ...highLookingProfile,
      valuation: { ...highLookingProfile.valuation, confidence_tier: "standard" },
    }).tier,
    "standard",
  );
  // A garbage value is ignored (fallback to the client-side computation).
  assert.equal(
    computeConfidence({
      ...highLookingProfile,
      valuation: { ...highLookingProfile.valuation, confidence_tier: "certainly!" },
    }).tier,
    "high",
  );
});
