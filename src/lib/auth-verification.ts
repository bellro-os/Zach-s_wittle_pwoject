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
import { emailShell, sendEmail } from "@/lib/mailer";

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
 * Deliver the reset link. Sends through the Resend-backed mailer when
 * RESEND_API_KEY is set; otherwise (or on delivery failure) logs the full link
 * to the server console — an honest dev fallback, not silent success. sendEmail
 * never throws, so this can't break the requestPasswordReset flow.
 */
export async function sendResetLink(email: string, rawToken: string): Promise<void> {
  const base = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:4310";
  const url = `${base.replace(/\/$/, "")}/reset-password/${rawToken}`;

  const subject = "Reset your compbird password";
  const html = emailShell(
    subject,
    [
      `<p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#374151;">A password reset was requested for this address. Click the button below to choose a new password.</p>`,
      `<p style="margin:0 0 20px;"><a href="${url}" style="display:inline-block;background:#2563eb;color:#ffffff;padding:10px 20px;border-radius:6px;font-size:14px;font-weight:600;text-decoration:none;">Reset password</a></p>`,
      `<p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#6b7280;">This link expires in 15 minutes and can be used once.</p>`,
      `<p style="margin:0;font-size:13px;line-height:1.6;color:#6b7280;">If you didn't request this, you can safely ignore this email — your password is unchanged.</p>`,
    ].join(""),
  );
  const text = `Reset your compbird password: ${url}\n\nThis link expires in 15 minutes and can be used once. If you didn't request this, ignore this email — your password is unchanged.`;

  const sent = await sendEmail({ to: email, subject, html, text });
  if (sent) return;

  // Fallback (no provider configured, or delivery failed): surface the link on
  // the server console so local/dev resets still work.
  // eslint-disable-next-line no-console -- intentional dev-mode delivery channel
  console.log(`[auth] password-reset link (email not sent): ${url} (for ${email})`);
}
