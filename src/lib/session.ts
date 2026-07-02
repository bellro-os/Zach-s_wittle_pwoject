// Server-side session + entitlement access. Resolves the cb_session cookie →
// AuthUser + Account → an EntitlementContext, and exposes the guards routes
// use. SERVER ONLY (imports Prisma + next/headers). Reduced port of the
// platform's session.ts (no tenancy extension — explicit ids everywhere).

import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { db, systemDb } from "@/lib/db";
import { SESSION_COOKIE, verifyAppSessionToken, type AppSessionPayload } from "@/lib/auth";
import {
  can as canFeature,
  parseOverrides,
  quotaFor,
  withinQuota,
  type EntitlementContext,
  type FeatureKey,
  type Tier,
} from "@/lib/entitlements";
import {
  monthStart,
  reserveUsage as reserveUsageWith,
  refundUsage as refundUsageWith,
  type UsageClient,
  type UsageReservation,
} from "@/lib/usage";

export interface ActiveContext {
  session: AppSessionPayload;
  account: { id: string; name: string; tier: string; entitlementOverrides: string };
  ent: EntitlementContext;
}

/** Verify the cookie → payload (no DB hit). */
export async function getSession(): Promise<AppSessionPayload | null> {
  const jar = await cookies();
  return verifyAppSessionToken(jar.get(SESSION_COOKIE)?.value);
}

/** Full context: session + the account row + a resolved EntitlementContext.
 *  Re-validates the membership + super-admin flag against the DB on every call,
 *  making sessions effectively revocable before the 14-day token TTL. */
export async function getActiveContext(): Promise<ActiveContext | null> {
  const session = await getSession();
  if (!session) return null;
  const [account, membership, user] = await Promise.all([
    db.account.findUnique({ where: { id: session.accountId } }),
    db.membership.findUnique({
      where: { userId_accountId: { userId: session.userId, accountId: session.accountId } },
    }),
    db.authUser.findUnique({ where: { id: session.userId }, select: { isSuperAdmin: true } }),
  ]);
  if (!account || !membership || !user) return null;
  const isSuperAdmin = user.isSuperAdmin === true;
  const freshSession: AppSessionPayload = {
    ...session,
    role: membership.role as AppSessionPayload["role"],
    sa: isSuperAdmin || undefined,
  };
  const ent: EntitlementContext = {
    tier: account.tier as Tier,
    isSuperAdmin,
    overrides: parseOverrides(account.entitlementOverrides),
  };
  return { session: freshSession, account, ent };
}

/** Redirect to /join if there's no valid session; else return the context. */
export async function requireAccount(): Promise<ActiveContext> {
  const ctx = await getActiveContext();
  if (!ctx) redirect("/join");
  return ctx;
}

/** True if the CURRENT account may use this feature (super-admin always true). */
export async function can(feature: FeatureKey): Promise<boolean> {
  const ctx = await getActiveContext();
  if (!ctx) return false;
  return canFeature(ctx.ent, feature);
}

/** Count this calendar month's usage of a metered feature for an account. */
export async function monthlyUsage(feature: FeatureKey, accountId: string): Promise<number> {
  return systemDb.usageEvent.count({
    where: { accountId, feature, createdAt: { gte: monthStart() } },
  });
}

/**
 * Atomically reserve one usage of a metered feature, enforcing the tier quota
 * under concurrency. Reserve BEFORE the billable work and refundUsage() the
 * returned `eventId` if that work fails, so only successful actions stay metered.
 */
export async function reserveUsage(
  feature: FeatureKey,
  accountId: string,
  limit: number | null,
): Promise<UsageReservation> {
  return reserveUsageWith(systemDb as unknown as UsageClient, feature, accountId, limit);
}

/** Release a reservation made by reserveUsage() (best-effort). */
export async function refundUsage(eventId: string): Promise<void> {
  return refundUsageWith(systemDb as unknown as UsageClient, eventId);
}

export { quotaFor, withinQuota };
export type { UsageReservation };
