/**
 * Interaction-robustness tests (the demo gate, busy gating, live deep links).
 *
 * FIX 1 — demo autopilot gate: the observed live behavior (character-by-
 * character /api/compbird/search hits for "509 jefferson st" + auto-select)
 * has NO typing loop in this tree, so the studio enforces the user's side of
 * the contract: once-per-browser flag written the moment a demo starts, any
 * real interaction kills it permanently, live conditions refuse an auto-run,
 * and explicit ?demo=1 stays intentional.
 *
 * FIX 2 — busy gating: one shared predicate (`pickBlocked`) gates every
 * selection surface (preset chips, suggestion rows, recents chips, palette
 * rows) so they can never drift apart again.
 *
 * FIX 4 — live deep links: `planDeepLink` decides when a search-param change
 * routes into select() (which is the beginSubjectChange path) and when it is
 * ignored (mount double-render, params naming the subject already loaded).
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/components/compbird/studio/comp-studio.interaction.test.ts
 *
 * Same module-hook idiom as comp-studio.leak.test.ts: stub the one CSS import
 * riding the studio's component graph so it loads under plain Node.
 */
import { createRequire, register } from "node:module";
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileResult } from "@/lib/compbird/types";
import type { DemoFlagStore } from "./comp-studio";

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
async function loadStudio() {
  return await import("./comp-studio");
}
async function loadSearchBar() {
  return await import("./search-bar");
}

/** In-memory DemoFlagStore — what localStorage is to the browser wiring. */
function memStore(): DemoFlagStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    get: (k) => (data.has(k) ? (data.get(k) as string) : null),
    set: (k, v) => {
      data.set(k, v);
    },
  };
}

/** Every rule-(c) condition clear — the only state an auto-run may start in. */
const CLEAN = {
  inputHasContent: false,
  lookupInFlight: false,
  authedWithRecents: false,
  prefersReducedMotion: false,
};

/** Skeletal profile fixture — the session stores the base opaquely. */
function fakeProfile(address: string, mid: number): ProfileResult {
  return {
    ok: true,
    facts: { address, parcel_id: `P-${address}` },
    comps: [],
    valuation: { mid },
  } as unknown as ProfileResult;
}

test("demo gate: once per browser, killed forever by interaction, ?demo=1 stays forced", async () => {
  const { shouldAutoRunDemo, markDemoStarted, killDemo, demoAlreadyDone, DEMO_FLAG_KEY } =
    await loadStudio();

  // Fresh browser, clean conditions — an auto-run is allowed exactly once.
  const store = memStore();
  assert.equal(shouldAutoRunDemo({ forced: false, store, ...CLEAN }), true);

  // Rule (a): the flag is written the moment the demo STARTS → never again.
  markDemoStarted(store);
  assert.equal(store.data.get(DEMO_FLAG_KEY), "ran");
  assert.equal(shouldAutoRunDemo({ forced: false, store, ...CLEAN }), false);

  // Rule (b): a real user interaction (the studio's capture-phase keydown/
  // pointerdown/combobox-focus listeners call killDemo) is permanent.
  const store2 = memStore();
  killDemo(store2);
  assert.equal(demoAlreadyDone(store2), true);
  assert.equal(
    shouldAutoRunDemo({ forced: false, store: store2, ...CLEAN }),
    false,
    "an interacted-with browser must never auto-run the demo",
  );

  // Rule (d): explicit ?demo=1 forces through BOTH the ran and killed flags.
  assert.equal(shouldAutoRunDemo({ forced: true, store, ...CLEAN }), true);
  assert.equal(shouldAutoRunDemo({ forced: true, store: store2, ...CLEAN }), true);
});

