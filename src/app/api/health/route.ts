import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import pkg from "../../../../package.json";

/**
 * Cheap unauthenticated ops probe for uptime monitoring (deploy/ops/monitor.sh)
 * and the container healthcheck. GET /api/health -> { ok, version, db }.
 * 200 when the SQLite DB answers a trivial query, 503 otherwise. No secrets,
 * no user data, no engine call (the engine has its own /healthz).
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 10;

export async function GET() {
  let dbUp = false;
  try {
    await db.$queryRaw`SELECT 1`;
    dbUp = true;
  } catch {
    dbUp = false;
  }
  return NextResponse.json(
    { ok: dbUp, version: pkg.version, db: dbUp ? "up" : "down" },
    { status: dbUp ? 200 : 503, headers: { "Cache-Control": "no-store" } },
  );
}
