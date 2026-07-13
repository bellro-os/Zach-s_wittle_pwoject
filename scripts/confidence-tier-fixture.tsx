/**
 * Confidence-tier presentation fixture — renders the REAL <ValuationPanel/>
 * with renderToStaticMarkup and asserts the tier contract:
 *
 *   1. HIGH (ensemble arm: ai_blind + ai_ensemble, tight comps, arms agree)
 *      → mid-hero layout, "High confidence" badge, range as support text
 *   2. STANDARD (far/few comps, arms disagree)
 *      → the RANGE is the hero (at the mid's hero size), mid demoted to
 *        "midpoint $X", one honest line ("…farther/fewer — treat this as a
 *        range, not a point estimate")
 *   3. ai_blind ABSENT → graceful fallback to the distance/spread gate; the
 *      SAMPLE dossier must land HIGH (the demo shows the confident state)
 *
 * Plus computeConfidence unit checks (locked degradation path, ensemble-arm
 * gating) and the proof that the "AI comparable read" method row renders with
 * no name special-casing.
 *
 * Run (repo root):
 *   node <driver that shims globalThis.React and jiti-imports this file>
 *   — see the L2 confidence work driver; jiti opts { jsx: true, alias: { "@": "<repo>/src" } }.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { ValuationPanel } from "@/components/compbird/studio/valuation-panel";
import {
  computeConfidence,
  computeConfidenceFromSignals,
} from "@/lib/compbird/confidence";
import { SAMPLE_PROFILE } from "@/lib/compbird/sample";
import type { Valuation } from "@/lib/compbird/types";

let failures = 0;
function check(name: string, cond: boolean, detail?: string) {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${!cond && detail ? ` — ${detail}` : ""}`);
  if (!cond) failures++;
}
const count = (hay: string, needle: string) => hay.split(needle).length - 1;

/* ── 1. HIGH via the ensemble arm ──────────────────────────────────────────── */
const highVal: Valuation = {
  mid: 300000,
  low: 270000,
  high: 330000,
  comp_ppsf: 210,
  implied_subject_ppsf: 205,
  divergence_pct: 6.5,
  // agreement = 2·|300k − 306k| / 300k = 4% ≤ 10 → the ensemble gate holds
  ai_blind: 306000,
  ai_ensemble: true,
  methods: [
    { name: "Direct comp + acreage adjustment", value: 296000, rationale: "top comps" },
    { name: "$/sqft", value: 305000, rationale: "median adjusted" },
    { name: "AI comparable read", value: 306000, rationale: "blind AI estimate over the same comp set" },
  ],
};
const highHtml = renderToStaticMarkup(
  <ValuationPanel valuation={highVal} nearestMi={0.2} farthestMi={0.9} compCount={6} />,
);
check(
  "HIGH: mid-hero layout (eyebrow 'Estimated value', never 'Estimated range')",
  highHtml.includes("Estimated value") && !highHtml.includes("Estimated range"),
);
check("HIGH: badge reads High confidence", highHtml.includes("High confidence"));
check("HIGH: exactly ONE hero-size figure (the mid)", count(highHtml, "text-5xl") === 1);
check(
  "HIGH: range renders as support text",
  highHtml.includes("$270,000") && highHtml.includes("$330,000"),
);
check("HIGH: no honest-range line", !highHtml.includes("treat this as a range"));
check("HIGH: no midpoint demotion", !highHtml.includes("midpoint"));
check(
  "methods table renders 'AI comparable read' row with no special-casing",
  highHtml.includes("AI comparable read") && highHtml.includes("$306,000"),
);

