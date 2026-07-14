/**
 * Pure billing-tier decision helpers (launch security review 2026-07, P2 #6/#7).
 *
 * The Stripe webhook is the ONLY writer of Account.tier, and Stripe does NOT
 * guarantee event delivery order — so the webhook must never trust the state
 * snapshot embedded in an event. Both handlers re-read the LIVE subscription
 * from the Stripe API and feed it through `tierDecisionFor`, which maps a
 * subscription's real status + price to the tier the account should hold RIGHT
 * NOW. That makes event handling idempotent and order-independent: a replayed
 * or reordered event converges on the same live state.
 *
 * Pure module — no "server-only", no Stripe client, no Prisma — so the tier
 * mapping is unit-testable under plain tsx (`npx tsx src/lib/billing-grant.test.ts`).
 * `src/lib/stripe.ts` re-exports `subscribedTier`/`tierForPriceId` from here so
 * existing imports keep working.
 */

/** The AccountTier a paid subscription grants. compbird sells ONE paid plan. */
export function subscribedTier(): "SOLO" {
  return "SOLO";
}

/** Map a Stripe Price id → the tier it grants. With a single paid plan every
 *  recognized (or unrecognized) price grants SOLO — the map exists so the
 *  webhook code stays shape-compatible if a higher rung is ever added. */
export function tierForPriceId(_priceId: string | null | undefined): "SOLO" {
  return "SOLO";
}

/** Minimal shape of a live Stripe subscription the tier decision needs —
 *  structural so tests never touch the Stripe SDK types. */
export interface SubscriptionLike {
  status: string;
  items?: {
    data?: Array<{ price?: { id?: string | null } | null } | null> | null;
  } | null;
}

/** First line item's price id, or null when the shape is missing/empty. */
export function firstPriceId(sub: SubscriptionLike): string | null {
  return sub.items?.data?.[0]?.price?.id ?? null;
}

export interface TierDecision {
  /** True when the subscription entitles the account to a paid tier. */
  active: boolean;
  /** The tier the account should hold NOW: the price's paid tier, or FREE. */
  tier: "SOLO" | "FREE";
  /** The live subscription status, persisted for display/debugging. */
  status: string;
}

/**
 * The single tier rule: `active`/`trialing` → the price's paid tier; every
 * other status (past_due, canceled, unpaid, incomplete, incomplete_expired,
 * paused…) → FREE, which keeps the free-trial quota rather than locking the
 * account out entirely.
 */
export function tierDecisionFor(sub: SubscriptionLike): TierDecision {
  const active = sub.status === "active" || sub.status === "trialing";
  return {
    active,
    tier: active ? tierForPriceId(firstPriceId(sub)) : "FREE",
    status: sub.status,
  };
}
