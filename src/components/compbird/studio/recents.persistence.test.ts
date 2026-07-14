/**
 * Persistence + migration tests for session recents (recents.tsx) — the
 * enriched schema (a resolved-facts snapshot stored alongside identity) that
 * powers the instant subject preview on a re-pick:
 *
 *  - READ COMPAT: entries written by the previous identity-only schema load
 *    unchanged (no crash, no wipe) and re-pick as identity-only selections —
 *    the plain-skeleton path, exactly as before;
 *  - ENRICHED WRITE: pushRecent stores the resolved profile's facts snapshot,
 *    sanitized (junk → null, all-null → omitted), inside the existing cap;
 *  - RE-PICK: toSelection(entry) yields a LookupSelection whose
 *    buildSubjectPreview (imported from subject-preview.tsx — untouched)
 *    returns a NON-NULL payload carrying the stored facts ⇒ the wave-2
 *    preview machinery paints on re-pick;
 *  - PALETTE PARITY: the chip row and the Cmd-K palette rows build their
 *    selection through the SAME exported toSelection — asserted functionally
 *    and structurally (no identity-literal onPick call site remains).
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/recents.persistence.test.ts
 *
 * Same module-hook idiom as the sibling suites (stub CSS imports so the
 * component graph loads under plain Node), plus a minimal `window` carrying an
 * in-memory localStorage: recents.tsx touches window only inside its helpers,
 * so installing the stub before the calls is sufficient.
 */
import { createRequire, register } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

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

/* ── window/localStorage stub (recents.tsx storage helpers need both) ──────── */

const mem = new Map<string, string>();
const localStorageStub = {
  getItem: (k: string) => (mem.has(k) ? (mem.get(k) as string) : null),
  setItem: (k: string, v: string) => {
    mem.set(k, String(v));
  },
  removeItem: (k: string) => {
    mem.delete(k);
  },
};
(globalThis as Record<string, unknown>).window = {
  localStorage: localStorageStub,
  dispatchEvent: () => true, // writeRecents announces on a custom Event
  addEventListener: () => {},
  removeEventListener: () => {},
};

const KEY = "cb-recents";
/** Mirrors recents.tsx's RECENTS_CAP — the cap the schema change must respect. */
const CAP = 10;

function seed(raw: unknown) {
  mem.set(KEY, JSON.stringify(raw));
}

/** Import the real modules AFTER the css hook + window stub are in place. */
async function loadRecents() {
  return await import("./recents");
}
async function loadPreview() {
  return await import("./subject-preview");
}

/** The resolved-profile snapshot the studio stores (ProfileFacts-derived). */
const WALNUT_FACTS = {
  sqft: 2096,
  bedrooms: 4,
  full_baths: 2,
  half_baths: 1,
  acres: 0.4,
  year_built: 1998,
  status: "Closed",
  city: "Christiansburg",
  county: "Montgomery",
  subdivision: "Walnut Ridge",
};

test("read compat: old identity-only entries load untouched — no crash, no wipe, skeleton re-pick", async () => {
  const { readRecents, toSelection } = await loadRecents();
  const { buildSubjectPreview } = await loadPreview();

  // Exactly what the previous schema persisted: identity + timestamp only.
  const oldShape = [
    { address: "509 Jefferson St, Blacksburg, VA 24060", parcel_id: "P1", at: 1_000 },
    { address: "114 Orchard Drive, Narrows, VA 24124", parcel_id: "", at: 900 },
  ];
  seed(oldShape);

  const entries = readRecents();
  assert.equal(entries.length, 2, "every old-shape entry survives the migration");
  assert.equal(entries[0].address, "509 Jefferson St, Blacksburg, VA 24060");
  assert.equal(entries[0].parcel_id, "P1");
  assert.equal(entries[0].facts, undefined, "old entries carry no facts snapshot");

  // Re-pick: identity-only selection ⇒ buildSubjectPreview null ⇒ the plain
  // skeleton path, exactly the pre-change behavior.
  const sel = toSelection(entries[0]);
  assert.deepEqual(sel, {
    address: "509 Jefferson St, Blacksburg, VA 24060",
    parcel_id: "P1",
  });
  assert.equal(buildSubjectPreview(sel), null, "old entry re-pick keeps the skeleton");

  // Read is read-only: the stored v1 payload was not rewritten or wiped.
  assert.equal(mem.get(KEY), JSON.stringify(oldShape), "no migration-on-read rewrite");
});

