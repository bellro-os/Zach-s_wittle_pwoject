/**
 * Portfolio (batch) valuation — shared wire types + the in-process batch runner.
 *
 * THE CONTRACT (both the API route and the studio UI build against this file):
 *
 *   POST   /api/compbird/portfolio       {items:[{address?,parcelId?,label?}]} (1..50)
 *          → 200 {ok:true, runId} | 401 auth_required | 403 pro_required | 400
 *   GET    /api/compbird/portfolio?id=X  → {ok, run: PortfolioRunDto}
 *   GET    /api/compbird/portfolio       → {ok, runs: PortfolioRunSummaryDto[]}
 *   DELETE /api/compbird/portfolio?id=X  → {ok}
 *
 * FILE LAYOUT — deliberately two-zone:
 *   1. The top of the file (types, caps, parse/DTO helpers) is CLIENT-SAFE:
 *      no server imports, so the studio can `import type` (or even value-import
 *      the parse helper) without dragging Prisma/engine code into the bundle.
 *   2. The RUNNER at the bottom is SERVER-ONLY in effect: it loads its deps
 *      (Prisma client, engine adapter) via lazy dynamic import on first use, so
 *      merely importing this module never evaluates server-only code.
 */

import type { ProfileResult } from "@/lib/compbird/types";
import { LIST_CAPS } from "@/lib/compbird/validate";

/* ── wire types ─────────────────────────────────────────────────────────────── */

export type PortfolioRunStatus = "running" | "done" | "failed";
export type PortfolioItemStatus = "pending" | "running" | "done" | "error";
export type PortfolioConfidenceTier = "high" | "standard";

/** One property in a POST body. Needs `address` or `parcelId`. */
export interface PortfolioItemInput {
  address?: string;
  parcelId?: string;
  /** Optional display label ("123 Main — rental #2"); echoed back verbatim. */
  label?: string;
}

export interface PortfolioPostBody {
  items: PortfolioItemInput[];
}

/** One item as GET returns it (matches the PortfolioItem row 1:1). */
export interface PortfolioItemDto {
  id: string;
  position: number;
  label: string | null;
  inputAddress: string | null;
  inputParcelId: string | null;
  status: PortfolioItemStatus;
  resolvedAddress: string | null;
  parcelId: string | null;
  mid: number | null;
  low: number | null;
  high: number | null;
  confidenceTier: PortfolioConfidenceTier | null;
  caution: boolean | null;
  compCount: number | null;
  nearestMi: number | null;
  /** Subject-level average comp match (0–100) — profile.similarity_summary.avg. */
  avgMatch: number | null;
  /** Terse human message when status === "error". */
  error: string | null;
}

/** Full run payload — GET /api/compbird/portfolio?id=X. */
export interface PortfolioRunDto {
  id: string;
  status: PortfolioRunStatus;
  createdAt: string;
  total: number;
  /** Items that have SETTLED (done or error) — drives the progress bar. */
  completed: number;
  /** Sum of `mid` across done items; null until at least one item lands. */
  portfolioMid: number | null;
  items: PortfolioItemDto[];
}

/** Run-list entry — GET /api/compbird/portfolio (no ?id). */
export interface PortfolioRunSummaryDto {
  id: string;
  createdAt: string;
  status: PortfolioRunStatus;
  total: number;
  completed: number;
  portfolioMid: number | null;
  /** Label (or input address/parcel) of the first item — the list's display name. */
  firstLabel: string | null;
}

/**
 * Un-suffixed aliases — the studio components import these names; the Dto
 * names above stay canonical for the route/runner side.
 */
export type PortfolioItem = PortfolioItemDto;
export type PortfolioRun = PortfolioRunDto;
export type PortfolioRunSummary = PortfolioRunSummaryDto;

/* ── validation (client-safe; the route is the enforcing caller) ───────────── */

export const PORTFOLIO_MAX_ITEMS = 50;
/** Display-label cap — inputs share LIST_CAPS.maxLen with the comp lists. */
export const PORTFOLIO_LABEL_MAX_LEN = 80;

/** A normalized, length-capped item ready to persist. */
export interface NormalizedPortfolioItem {
  address: string | null;
  parcelId: string | null;
  label: string | null;
}

export type ParsedPortfolioItems =
  | { ok: true; items: NormalizedPortfolioItem[] }
  | { ok: false; error: string };

function capOpt(v: unknown, maxLen: number): string | null {
  if (typeof v !== "string") return null;
  const s = v.trim().slice(0, maxLen);
  return s === "" ? null : s;
}

