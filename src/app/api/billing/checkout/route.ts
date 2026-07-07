import { NextResponse } from "next/server";
import { cookies, headers } from "next/headers";
import { SESSION_COOKIE, verifyAppSessionToken } from "@/lib/auth";
import { getActiveContext } from "@/lib/session";
import { systemDb } from "@/lib/db";
import { stripe, subscriptionPriceId, stripeConfigured, StripeNotConfigured } from "@/lib/stripe";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Start a Stripe subscription Checkout for the signed-in account. Returns
 * { url } for the client to redirect to. Reuses the account's Stripe customer
 * (creating one keyed to the accountId on first purchase). The webhook
 * (/api/billing/webhook) is what actually flips the account tier on completion —
 * this route only opens the hosted Checkout.
 */
export async function POST() {
  const session = await verifyAppSessionToken((await cookies()).get(SESSION_COOKIE)?.value);
  if (!session) return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  if (!stripeConfigured()) {
    return NextResponse.json({ ok: false, error: "Billing is not configured yet." }, { status: 503 });
  }

  const ctx = await getActiveContext();
  if (!ctx) return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });

  try {
    const account = await systemDb.account.findUnique({ where: { id: ctx.account.id } });
    if (!account) return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });

    // Reuse the account's Stripe customer, or create one keyed to the account so
    // the webhook can map the subscription back to this account.
    let customerId = account.stripeCustomerId ?? undefined;
    if (!customerId) {
      const customer = await stripe().customers.create({ metadata: { accountId: account.id } });
      customerId = customer.id;
      await systemDb.account.update({
        where: { id: account.id },
        data: { stripeCustomerId: customerId },
      });
    }

    const origin =
      (await headers()).get("origin") || process.env.NEXT_PUBLIC_APP_URL?.trim() || "";
    // Ad-consent flag rides through Stripe metadata to the webhook, which only
    // sends the server-side Meta conversion if the buyer accepted the banner.
    const adConsent = (await cookies()).get("cb_consent")?.value === "granted";
    const checkout = await stripe().checkout.sessions.create({
      mode: "subscription",
      customer: customerId,
      line_items: [{ price: subscriptionPriceId(), quantity: 1 }],
      // `cs` (the Checkout session id) lets the browser pixel fire Subscribe with
      // the SAME event id the webhook sends via the Conversions API → Meta dedups.
      success_url: `${origin}/comps?subscribed=1&cs={CHECKOUT_SESSION_ID}`,
      cancel_url: `${origin}/comps?checkout=cancelled`,
      allow_promotion_codes: true,
      // accountId on BOTH the session and the subscription so the webhook can map
      // either event back to the account.
      metadata: { accountId: account.id, adConsent: adConsent ? "1" : "0" },
      subscription_data: { metadata: { accountId: account.id } },
    });
    return NextResponse.json({ ok: true, url: checkout.url });
  } catch (err) {
    if (err instanceof StripeNotConfigured) {
      return NextResponse.json({ ok: false, error: "Billing is not configured yet." }, { status: 503 });
    }
    return NextResponse.json({ ok: false, error: "Could not start checkout." }, { status: 500 });
  }
}
