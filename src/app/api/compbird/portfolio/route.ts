import { NextResponse } from "next/server";
import { checkRateLimit, getClientIp } from "@/lib/compbird-ratelimit";
import { capString, STRING_CAPS } from "@/lib/compbird/validate";
import { getActiveContext } from "@/lib/session";
import { can as canFeature } from "@/lib/entitlements";
import {
  getPortfolioDb,
  parsePortfolioItems,
  startPortfolioRun,
  isRunActive,
  toRunDto,
  toRunSummaryDto,
} from "@/lib/compbird/portfolio";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Portfolio (batch) valuation — Pro-only ("cma.portfolio", SOLO+).
 *
 * POST creates a run + items and kicks the in-process batch runner
 * fire-and-forget; the client then POLLS GET ?id=… for per-item results as they
 * land. GET doubles as the recovery path: a run stranded "running" by a server
 * restart is resumed on the next poll (see startPortfolioRun/isRunActive).
 * Everything is account-scoped — a run id from another account 404s.
 */

export async function POST(req: Request) {
  // Strictest public budget: one POST can enqueue up to 50 engine valuations.
  const rl = checkRateLimit("compbird:portfolio", await getClientIp());
  if (rl.limited) {
    return NextResponse.json(
      { ok: false, error: "Too many requests. Please slow down." },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }

  let payload: { items?: unknown };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }
  const parsed = parsePortfolioItems(payload.items);
  if (!parsed.ok) {
    return NextResponse.json({ ok: false, error: parsed.error }, { status: 400 });
  }

  // ── Account + Pro gate (same shape as /generate) ──────────────────────────
  const ctx = await getActiveContext();
  if (!ctx) {
    return NextResponse.json(
      { ok: false, error: "Sign in to run portfolio valuations.", code: "auth_required" },
      { status: 401 },
    );
  }
  if (!canFeature(ctx.ent, "cma.portfolio")) {
    return NextResponse.json(
      { ok: false, error: "Portfolio valuations are part of Pro.", code: "pro_required" },
      { status: 403 },
    );
  }

  const db = await getPortfolioDb();
  const run = await db.portfolioRun.create({
    data: {
      accountId: ctx.account.id,
      userId: ctx.session.userId,
      status: "running",
      items: {
        create: parsed.items.map((it, position) => ({
          position,
          label: it.label,
          inputAddress: it.address,
          inputParcelId: it.parcelId,
          status: "pending",
        })),
      },
    },
    select: { id: true },
  });

  // Fire-and-forget: the runner writes each item to the DB as it lands and
  // settles the run status itself. Never blocks (or fails) this response.
  startPortfolioRun(run.id);

  return NextResponse.json({ ok: true, runId: run.id });
}

export async function GET(req: Request) {
  const ctx = await getActiveContext();
  if (!ctx) {
    return NextResponse.json(
      { ok: false, error: "Sign in to view portfolio runs.", code: "auth_required" },
      { status: 401 },
    );
  }

  // Length-cap the id before it reaches Prisma (a cuid is ~25 chars; anything
  // longer can never match a row, so truncation preserves the 404).
  const id = capString(new URL(req.url).searchParams.get("id"), STRING_CAPS.runId);
  const db = await getPortfolioDb();

  if (id) {
    // Account-scoped: someone else's run id is indistinguishable from absent.
    const run = await db.portfolioRun.findFirst({
      where: { id, accountId: ctx.account.id },
      include: { items: { orderBy: { position: "asc" } } },
    });
    if (!run) {
      return NextResponse.json({ ok: false, error: "Run not found." }, { status: 404 });
    }
    // Restart resilience: a run left "running" with no live processor (the
    // module-level Set is empty after a dev-server restart) resumes here,
    // fire-and-forget — polling IS the recovery mechanism.
    if (run.status === "running" && !isRunActive(run.id)) startPortfolioRun(run.id);
    return NextResponse.json({ ok: true, run: toRunDto(run) });
  }

  const runs = await db.portfolioRun.findMany({
    where: { accountId: ctx.account.id },
    orderBy: { createdAt: "desc" },
    take: 20,
    include: { items: { orderBy: { position: "asc" } } },
  });
  return NextResponse.json({ ok: true, runs: runs.map(toRunSummaryDto) });
}

export async function DELETE(req: Request) {
  const ctx = await getActiveContext();
  if (!ctx) {
    return NextResponse.json(
      { ok: false, error: "Sign in to manage portfolio runs.", code: "auth_required" },
      { status: 401 },
    );
  }

  // Same cap as GET: bounded before the Prisma where; oversized ids still 404.
  const id = capString(new URL(req.url).searchParams.get("id"), STRING_CAPS.runId);
  if (!id) {
    return NextResponse.json({ ok: false, error: "Provide a run id." }, { status: 400 });
  }

  // deleteMany + account scope: cascades items; a foreign/unknown id → count 0
  // → 404, never a cross-account delete. An in-flight runner notices the
  // vanished run and stops (its item writes are updateMany no-ops).
  const db = await getPortfolioDb();
  const { count } = await db.portfolioRun.deleteMany({
    where: { id, accountId: ctx.account.id },
  });
  if (count === 0) {
    return NextResponse.json({ ok: false, error: "Run not found." }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
