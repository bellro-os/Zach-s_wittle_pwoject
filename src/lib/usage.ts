// Atomic usage metering for quota-gated features.
//
// The naive "count → do the expensive work → record" sequence is a
// check-then-act TOCTOU race: under concurrent requests every caller reads the
// SAME pre-work count, every caller passes the quota check, and every caller
// records afterward — so a capped tier (FREE = 2/mo, BETA = 25/mo) can overshoot
// its plan per burst. reserveUsage() closes the race by inserting the usage row
// and re-counting INSIDE one transaction: the SQLite engine serializes writers
// (the app runs a single connection), so each caller sees every earlier caller's
// row and only the first `limit` reservations survive.
//
// Pure + dependency-light by design. The only thing it touches is an INJECTED
// Prisma-shaped client, so it can be exercised against a throwaway SQLite DB
// (see tests/usage-quota.test.ts) without pulling in `server-only` /
// `next/headers`. The app wires the real `systemDb` in via src/lib/session.ts.

import type { FeatureKey } from "@/lib/entitlements";

/** The slice of a Prisma `usageEvent` delegate reserveUsage/refundUsage need. */
export interface UsageEventDelegate {
  create(args: { data: { feature: string; accountId: string } }): Promise<{ id: string }>;
  count(args: {
    where: { accountId: string; feature: string; createdAt: { gte: Date } };
  }): Promise<number>;
  delete(args: { where: { id: string } }): Promise<unknown>;
}

/** A transaction-scoped client (interactive `$transaction` callback arg). */
export interface UsageTxClient {
  usageEvent: UsageEventDelegate;
}

/** A Prisma-shaped client. The app's `systemDb` and a bare test PrismaClient
 *  both satisfy this structurally. */
export interface UsageClient extends UsageTxClient {
  $transaction<T>(fn: (tx: UsageTxClient) => Promise<T>): Promise<T>;
}

/** Outcome of reserveUsage(). On success `eventId` is the row to refundUsage()
 *  if the billable work then fails; on rejection nothing was kept. */
export type UsageReservation =
  | { ok: true; used: number; eventId: string }
  | { ok: false; used: number };

/** First instant of the current calendar month (local time) — the metering
 *  window. Kept here so monthlyUsage() (session.ts) and reserveUsage() agree on
 *  exactly one definition of "this month". */
export function monthStart(now: Date = new Date()): Date {
  return new Date(now.getFullYear(), now.getMonth(), 1);
}

/**
 * Atomically reserve one usage of `feature` for `accountId`, enforcing `limit`
 * under concurrency.
 *
 *   limit === null → unlimited (e.g. super-admin); the row is still inserted for
 *                    metering and `ok` is always true.
 *   used > limit   → over quota; the just-inserted row is removed inside the
 *                    same transaction (net zero) and `ok` is false.
 *
 * Reserve BEFORE the billable work and refundUsage() the returned `eventId` if
 * that work fails, so only successful actions stay metered (matching the prior
 * record-on-success behavior).
 */
export async function reserveUsage(
  client: UsageClient,
  feature: FeatureKey,
  accountId: string,
  limit: number | null,
): Promise<UsageReservation> {
  const since = monthStart();
  return client.$transaction(async (tx) => {
    // Insert FIRST so the re-count includes THIS reservation, then enforce the
    // post-increment count. Both run in one transaction, so a concurrent caller
    // cannot slip its own check between our insert and our count.
    const created = await tx.usageEvent.create({ data: { feature, accountId } });
    const used = await tx.usageEvent.count({
      where: { accountId, feature, createdAt: { gte: since } },
    });
    if (limit !== null && used > limit) {
      // Over quota — undo the reservation so the cap holds exactly.
      await tx.usageEvent.delete({ where: { id: created.id } });
      return { ok: false, used: used - 1 };
    }
    return { ok: true, used, eventId: created.id };
  });
}

/** Release a reservation (the billable work failed). Best-effort: a failed
 *  refund must never mask the original error. */
export async function refundUsage(client: UsageClient, eventId: string): Promise<void> {
  try {
    await client.usageEvent.delete({ where: { id: eventId } });
  } catch {
    /* row already gone / transient DB error — metering is best-effort */
  }
}
