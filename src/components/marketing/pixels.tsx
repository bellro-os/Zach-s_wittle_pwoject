"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import {
  CONSENT_EVENT,
  GOOGLE_ADS_ID,
  META_PIXEL_ID,
  readConsent,
  trackPageView,
  trackSignup,
} from "@/lib/marketing/track";

/**
 * Loads the Meta Pixel + Google tag AFTER the visitor grants consent, then
 * tracks SPA route changes as page views. Renders nothing. With no pixel ids
 * configured (dev default) this whole component is inert.
 *
 * Also consumes the `?signedup=1` marker the signup action appends to its
 * post-registration redirect (same pattern as SubscribeToast's ?subscribed=1):
 * fires CompleteRegistration once, then strips the param from the URL.
 */
export function MarketingPixels() {
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const loadedRef = useRef(false);

  // Load pixels when consent is already granted, or the moment it becomes so.
  useEffect(() => {
    if (!META_PIXEL_ID && !GOOGLE_ADS_ID) return;

    const load = () => {
      if (loadedRef.current) return;
      loadedRef.current = true;

      if (META_PIXEL_ID && !window.fbq) {
        // Standard Meta bootstrap (queues calls until the script arrives).
        const fbq: {
          (...args: unknown[]): void;
          callMethod?: (...args: unknown[]) => void;
          queue: unknown[];
          push: unknown;
          loaded: boolean;
          version: string;
        } = function (...args: unknown[]) {
          if (fbq.callMethod) fbq.callMethod(...args);
          else fbq.queue.push(args);
        };
        fbq.push = fbq;
        fbq.loaded = true;
        fbq.version = "2.0";
        fbq.queue = [];
        window.fbq = fbq;
        const s = document.createElement("script");
        s.async = true;
        s.src = "https://connect.facebook.net/en_US/fbevents.js";
        document.head.appendChild(s);
        window.fbq("init", META_PIXEL_ID);
        window.fbq("track", "PageView");
      }

      if (GOOGLE_ADS_ID && !window.gtag) {
        const w = window as unknown as { dataLayer?: unknown[] };
        w.dataLayer = w.dataLayer ?? [];
        window.gtag = function (...args: unknown[]) {
          w.dataLayer!.push(args);
        };
        const s = document.createElement("script");
        s.async = true;
        s.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GOOGLE_ADS_ID)}`;
        document.head.appendChild(s);
        window.gtag("js", new Date());
        window.gtag("config", GOOGLE_ADS_ID);
      }

      setReady(true);
    };

    if (readConsent() === "granted") load();
    window.addEventListener(CONSENT_EVENT, load);
    return () => window.removeEventListener(CONSENT_EVENT, load);
  }, []);

  // SPA route-change page views (initial load is covered by the bootstrap above).
  const firstRoute = useRef(true);
  useEffect(() => {
    if (!ready) return;
    if (firstRoute.current) {
      firstRoute.current = false;
      return;
    }
    trackPageView();
  }, [pathname, ready]);

  // ?signedup=1 → CompleteRegistration, once, param stripped before firing.
  useEffect(() => {
    if (!ready) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("signedup") !== "1") return;
    params.delete("signedup");
    const qs = params.toString();
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`,
    );
    trackSignup();
  }, [ready]);

  return null;
}
