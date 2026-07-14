import { NextResponse } from "next/server";
import { engineProfile } from "@/lib/cma/engine";
import type { ProfileResult } from "@/lib/compbird/types";
import { capString, STRING_CAPS } from "@/lib/compbird/validate";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import { getActiveContext } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";
import { redactEvidence } from "@/lib/compbird/redact";
import { bodyTooLarge, BODY_TOO_LARGE_RESPONSE } from "@/lib/compbird/body-limit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

// P0 #12: per-IP throttle on the heavy dossier lookup (warm worker / spawn).
function tooManyRequests(retryAfterSeconds: number) {
  return NextResponse.json(
    { ok: false, error: "Too many requests. Please slow down." },
    { status: 429, headers: { "Retry-After": String(retryAfterSeconds) } },
  );
}

/**
 * Evidence paywall (server-side). FREE + anonymous callers get the ESTIMATE
 * only — comps, market analytics, sale history, and the method breakdown are
 * Pro ("cma.evidence"). Redacting HERE means the evidence never ships to a
 * non-Pro client, so a blur overlay can't be bypassed in devtools.
 * `ctx` is the already-resolved session (resolved once per request, shared
 * with the aiHygiene decision so both read the same auth state).
 */
function respondWithEntitlement(
  status: number,
  body: ProfileResult | { ok: false; error: string },
  ctx: Awaited<ReturnType<typeof getActiveContext>>,
) {
  if (body?.ok) {
    const evidence = ctx ? canFeature(ctx.ent, "cma.evidence") : false; // anonymous = locked
    if (!evidence) return NextResponse.json(redactEvidence(body), { status });
  }
  return NextResponse.json(body, { status });
}

export async function POST(req: Request) {
  const rl = checkRateLimit("compbird:profile", await getClientIp());
  if (rl.limited) return tooManyRequests(rl.retryAfterSeconds);

  // Size gate BEFORE the body is read (see body-limit.ts).
  if (bodyTooLarge(req)) {
    return NextResponse.json(BODY_TOO_LARGE_RESPONSE, { status: 413 });
  }

  let payload: { address?: string; parcelId?: string };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }
  // aiHygiene mirrors the preview route's server-side decision (authed → full
  // LLM hygiene, anon → off) so the profile's first-paint estimate is computed
  // by the EXACT pipeline every tuning /preview recompute uses — one number.
  // Identity strings are trimmed + length-capped at the parse point (clamp,
  // never 400; non-string garbage → absent → the engine's own 400).
  const ctx = await getActiveContext();
  const { status, body } = await engineProfile<ProfileResult>({
    address: capString(payload.address, STRING_CAPS.address),
    parcelId: capString(payload.parcelId, STRING_CAPS.parcelId),
    aiHygiene: !!ctx,
  });
  return respondWithEntitlement(status, body, ctx);
}

// GET wrapper so the studio can deep-link with ?address= / ?parcelId=.
export async function GET(req: Request) {
  const rl = checkRateLimit("compbird:profile", await getClientIp());
  if (rl.limited) return tooManyRequests(rl.retryAfterSeconds);

  const url = new URL(req.url);
  const ctx = await getActiveContext();
  // Same parse-point caps as POST (an absent/oversized param degrades the same
  // way: trimmed to 200 chars or treated as not provided).
  const { status, body } = await engineProfile<ProfileResult>({
    address: capString(url.searchParams.get("address"), STRING_CAPS.address),
    parcelId: capString(url.searchParams.get("parcelId"), STRING_CAPS.parcelId),
    aiHygiene: !!ctx,
  });
  return respondWithEntitlement(status, body, ctx);
}
