import { appendFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { NextResponse } from "next/server";
import { checkWaitlist, getClientIp, recordWaitlistAttempt } from "@/lib/auth-ratelimit";
import { bodyTooLarge, BODY_TOO_LARGE_RESPONSE } from "@/lib/compbird/body-limit";
import { createLogger } from "@/lib/utils/logger";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const log = createLogger("Waitlist");

/**
 * Coverage waitlist — the "tell me when you reach my state" capture behind the
 * out-of-coverage no-results panel. Deliberately tiny: no account, no DB row,
 * just an append-only JSONL file on the persistent /data volume (one line per
 * submission: {email, q?, ts}). The launch list for the US expansion gets
 * harvested from that file offline.
 *
 * POST {email: string, q?: string} → 200 {ok:true} | 400 invalid | 429 throttled.
 * The email is NEVER echoed back (nor is anything else request-derived).
 * GET → 405: there is no read surface — the file is operator-only.
 */

/** Simple shape check — one "@" with something either side, no whitespace. */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const EMAIL_MAX = 254;
/** Cap on the optional context field (the search query that dead-ended). */
const Q_MAX = 120;

function waitlistPath(): string {
  return process.env.WAITLIST_PATH || "/data/waitlist.jsonl";
}

/** Strip C0 control chars + DEL (JSONL is line-delimited — no raw newlines). */
function stripControl(value: string): string {
  let out = "";
  for (const ch of value) {
    const code = ch.charCodeAt(0);
    if (code < 0x20 || code === 0x7f) continue;
    out += ch;
  }
  return out;
}

export async function POST(req: Request) {
  // Per-IP cap (5/hour — see auth-ratelimit). Every attempt counts, valid or
  // not, so scripted garbage throttles itself instead of probing the validator.
  const ip = await getClientIp();
  const rl = checkWaitlist(ip);
  if (rl.limited) {
    return NextResponse.json(
      { ok: false, error: "Too many requests. Please try again later." },
      { status: 429, headers: { "Retry-After": String(rl.retryAfterSeconds) } },
    );
  }
  recordWaitlistAttempt(ip);

  // Size gate BEFORE the body is read (see body-limit.ts) — a one-field email
  // capture has no business carrying more than a few hundred bytes.
  if (bodyTooLarge(req)) {
    return NextResponse.json(BODY_TOO_LARGE_RESPONSE, { status: 413 });
  }

  let payload: { email?: unknown; q?: unknown };
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }

  const email =
    typeof payload.email === "string" ? stripControl(payload.email.trim()).toLowerCase() : "";
  if (!email || email.length > EMAIL_MAX || !EMAIL_RE.test(email)) {
    return NextResponse.json(
      { ok: false, error: "Enter a valid email address." },
      { status: 400 },
    );
  }
  const q =
    typeof payload.q === "string" ? stripControl(payload.q.trim()).slice(0, Q_MAX) : "";

  const line =
    JSON.stringify({ email, ...(q ? { q } : {}), ts: new Date().toISOString() }) + "\n";
  try {
    const path = waitlistPath();
    // Create-if-missing, both dir and file: mkdir is a no-op when /data exists;
    // appendFile's default "a" flag creates the file on first write.
    await mkdir(dirname(path), { recursive: true });
    await appendFile(path, line, "utf8");
  } catch (err) {
    // Never surface (or log) the address on failure — the capture is best
    // effort, but the caller deserves an honest signal to retry.
    log.error("Waitlist append failed", err);
    return NextResponse.json(
      { ok: false, error: "Couldn't save that right now — please try again." },
      { status: 500 },
    );
  }

  return NextResponse.json({ ok: true });
}

export function GET() {
  return NextResponse.json(
    { ok: false, error: "Method not allowed" },
    { status: 405, headers: { Allow: "POST" } },
  );
}
