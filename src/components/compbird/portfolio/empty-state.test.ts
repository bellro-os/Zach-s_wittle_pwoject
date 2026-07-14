/**
 * Portfolio first-visit empty state — the visibility predicate and the "Try an
 * example" fill. The predicate is pure (csv.ts) so the panel's show/hide logic
 * is exercised without React; the fill test proves the three ghost lines
 * round-trip through the REAL textarea parser into a 3-item queue with the
 * labeled line keeping its label (the whole point of showing a label column).
 *
 * The repo has no test runner — plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/portfolio/empty-state.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  showPortfolioEmptyState,
  parseAddressLines,
  buildQueue,
  PORTFOLIO_EXAMPLE_LINES,
  PORTFOLIO_EXAMPLE_TEXT,
} from "./csv";

test("empty state shows only on a truly untouched first visit", () => {
  assert.equal(showPortfolioEmptyState({ hasRuns: false, text: "", csvCount: 0 }), true);
  // Whitespace is not typing.
  assert.equal(showPortfolioEmptyState({ hasRuns: false, text: "  \n ", csvCount: 0 }), true);
});

test("any typed content hides it", () => {
  assert.equal(showPortfolioEmptyState({ hasRuns: false, text: "509 Jeff", csvCount: 0 }), false);
});

test("a parsed CSV hides it", () => {
  assert.equal(showPortfolioEmptyState({ hasRuns: false, text: "", csvCount: 3 }), false);
});

test("any previous run hides it", () => {
  assert.equal(showPortfolioEmptyState({ hasRuns: true, text: "", csvCount: 0 }), false);
});

test("the example fill parses to a 3-item queue, labeled line keeps its label", () => {
  const entries = parseAddressLines(PORTFOLIO_EXAMPLE_TEXT);
  assert.equal(entries.length, PORTFOLIO_EXAMPLE_LINES.length);

  // Plain lines: whole line is the address, no label.
  assert.equal(entries[0].address, "509 Jefferson St, Blacksburg, VA 24060");
  assert.equal(entries[0].label, undefined);

  // The CSV-style third line: quoted address + label column, clearly example-marked.
  assert.equal(entries[2].address, "612 Amherst Ave, Blacksburg, VA 24060");
  assert.match(entries[2].label ?? "", /example/i);

  // And it survives the dedupe/cap queue builder intact.
  const queue = buildQueue(entries);
  assert.equal(queue.items.length, 3);
  assert.equal(queue.duplicates, 0);
  assert.equal(queue.trimmed, 0);
});

test("ordinary comma-bearing addresses are NOT mistaken for CSV rows", () => {
  const [entry] = parseAddressLines("1203 Walnut Ridge Rd, Christiansburg, VA 24073");
  assert.equal(entry.address, "1203 Walnut Ridge Rd, Christiansburg, VA 24073");
  assert.equal(entry.label, undefined);
});
