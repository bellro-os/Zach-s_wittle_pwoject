import { NextResponse } from "next/server";
import { engineSearch } from "@/lib/cma/engine";
import { clampInt, COMPBIRD_BOUNDS } from "@/lib/compbird/validate";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 8;

// Public compbird typeahead. Isolated from the host's gated /api/cma routes.
export async function GET(req: Request) {
  // P0 #12: per-IP throttle (looser — this is the cheap typeahead).
  const rl = checkRateLimit("compbird:search", await getClientIp());
  if (rl.limited) {
    return NextResponse.json(
      { ok: false, error: "Too many requests. Please slow down.", matches: [] },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }

  const url = new URL(req.url);
  // Bound the query params (clamp, never 400): q capped so an oversized string
  // never reaches the index/spawn; non-numeric limit → default 8.
  const q = (url.searchParams.get("q") ?? "").trim().slice(0, 120);
  const limit = clampInt(url.searchParams.get("limit"), COMPBIRD_BOUNDS.searchLimit) ?? 8;
  const { status, body } = await engineSearch(q, limit);
  return NextResponse.json(body, { status });
}
