/**
 * Unit tests for the Match-chip affordance + copy pass (2026-07):
 *
 * HINT GATE — the one-time "Tap any match score to see why." line
 * (comps-table.tsx pure helpers, same storage-injected idiom as the studio's
 * demo gate):
 *   - shows at most once per browser, and ONLY on a live (tunable) scored table
 *   - sample/read-only and unscored tables never show it — and never write
 *   - unreadable/unwritable storage fails safe (never show, never throw)
 *
 * AFFORDANCE — renderToStaticMarkup fixtures:
 *   - the Match trigger reads tappable: cursor-pointer, the ember hover-border
 *     shift, the disclosure chevron glyph, aria-expanded wired (closed=false)
 *   - the hint line ships the exact copy + marker, and never appears in server
 *     markup (client-effect only — no hydration flash, nothing on sample)
 *   - an unscored set grows no Match column and no trigger at all
 *
 * COPY — the de-jargoned strings render (and the old jargon does not):
 *   - valuation-panel tuning ticker "Suggested comps $X → your set $Y" +
 *     "Reset to suggested comps" (was "Engine set … yours …" / "…engine picks")
 *   - pricing-strategy anchor tag "Market value" (was "Anchor")
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/comps-table.match-hint.test.ts
 *
 * Same module-hook idiom as valuation-panel.delta.test.ts: stub any CSS import
 * riding the component graph so it loads under plain Node.
 */
import { createRequire, register } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ProfileComp, Valuation, MarketContext } from "@/lib/compbird/types";

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

/** Import the real modules AFTER the css hook is registered. */
async function loadTable() {
  return await import("./comps-table");
}

/** In-memory HintFlagStore — what localStorage is to the browser wiring. */
function fakeStore() {
  const data = new Map<string, string>();
  return {
    data,
    get: (k: string) => data.get(k) ?? null,
    set: (k: string, v: string) => void data.set(k, v),
  };
}

/** Honest comp fixture — every field the table actually renders. */
function comp(address: string, extra?: Partial<ProfileComp>): ProfileComp {
  return {
    address,
    city: null,
    subdivision: null,
    sold_price: 450_000,
    ppsf: 210,
    sqft: 2_100,
    acres: null,
    beds: 3,
    baths: 2,
    year_built: 1999,
    close_date: "2026-03-14",
    dom: 12,
    distance_mi: 0.4,
    lat: null,
    lng: null,
    pending: false,
    atypical: false,
    ...extra,
  } as ProfileComp;
}

/* ── The hint gate (pure) ──────────────────────────────────────────────────── */

test("hint gate: shows exactly once per browser, on a live scored table", async () => {
  const { shouldShowMatchHint, markMatchHintShown, MATCH_HINT_KEY } = await loadTable();
  const store = fakeStore();

  assert.equal(
    shouldShowMatchHint({ live: true, scored: true, store }),
    true,
    "fresh browser + live scored table ⇒ show",
  );

  // The component writes the flag the moment the hint renders.
  markMatchHintShown(store);
  assert.equal(store.get(MATCH_HINT_KEY), "shown", "the cb-* flag is written");
  assert.equal(
    shouldShowMatchHint({ live: true, scored: true, store }),
    false,
    "never a second time for this browser",
  );
});

test("hint gate: never on sample/read-only or unscored tables — and never writes", async () => {
  const { shouldShowMatchHint } = await loadTable();
  const store = fakeStore();

  assert.equal(
    shouldShowMatchHint({ live: false, scored: true, store }),
    false,
    "sample/read-only (no onToggle) ⇒ no hint",
  );
  assert.equal(
    shouldShowMatchHint({ live: true, scored: false, store }),
    false,
    "unscored set (no Match column) ⇒ no hint",
  );
  assert.equal(store.data.size, 0, "ineligible renders must not burn the once-per-browser flag");

  // ...so the hint is still available the first time a live scored table shows.
  assert.equal(shouldShowMatchHint({ live: true, scored: true, store }), true);
});

test("hint gate: broken storage fails safe — never show, never throw", async () => {
  const { shouldShowMatchHint, markMatchHintShown } = await loadTable();
  const broken = {
    get: () => {
      throw new Error("storage disabled");
    },
    set: () => {
      throw new Error("storage disabled");
    },
  };

  assert.equal(
    shouldShowMatchHint({ live: true, scored: true, store: broken }),
    false,
    "can't prove once-per-browser ⇒ never show",
  );
  assert.doesNotThrow(() => markMatchHintShown(broken));
});

/* ── The trigger affordance (fixture renders) ──────────────────────────────── */

