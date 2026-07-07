"use client";

/**
 * Client-side ad-event helpers — Meta Pixel (fbq) + Google Ads (gtag).
 *
 * Everything here is a safe no-op unless (a) the visitor accepted the consent
 * banner and (b) the corresponding pixel id is configured, so the app runs
 * identically with zero marketing env vars set (mirrors the Stripe/Resend
 * graceful-degradation pattern).
 *
 * Consent is a plain (non-httpOnly) cookie so this module, the banner, and the
 * server (checkout route → Stripe metadata → webhook CAPI) all read one flag.
 */

export const CONSENT_COOKIE = "cb_consent";
export const CONSENT_EVENT = "cb-consent-granted";

export const META_PIXEL_ID = process.env.NEXT_PUBLIC_META_PIXEL_ID?.trim() || "";
export const GOOGLE_ADS_ID = process.env.NEXT_PUBLIC_GOOGLE_ADS_ID?.trim() || "";
const GADS_SIGNUP_LABEL = process.env.NEXT_PUBLIC_GOOGLE_ADS_SIGNUP_LABEL?.trim() || "";
const GADS_SUBSCRIBE_LABEL = process.env.NEXT_PUBLIC_GOOGLE_ADS_SUBSCRIBE_LABEL?.trim() || "";

/** Minimal typings for the injected globals (loaded by <MarketingPixels/>). */
declare global {
  interface Window {
    fbq?: (...args: unknown[]) => void;
    gtag?: (...args: unknown[]) => void;
  }
}

export type ConsentState = "granted" | "denied" | "unset";

export function readConsent(): ConsentState {
  if (typeof document === "undefined") return "unset";
  const m = document.cookie.match(/(?:^|;\s*)cb_consent=(granted|denied)(?:;|$)/);
  return (m?.[1] as ConsentState) ?? "unset";
}

export function writeConsent(value: "granted" | "denied"): void {
  if (typeof document === "undefined") return;
  // 12 months; SameSite=Lax so the checkout route sees it on navigation POSTs.
  document.cookie = `${CONSENT_COOKIE}=${value}; Max-Age=31536000; Path=/; SameSite=Lax`;
  if (value === "granted") window.dispatchEvent(new Event(CONSENT_EVENT));
}

const canTrack = (): boolean => typeof window !== "undefined" && readConsent() === "granted";

/** Meta standard event (PageView, CompleteRegistration, InitiateCheckout, …). */
export function metaTrack(
  event: string,
  params?: Record<string, unknown>,
  eventId?: string,
): void {
  if (!canTrack() || !window.fbq) return;
  // eventID enables dedup against the server-side Conversions API copy.
  window.fbq("track", event, params ?? {}, eventId ? { eventID: eventId } : undefined);
}

/** Google Ads conversion ping (no-op unless the id + label are configured). */
function gadsConversion(label: string, params?: Record<string, unknown>): void {
  if (!canTrack() || !window.gtag || !GOOGLE_ADS_ID || !label) return;
  window.gtag("event", "conversion", { send_to: `${GOOGLE_ADS_ID}/${label}`, ...params });
}

/** SPA page view on route change — both networks. */
export function trackPageView(): void {
  if (!canTrack()) return;
  window.fbq?.("track", "PageView");
  if (GOOGLE_ADS_ID) window.gtag?.("config", GOOGLE_ADS_ID, { page_path: window.location.pathname });
}

/** Free account created. */
export function trackSignup(): void {
  metaTrack("CompleteRegistration", { content_name: "free_account" });
  gadsConversion(GADS_SIGNUP_LABEL);
}

/** Pro checkout opened (fires before the redirect to Stripe). */
export function trackCheckoutStart(): void {
  metaTrack("InitiateCheckout", { content_name: "pro_monthly", currency: "USD", value: 20 });
}

/**
 * Pro subscription confirmed (back from Stripe with ?subscribed=1&cs=…).
 * `eventId` is the Stripe Checkout session id — the SAME id the webhook sends
 * via the Conversions API, so Meta dedups the browser + server copies.
 */
export function trackSubscribe(eventId?: string): void {
  metaTrack("Subscribe", { content_name: "pro_monthly", currency: "USD", value: 20 }, eventId);
  gadsConversion(GADS_SUBSCRIBE_LABEL, { value: 20, currency: "USD", transaction_id: eventId });
}

/** A comp report was generated — the "activation" moment ads optimize toward. */
export function trackReportGenerated(): void {
  metaTrack("Lead", { content_name: "comp_report" });
}
