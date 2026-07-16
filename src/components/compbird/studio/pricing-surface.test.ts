/**
 * Unit tests for the pricing-surface feature wave (CMA_PRICING_SURFACE=1):
 *
 *   - sold-vs-ask chip math + the set-level median (comps-table.tsx)
 *   - engine pricing-band validation, target-DOM points, and the derived
 *     overpricing-cost sentence (pricing-strategy.tsx)
 *   - the defensive confidence-evidence sentence (confidence.ts)
 *   - the equity card's prior-sale pick (equity-snapshot.tsx)
 *   - redaction: `pricing` / `active_model` are Pro evidence and must be
 *     stripped, while `valuation.confidence_signals` survives (redact.ts)
 *
 * The repo has no test runner — plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/pricing-surface.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { PricingSurface } from "@/lib/compbird/types";
import { redactEvidence } from "@/lib/compbird/redact";
import { confidenceEvidenceSentence } from "@/lib/compbird/confidence";
import { soldVsAsk, medianSoldVsAskPct } from "./comps-table";
import { buildModelBands, buildTargetDom, overpricingSentence } from "./pricing-strategy";
import { priorSaleOf } from "./equity-snapshot";

/* ── sold-vs-ask ───────────────────────────────────────────────────────────── */

test("soldVsAsk: under / over / at ask, and the null cases", () => {
  assert.deepEqual(soldVsAsk(484_500, 500_000), {
    pct: -3.1,
    label: "sold 3.1% under ask",
  });
  assert.equal(soldVsAsk(510_000, 500_000)?.label, "sold 2.0% over ask");
  assert.equal(soldVsAsk(500_000, 500_000)?.label, "sold at ask");
  assert.equal(soldVsAsk(null, 500_000), null);
  assert.equal(soldVsAsk(500_000, null), null);
  assert.equal(soldVsAsk(500_000, 0), null, "zero ask never divides");
});

test("medianSoldVsAskPct: median over the comps that carry both figures", () => {
  const comps = [
    { sold_price: 97_000, original_list_price: 100_000 }, // -3
    { sold_price: 99_000, original_list_price: 100_000 }, // -1
    { sold_price: 105_000, original_list_price: 100_000 }, // +5
    { sold_price: 105_000, original_list_price: null }, // no ask → skipped
  ];
  assert.equal(medianSoldVsAskPct(comps), -1);
  assert.equal(medianSoldVsAskPct([{ sold_price: 1, original_list_price: null }]), null);
});

/* ── engine pricing bands ──────────────────────────────────────────────────── */

const WIRE_PRICING: PricingSurface = {
  bands: [
    { key: "maximize", price: 480_000, dom_q25: 28, dom_q50: 41, dom_q75: 63, cut_probability: 0.42 },
    { key: "sell_fast", price: 438_000, dom_q25: 9, dom_q50: 14, dom_q75: 22, cut_probability: 0.06 },
    { key: "market", price: 455_000, dom_q25: 14, dom_q50: 21, dom_q75: 33, cut_probability: 0.18 },
  ],
  target_dom: [
    { days: 60, price: 462_000 },
    { days: 30, price: 438_000 },
    { days: 45, price: 451_000 },
  ],
};

test("buildModelBands: validates, maps keys, sorts by price, anchors market", () => {
  const bands = buildModelBands(WIRE_PRICING)!;
  assert.deepEqual(
    bands.map((b) => b.key),
    ["fast", "market", "maximize"],
  );
  assert.equal(bands[1].isAnchor, true);
  assert.equal(bands[1].cutProbability, 0.18);
  assert.deepEqual([bands[2].domQ25, bands[2].domQ50, bands[2].domQ75], [28, 41, 63]);
});

test("buildModelBands: absent/empty/garbage wire ⇒ null (synthetic path keeps governing)", () => {
  assert.equal(buildModelBands(undefined), null);
  assert.equal(buildModelBands({}), null);
  assert.equal(buildModelBands({ bands: [] }), null);
  assert.equal(
    buildModelBands({
      bands: [{ key: "market", price: NaN, dom_q25: 1, dom_q50: 2, dom_q75: 3, cut_probability: 0.5 }],
    }),
    null,
  );
});

test("buildModelBands: a bad probability degrades to null on an otherwise-good band", () => {
  const bands = buildModelBands({
    bands: [{ key: "market", price: 455_000, dom_q25: 14, dom_q50: 21, dom_q75: 33, cut_probability: 7 }],
  })!;
  assert.equal(bands[0].cutProbability, null);
  assert.equal(bands[0].price, 455_000);
});