/* ── 2. STANDARD → the range becomes the hero ──────────────────────────────── */
const stdVal: Valuation = { ...highVal, ai_blind: 360000 }; // arms differ ~40%
const stdHtml = renderToStaticMarkup(
  <ValuationPanel valuation={stdVal} nearestMi={0.9} farthestMi={2.4} compCount={4} />,
);
check("STANDARD: eyebrow flips to 'Estimated range'", stdHtml.includes("Estimated range"));
check("STANDARD: badge reads Standard", stdHtml.includes("Standard</button>"));
check(
  "STANDARD: TWO hero-size figures (low + high — range at the mid's size)",
  count(stdHtml, "text-5xl") === 2,
);
check(
  "STANDARD: mid demoted to 'midpoint $300,000'",
  stdHtml.includes("midpoint") && stdHtml.includes("$300,000"),
);
check(
  "STANDARD: honest one-liner present",
  stdHtml.includes("treat this as a range, not a point estimate"),
);
check(
  "STANDARD: the line names the measured driver (farther + fewer)",
  stdHtml.includes("farther away and fewer"),
);

/* ── 3. ai_blind ABSENT → graceful fallback; sample dossier lands HIGH ─────── */
const sComps = SAMPLE_PROFILE.comps;
const sNear = Math.min(...sComps.map((c) => c.distance_mi ?? Infinity));
const sFar = Math.max(...sComps.map((c) => c.distance_mi ?? 0));
const sampleHtml = renderToStaticMarkup(
  <ValuationPanel
    valuation={SAMPLE_PROFILE.valuation!}
    nearestMi={sNear}
    farthestMi={sFar}
    compCount={sComps.length}
  />,
);
check(
  "SAMPLE (no ai_blind): distance/spread fallback still grants HIGH — demo shows the confident state",
  sampleHtml.includes("High confidence") && sampleHtml.includes("Estimated value"),
);

/* ── computeConfidence unit checks ─────────────────────────────────────────── */
// Locked/redacted body — today's degradation path (summary + divergence_pct).
const lockedHigh = computeConfidence({
  locked: true,
  comps: [],
  compsSummary: { count: 6, nearest_mi: 0.3, farthest_mi: 0.7 },
  valuation: { mid: 400000, divergence_pct: 5, methods: [] },
});
check("locked fallback: tight summary + low divergence → high", lockedHigh.tier === "high");

const lockedFar = computeConfidence({
  locked: true,
  comps: [],
  compsSummary: { count: 6, nearest_mi: 0.3, farthest_mi: 1.6 },
  valuation: { mid: 400000, divergence_pct: 5, methods: [] },
});
check("locked fallback: farthest 1.6 mi breaks the 0.8-mi bound → standard", lockedFar.tier === "standard");

// Ensemble arm: agreement REPLACES the spread gate…
const ensAgree = computeConfidenceFromSignals({
  compCount: 6,
  nearestMi: 0.25,
  farthestMi: 0.9,
  methodValues: [280000, 340000], // 20% spread — would fail the fallback gate
  mid: 300000,
  aiBlind: 306000,
  aiEnsemble: true,
});
check("ensemble arm: 4% agreement gates high even with 20% method spread", ensAgree.tier === "high");
check("ensemble arm: agreementPct computed (≈4)", Math.round(ensAgree.agreementPct ?? 0) === 4);

// …and the TIGHTER measured distance bounds govern on that arm.
const ensFar = computeConfidenceFromSignals({
  compCount: 6,
  nearestMi: 0.4, // fine for the 0.5-mi fallback, outside the 0.3-mi ensemble gate
  farthestMi: 0.7,
  methodValues: [296000, 305000],
  mid: 300000,
  aiBlind: 306000,
  aiEnsemble: true,
});
check("ensemble arm: nearest 0.4 mi > 0.3 gate → standard", ensFar.tier === "standard");

const noAi = computeConfidenceFromSignals({
  compCount: 6,
  nearestMi: 0.4,
  farthestMi: 0.7,
  methodValues: [296000, 305000],
  mid: 300000,
});
check("no ai_blind: same signals fall back to the 0.5-mi/spread gate → high", noAi.tier === "high");

if (failures) {
  console.error(`\n${failures} check(s) FAILED`);
  process.exit(1);
}
console.log("\nALL CHECKS PASSED");
