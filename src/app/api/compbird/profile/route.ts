import { NextResponse } from "next/server";
import { engineProfile } from "@/lib/cma/engine";
import type { ProfileResult } from "@/lib/compbird/types";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";

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
  return NextResponse.json(body, { status });
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
  return NextResponse.json(body, { status });
}