test("read compat: malformed facts are dropped, the entry is kept; junk entries filter as before", async () => {
  const { readRecents } = await loadRecents();

  seed([
    // v2 entry with a garbage snapshot — entry KEPT, facts dropped.
    { address: "A St", parcel_id: "PA", at: 3, facts: "garbage" },
    // v2 entry with junk-typed fields — junk → null, real fields survive.
    {
      address: "B St",
      parcel_id: "PB",
      at: 2,
      facts: { sqft: "2000", bedrooms: 3, city: "   ", year_built: Infinity },
    },
    // Identity broken — filtered out, as the old reader always did.
    { address: 42, parcel_id: "PC", at: 1 },
    // All-null snapshot — normalized to NO snapshot.
    { address: "D St", parcel_id: "PD", at: 0, facts: { sqft: null, city: null } },
  ]);

  const entries = readRecents();
  assert.equal(entries.length, 3, "only the identity-broken entry is dropped");
  assert.equal(entries[0].facts, undefined, "non-object facts blob is discarded");
  assert.deepEqual(
    entries[1].facts,
    {
      sqft: null, // was a string — junk, never coerced
      bedrooms: 3,
      full_baths: null,
      half_baths: null,
      acres: null,
      year_built: null, // Infinity is not a fact
      status: null,
      city: null, // whitespace is absence
      county: null,
      subdivision: null,
    },
    "junk fields null out, real fields survive",
  );
  assert.equal(entries[2].facts, undefined, "an all-null snapshot is stored as none");

  // Corrupt storage still degrades to empty, never a throw.
  mem.set(KEY, "{not json");
  assert.deepEqual(readRecents(), []);
  seed({ nope: true });
  assert.deepEqual(readRecents(), []);
});

test("enriched write: pushRecent stores the resolved-facts snapshot; all-null prunes; cap holds", async () => {
  const { pushRecent, readRecents } = await loadRecents();
  mem.delete(KEY);

  // The studio's select() success path: identity + the profile's facts.
  pushRecent({
    address: "1203 Walnut Ridge Road, Christiansburg, VA 24073",
    parcel_id: "230322",
    facts: WALNUT_FACTS,
  });
  let entries = readRecents();
  assert.equal(entries.length, 1);
  assert.deepEqual(entries[0].facts, WALNUT_FACTS, "the snapshot round-trips verbatim");
  assert.ok(
    (mem.get(KEY) as string).includes('"sqft":2096'),
    "the snapshot is actually persisted, not just in-memory",
  );

  // A snapshot with nothing on record is stored as NO snapshot.
  pushRecent({
    address: "2 Empty Facts Ln",
    parcel_id: "P-EMPTY",
    facts: { sqft: null, status: null },
  });
  entries = readRecents();
  assert.equal(entries[0].address, "2 Empty Facts Ln");
  assert.equal(entries[0].facts, undefined, "all-null snapshot pruned on write");
  const stored = JSON.parse(mem.get(KEY) as string) as Array<Record<string, unknown>>;
  assert.ok(!("facts" in stored[0]), "no facts key serialized for an empty snapshot");

  // The existing cap still applies with snapshots aboard (~200B each).
  for (let i = 0; i < 15; i++) {
    pushRecent({ address: `${i} Cap St`, parcel_id: `CAP-${i}`, facts: WALNUT_FACTS });
  }
  entries = readRecents();
  assert.equal(entries.length, CAP, "enriched entries respect the existing cap");
  assert.equal(entries[0].address, "14 Cap St", "newest first, as before");
});