/**
 * Validate + normalize a POST body's `items`. Mirrors the validate.ts idiom:
 * strings are trimmed and LENGTH-CAPPED (a long address is still a valid ask),
 * but a structurally invalid item — no address AND no parcelId — is REJECTED
 * with a terse, position-named message (→ respond 400).
 */
export function parsePortfolioItems(raw: unknown): ParsedPortfolioItems {
  if (!Array.isArray(raw)) return { ok: false, error: "items must be an array" };
  if (raw.length === 0) return { ok: false, error: "items must not be empty" };
  if (raw.length > PORTFOLIO_MAX_ITEMS) {
    return { ok: false, error: `At most ${PORTFOLIO_MAX_ITEMS} items per run` };
  }
  const items: NormalizedPortfolioItem[] = [];
  for (let i = 0; i < raw.length; i++) {
    const entry = raw[i];
    if (entry == null || typeof entry !== "object" || Array.isArray(entry)) {
      return { ok: false, error: `Item ${i + 1} must be an object` };
    }
    const o = entry as Record<string, unknown>;
    const address = capOpt(o.address, LIST_CAPS.maxLen);
    const parcelId = capOpt(o.parcelId, LIST_CAPS.maxLen);
    const label = capOpt(o.label, PORTFOLIO_LABEL_MAX_LEN);
    if (!address && !parcelId) {
      return { ok: false, error: `Item ${i + 1} needs an address or parcelId` };
    }
    items.push({ address, parcelId, label });
  }
  return { ok: true, items };
}

/* ── row → DTO mapping (structural, so this stays Prisma-free) ─────────────── */

/** The PortfolioItem row fields the DTO reads (Prisma rows satisfy this). */
export interface PortfolioItemRecord {
  id: string;
  position: number;
  label: string | null;
  inputAddress: string | null;
  inputParcelId: string | null;
  status: string;
  resolvedAddress: string | null;
  parcelId: string | null;
  mid: number | null;
  low: number | null;
  high: number | null;
  confidenceTier: string | null;
  caution: boolean | null;
  compCount: number | null;
  nearestMi: number | null;
  avgMatch: number | null;
  error: string | null;
}

export interface PortfolioRunRecord {
  id: string;
  status: string;
  createdAt: Date | string;
  items: PortfolioItemRecord[];
}

function asRunStatus(s: string): PortfolioRunStatus {
  return s === "done" || s === "failed" ? s : "running";
}

function asItemStatus(s: string): PortfolioItemStatus {
  return s === "running" || s === "done" || s === "error" ? s : "pending";
}

function asTier(s: string | null): PortfolioConfidenceTier | null {
  return s === "high" || s === "standard" ? s : null;
}

