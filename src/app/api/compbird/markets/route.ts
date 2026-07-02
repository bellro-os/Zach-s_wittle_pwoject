import { NextResponse } from "next/server";
import { engineMarkets } from "@/lib/cma/engine";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";

/**
 * Live neighborhood market reports for the landing showcase.
 *
 * GET → engineMarkets() → { markets: NeighborhoodMarket[] }. engineMarkets never
 * throws and returns an empty array on any failure, so this route is a
 * one-liner and the client keeps its sample when the engine has no data.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 20;

export async function GET() {
  const rl = checkRateLimit("compbird:markets", await getClientIp());
  if (rl.limited) {
    return NextResponse.json(
      { markets: [], error: "Too many requests. Please slow down." },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }
  const { status, body } = await engineMarkets();
  return NextResponse.json(body, { status });
}
