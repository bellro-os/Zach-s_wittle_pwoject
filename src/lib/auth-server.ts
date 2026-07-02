// NODE-ONLY password hashing. Uses node:crypto scrypt — no extra dependency,
// no plaintext at rest. DO NOT import this from middleware (Edge runtime) or
// any client component; it is for server actions / route handlers only.
// (auth.ts stays Edge-safe and imports nothing from here.)

import { randomBytes, scrypt as _scrypt, timingSafeEqual, type ScryptOptions } from "node:crypto";

// Promisified scrypt that preserves the OPTIONS overload (promisify() narrows to
// the 3-arg form and drops the cost-parameter argument).
function scrypt(password: string, salt: Buffer, keylen: number, options: ScryptOptions): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    _scrypt(password, salt, keylen, options, (err, derivedKey) => {
      if (err) reject(err);
      else resolve(derivedKey as Buffer);
    });
  });
}

// scrypt cost parameters. N*r*128 = ~16 MB at N=16384,r=8 — within the default
// 32 MB maxmem, and a sensible interactive-login cost. Parameters are embedded
// in the stored string so they can be raised later without breaking old hashes.
const N = 16384;
const R = 8;
const P = 1;
const KEYLEN = 64;

/** Returns "scrypt$N$r$p$saltB64$hashB64". */
export async function hashPassword(plain: string): Promise<string> {
  if (!plain || plain.length < 8) {
    throw new Error("Password must be at least 8 characters.");
  }
  const salt = randomBytes(16);
  const dk = (await scrypt(plain, salt, KEYLEN, { N, r: R, p: P, maxmem: 64 * 1024 * 1024 })) as Buffer;
  return `scrypt$${N}$${R}$${P}$${salt.toString("base64")}$${dk.toString("base64")}`;
}

/** Constant-time verify against a stored "scrypt$..." string. */
export async function verifyPassword(plain: string, stored: string | null | undefined): Promise<boolean> {
  if (!stored || !plain) return false;
  const parts = stored.split("$");
  if (parts.length !== 6 || parts[0] !== "scrypt") return false;
  const [, ns, rs, ps, saltB64, hashB64] = parts;
  try {
    const salt = Buffer.from(saltB64, "base64");
    const expected = Buffer.from(hashB64, "base64");
    const dk = (await scrypt(plain, salt, expected.length, {
      N: Number(ns), r: Number(rs), p: Number(ps), maxmem: 64 * 1024 * 1024,
    })) as Buffer;
    return dk.length === expected.length && timingSafeEqual(dk, expected);
  } catch {
    return false;
  }
}
