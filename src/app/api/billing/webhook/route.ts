import { NextResponse } from "next/server";
import type Stripe from "stripe";
import { systemDb } from "@/lib/db";
import { emailShell, sendEmail } from "@/lib/mailer";
import { sendMetaSubscribeEvent } from "@/lib/marketing/meta-capi";
import { tierDecisionFor } from "@/lib/billing-grant";
import { stripe, webhookSecret } from "@/lib/stripe";
import { createLogger } from "@/lib/utils/logger";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const log = createLogger("billing/webhook");

/**
 * Best-effort "welcome to Pro" email to the account's owner. Strictly
 * fire-and-forget: everything (DB lookup included) is caught, nothing is
 * awaited by the webhook, and sendEmail itself never throws — Stripe retries
 * exist for STATE changes, not mail, so a delivery failure must never 500
 * the webhook.
 */
function sendWelcomeEmail(accountId: string): void {
  void (async () => {
    const owner = await systemDb.membership.findFirst({
      where: { accountId, role: "OWNER" },
      orderBy: { createdAt: "asc" },
      include: { user: { select: { email: true } } },
    });
    const email = owner?.user.email;
    if (!email) return;

    const base = (process.env.NEXT_PUBLIC_APP_URL || "http://localhost:4310").replace(/\/$/, "");
    const subject = "Welcome to compbird Pro";
    const html = emailShell(
      subject,
      [
        `<p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#374151;">Your subscription is active. Your account now includes:</p>`,
        `<ul style="margin:0 0 20px;padding-left:20px;font-size:14px;line-height:1.8;color:#374151;">`,
        `<li>Every comparable sale — distances and $/sqft</li>`,
        `<li>Neighborhood market analytics</li>`,
        `<li>Unlimited watermark-free branded PDF reports</li>`,
        `<li>Statewide coverage</li>`,
        `</ul>`,
        `<p style="margin:0;font-size:13px;line-height:1.6;color:#6b7280;">Manage your billing anytime at <a href="${base}/account" style="color:#2563eb;text-decoration:none;">${base}/account</a>.</p>`,
      ].join(""),
    );
    const text = `Your compbird Pro subscription is active: every comparable sale, neighborhood market analytics, unlimited watermark-free branded reports, and statewide coverage. Manage billing at ${base}/account`;

    await sendEmail({ to: email, subject, html, text });
  })().catch((err) => {
    log.warn("Welcome email skipped", {
      accountId,
      error: err instanceof Error ? err.message : String(err),
    });
  });
}

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
          // A retrieve FAILURE deliberately bubbles to the outer catch → 500 →
          // Stripe retries; we never grant a paid tier on an unverified state
          // (launch security review 2026-07, P2 #7 — the old code optimistically
          // granted SOLO when the retrieve threw).
          const sub = await stripe().subscriptions.retrieve(subscriptionId);
          const decision = tierDecisionFor(sub);
          if (decision.active) {
            await systemDb.account.update({
              where: { id: accountId },
              data: {
                tier: decision.tier,
                subscriptionStatus: decision.status,
                stripeCustomerId: customerId ?? undefined,
                stripeSubscriptionId: subscriptionId ?? undefined,
              },
            });
            log.info("Subscription activated", { accountId, tier: decision.tier });
            // AFTER the tier flip — the state change is durable regardless of mail.
            sendWelcomeEmail(accountId);
            // Server-side ad conversion (Meta CAPI). Fire-and-forget like the
            // email; event_id = session id dedups against the browser pixel.
            // Only sent when the buyer accepted the consent banner (metadata
            // set by the checkout route) — and inert unless META_CAPI_ACCESS_TOKEN
            // + a pixel id are configured.
            void (async () => {
              const owner = await systemDb.membership.findFirst({
                where: { accountId, role: "OWNER" },
                orderBy: { createdAt: "asc" },
                include: { user: { select: { email: true } } },
              });
              sendMetaSubscribeEvent({
                email: owner?.user.email ?? s.customer_details?.email,
                eventId: s.id,
                consented: s.metadata?.adConsent === "1",
              });
            })().catch((err) => {
              log.warn("Meta CAPI lookup skipped", {
                accountId,
                error: err instanceof Error ? err.message : String(err),
              });
            });
          }
        }
        break;
      }

      case "customer.subscription.created":
      case "customer.subscription.updated":
      case "customer.subscription.deleted": {
        const sub = event.data.object as Stripe.Subscription;
        const customerId = typeof sub.customer === "string" ? sub.customer : sub.customer?.id;

        // Map back to the account via subscription metadata, else the customer id.
        const metaAccountId = sub.metadata?.accountId;
        const account = metaAccountId
          ? await systemDb.account.findUnique({ where: { id: metaAccountId } })
          : customerId
            ? await systemDb.account.findFirst({ where: { stripeCustomerId: customerId } })
            : null;

        if (account) {
          // Stripe does NOT guarantee delivery order, so never apply the state
          // snapshot embedded in the event — a delayed `updated(status=active)`
          // arriving after `deleted` would re-grant the paid tier. Re-read the
          // LIVE subscription and apply THAT, which makes handling idempotent
          // and order-independent (launch security review 2026-07, P2 #6).
          // Cancelled subscriptions stay retrievable (status=canceled); a
          // retrieve failure bubbles to the outer catch → 500 → Stripe retries.
          const live = await stripe().subscriptions.retrieve(sub.id);
          const decision = tierDecisionFor(live);
          await systemDb.account.update({
            where: { id: account.id },
            data: {
              // Active/trialing → the price's tier; anything else (past_due,
              // canceled, unpaid, incomplete) drops to FREE — which keeps the
              // free-trial quota rather than locking the account out entirely.
              tier: decision.tier,
              subscriptionStatus: decision.status,
              stripeSubscriptionId: decision.active ? sub.id : null,
            },
          });
          log.info("Subscription state synced", {
            accountId: account.id,
            status: decision.status,
            tier: decision.tier,
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
