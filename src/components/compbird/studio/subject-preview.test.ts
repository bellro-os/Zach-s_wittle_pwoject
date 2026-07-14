/**
 * Tests for the progressive-first-paint preview state (subject-preview.tsx):
 *
 *  - buildSubjectPreview: a match-carrying selection yields the preview
 *    payload (the facts painted early); an identity-only selection (deep
 *    link seed / retry / recents chip) yields null ⇒ the skeleton path.
 *  - previewReducer: "start" paints a lookup's preview stamped with its
 *    subject epoch; the shared subject-change reset clears it; a straggler
 *    "settled" for a superseded epoch can NOT blank the newer lookup's paint;
 *    a failed/finished lookup's own "settled" clears it.
 *
 * The epochs come from the real createSubjectSession so the test binds the
 * preview lifecycle to the exact epoch machinery the studio stamps every
 * async lookup with.
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/subject-preview.test.ts
 *
 * Same module-hook idiom as comp-studio.leak.test.ts: stub CSS imports so the
 * component graph loads under plain Node.
 */
import { createRequire, register } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";
import type { PropertyMatch } from "@/lib/compbird/types";

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
async function loadPreview() {
  return await import("./subject-preview");
}
async function loadStudio() {
  return await import("./comp-studio");
}

/** A full search-suggestion match — what the SearchBar hands select(). */
const MATCH: PropertyMatch = {
  source: "mls",
  address: "1203 Walnut Ridge Road, Christiansburg, VA 24073",
  city: "Christiansburg",
  county: "Montgomery",
  parcel_id: "230322",
  sqft: 2096,
  bedrooms: 4,
  full_baths: 2,
  half_baths: 1,
  acres: 0.4,
  year_built: 1998,
  status: "Closed",
};

test("match-carrying selection → preview payload with the early-paint facts", async () => {
  const { buildSubjectPreview } = await loadPreview();
  const data = buildSubjectPreview(MATCH);
  assert.ok(data, "a full PropertyMatch must yield a preview");
  assert.equal(data.address, "1203 Walnut Ridge Road, Christiansburg, VA 24073");
  assert.equal(data.parcelId, "230322");
  assert.equal(data.city, "Christiansburg");
  assert.equal(data.county, "Montgomery");
  assert.equal(data.status, "Closed");
  assert.equal(data.sqft, 2096);
  assert.equal(data.bedrooms, 4);
  assert.equal(data.fullBaths, 2);
  assert.equal(data.halfBaths, 1);
  assert.equal(data.acres, 0.4);
  assert.equal(data.yearBuilt, 1998);

  // Sparse but real: one known fact beyond identity is enough to paint.
  const sparse = buildSubjectPreview({
    address: "114 Orchard Drive, Narrows, VA 24124",
    parcel_id: "8247",
    county: "Giles",
  });
  assert.ok(sparse, "a single enrichment fact still previews");
  assert.equal(sparse.county, "Giles");
  assert.equal(sparse.sqft, null, "unknown facts are null, never invented");
});

test("identity-only / degenerate selections → null ⇒ the skeleton path", async () => {
  const { buildSubjectPreview } = await loadPreview();

  // The deep-link seed, the failure banner's retry, and a recents chip all
  // carry exactly {address, parcel_id} — no preview, the skeleton names the
  // address instead.
  assert.equal(
    buildSubjectPreview({ address: "509 Jefferson St, Blacksburg", parcel_id: "P1" }),
    null,
  );

  // Empty-string facts are absence, not enrichment.
  assert.equal(
    buildSubjectPreview({
      address: "509 Jefferson St, Blacksburg",
      parcel_id: "P1",
      city: "  ",
      county: "",
      status: "",
    }),
    null,
  );

  // No address ⇒ nothing to headline ⇒ never a preview (parcel-only deep link).
  assert.equal(buildSubjectPreview({ address: "   ", parcel_id: "P1", city: "Blacksburg" }), null);
});