test("re-pick: toSelection ⇒ buildSubjectPreview non-null with the STORED facts (the wave-2 preview paints)", async () => {
  const { pushRecent, readRecents, toSelection } = await loadRecents();
  const { buildSubjectPreview } = await loadPreview();
  mem.delete(KEY);

  pushRecent({
    address: "1203 Walnut Ridge Road, Christiansburg, VA 24073",
    parcel_id: "230322",
    facts: WALNUT_FACTS,
  });

  const sel = toSelection(readRecents()[0]);
  // The selection carries identity + every stored fact under PropertyMatch names.
  assert.equal(sel.address, "1203 Walnut Ridge Road, Christiansburg, VA 24073");
  assert.equal(sel.parcel_id, "230322");
  assert.equal(sel.sqft, 2096);
  assert.equal(sel.bedrooms, 4);

  const data = buildSubjectPreview(sel);
  assert.ok(data, "an enriched re-pick must yield a preview payload — not the skeleton");
  assert.equal(data.address, "1203 Walnut Ridge Road, Christiansburg, VA 24073");
  assert.equal(data.parcelId, "230322");
  assert.equal(data.city, "Christiansburg");
  assert.equal(data.county, "Montgomery");
  assert.equal(data.subdivision, "Walnut Ridge");
  assert.equal(data.status, "Closed");
  assert.equal(data.sqft, 2096);
  assert.equal(data.bedrooms, 4);
  assert.equal(data.fullBaths, 2);
  assert.equal(data.halfBaths, 1);
  assert.equal(data.acres, 0.4);
  assert.equal(data.yearBuilt, 1998);

  // Sparse snapshot: one known fact is enough to paint, unknowns stay null.
  pushRecent({
    address: "114 Orchard Drive, Narrows, VA 24124",
    parcel_id: "8247",
    facts: { county: "Giles" },
  });
  const sparse = buildSubjectPreview(toSelection(readRecents()[0]));
  assert.ok(sparse, "a single stored fact still previews");
  assert.equal(sparse.county, "Giles");
  assert.equal(sparse.sqft, null, "unknown facts are null, never invented");
});

test("re-resolve upgrades an old identity-only entry in place (same dedupe key)", async () => {
  const { pushRecent, readRecents } = await loadRecents();

  // A pre-snapshot browser: the entry has identity only.
  seed([{ address: "1203 Walnut Ridge Rd", parcel_id: "230322", at: 1_000 }]);

  // The same subject resolves again → select() pushes the enriched row; the
  // parcel-keyed dedupe replaces the old row instead of duplicating it.
  pushRecent({
    address: "1203 Walnut Ridge Road, Christiansburg, VA 24073",
    parcel_id: "230322",
    facts: WALNUT_FACTS,
  });
  const entries = readRecents();
  assert.equal(entries.length, 1, "dedupe by parcel — upgraded, not duplicated");
  assert.deepEqual(entries[0].facts, WALNUT_FACTS, "the old entry is now enriched");
});

test("palette parity: chip row and Cmd-K rows share ONE selection builder", async () => {
  const { toSelection } = await loadRecents();
  const { buildSubjectPreview } = await loadPreview();

  // Functionally: the same stored entry yields the identical selection — and
  // the identical preview payload — no matter which surface picks it, because
  // both funnel through toSelection.
  const entry = {
    address: "1203 Walnut Ridge Road, Christiansburg, VA 24073",
    parcel_id: "230322",
    at: 1_000,
    facts: WALNUT_FACTS,
  };
  const chipSelection = toSelection(entry);
  const paletteSelection = toSelection(entry);
  assert.deepEqual(paletteSelection, chipSelection);
  assert.deepEqual(
    buildSubjectPreview(paletteSelection),
    buildSubjectPreview(chipSelection),
  );

  // Structurally: every onPick call site in recents.tsx routes through
  // toSelection — the chip row AND the palette's pick() — and no
  // identity-literal call site survives to reintroduce the skeleton-only
  // re-pick. The wave-1 busy gate is still on both handlers.
  const src = readFileSync(
    fileURLToPath(new URL("./recents.tsx", import.meta.url)),
    "utf8",
  );
  const routed = src.match(/onPick\(toSelection\(/g) ?? [];
  assert.ok(
    routed.length >= 2,
    "both surfaces (chip row + palette pick) must call onPick(toSelection(…))",
  );
  assert.ok(
    !src.includes("onPick({"),
    "no identity-literal onPick call site may remain",
  );
  assert.ok(
    (src.match(/if \(pickBlocked\(busy\)\) return;/g) ?? []).length >= 2,
    "the busy gate still guards both pick handlers",
  );
});