test("Match trigger reads tappable: cursor, hover border shift, chevron, aria-expanded", async () => {
  const { CompsTable } = await loadTable();

  const html = renderToStaticMarkup(
    createElement(CompsTable, {
      comps: [comp("101 Larkspur Ln", { similarity: 91 }), comp("14 Bluff Rd", { similarity: 62 })],
      onToggle: () => {},
    }),
  );

  assert.ok(html.includes("cursor-pointer"), "pointer cursor on the trigger");
  assert.ok(
    html.includes("hover:border-[var(--cb-ember)]/40"),
    "hover treatment shifts the border in the existing token vocabulary",
  );
  assert.ok(html.includes("border-transparent"), "transparent placeholder border — no hover layout shift");
  assert.ok(html.includes('data-cb-match-glyph=""'), "disclosure chevron glyph present");
  assert.ok(html.includes('aria-expanded="false"'), "aria-expanded wired to the (closed) popover state");
  assert.ok(html.includes('aria-haspopup="dialog"'), "dialog semantics preserved");
});

test("hint line: exact quiet copy — and never in server markup (client-effect only)", async () => {
  const { CompsTable, MatchHintLine, MATCH_HINT_TEXT } = await loadTable();

  const line = renderToStaticMarkup(createElement(MatchHintLine));
  assert.ok(line.includes("Tap any match score to see why."), "the shipped hint copy");
  assert.equal(MATCH_HINT_TEXT, "Tap any match score to see why.");
  assert.ok(line.includes('data-cb-match-hint=""'), "marker for the studio/report wiring");
  assert.ok(line.includes("text-muted-foreground"), "quiet — muted, not a banner");

  // Server render of even a LIVE scored table never carries the hint: it is
  // gated behind a client effect (no hydration flash, nothing on sample —
  // sample tables additionally fail the live gate).
  const html = renderToStaticMarkup(
    createElement(CompsTable, {
      comps: [comp("101 Larkspur Ln", { similarity: 91 })],
      onToggle: () => {},
    }),
  );
  assert.ok(!html.includes("data-cb-match-hint"), "no hint in static/server markup");
  assert.ok(!html.includes(MATCH_HINT_TEXT), "no hint copy in static/server markup");
});

test("unscored set: no Match column, no trigger, no aria-expanded", async () => {
  const { CompsTable } = await loadTable();

  const html = renderToStaticMarkup(
    createElement(CompsTable, {
      comps: [comp("101 Larkspur Ln"), comp("14 Bluff Rd")],
      onToggle: () => {},
    }),
  );

  assert.ok(!html.includes(">Match<"), "no Match header without engine scores");
  assert.ok(!html.includes("aria-expanded"), "no popover trigger without a score");
  assert.ok(!html.includes("data-cb-match-glyph"), "no chevron without a score");
});

/* ── The de-jargoned copy (fixture renders) ────────────────────────────────── */

test("valuation panel tuning readout speaks realtor: suggested comps, not engine sets", async () => {
  const { ValuationPanel } = await import("./valuation-panel");

  const valuation: Valuation = {
    mid: 470_000,
    low: 450_000,
    high: 490_000,
    comp_ppsf: 210,
    implied_subject_ppsf: null,
    divergence_pct: null,
    methods: [
      { name: "Direct comparison", value: 468_000, rationale: "" },
      { name: "$/sqft benchmark", value: 472_000, rationale: "" },
    ],
  };

  const html = renderToStaticMarkup(
    createElement(ValuationPanel, {
      valuation,
      compCount: 6,
      nearestMi: 0.2,
      farthestMi: 0.6,
      subjectKey: "A",
      engineMid: 455_000,
      tunedCount: 1,
      onResetTuning: () => {},
    }),
  );

  assert.ok(html.includes("Suggested comps"), "ticker leads with the suggested set");
  assert.ok(html.includes("your set"), "…against the agent's set");
  assert.ok(html.includes("Reset to suggested comps"), "reset chip copy");
  assert.ok(!html.includes("Engine set"), "old jargon gone from the ticker");
  assert.ok(!html.includes("Reset to engine picks"), "old jargon gone from the chip");
  assert.ok(html.includes("How we got this number"), "method-breakdown heading de-jargoned");
  assert.ok(!html.includes("triangulated"), "no 'triangulated' in the studio panel");
});

test("pricing strategy: the anchor band is tagged 'Market value', never 'Anchor'", async () => {
  const { PricingStrategy } = await import("./pricing-strategy");

  const valuation = {
    mid: 450_000,
    low: 430_000,
    high: 470_000,
    comp_ppsf: 210,
    implied_subject_ppsf: null,
    divergence_pct: null,
    methods: [],
  } as Valuation;
  const marketContext = {
    ppsf_median: 210,
    ppsf_trend: null,
    median_dom: 14,
    active_count: 40,
    sold_count: 22,
    months_of_inventory: 2.4,
    scope: "Walnut Creek",
  } as MarketContext;

  const html = renderToStaticMarkup(
    createElement(PricingStrategy, { valuation, marketContext, areaName: "Walnut Creek" }),
  );

  assert.ok(html.includes("Market value"), "anchor tag speaks realtor");
  assert.ok(!html.includes("Anchor"), "the engineering tag is gone");
  assert.ok(html.includes("A directional estimate, not a guarantee."), "disclosure stays a disclosure");
});
