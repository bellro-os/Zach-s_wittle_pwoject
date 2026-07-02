"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import {
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  createAppSessionToken,
  type AppRole,
} from "@/lib/auth";
import { hashPassword, verifyPassword } from "@/lib/auth-server";
import {
  consumeResetToken,
  hashResetToken,
  issueResetToken,
  sendResetLink,
} from "@/lib/auth-verification";
import { db } from "@/lib/db";
import { createLogger } from "@/lib/utils/logger";
import {
  checkGlobalSignup,
  checkThrottle,
  checkThrottleKey,
  getClientIp,
  loginEmailKey,
  recordFailure,
  recordFailureKey,
  recordGlobalSignupAttempt,
  recordSuccess,
  recordSuccessKey,
} from "@/lib/auth-ratelimit";

const log = createLogger("Auth");

// A real, well-formed scrypt hash (of a throwaway password) used ONLY as a
// constant-time decoy when the supplied email has no account, so response
// timing doesn't leak whether an account exists. Same cost parameters as live
// hashes (see auth-server.ts).
const DUMMY_PASSWORD_HASH =
  "scrypt$16384$8$1$wZcfqLAXJppP1DAc/M1GFQ==$4pxjyzZfcG/v4HBOvGsoawU6LC9c2hPhsdB/noym90EIkCPORDVggMoTQBwjACTS0y3xuynF1nXdXZTYyG1aYw==";

async function setSessionCookie(args: {
  userId: string;
  accountId: string;
  role: AppRole;
  isSuperAdmin: boolean;
}): Promise<void> {
  const token = await createAppSessionToken(args);
  const jar = await cookies();
  jar.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });
}

/** Allowlist a post-auth redirect target — internal studio paths only. */
function safeAuthRedirect(raw: FormDataEntryValue | null): string {
  const v = typeof raw === "string" ? raw.trim() : "";
  return /^\/(?:comps(?:\/[A-Za-z0-9._~-]*)?)?$/.test(v) ? v || "/comps" : "/comps";
}

/** Email + password login → session scoped to the user's account. */
export async function login(formData: FormData): Promise<void> {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");
  const redirectTo = safeAuthRedirect(formData.get("redirect"));
  const errUrl = (q: string) => `/signin?redirect=${encodeURIComponent(redirectTo)}&${q}`;

  // Throttle on TWO dimensions so neither IP rotation nor a single targeted
  // account defeats the limit: per-IP AND per-email.
  const ip = await getClientIp();
  const emailKey = email ? loginEmailKey(email) : null;
  if (checkThrottle("login", ip).limited) redirect(errUrl("error=throttled"));
  if (emailKey && checkThrottleKey(emailKey).limited) redirect(errUrl("error=throttled"));

  const user = email
    ? await db.authUser.findUnique({
        where: { email },
        include: { memberships: { orderBy: { createdAt: "asc" } } },
      })
    : null;

  // Always run the password KDF — verify against a fixed dummy hash when the
  // user is missing so timing doesn't leak account existence.
  const ok = await verifyPassword(password, user ? user.passwordHash : DUMMY_PASSWORD_HASH);
  if (!ok || !user) {
    const after = recordFailure("login", ip);
    if (emailKey) recordFailureKey(emailKey);
    redirect(errUrl(after.limited ? "error=throttled" : "error=1"));
  }

  const membership = user.memberships[0];
  if (!membership) redirect(errUrl("error=noaccount"));

  recordSuccess("login", ip);
  if (emailKey) recordSuccessKey(emailKey);
  await db.authUser.update({ where: { id: user.id }, data: { lastLoginAt: new Date() } });
  await setSessionCookie({
    userId: user.id,
    accountId: membership.accountId,
    role: membership.role as AppRole,
    isSuperAdmin: user.isSuperAdmin,
  });
  redirect(redirectTo);
}

/** Self-serve signup → a metered FREE account + an OWNER user, then signs in.
 *  Every public signup mints FREE — the paid tier comes only from Stripe. */