test("demo gate: live conditions refuse an auto-run; broken storage fails safe", async () => {
  const { shouldAutoRunDemo } = await loadStudio();
  const store = memStore();

  // Rule (c), each condition alone is disqualifying.
  assert.equal(
    shouldAutoRunDemo({ forced: false, store, ...CLEAN, inputHasContent: true }),
    false,
    "input has content ⇒ no demo",
  );
  assert.equal(
    shouldAutoRunDemo({ forced: false, store, ...CLEAN, lookupInFlight: true }),
    false,
    "lookup in flight ⇒ no demo",
  );
  assert.equal(
    shouldAutoRunDemo({ forced: false, store, ...CLEAN, authedWithRecents: true }),
    false,
    "authenticated user with recents ⇒ no demo",
  );
  assert.equal(
    shouldAutoRunDemo({ forced: false, store, ...CLEAN, prefersReducedMotion: true }),
    false,
    "prefers-reduced-motion ⇒ no demo",
  );

  // Unreadable storage: once-per-browser can't be proven ⇒ never auto-run
  // (but the forced path is still intentional).
  const broken: DemoFlagStore = {
    get: () => {
      throw new Error("storage blocked");
    },
    set: () => {
      throw new Error("storage blocked");
    },
  };
  assert.equal(shouldAutoRunDemo({ forced: false, store: broken, ...CLEAN }), false);
  assert.equal(shouldAutoRunDemo({ forced: true, store: broken, ...CLEAN }), true);
});

test("busy gating: the one shared predicate every selection surface consumes", async () => {
  const { pickBlocked } = await loadSearchBar();
  // Dropdown rows, preset chips (search-bar.tsx) and recents chips + palette
  // rows (recents.tsx) all disable, dim, aria-disable AND guard their pick
  // handlers on this exact predicate — asymmetry is structurally gone.
  assert.equal(pickBlocked(true), true, "in-flight lookup gates every pick");
  assert.equal(pickBlocked(false), false, "idle studio accepts picks");
});

test("deep link: mount double-render fires once; param change selects; matching subject is ignored", async () => {
  const { planDeepLink, createSubjectSession } = await loadStudio();
  const s = createSubjectSession();

  // ── Initial mount with ?address= — the param must load, exactly once ─────
  const raw = { demo: null, address: "509 Jefferson St, Blacksburg", parcelId: null };
  const first = planDeepLink(raw, null, s.subject());
  assert.equal(first.action, "select");
  assert.equal(first.address, "509 Jefferson St, Blacksburg");

  // Applying the plan = select() = THE shared beginSubjectChange path.
  const epoch = s.beginSubjectChange();
  s.armSubject(
    epoch,
    { address: "509 Jefferson St, Blacksburg", parcelId: "P1" },
    fakeProfile("509 Jefferson St, Blacksburg", 400_000),
  );

  // Mount double-render / unrelated re-render, SAME params ⇒ no re-fire.
  const second = planDeepLink(raw, first.sig, s.subject());
  assert.equal(second.action, "none", "identical params must not re-fire");

  // ── LIVE param change while mounted ⇒ loads the new subject ──────────────
  const changed = planDeepLink(
    { demo: null, address: "1203 Walnut Ridge Rd, Christiansburg", parcelId: null },
    first.sig,
    s.subject(),
  );
  assert.equal(changed.action, "select", "a param CHANGE must load the new subject");

  // ── A param naming the CURRENT subject is ignored (case-insensitive), even
  // when the signature differs (e.g. returning to an old URL after in-studio
  // selections that never touched it) ───────────────────────────────────────
  const sameAddr = planDeepLink(
    { demo: null, address: "509 JEFFERSON ST, BLACKSBURG", parcelId: null },
    changed.sig,
    s.subject(),
  );
  assert.equal(sameAddr.action, "none", "current subject by address ⇒ ignored");
  const sameParcel = planDeepLink(
    { demo: null, address: null, parcelId: "p1" },
    changed.sig,
    s.subject(),
  );
  assert.equal(sameParcel.action, "none", "current subject by parcel id ⇒ ignored");

  // ── Empty/absent params never fire (in-studio selections stay URL-silent,
  // so this is the everyday steady state) ──────────────────────────────────
  const empty = planDeepLink({ demo: null, address: "   ", parcelId: null }, null, s.subject());
  assert.equal(empty.action, "none");

  // ── ?demo=1 routes to the demo branch, deduped like everything else ──────
  const demo = planDeepLink({ demo: "1", address: null, parcelId: null }, empty.sig, s.subject());
  assert.equal(demo.action, "demo");
  const demoAgain = planDeepLink({ demo: "1", address: null, parcelId: null }, demo.sig, s.subject());
  assert.equal(demoAgain.action, "none", "the demo branch dedupes on its signature too");
});