function isFiniteNum(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

export function toItemDto(row: PortfolioItemRecord): PortfolioItemDto {
  return {
    id: row.id,
    position: row.position,
    label: row.label,
    inputAddress: row.inputAddress,
    inputParcelId: row.inputParcelId,
    status: asItemStatus(row.status),
    resolvedAddress: row.resolvedAddress,
    parcelId: row.parcelId,
    mid: row.mid,
    low: row.low,
    high: row.high,
    confidenceTier: asTier(row.confidenceTier),
    caution: row.caution,
    compCount: row.compCount,
    nearestMi: row.nearestMi,
    avgMatch: row.avgMatch,
    error: row.error,
  };
}

/** Sum of done-item mids; null when nothing has landed yet. */
export function portfolioMidOf(items: PortfolioItemRecord[]): number | null {
  let sum = 0;
  let any = false;
  for (const it of items) {
    if (it.status === "done" && isFiniteNum(it.mid)) {
      sum += it.mid;
      any = true;
    }
  }
  return any ? sum : null;
}

/** Settled (done | error) item count — the "completed" of the contract. */
export function completedOf(items: PortfolioItemRecord[]): number {
  return items.filter((it) => it.status === "done" || it.status === "error").length;
}

export function toRunDto(run: PortfolioRunRecord): PortfolioRunDto {
  const items = [...run.items].sort((a, b) => a.position - b.position);
  return {
    id: run.id,
    status: asRunStatus(run.status),
    createdAt: new Date(run.createdAt).toISOString(),
    total: items.length,
    completed: completedOf(items),
    portfolioMid: portfolioMidOf(items),
    items: items.map(toItemDto),
  };
}

export function toRunSummaryDto(run: PortfolioRunRecord): PortfolioRunSummaryDto {
  const items = [...run.items].sort((a, b) => a.position - b.position);
  const first = items[0];
  return {
    id: run.id,
    createdAt: new Date(run.createdAt).toISOString(),
    status: asRunStatus(run.status),
    total: items.length,
    completed: completedOf(items),
    portfolioMid: portfolioMidOf(items),
    firstLabel: first ? (first.label ?? first.inputAddress ?? first.inputParcelId) : null,
  };
}

/* ── the batch runner (server-only in effect; deps are lazy-loaded) ────────── */

/** Items processed at once per run. Two, matching COMPBIRD_SPAWN_BUDGET so a
 *  portfolio can never occupy more engine slots than the interactive studio. */
const PORTFOLIO_CONCURRENCY = 2;
/** Hard per-item budget. Covers the warm-worker path (45s) + retry headroom;
 *  a cold-spawn fallback that would blow past this is cut off as an item error
 *  rather than stalling the whole run. */
const ITEM_TIMEOUT_MS = 90_000;

/**
 * Active processors in THIS process. The GET handler uses isRunActive() to
 * detect a run stranded "running" by a dev-server restart and resumes it
 * fire-and-forget — so polling is also the recovery mechanism.
 */
const activeRuns = new Set<string>();

export function isRunActive(runId: string): boolean {
  return activeRuns.has(runId);
}

/**
 * Prisma access for the portfolio surface. Normally just the shared singleton —
 * but in dev, `prisma db push` + generate can land while the dev server is
 * already running, and the HMR-surviving `globalThis` cache then holds a client
 * built BEFORE the PortfolioRun/PortfolioItem models existed (its delegates are
 * undefined). Detect that and construct ONE fresh client from the regenerated
 * module (cached process-wide) instead of asking the user to restart. After any
 * real restart the singleton has the models and this is a pure pass-through.
 */
async function portfolioDb(): Promise<import("@/generated/prisma").PrismaClient> {
  const { systemDb } = await import("@/lib/db");
  if ((systemDb as { portfolioRun?: unknown }).portfolioRun) return systemDb;
  const g = globalThis as unknown as {
    __compbirdPortfolioDb?: import("@/generated/prisma").PrismaClient;
  };
  if (!g.__compbirdPortfolioDb) {
    const { PrismaClient } = await import("@/generated/prisma");
    g.__compbirdPortfolioDb = new PrismaClient();
  }
  return g.__compbirdPortfolioDb;
}

/** The route imports this: same self-healing client the runner uses. */
export async function getPortfolioDb(): Promise<import("@/generated/prisma").PrismaClient> {
  return portfolioDb();
}

/** Lazy server deps — resolved on first runner invocation so importing this
 *  module from client code never evaluates Prisma or the server-only engine. */
async function serverDeps() {
  const [db, { engineProfile }, { computeConfidence }, { createLogger }] = await Promise.all([
    portfolioDb(),
    import("@/lib/cma/engine"),
    import("@/lib/compbird/confidence"),
    import("@/lib/utils/logger"),
  ]);
  return { db, engineProfile, computeConfidence, log: createLogger("compbird/portfolio") };
}

type ServerDeps = Awaited<ReturnType<typeof serverDeps>>;

const TIMEOUT = Symbol("timeout");

/** Race a promise against the per-item budget. Rejections surface to the caller
 *  (engineProfile never throws by contract, but the runner must not wedge). */
function withItemTimeout<T>(p: Promise<T>): Promise<T | typeof TIMEOUT> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => resolve(TIMEOUT), ITEM_TIMEOUT_MS);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (err) => {
        clearTimeout(t);
        reject(err);
      },
    );
  });
}

/** Terse, human item errors — never engine internals. */
function terseEngineError(status: number, engineMessage?: string): string {
  if (status === 400) return "Couldn't resolve this address";
  if (status === 503) return "Engine was busy — retry this run later";
  if (engineMessage && /timed out/i.test(engineMessage)) return "Valuation timed out";
  return "Valuation failed";
}

interface RunnerItem {
  id: string;
  inputAddress: string | null;
  inputParcelId: string | null;
}

