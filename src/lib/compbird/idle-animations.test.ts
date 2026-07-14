/**
 * Unit test for the decorative-animation governor (idle-animations.ts): the
 * `data-cb-anim-paused` attribute must appear on the root element when the
 * tab hides OR the user idles past the threshold, and disappear again on
 * return/interaction. Cleanup must detach everything and lift the pause.
 *
 * The repo has no test runner — this is plain `node:test`, run with:
 *
 *   npx tsx src/lib/compbird/idle-animations.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { setTimeout as sleep } from "node:timers/promises";
import {
  startAnimationGovernor,
  ANIM_PAUSED_ATTR,
  ACTIVITY_EVENTS,
  type GovernorDocument,
} from "./idle-animations";

/** Structural stand-in for `document` — records attributes + listeners. */
class FakeDoc implements GovernorDocument {
  hidden = false;
  attrs = new Map<string, string>();
  listeners = new Map<string, Set<() => void>>();
  documentElement = {
    setAttribute: (name: string, value: string) => void this.attrs.set(name, value),
    removeAttribute: (name: string) => void this.attrs.delete(name),
  };
  addEventListener(type: string, listener: () => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }
  removeEventListener(type: string, listener: () => void) {
    this.listeners.get(type)?.delete(listener);
  }
  dispatch(type: string) {
    for (const l of this.listeners.get(type) ?? []) l();
  }
  paused() {
    return this.attrs.has(ANIM_PAUSED_ATTR);
  }
  listenerCount() {
    let n = 0;
    for (const set of this.listeners.values()) n += set.size;
    return n;
  }
}

// Short idle threshold so the tests run in milliseconds; the production
// default (IDLE_AFTER_MS = 30s) is just the same timer with a bigger number.
const IDLE = 40;

test("visibilitychange: pauses while the tab is hidden, resumes on return", () => {
  const doc = new FakeDoc();
  const stop = startAnimationGovernor(doc, IDLE);

  assert.equal(doc.paused(), false, "visible + fresh ⇒ running");

  doc.hidden = true;
  doc.dispatch("visibilitychange");
  assert.equal(doc.paused(), true, "hidden tab ⇒ paused");

  doc.hidden = false;
  doc.dispatch("visibilitychange");
  assert.equal(doc.paused(), false, "returning to the tab resumes immediately");

  stop();
});

test("idle: settles after the threshold with no input, resumes on the next interaction", async () => {
  const doc = new FakeDoc();
  const stop = startAnimationGovernor(doc, IDLE);

  assert.equal(doc.paused(), false);
  await sleep(IDLE + 30);
  assert.equal(doc.paused(), true, "no input past the threshold ⇒ settled");

  doc.dispatch("pointermove");
  assert.equal(doc.paused(), false, "interaction resumes the loops");

  // Activity keeps re-arming the timer — no pause while the user keeps moving.
  await sleep(IDLE / 2);
  doc.dispatch("keydown");
  await sleep(IDLE / 2);
  doc.dispatch("scroll");
  assert.equal(doc.paused(), false, "steady activity never lets the timer fire");

  await sleep(IDLE + 30);
  assert.equal(doc.paused(), true, "goes idle again once input stops");

  stop();
});

test("hidden time is not idle time: returning to the tab restarts a fresh idle clock", async () => {
  const doc = new FakeDoc();
  const stop = startAnimationGovernor(doc, IDLE);

  doc.hidden = true;
  doc.dispatch("visibilitychange");
  await sleep(IDLE + 30); // longer than the idle threshold, but hidden
  doc.hidden = false;
  doc.dispatch("visibilitychange");
  assert.equal(doc.paused(), false, "return ⇒ running, even after a long hide");

  await sleep(IDLE + 30);
  assert.equal(doc.paused(), true, "the fresh clock still settles on schedule");

  stop();
});

test("interaction while hidden does not resume a hidden tab", () => {
  const doc = new FakeDoc();
  const stop = startAnimationGovernor(doc, IDLE);

  doc.hidden = true;
  doc.dispatch("visibilitychange");
  doc.dispatch("pointermove"); // e.g. a stray event while backgrounded
  assert.equal(doc.paused(), true, "hidden wins over activity");

  stop();
});

test("every activity event is wired, and cleanup detaches all listeners + lifts the pause", async () => {
  const doc = new FakeDoc();
  const stop = startAnimationGovernor(doc, IDLE);

  for (const type of ACTIVITY_EVENTS) {
    assert.equal(
      (doc.listeners.get(type)?.size ?? 0) > 0,
      true,
      `listener attached for "${type}"`,
    );
  }
  assert.equal((doc.listeners.get("visibilitychange")?.size ?? 0) > 0, true);

  await sleep(IDLE + 30);
  assert.equal(doc.paused(), true);

  stop();
  assert.equal(doc.paused(), false, "cleanup lifts the pause attribute");
  assert.equal(doc.listenerCount(), 0, "cleanup removes every listener");

  // The cancelled timer must not fire after cleanup.
  await sleep(IDLE + 30);
  assert.equal(doc.paused(), false);
});