test("buildTargetDom: validates and sorts ascending by days", () => {
  assert.deepEqual(
    buildTargetDom(WIRE_PRICING).map((t) => t.days),
    [30, 45, 60],
  );
  assert.deepEqual(buildTargetDom({}), []);
});

test("overpricingSentence: derives days + cut-risk clauses from maximize vs market", () => {
  const s = overpricingSentence(buildModelBands(WIRE_PRICING)!);
  assert.equal(
    s,
    "Listing +$25K above market costs ~20 extra days and raises the chance of a price cut from 18% to 42%.",
  );
  // No maximize band ⇒ nothing to compare.
  assert.equal(
    overpricingSentence(
      buildModelBands({
        bands: [{ key: "market", price: 455_000, dom_q25: 14, dom_q50: 21, dom_q75: 33, cut_probability: 0.18 }],
      })!,
    ),
    null,
  );
});

/* ── confidence evidence sentence ──────────────────────────────────────────── */

test("confidenceEvidenceSentence: full signals read like the spec example", () => {
  assert.equal(
    confidenceEvidenceSentence({
      tier: "high",
      count: 6,
      nearest_mi: 0.2,
      farthest_mi: 0.9,
      agreement_pct: 3.4,
      spread_pct: 6.1,
      ensemble_arm: true,
    }),
    "HIGH — 6 comps, nearest 0.2 mi, independent AI within 4%.",
  );
});

test("confidenceEvidenceSentence: builds from whichever keys exist", () => {
  assert.equal(
    confidenceEvidenceSentence({ count: 4, spread_pct: 8.2 }, "standard"),
    "STANDARD — 4 comps, methods within 9%.",
  );
  assert.equal(confidenceEvidenceSentence({}, "high"), null, "no usable keys ⇒ null");
  assert.equal(
    confidenceEvidenceSentence({ nearest_mi: 0.4 }),
    "nearest 0.4 mi.",
    "no tier anywhere ⇒ no tier lead-in",
  );
});

/* ── equity snapshot prior sale ────────────────────────────────────────────── */

test("priorSaleOf: picks the most recent priced entry and its year", () => {
  assert.deepEqual(
    priorSaleOf([
      { price: 310_000, date: "2019-06-14" },
      { price: 255_000, date: "2012-03-02" },
      { price: null, date: "2024-01-01" }, // price-less entries never win
    ]),
    { price: 310_000, year: 2019 },
  );
  assert.equal(priorSaleOf([]), null);
  assert.equal(priorSaleOf([{ price: null, date: "2020-01-01" }]), null);
});

/* ── redaction of the new surfaces ─────────────────────────────────────────── */

test("redactEvidence: strips pricing + active_model, keeps confidence_signals", () => {
  const body = {
    ok: true,
    comps: [{ distance_mi: 0.3, similarity: 82 }],
    saleHistory: [{ price: 310_000, date: "2019-06-14" }],
    marketContext: { median_dom: 21 },
    valuation: {
      mid: 455_000,
      divergence_pct: 6.5,
      methods: [{ value: 450_000 }],
      confidence_signals: { tier: "high", count: 6, nearest_mi: 0.2 },
    },
    pricing: WIRE_PRICING,
    active_model: { expected_dom_q50: 19, cut_probability: 0.68 },
    subject: { list_price: 475_000, active_model: { expected_dom_q50: 19, cut_probability: 0.68 } },
    facts: { address: "x", active_model: { expected_dom_q50: 19, cut_probability: 0.68 } },
  };
  const out = redactEvidence(body) as Record<string, unknown>;
  assert.equal(out.locked, true);
  assert.equal("pricing" in out, false, "pricing is Pro evidence");
  assert.equal("active_model" in out, false, "top-level active_model is Pro evidence");
  assert.equal(
    (out.subject as Record<string, unknown>).list_price,
    475_000,
    "other subject fields survive",
  );
  assert.equal("active_model" in (out.subject as Record<string, unknown>), false);
  assert.equal("active_model" in (out.facts as Record<string, unknown>), false);
  assert.deepEqual(
    (out.valuation as Record<string, unknown>).confidence_signals,
    { tier: "high", count: 6, nearest_mi: 0.2 },
    "the tier's evidence line survives redaction like compsSummary does",
  );
  // The original body is never mutated (pure-function contract).
  assert.deepEqual(body.pricing, WIRE_PRICING);
  assert.equal(body.subject.active_model.expected_dom_q50, 19);
});