async function processItem(deps: ServerDeps, accountId: string, item: RunnerItem): Promise<void> {
  const { db, engineProfile, computeConfidence, log } = deps;

  await db.portfolioItem.updateMany({ where: { id: item.id }, data: { status: "running" } });

  let update: Record<string, unknown>;
  try {
    // Authed posture, same as the studio's signed-in profile call: full
    // valuation (profile == preview == PDF) + LLM hygiene. engineProfile
    // resolves address strings itself — no pre-resolution here, the engine's
    // facts are recorded as the resolved identity.
    const outcome = await withItemTimeout(
      engineProfile<ProfileResult>({
        address: item.inputAddress ?? undefined,
        parcelId: item.inputParcelId ?? undefined,
        aiHygiene: true,
      }),
    );

    if (outcome === TIMEOUT) {
      update = { status: "error", error: "Valuation timed out" };
    } else if (!outcome.body.ok) {
      update = {
        status: "error",
        error: terseEngineError(outcome.status, outcome.body.error),
      };
    } else {
      const profile = outcome.body as ProfileResult;
      const mid = profile.valuation?.mid ?? null;
      if (!isFiniteNum(mid)) {
        // ok:true but no headline number — an honest error beats a null "done".
        update = { status: "error", error: "No valuation available for this property" };
      } else {
        const conf = computeConfidence(profile);
        update = {
          status: "done",
          error: null,
          resolvedAddress: profile.facts?.address ?? null,
          parcelId: profile.facts?.parcel_id ?? null,
          mid,
          low: profile.valuation?.low ?? null,
          high: profile.valuation?.high ?? null,
          confidenceTier: conf.tier,
          caution: conf.caution,
          compCount: conf.compCount,
          nearestMi: conf.nearestMi,
          avgMatch: profile.similarity_summary?.avg ?? null,
        };
      }
    }
  } catch (err) {
    log.error("Portfolio item crashed", err, { itemId: item.id });
    update = { status: "error", error: "Valuation failed" };
  }

  // updateMany (not update): a run deleted mid-flight makes this a no-op
  // instead of a throw.
  const { count } = await db.portfolioItem.updateMany({ where: { id: item.id }, data: update });

  // Telemetry, not quota: one UsageEvent per successfully valued property.
  // SOLO's portfolio capacity is unlimited (`true`), so no reserve/refund dance —
  // and a telemetry hiccup must never fail the run.
  if (count > 0 && update.status === "done") {
    try {
      await db.usageEvent.create({ data: { accountId, feature: "cma.portfolio" } });
    } catch (err) {
      log.warn("Portfolio usage telemetry failed", {
        itemId: item.id,
        err: err instanceof Error ? err.message : String(err),
      });
    }
  }
}

async function processRun(runId: string): Promise<void> {
  const deps = await serverDeps();
  const { db, log } = deps;

  const run = await db.portfolioRun.findUnique({ where: { id: runId } });
  if (!run || run.status !== "running") return;

  // pending = fresh work; running = items orphaned by a restart mid-flight
  // (startPortfolioRun only admits one processor per runId per process, so a
  // "running" item here can't belong to a live processor).
  const queue = await db.portfolioItem.findMany({
    where: { runId, status: { in: ["pending", "running"] } },
    orderBy: { position: "asc" },
    select: { id: true, inputAddress: true, inputParcelId: true },
  });

  let cancelled = false;
  const worker = async () => {
    while (!cancelled) {
      const item = queue.shift();
      if (!item) return;
      // A deleted run stops the batch instead of burning engine time on
      // results nobody can read.
      const alive = await db.portfolioRun.count({ where: { id: runId } });
      if (alive === 0) {
        cancelled = true;
        return;
      }
      await processItem(deps, run.accountId, item);
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(PORTFOLIO_CONCURRENCY, queue.length || 1) }, worker),
  );
  if (cancelled) return;

  // Settle the run from the DB truth (resumed runs include previously-landed
  // items): failed ONLY when every item errored; any success = done.
  const items = await db.portfolioItem.findMany({ where: { runId }, select: { status: true } });
  const allErrored = items.length > 0 && items.every((it) => it.status === "error");
  await db.portfolioRun.updateMany({
    where: { id: runId },
    data: { status: allErrored ? "failed" : "done" },
  });
  log.info("Portfolio run settled", {
    runId,
    items: items.length,
    status: allErrored ? "failed" : "done",
  });
}

/**
 * Kick (or resume) a run's processor, fire-and-forget. Idempotent per process:
 * a second call while the run is active is a no-op, so POST-then-poll can never
 * double-process. Never throws.
 */
export function startPortfolioRun(runId: string): void {
  if (activeRuns.has(runId)) return;
  activeRuns.add(runId);
  void processRun(runId)
    .catch(async (err) => {
      // Last-ditch: a crashed processor must not strand the run "running"
      // forever with no items left to resume.
      try {
        const { log, db } = await serverDeps();
        log.error("Portfolio run crashed", err, { runId });
        await db.portfolioRun.updateMany({
          where: { id: runId, status: "running" },
          data: { status: "failed" },
        });
      } catch {
        /* logging/settling is best-effort */
      }
    })
    .finally(() => {
      activeRuns.delete(runId);
    });
}
