/**
 * Billing tier-decision helpers (launch security review 2026-07, P2 #6/#7 fix).
 *
 * Contract under test: `tierDecisionFor` maps a LIVE Stripe subscription state
 * to the tier the account should hold — active/trialing grant the paid tier,
 * every other status (canceled, past_due, unpaid, incomplete, paused…) drops
 * to FREE. The webhook applies ONLY this decision (never the event snapshot),
 * so these cases are exactly the webhook's grant/downgrade behavior, including
 * what a replayed or out-of-order event converges to.
 *
 * Run with: npx tsx src/lib/billing-grant.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  firstPriceId,
  subscribedTier,
  tierDecisionFor,
  tierForPriceId,
  type SubscriptionLike,
} from "./billing-grant";

function sub(status: string, priceId?: string | null): SubscriptionLike {
  return {
    status,
    items: { data: [{ price: priceId === undefined ? null : { id: priceId } }] },
  };
}

test("active subscription grants the paid tier", () => {
  const d = tierDecisionFor(sub("active", "price_solo_monthly"));
  assert.equal(d.active, true);
  assert.equal(d.tier, "SOLO");
  assert.equal(d.status, "active");
});

test("trialing subscription grants the paid tier", () => {
  const d = tierDecisionFor(sub("trialing", "price_solo_annual"));
  assert.equal(d.active, true);
  assert.equal(d.tier, "SOLO");
});

test("every non-active status downgrades to FREE (replayed/reordered events converge here)", () => {
  for (const status of [
    "canceled",
    "past_due",
    "unpaid",
    "incomplete",
    "incomplete_expired",
    "paused",
  ]) {
    const d = tierDecisionFor(sub(status, "price_solo_monthly"));
    assert.equal(d.active, false, `${status} must not be active`);
    assert.equal(d.tier, "FREE", `${status} must drop to FREE`);
    assert.equal(d.status, status, "live status is passed through for persistence");
  }
});

test("garbage/unknown status is NOT a grant (deny by default)", () => {
  for (const status of ["", "ACTIVE", "Active ", "activeX", "deleted"]) {
    const d = tierDecisionFor(sub(status, "price_solo_monthly"));
    assert.equal(d.active, false);
    assert.equal(d.tier, "FREE");
  }
});

test("active with a missing/unrecognized price still grants the single paid plan", () => {
  // Single-plan product: tierForPriceId maps EVERY price (or none) to SOLO.
  assert.equal(tierDecisionFor(sub("active", null)).tier, "SOLO");
  assert.equal(tierDecisionFor({ status: "active" }).tier, "SOLO");
  assert.equal(tierForPriceId("price_unknown"), "SOLO");
  assert.equal(tierForPriceId(null), "SOLO");
  assert.equal(subscribedTier(), "SOLO");
});

test("firstPriceId tolerates every missing shape", () => {
  assert.equal(firstPriceId(sub("active", "price_x")), "price_x");
  assert.equal(firstPriceId(sub("active", null)), null);
  assert.equal(firstPriceId(sub("active")), null);
  assert.equal(firstPriceId({ status: "active" }), null);
  assert.equal(firstPriceId({ status: "active", items: null }), null);
  assert.equal(firstPriceId({ status: "active", items: { data: [] } }), null);
  assert.equal(firstPriceId({ status: "active", items: { data: [null] } }), null);
});
