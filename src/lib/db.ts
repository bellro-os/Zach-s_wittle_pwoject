// Prisma client singleton. compbird has NO multi-tenant scoping extension —
// every server codepath passes explicit ids — so `db` and `systemDb` are the
// same plain client; both names exist because the ported platform code uses
// `db` in actions and `systemDb` in billing/metering.

import { PrismaClient } from "@/generated/prisma";

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const systemDb: PrismaClient = globalForPrisma.prisma ?? new PrismaClient();
export const db = systemDb;

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = systemDb;
