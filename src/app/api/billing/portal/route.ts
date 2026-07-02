import { NextResponse } from "next/server";
import { cookies, headers } from "next/headers";
import { SESSION_COOKIE, verifyAppSessionToken } from "@/lib/auth";
import { getActiveContext } from "@/lib/session";
import { systemDb } from "@/lib/db";
import { stripe, stripeConfigured, StripeNotConfigured } from "@/lib/stripe";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Open the Stripe customer billing portal for the signed-in account (manage /
 * cancel the subscription, update the card). Returns { url } to redirect to.
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
    if (!account?.stripeCustomerId) {
      return NextResponse.json({ ok: false, error: "No subscription to manage." }, { status: 400 });
    }
    const origin =
      (await headers()).get("origin") || process.env.NEXT_PUBLIC_APP_URL?.trim() || "";
    const portal = await stripe().billingPortal.sessions.create({
      customer: account.stripeCustomerId,
      return_url: `${origin}/comps`,
    });
    return NextResponse.json({ ok: true, url: portal.url });
  } catch (err) {
    if (err instanceof StripeNotConfigured) {
      return NextResponse.json({ ok: false, error: "Billing is not configured yet." }, { status: 503 });
    }
    return NextResponse.json({ ok: false, error: "Could not open the billing portal." }, { status: 500 });
  }
}
