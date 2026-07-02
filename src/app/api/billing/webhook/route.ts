import { NextResponse } from "next/server";
import type Stripe from "stripe";
import { systemDb } from "@/lib/db";
import { stripe, webhookSecret, subscribedTier, tierForPriceId } from "@/lib/stripe";
import { createLogger } from "@/lib/utils/logger";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const log = createLogger("billing/webhook");

/**
 * Stripe webhook — the ONLY place the account tier is changed by a payment event.
 * The raw body is verified against STRIPE_WEBHOOK_SECRET (never trust an unsigned
 * caller). On an active subscription the account is lifted to the paid tier; on
 * cancellation/lapse it reverts to FREE (which keeps the free-trial quota).
 */
export async function POST(req: Request) {
  const sig = req.headers.get("stripe-signature");
  if (!sig) return NextResponse.json({ error: "missing signature" }, { status: 400 });

  // RAW body is required for signature verification — do NOT parse it first.
  let event: Stripe.Event;
  try {
    const raw = await req.text();
    event = stripe().webhooks.constructEvent(raw, sig, webhookSecret());
  } catch (err) {
    log.warn("Stripe signature verification failed", {
      error: err instanceof Error ? err.message : String(err),
    });
    return NextResponse.json({ error: "invalid signature" }, { status: 400 });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const s = event.data.object as Stripe.Checkout.Session;
        const accountId = s.metadata?.accountId;
        const customerId = typeof s.customer === "string" ? s.customer : s.customer?.id;
        const subscriptionId =
          typeof s.subscription === "string" ? s.subscription : s.subscription?.id;
        if (accountId && s.payment_status !== "unpaid" && subscriptionId) {
          // Re-read the subscription's LIVE status before granting. This makes a
          // replayed or reordered checkout.session.completed harmless — it can't
          // revive a cancelled paid state, because a cancelled sub reports a
          // non-active status here — and lets us map the real price id to the tier.
          let grant: "SOLO" | "TEAM" | null = subscribedTier();
          let statusStr = "active";
          try {
            const sub = await stripe().subscriptions.retrieve(subscriptionId);
            statusStr = sub.status;
            const isActive = sub.status === "active" || sub.status === "trialing";
            grant = isActive ? tierForPriceId(sub.items?.data?.[0]?.price?.id ?? null) : null;
          } catch {
            // Retrieve failed — fall back to the single-price grant (best-effort).
          }
          if (grant) {
            await systemDb.account.update({
              where: { id: accountId },
              data: {
                tier: grant,
                subscriptionStatus: statusStr,
                stripeCustomerId: customerId ?? undefined,
                stripeSubscriptionId: subscriptionId ?? undefined,
              },
            });
            log.info("Subscription activated", { accountId, tier: grant });
          }
        }
        break;
      }

      case "customer.subscription.created":
      case "customer.subscription.updated":
      case "customer.subscription.deleted": {
        const sub = event.data.object as Stripe.Subscription;
        const customerId = typeof sub.customer === "string" ? sub.customer : sub.customer?.id;
        const active = sub.status === "active" || sub.status === "trialing";
        // The subscription's own price id decides which paid tier it grants, so a
        // future TEAM plan lifts to TEAM and SOLO stays SOLO — driven by env, not code.
        const priceId = sub.items?.data?.[0]?.price?.id ?? null;

        // Map back to the account via subscription metadata, else the customer id.
        const metaAccountId = sub.metadata?.accountId;
        const account = metaAccountId
          ? await systemDb.account.findUnique({ where: { id: metaAccountId } })
          : customerId
            ? await systemDb.account.findFirst({ where: { stripeCustomerId: customerId } })
            : null;

        if (account) {
          await systemDb.account.update({
            where: { id: account.id },
            data: {
              // Active/trialing → the price's tier; anything else (past_due,
              // canceled, unpaid, incomplete) drops to FREE — which keeps the
              // free-trial quota rather than locking the account out entirely.
              tier: active ? tierForPriceId(priceId) : "FREE",
              subscriptionStatus: sub.status,
              stripeSubscriptionId: active ? sub.id : null,
            },
          });
          log.info("Subscription state synced", {
            accountId: account.id,
            status: sub.status,
            tier: active ? tierForPriceId(priceId) : "FREE",
          });
        }
        break;
      }

      default:
        // Unhandled event types are acknowledged (200) so Stripe stops retrying.
        break;
    }
  } catch (err) {
    // 500 so Stripe RETRIES — never drop a paid-state change silently.
    log.error("Webhook handler failed", err, { type: event.type });
    return NextResponse.json({ error: "handler failed" }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}
