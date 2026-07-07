"use client";

import { useEffect, useState } from "react";
import { GOOGLE_ADS_ID, META_PIXEL_ID, readConsent, writeConsent } from "@/lib/marketing/track";

/**
 * Minimal cookie-consent bar for the ad pixels. Only renders when a pixel is
 * actually configured AND the visitor hasn't chosen yet — so dev machines and
 * pixel-less deploys never see it. "Accept" loads the pixels immediately
 * (via the cb-consent-granted event <MarketingPixels/> listens for);
 * "Essential only" persists the opt-out and nothing ever loads.
 */
export function ConsentBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!META_PIXEL_ID && !GOOGLE_ADS_ID) return;
    setVisible(readConsent() === "unset");
  }, []);

  if (!visible) return null;

  const choose = (value: "granted" | "denied") => {
    writeConsent(value);
    setVisible(false);
  };

  return (
    <div
      role="region"
      aria-label="Cookie consent"
      className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-card/95 px-5 py-4 backdrop-blur supports-[backdrop-filter]:bg-card/85"
    >
      <div className="mx-auto flex max-w-6xl flex-col items-start gap-3 sm:flex-row sm:items-center">
        <p className="flex-1 text-sm leading-relaxed text-muted-foreground">
          We use cookies for analytics and advertising — they help us measure what
          works and show compbird to people pricing homes. Essential cookies (like
          staying signed in) are always on.{" "}
          <a href="/privacy" className="underline underline-offset-2 hover:text-foreground">
            Privacy policy
          </a>
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => choose("denied")}
            className="rounded-full border border-border bg-transparent px-4 py-2 text-sm font-semibold text-muted-foreground transition-colors hover:text-foreground"
          >
            Essential only
          </button>
          <button
            type="button"
            onClick={() => choose("granted")}
            className="rounded-full bg-[var(--cb-ember)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          >
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}
