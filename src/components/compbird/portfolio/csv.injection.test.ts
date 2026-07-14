/**
 * CSV formula-injection guard (launch security review 2026-07, P1 fix).
 *
 * Contract under test: buildResultsCsv neutralizes user-supplied STRING cells
 * (label / address / parcel) that start with a spreadsheet formula trigger
 * (= + - @, or a tab/CR-smuggled variant) by prefixing a single quote, while
 * numeric figure columns and ordinary text pass through byte-identically.
 *
 * The repo has no test runner — plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/portfolio/csv.injection.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildResultsCsv, RESULTS_CSV_HEADER } from "./csv";
import type { PortfolioItemDto } from "@/lib/compbird/portfolio";

function item(overrides: Partial<PortfolioItemDto>): PortfolioItemDto {
  return {
    id: "it_1",
    position: 0,
    label: null,
    inputAddress: "509 Jefferson St, Blacksburg, VA 24060",
    inputParcelId: null,
    status: "done",
    resolvedAddress: null,
    parcelId: null,
    mid: 400000,
    low: 380000,
    high: 420000,
    confidenceTier: "high",
    caution: null,
    compCount: 6,
    nearestMi: 0.42,
    avgMatch: 81,
    error: null,
    ...overrides,
  } as PortfolioItemDto;
}

function rowOf(csv: string, index = 1): string {
  return csv.split("\r\n")[index];
}

test("a =formula label is neutralized with a leading quote", () => {
  const csv = buildResultsCsv([
    item({ label: '=HYPERLINK("http://evil.test","click")' }),
  ]);
  const row = rowOf(csv);
  // Quote-prefixed, then RFC-4180 quoted because it contains commas/quotes.
  assert.ok(row.startsWith(`"'=HYPERLINK(`), `row was: ${row}`);
  assert.ok(!row.startsWith("="), "raw formula must never lead a cell");
});

test("each formula trigger character is neutralized in string cells", () => {
  for (const lead of ["=", "+", "-", "@", "\t", "\r"]) {
    const csv = buildResultsCsv([item({ label: `${lead}cmd` })]);
    const cell = rowOf(csv).split(",")[0];
    const unquoted = cell.startsWith('"') ? cell.slice(1, -1).replace(/""/g, '"') : cell;
    assert.equal(
      unquoted[0],
      "'",
      `label starting with ${JSON.stringify(lead)} must be quote-prefixed (cell: ${JSON.stringify(cell)})`,
    );
  }
});

test("addresses and parcel ids get the same guard", () => {
  const csv = buildResultsCsv([
    item({ resolvedAddress: "@import(evil)", parcelId: "=1+1" }),
  ]);
  const cols = rowOf(csv).split(",");
  assert.equal(cols[1], "'@import(evil)");
  assert.equal(cols[2], "'=1+1");
});

test("numeric figures are untouched (no quote prefix on numbers)", () => {
  // Comma-free address so the naive split below stays column-aligned.
  const csv = buildResultsCsv([item({ inputAddress: "509 Jefferson St", mid: -5, low: 380000 })]);
  const cols = rowOf(csv).split(",");
  // mid is column index 3 per the header contract.
  assert.equal(RESULTS_CSV_HEADER.split(",")[3], "mid");
  assert.equal(cols[3], "-5", "numbers pass through verbatim, even negative");
});

test("ordinary labels and addresses are byte-identical to before", () => {
  const csv = buildResultsCsv([
    item({ label: "Rental unit 4", resolvedAddress: "612 Amherst Ave, Blacksburg, VA 24060" }),
  ]);
  const row = rowOf(csv);
  assert.ok(row.startsWith("Rental unit 4,"));
  assert.ok(row.includes('"612 Amherst Ave, Blacksburg, VA 24060"'));
  assert.ok(!row.includes("'612"), "plain text must not gain a quote prefix");
});

test("empty / pending rows still render honest blanks", () => {
  // Comma-free address so the naive split below stays column-aligned.
  const csv = buildResultsCsv([item({ inputAddress: "509 Jefferson St", status: "error", label: null })]);
  const cols = rowOf(csv).split(",");
  assert.equal(cols[0], "");
  assert.equal(cols[3], "");
});
