// compbird's entitlement matrix — a deliberately tiny port of the platform's
// tier system, keeping the SAME API surface (can / quotaFor / withinQuota /
// parseOverrides / EntitlementContext) so the ported routes run unchanged.
//
// Two rungs + admin:
//   FREE — the teaser: the ESTIMATED VALUE of a property (profile lookup +
//          on-screen market cards). No evidence, no downloads.
//   SOLO — "Pro", $20/mo: the EVIDENCE — comps, market analytics, sale
//          history, method breakdown ("cma.evidence") — plus unlimited
//          un-watermarked downloads, whitelabel, statewide coverage.

export type Tier = "FREE" | "SOLO" | "ADMIN";

export type FeatureKey =
  | "cma.profile"
  | "cma.generate"
  | "cma.evidence"
  | "cma.whitelabel"
  | "cma.statewide_data"
  | "market.reports";

/**
 * Capacity of a feature within a tier:
 *   - absent / false → DENIED
 *   - true           → ALLOWED, unlimited
 *   - { limit, period? } → ALLOWED up to `limit` per period
 */
export type Capacity = boolean | { limit: number; period?: "month" };

export type TierMatrix = Partial<Record<FeatureKey, Capacity>>;

export const TIER_MATRIX: Record<Tier, TierMatrix> = {
  FREE: {
    "cma.profile": true, // estimate-only: profile responses are evidence-REDACTED server-side
    "market.reports": true, // on-screen market cards are part of the teaser
  },
  SOLO: {
    "cma.profile": true,
    "cma.generate": true,
    "cma.evidence": true, // comps / market analytics / sale history / method breakdown
    "cma.whitelabel": true,
    "cma.statewide_data": true,
    "market.reports": true,
  },
  ADMIN: {
    "cma.profile": true,
    "cma.generate": true,
    "cma.evidence": true,
    "cma.whitelabel": true,
    "cma.statewide_data": true,
    "market.reports": true,
  },
};

export interface EntitlementContext {
  tier: Tier;
  isSuperAdmin: boolean;
  overrides: TierMatrix;
}

/** Parse the Account.entitlementOverrides JSON column (admin escape hatch). */
export function parseOverrides(raw: string | null | undefined): TierMatrix {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" ? (parsed as TierMatrix) : {};
  } catch {
    return {};
  }
}

function resolveCapacity(ctx: EntitlementContext, feature: FeatureKey): Capacity | undefined {
  if (feature in ctx.overrides) return ctx.overrides[feature];
  return (TIER_MATRIX[ctx.tier] ?? {})[feature];
}

/** Is this feature allowed at all? Super-admin always true. */
export function can(ctx: EntitlementContext, feature: FeatureKey): boolean {
  if (ctx.isSuperAdmin) return true;
  const cap = resolveCapacity(ctx, feature);
  if (cap === true) return true;
  if (cap && typeof cap === "object") return cap.limit > 0;
  return false;
}

/**
 * Quota for a feature:
 *   null   → allowed, UNLIMITED (or super-admin)
 *   number → allowed up to this many
 *   0      → DENIED
 */
export function quotaFor(ctx: EntitlementContext, feature: FeatureKey): number | null {
  if (ctx.isSuperAdmin) return null;
  const cap = resolveCapacity(ctx, feature);
  if (cap === true) return null;
  if (cap && typeof cap === "object") return cap.limit;
  return 0;
}

/** Quota check given current usage. */
export function withinQuota(ctx: EntitlementContext, feature: FeatureKey, usage: number): boolean {
  const q = quotaFor(ctx, feature);
  if (q === null) return true;
  return usage < q;
}
