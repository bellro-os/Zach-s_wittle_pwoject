import { createHash } from "node:crypto";
import { createLogger } from "@/lib/utils/logger";

/**
 * Meta Conversions API (server-side events) — used by the Stripe webhook to
 * report the Subscribe conversion even when the browser pixel is blocked.
 *
 * Fire-and-forget by design: ad reporting must NEVER fail (or slow) a billing
 * webhook. Configured via META_PIXEL_ID (or NEXT_PUBLIC_META_PIXEL_ID) +
 * META_CAPI_ACCESS_TOKEN; silently inactive when either is missing.
 *
 * Consent: callers pass `consented` (read from the cb_consent cookie at
 * checkout time and carried through Stripe metadata) — no consent, no event.
 */

const log = createLogger("marketing/meta-capi");

const GRAPH_VERSION = "v21.0";

function pixelId(): string {
  return (
    process.env.META_PIXEL_ID?.trim() ||
    process.env.NEXT_PUBLIC_META_PIXEL_ID?.trim() ||
    ""
  );
}

function accessToken(): string {
  return process.env.META_CAPI_ACCESS_TOKEN?.trim() || "";
}

export function metaCapiConfigured(): boolean {
  return Boolean(pixelId() && accessToken());
}

/** Meta requires SHA-256 of the normalized (trimmed, lowercased) value. */
function sha256(value: string): string {
  return createHash("sha256").update(value.trim().toLowerCase()).digest("hex");
}

/**
 * Send the Subscribe event for a completed checkout. `eventId` MUST be the
 * Stripe Checkout session id — the browser fires the same id, Meta dedups.
 */
export function sendMetaSubscribeEvent(args: {
  email: string | null | undefined;
  eventId: string;
  consented: boolean;
  value?: number;
  currency?: string;
}): void {
  if (!metaCapiConfigured()) return;
  if (!args.consented) return; // visitor never accepted the banner — stay silent

  const base = (process.env.NEXT_PUBLIC_APP_URL || "").replace(/\/$/, "");
  const body = {
    data: [
      {
        event_name: "Subscribe",
        event_time: Math.floor(Date.now() / 1000),
        event_id: args.eventId,
        action_source: "website",
        event_source_url: base ? `${base}/comps` : undefined,
        user_data: {
          // Hashed email is the only identifier we send — no IP/UA spoofing
          // from a server hop (the webhook's caller is Stripe, not the user).
          em: args.email ? [sha256(args.email)] : undefined,
        },
        custom_data: {
          currency: args.currency ?? "USD",
          value: args.value ?? 20,
          content_name: "pro_monthly",
        },
      },
    ],
  };

  // Deliberately not awaited by callers — see module docblock.
  void fetch(
    `https://graph.facebook.com/${GRAPH_VERSION}/${pixelId()}/events?access_token=${encodeURIComponent(accessToken())}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
  )
    .then(async (res) => {
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        log.warn("Meta CAPI event rejected", { status: res.status, body: text.slice(0, 300) });
      } else {
        log.info("Meta CAPI Subscribe sent", { eventId: args.eventId });
      }
    })
    .catch((err) => {
      log.warn("Meta CAPI event failed", {
        error: err instanceof Error ? err.message : String(err),
      });
    });
}
