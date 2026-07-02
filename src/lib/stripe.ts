import "server-only";
import Stripe from "stripe";

/**
 * Stripe client + subscription config — compbird's OWN Stripe product (one
 * paid plan: SOLO "Pro" $20/mo). Every value comes from env — NO secrets in
 * code. The client is created lazily so the app boots fine without Stripe
 * configured; the billing routes surface a clean error when a key is missing.
 *
 * Required env (add to .env / .env.local):
 *   STRIPE_SECRET_KEY      — sk_test_… / sk_live_…
 *   STRIPE_PRICE_ID        — the RECURRING Pro Price (the $20/mo plan, price_…)
 *   STRIPE_WEBHOOK_SECRET  — whsec_… (signing secret for /api/billing/webhook)
 * Optional:
 *   STRIPE_PRICE_ID_ANNUAL — the annual Pro Price (also maps → SOLO).
 */

export class StripeNotConfigured extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = "StripeNotConfigured";
  }
}

let _client: Stripe | null = null;

/** The Stripe client. Throws StripeNotConfigured when STRIPE_SECRET_KEY is unset. */
export function stripe(): Stripe {
  const key = process.env.STRIPE_SECRET_KEY?.trim();
  if (!key) throw new StripeNotConfigured("STRIPE_SECRET_KEY is not set");
  if (!_client) _client = new Stripe(key);
  return _client;
}

/** True when the minimum config to sell a subscription is present. */
export function stripeConfigured(): boolean {
  return Boolean(process.env.STRIPE_SECRET_KEY?.trim() && process.env.STRIPE_PRICE_ID?.trim());
}

export function subscriptionPriceId(): string {
  const id = process.env.STRIPE_PRICE_ID?.trim();
  if (!id) throw new StripeNotConfigured("STRIPE_PRICE_ID is not set");
  return id;
}

export function webhookSecret(): string {
  const s = process.env.STRIPE_WEBHOOK_SECRET?.trim();
  if (!s) throw new StripeNotConfigured("STRIPE_WEBHOOK_SECRET is not set");
  return s;
}

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
