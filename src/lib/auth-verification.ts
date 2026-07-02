// Self-serve password-reset tokens (review item 28). NODE-ONLY (node:crypto +
// Prisma) — server actions / route handlers only, never the Edge proxy.
//
// Token model: 32 random bytes, hex-encoded, handed to the user in a link;
// only the sha256 HASH is stored (a DB leak exposes nothing usable). Tokens
// are single-use and expire after 15 minutes. Issuing a new token invalidates
// any prior unused reset tokens for the same user, so only the latest link
// works.
//
// consumeResetToken deliberately does NOT mark the token used — the reset
// action marks it used in the SAME $transaction as the password update, so a
// crash between "token spent" and "password changed" can't strand the user.

import { createHash, randomBytes } from "node:crypto";

import { db } from "@/lib/db";
import { createLogger } from "@/lib/utils/logger";

const log = createLogger("AuthVerify");

const RESET_KIND = "reset";
const RESET_TTL_MS = 15 * 60 * 1000; // 15 minutes

/** sha256 hex of a raw token — the ONLY form ever stored or queried. Exported
 *  so the reset action can address the row inside its own transaction. */
export function hashResetToken(raw: string): string {
  return createHash("sha256").update(raw).digest("hex");
}

/**
 * Mint a fresh reset token for the user: invalidates any prior unused reset
 * tokens, stores the sha256 hash with a 15-minute expiry, and returns the RAW
 * token (the only place it ever exists in plaintext).
 */
export async function issueResetToken(userId: string): Promise<string> {
  const rawToken = randomBytes(32).toString("hex");
  const now = new Date();

  await db.$transaction([
    // Only the most recently issued link may be live — retire earlier ones.
    db.verificationToken.updateMany({
      where: { userId, kind: RESET_KIND, usedAt: null },
      data: { usedAt: now },
    }),
    db.verificationToken.create({
      data: {
        userId,
        kind: RESET_KIND,
        tokenHash: hashResetToken(rawToken),
        expiresAt: new Date(now.getTime() + RESET_TTL_MS),
      },
    }),
  ]);

  return rawToken;
}

/**
 * Resolve a raw reset token to its user — must be kind=reset, unused, and
 * unexpired. Does NOT spend the token; the caller marks it used inside the
 * same transaction that updates the password (see resetPassword).
 */
export async function consumeResetToken(rawToken: string): Promise<{ userId: string } | null> {
  if (!rawToken) return null;
  const token = await db.verificationToken.findUnique({
    where: { tokenHash: hashResetToken(rawToken) },
  });
  if (!token) return null;
  if (token.kind !== RESET_KIND) return null;
  if (token.usedAt !== null) return null;
  if (token.expiresAt.getTime() < Date.now()) return null;
  return { userId: token.userId };
}

/**
 * Deliver the reset link. No email provider is configured yet, so when neither
 * RESEND_API_KEY nor SMTP settings are present this logs the full link to the
 * server console — an honest dev fallback, not silent success.
 */
export async function sendResetLink(email: string, rawToken: string): Promise<void> {
  const base = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:4310";
  const url = `${base.replace(/\/$/, "")}/reset-password/${rawToken}`;

  const hasProvider = Boolean(process.env.RESEND_API_KEY || process.env.SMTP_HOST);
  if (!hasProvider) {
    // eslint-disable-next-line no-console -- intentional dev-mode delivery channel
    console.log(`[auth] password-reset link (no email provider configured): ${url} (for ${email})`);
    return;
  }

  // TODO: wire a real provider (Resend or SMTP) here — send `url` to `email`
  // with a "Reset your compbird password" template. Until then, providers that
  // set the env vars still get the console fallback below.
  log.warn("Email provider env present but sender not implemented — logging reset link instead", {
    email,
  });
  // eslint-disable-next-line no-console -- fallback until the provider is wired
  console.log(`[auth] password-reset link (provider not wired): ${url} (for ${email})`);
}