export async function signup(formData: FormData): Promise<void> {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const redirectTo = safeAuthRedirect(formData.get("redirect"));

  const ip = await getClientIp();
  if (checkThrottle("signup", ip).limited) redirect("/join?error=throttled");
  if (checkGlobalSignup().limited) redirect("/join?error=throttled");
  recordGlobalSignupAttempt();

  // Bounce back to the form on a validation error, preserving the typed fields
  // (NEVER the password).
  const back = (errorCode: string): never => {
    const qs = new URLSearchParams({ error: errorCode });
    if (name) qs.set("name", name);
    if (email) qs.set("email", email);
    redirect(`/join?${qs.toString()}`);
  };

  if (!email || !email.includes("@")) back("email");
  if (password.length < 8) back("weak");

  const existing = await db.authUser.findUnique({ where: { email } });
  if (existing) {
    recordFailure("signup", ip);
    back("exists");
  }

  let passwordHash: string;
  try {
    passwordHash = await hashPassword(password);
  } catch {
    back("weak");
  }

  // Account + owner user + membership, atomically. The findUnique pre-check has
  // a race; the DB unique constraint is the real guard — map its P2002 to the
  // same friendly "already in use" result.
  let user: { id: string };
  let accountId: string;
  try {
    const result = await db.$transaction(async (tx) => {
      const account = await tx.account.create({ data: { name: name || email, tier: "FREE" } });
      const created = await tx.authUser.create({
        data: { email, name: name || null, passwordHash },
      });
      await tx.membership.create({
        data: { userId: created.id, accountId: account.id, role: "OWNER" },
      });
      return { user: created, accountId: account.id };
    });
    user = result.user;
    accountId = result.accountId;
  } catch (err) {
    // redirect() unwinds via a thrown NEXT_REDIRECT — never swallow it.
    if ((err as { digest?: string }).digest?.startsWith("NEXT_REDIRECT")) throw err;
    if ((err as { code?: string }).code === "P2002") {
      recordFailure("signup", ip);
      back("exists");
    }
    throw err;
  }

  recordSuccess("signup", ip);
  log.info("Account created", { accountId });
  await setSessionCookie({ userId: user.id, accountId, role: "OWNER", isSuperAdmin: false });
  redirect(redirectTo);
}

export async function logout(): Promise<void> {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  redirect("/");
}

/** Self-serve password reset, step 1: request a reset link by email.
 *  ALWAYS lands on /forgot-password?sent=1 whether or not the account exists —
 *  the response must not leak account existence. Throttled on the SAME buckets
 *  as login (per-IP + per-email), and every attempt records a failure so
 *  address probing throttles itself. */
export async function requestPasswordReset(formData: FormData): Promise<void> {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();

  const ip = await getClientIp();
  const emailKey = email ? loginEmailKey(email) : null;
  if (checkThrottle("login", ip).limited) redirect("/forgot-password?error=throttled");
  if (emailKey && checkThrottleKey(emailKey).limited) redirect("/forgot-password?error=throttled");

  // Every request counts as a "failure" — there is no success signal that
  // should clear the bucket, and probing many addresses must hit the limiter.
  recordFailure("login", ip);
  if (emailKey) recordFailureKey(emailKey);

  if (email && email.includes("@")) {
    const user = await db.authUser.findUnique({ where: { email } });
    if (user) {
      // Best-effort: a delivery hiccup must not turn into an existence oracle.
      try {
        const rawToken = await issueResetToken(user.id);
        await sendResetLink(email, rawToken);
      } catch (err) {
        log.error("Password-reset issue/send failed", err, { userId: user.id });
      }
    }
  }

  redirect("/forgot-password?sent=1");
}

/** Self-serve password reset, step 2: set the new password with a valid token.
 *  The token is spent in the SAME transaction as the password update. */
export async function resetPassword(formData: FormData): Promise<void> {
  const token = String(formData.get("token") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const confirm = String(formData.get("confirm") ?? "");

  if (!token) redirect("/signin?resetError=1");

  // Form-shape errors bounce back to the reset form (token still in the URL);
  // token errors dead-end to signin — the link is unusable, retrying won't help.
  const back = (errorCode: string): never =>
    redirect(`/reset-password/${encodeURIComponent(token)}?error=${errorCode}`);
  if (password.length < 8) back("weak");
  if (password !== confirm) back("mismatch");

  const resolved = await consumeResetToken(token);
  if (!resolved) redirect("/signin?resetError=1");

  let passwordHash: string;
  try {
    passwordHash = await hashPassword(password);
  } catch {
    back("weak");
  }

  // Spend the token and set the password atomically — updateMany's usedAt:null
  // guard makes a concurrent double-submit a no-op on the second run.
  const tokenHash = hashResetToken(token);
  const spent = await db.$transaction(async (tx) => {
    const marked = await tx.verificationToken.updateMany({
      where: { tokenHash, usedAt: null },
      data: { usedAt: new Date() },
    });
    if (marked.count === 0) return false;
    await tx.authUser.update({
      where: { id: resolved.userId },
      data: { passwordHash },
    });
    return true;
  });
  if (!spent) redirect("/signin?resetError=1");

  log.info("Password reset completed", { userId: resolved.userId });
  redirect("/signin?reset=1");
}
