import { NextResponse } from "next/server";
import { engineProfile } from "@/lib/cma/engine";
import type { ProfileResult } from "@/lib/compbird/types";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import { getActiveContext } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";
import { redactEvidence } from "@/lib/compbird/redact";

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
 */
async function respondWithEntitlement(
  status: number,
  body: ProfileResult | { ok: false; error: string },
) {
  if (body?.ok) {
    const ctx = await getActiveContext();
    const evidence = ctx ? canFeature(ctx.ent, "cma.evidence") : false; // anonymous = locked
    if (!evidence) return NextResponse.json(redactEvidence(body), { status });
  }
  return NextResponse.json(body, { status });
}

export async function POST(req: Request) {
  const rl = checkRateLimit("compbird:profile", await getClientIp());
  if (rl.limited) return tooManyRequests(rl.retryAfterSeconds);

  let payload: { address?: string; parcelId?: string };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }
  const { status, body } = await engineProfile<ProfileResult>(payload);
  return respondWithEntitlement(status, body);
}

// GET wrapper so the studio can deep-link with ?address= / ?parcelId=.
export async function GET(req: Request) {
  const rl = checkRateLimit("compbird:profile", await getClientIp());
  if (rl.limited) return tooManyRequests(rl.retryAfterSeconds);

  const url = new URL(req.url);
  const { status, body } = await engineProfile<ProfileResult>({
    address: url.searchParams.get("address") ?? "",
    parcelId: url.searchParams.get("parcelId") ?? "",
  });
  return respondWithEntitlement(status, body);
}
