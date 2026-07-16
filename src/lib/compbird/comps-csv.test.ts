/**
 * Unit tests for the single-report comps CSV export (comps-csv.ts) — column
 * contract, honest blanks, the formula-injection guard (duplicated from the
 * portfolio's csvCell — keep the two in sync), and the download filename.
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/lib/compbird/comps-csv.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileComp } from "@/lib/compbird/types";
import { buildCompsCsv, compsCsvFilename, COMPS_CSV_HEADER } from "./comps-csv";

/** Minimal honest comp fixture — every field the builder reads, defaulted null. */
function comp(extra: Partial<ProfileComp>): ProfileComp {
  return {
    address: "509 Jefferson St, Blacksburg, VA 24060",
    city: "Blacksburg",
    subdivision: null,
    sold_price: null,
    ppsf: null,
    sqft: null,
    acres: null,
    beds: null,
    baths: null,
    year_built: null,
    close_date: null,
    dom: null,
    distance_mi: null,
    lat: null,
    lng: null,
    pending: false,
    atypical: false,
    ...extra,
  };
}

test("header row matches the contract column order", () => {
  const out = buildCompsCsv([]);
  assert.equal(out, COMPS_CSV_HEADER);
});

test("figures land in their columns; unknowns stay empty, never zero", () => {
  const out = buildCompsCsv([
    comp({
      sold_price: 455000,
      ppsf: 270.4,
      sqft: 1810,
      beds: 4,
      baths: 2.5,
      year_built: 2017,
      close_date: "2026-05-01",
      dom: 12,
      distance_mi: 0.348,
      similarity: 81.6,
      source: "mls",
      pending: true,
      atypical: true,
    }),
  ]);
  const row = out.split("\r\n")[1];
  assert.equal(
    row,
    '"509 Jefferson St, Blacksburg, VA 24060",Blacksburg,,455000,270,1810,,4,2.5,2017,2026-05-01,12,0.3,82,mls,pending atypical',
  );
  // A fully-unknown comp keeps its identity and leaves every figure blank.
  const blank = buildCompsCsv([comp({ address: "1 Main St" })]).split("\r\n")[1];
  assert.equal(blank, "1 Main St,Blacksburg,,,,,,,,,,,,,,");
});

test("formula-injection guard: leading =+-@ in feed strings is neutralized", () => {
  const out = buildCompsCsv([
    comp({ address: '=HYPERLINK("http://evil")', subdivision: "@import" }),
  ]);
  const row = out.split("\r\n")[1];
  assert.ok(row.startsWith(`"'=HYPERLINK(""http://evil"")"`));
  assert.ok(row.includes(",'@import,"));
});

test("filename slugs the street line with a local date", () => {
  const d = new Date(2026, 6, 15); // Jul 15 2026, local
  assert.equal(
    compsCsvFilename("509 Jefferson St, Blacksburg, VA 24060", d),
    "comps-509-jefferson-st-2026-07-15.csv",
  );
  assert.equal(compsCsvFilename(null, d), "comps-2026-07-15.csv");
});
