// Edge-safe authentication helpers — compbird's OWN session realm.
// Uses only Web Crypto + standard globals so this module can be imported from
// the proxy (Edge runtime), server actions, and route handlers alike.
// Do NOT import Node-only modules or Prisma here.
//
// Ported from the platform's auth.ts but deliberately separate: its own cookie
// name (cb_session — a Ratifyly dca_session cookie means NOTHING here) and its
// own signing secret, so no session crosses the compbird/Ratifyly boundary.

export const SESSION_COOKIE = "cb_session";
export const SESSION_TTL_SECONDS = 60 * 60 * 24 * 14; // 14 days

const DEV_FALLBACK_SECRET = "dev-insecure-secret-change-me";

function getSecret(): string {
  const s = process.env.SESSION_SECRET;
  if (!s || s.length < 16) {
    if (process.env.NODE_ENV === "production") {
      throw new Error("SESSION_SECRET must be set to a string of at least 16 characters in production.");
    }
    return DEV_FALLBACK_SECRET;
  }
  return s;
}

// ─── base64url ────────────────────────────────────────────────

function base64urlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64urlDecode(str: string): Uint8Array {
  const pad = str.length % 4 === 0 ? "" : "=".repeat(4 - (str.length % 4));
  const bin = atob(str.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

// ─── crypto helpers ───────────────────────────────────────────

async function hmac(data: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(getSecret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
  return base64urlEncode(new Uint8Array(sig));
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return result === 0;
}

// ─── app session tokens ───────────────────────────────────────
// HMAC-signed envelope carrying who + which account + role, so the proxy and
// server code can scope without a DB hit.

export type AppRole = "OWNER" | "ADMIN" | "MEMBER" | "VIEWER";

export interface AppSessionPayload {
  userId: string;
  accountId: string;
  role: AppRole;
  /** Mirrors AuthUser.isSuperAdmin so the proxy can fast-path god-mode. */
  sa?: boolean;
  exp: number;
}

export async function createAppSessionToken(args: {
  userId: string;
  accountId: string;
  role: AppRole;
  isSuperAdmin?: boolean;
}): Promise<string> {
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const payload: AppSessionPayload = {
    userId: args.userId,
    accountId: args.accountId,
    role: args.role,
    sa: args.isSuperAdmin || undefined,
    exp,
  };
  const encoded = base64urlEncode(new TextEncoder().encode(JSON.stringify(payload)));
  const sig = await hmac(encoded);
  return `${encoded}.${sig}`;
}

export async function verifyAppSessionToken(
  token: string | undefined,
): Promise<AppSessionPayload | null> {
  if (!token) return null;
  const dot = token.indexOf(".");
  if (dot < 1) return null;
  const payload = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  if (!payload || !sig) return null;

  const expected = await hmac(payload);
  if (!timingSafeEqual(sig, expected)) return null;

  try {
    const d = JSON.parse(new TextDecoder().decode(base64urlDecode(payload))) as Partial<AppSessionPayload>;
    if (typeof d.exp !== "number" || d.exp < Math.floor(Date.now() / 1000)) return null;
    if (typeof d.userId !== "string" || typeof d.accountId !== "string") return null;
    if (d.role !== "OWNER" && d.role !== "ADMIN" && d.role !== "MEMBER" && d.role !== "VIEWER") return null;
    return { userId: d.userId, accountId: d.accountId, role: d.role, sa: d.sa === true, exp: d.exp };
  } catch {
    return null;
  }
}
