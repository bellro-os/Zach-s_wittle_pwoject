// Transactional email over Resend's plain HTTPS API — no SDK, no new deps.
//
// Contract: sendEmail NEVER throws. Email is always best-effort decoration on
// top of an auth/billing flow; a mail outage must never break a password reset
// or a Stripe webhook. Callers branch on the boolean (false = not delivered)
// and fall back to their own behavior (e.g. console-logging a reset link).
//
// Env:
//   RESEND_API_KEY — unset ⇒ every send is suppressed (logged) and returns false.
//   MAIL_FROM      — sender; replace the resend.dev default with the verified
//                    domain sender (e.g. "compbird <mail@compbird.com>") once
//                    the domain is verified in Resend.

import { createLogger } from "@/lib/utils/logger";

const log = createLogger("mailer");

const RESEND_ENDPOINT = "https://api.resend.com/emails";
const SEND_TIMEOUT_MS = 10_000;

export interface SendEmailArgs {
  to: string;
  subject: string;
  html: string;
  text?: string;
}

/** One POST attempt with a hard timeout. Never throws — network errors and
 *  timeouts come back as retryable failures. */
async function postOnce(
  apiKey: string,
  body: string,
): Promise<{ ok: boolean; retryable: boolean; detail: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SEND_TIMEOUT_MS);
  try {
    const res = await fetch(RESEND_ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body,
      signal: controller.signal,
    });
    if (res.ok) return { ok: true, retryable: false, detail: "" };
    const text = await res.text().catch(() => "");
    // 4xx (bad key, invalid from, malformed payload) won't get better on
    // retry; only 5xx is worth a second attempt.
    return { ok: false, retryable: res.status >= 500, detail: `${res.status} ${text}`.trim() };
  } catch (err) {
    // fetch rejection = network failure or our AbortController timeout.
    return { ok: false, retryable: true, detail: err instanceof Error ? err.message : String(err) };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Send one transactional email via Resend. Returns true only on accepted
 * delivery; false when no provider is configured or after the final failed
 * attempt (one retry on 5xx/network). NEVER throws.
 */
export async function sendEmail(args: SendEmailArgs): Promise<boolean> {
  try {
    const apiKey = process.env.RESEND_API_KEY;
    if (!apiKey) {
      log.info(`no provider configured — email suppressed: ${args.subject} -> ${args.to}`);
      return false;
    }

    const from = process.env.MAIL_FROM || "compbird <onboarding@resend.dev>";
    const body = JSON.stringify({
      from,
      to: [args.to],
      subject: args.subject,
      html: args.html,
      ...(args.text ? { text: args.text } : {}),
    });

    const first = await postOnce(apiKey, body);
    if (first.ok) return true;
    if (first.retryable) {
      const second = await postOnce(apiKey, body);
      if (second.ok) return true;
      log.error("send failed after retry", second.detail, { to: args.to, subject: args.subject });
      return false;
    }
    log.error("send failed", first.detail, { to: args.to, subject: args.subject });
    return false;
  } catch (err) {
    // Belt and braces: nothing above should throw, but the contract is
    // absolute — email must never take down an auth/billing flow.
    log.error("unexpected mailer failure", err, { to: args.to, subject: args.subject });
    return false;
  }
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Minimal clean HTML wrapper for transactional mail — plain card, blue
 * (#2563eb) accent, system fonts, no images. bodyHtml is trusted caller
 * markup; title is escaped.
 */
export function emailShell(title: string, bodyHtml: string): string {
  return [
    `<!doctype html><html><body style="margin:0;padding:0;background:#f4f5f7;">`,
    `<div style="max-width:520px;margin:0 auto;padding:32px 16px;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1f2937;">`,
    `<div style="background:#ffffff;border:1px solid #e5e7eb;border-top:3px solid #2563eb;border-radius:8px;padding:28px 32px;">`,
    `<p style="margin:0 0 16px;font-size:13px;font-weight:700;letter-spacing:0.04em;color:#2563eb;">compbird</p>`,
    `<h1 style="margin:0 0 16px;font-size:18px;line-height:1.3;color:#111827;">${escapeHtml(title)}</h1>`,
    bodyHtml,
    `</div>`,
    `<p style="margin:16px 8px 0;font-size:12px;color:#9ca3af;">You're receiving this because of activity on your compbird account.</p>`,
    `</div></body></html>`,
  ].join("");
}