test("reducer: start paints; the shared subject-change reset (epoch bump path) clears", async () => {
  const { previewReducer, INITIAL_PREVIEW_STATE, buildSubjectPreview } = await loadPreview();
  const { createSubjectSession } = await loadStudio();
  const session = createSubjectSession();

  // A lookup starts: the studio bumps the epoch via the ONE shared reset
  // (beginSubjectChange dispatches "reset"), then dispatches "start".
  const epochA = session.beginSubjectChange();
  let state = previewReducer(INITIAL_PREVIEW_STATE, { type: "reset" });
  state = previewReducer(state, {
    type: "start",
    epoch: epochA,
    data: buildSubjectPreview(MATCH),
    address: MATCH.address,
  });
  assert.ok(state.data, "the lookup's known facts are on the board");
  assert.equal(state.epoch, epochA);

  // The user switches subjects mid-flight: beginSubjectChange bumps the epoch
  // and dispatches "reset" — the preview is cleared unconditionally.
  session.beginSubjectChange();
  state = previewReducer(state, { type: "reset" });
  assert.equal(state.data, null, "epoch bump (subject change) clears the preview");
  assert.equal(state.address, null, "no orphaned skeleton headline either");
});

test("reducer: a superseded lookup's settle can't blank the newer paint; failure clears its own", async () => {
  const { previewReducer, INITIAL_PREVIEW_STATE, buildSubjectPreview } = await loadPreview();
  const { createSubjectSession } = await loadStudio();
  const session = createSubjectSession();

  // Lookup A starts…
  const epochA = session.beginSubjectChange();
  let state = previewReducer(INITIAL_PREVIEW_STATE, {
    type: "start",
    epoch: epochA,
    data: buildSubjectPreview(MATCH),
    address: MATCH.address,
  });

  // …then the user picks B before A settles (reset + start with the new epoch).
  const epochB = session.beginSubjectChange();
  state = previewReducer(state, { type: "reset" });
  const dataB = buildSubjectPreview({
    address: "114 Orchard Drive, Narrows, VA 24124",
    parcel_id: "8247",
    city: "Narrows",
    county: "Giles",
    sqft: 2433,
    bedrooms: 3,
    status: "Closed",
  });
  state = previewReducer(state, {
    type: "start",
    epoch: epochB,
    data: dataB,
    address: "114 Orchard Drive, Narrows, VA 24124",
  });

  // A's fetch finally stands down (its finally dispatches settled with A's
  // epoch, unguarded — the reducer must refuse the stale settle).
  const afterStale = previewReducer(state, { type: "settled", epoch: epochA });
  assert.equal(afterStale.data, dataB, "a stale settle must not blank B's preview");
  assert.equal(afterStale.address, "114 Orchard Drive, Narrows, VA 24124");

  // B fails (or resolves) — ITS settle clears the preview, so the failure
  // banner / resolved report never sits under an orphaned preview.
  const settled = previewReducer(afterStale, { type: "settled", epoch: epochB });
  assert.equal(settled.data, null, "the owning lookup's settle clears the preview");
  assert.equal(settled.address, null);

  // Idempotent: settling again (or resetting) on an empty state is a no-op
  // that keeps referential identity (no useless re-render).
  assert.equal(previewReducer(settled, { type: "settled", epoch: epochB }), settled);
  assert.equal(previewReducer(settled, { type: "reset" }), settled);
});

test("reducer: an identity-only lookup still tracks the address for the skeleton headline", async () => {
  const { previewReducer, INITIAL_PREVIEW_STATE } = await loadPreview();

  // Deep link / retry: no preview data, but the skeleton names the address.
  let state = previewReducer(INITIAL_PREVIEW_STATE, {
    type: "start",
    epoch: 7,
    data: null,
    address: "509 Jefferson St, Blacksburg",
  });
  assert.equal(state.data, null, "identity-only ⇒ skeleton path");
  assert.equal(state.address, "509 Jefferson St, Blacksburg");

  // Cancel (Escape) resets — the headline goes with it.
  state = previewReducer(state, { type: "reset" });
  assert.equal(state.address, null);
});
