"use server";

import { redirect } from "next/navigation";

import { hashPassword, verifyPassword } from "@/lib/auth-server";
import { db } from "@/lib/db";
import { getActiveContext } from "@/lib/session";
import {
  checkThrottle,
  checkThrottleKey,
  getClientIp,
  loginEmailKey,
  recordFailure,
  recordFailureKey,
  recordSuccess,
  recordSuccessKey,
} from "@/lib/auth-ratelimit";

/** Where the /account actions bounce anonymous callers (matches the page gate). */
const SIGNIN_URL = "/signin?redirect=%2Fcomps";

/** Update the signed-in user's display name (trimmed, capped at 80 chars). */
export async function updateName(formData: FormData): Promise<void> {
  const ctx = await getActiveContext();
  if (!ctx) redirect(SIGNIN_URL);

  const name = String(formData.get("name") ?? "").trim().slice(0, 80);
  await db.authUser.update({
    where: { id: ctx.session.userId },
    data: { name: name || null },
  });
  redirect("/account?saved=1");
}

/**
 * Change the signed-in user's password. Requires the CURRENT password (so a
 * hijacked session can't silently lock the owner out) and throttles the
 * current-password check on the same two dimensions as login — per-IP on the
 * "login" surface AND per-email — so it can't be used as a brute-force oracle.
 */
export async function changePassword(formData: FormData): Promise<void> {
  const ctx = await getActiveContext();
  if (!ctx) redirect(SIGNIN_URL);

  const current = String(formData.get("currentPassword") ?? "");
  const next = String(formData.get("newPassword") ?? "");
  const confirm = String(formData.get("confirmPassword") ?? "");

  const user = await db.authUser.findUnique({ where: { id: ctx.session.userId } });
  if (!user) redirect(SIGNIN_URL);

  // Throttle BEFORE any KDF work. Shares the login buckets deliberately:
  // guessing the current password here is the same attack as guessing it at
  // the sign-in form.
  const ip = await getClientIp();
  const emailKey = loginEmailKey(user.email);
  if (checkThrottle("login", ip).limited || checkThrottleKey(emailKey).limited) {
    redirect("/account?error=pw-throttled");
  }

  // Cheap validation first — these are not credential guesses, so they neither
  // run the KDF nor count against the throttle.
  if (next.length < 8) redirect("/account?error=pw-weak");
  if (next !== confirm) redirect("/account?error=pw-mismatch");

  // A null hash means no password is set (e.g. a provisioned user) — there is
  // no current password to prove, so reject rather than allow a free takeover.
  const ok = user.passwordHash ? await verifyPassword(current, user.passwordHash) : false;
  if (!ok) {
    recordFailure("login", ip);
    recordFailureKey(emailKey);
    redirect("/account?error=pw-current");
  }

  recordSuccess("login", ip);
  recordSuccessKey(emailKey);
  await db.authUser.update({
    where: { id: user.id },
    data: { passwordHash: await hashPassword(next) },
  });
  redirect("/account?pw=1");
}
