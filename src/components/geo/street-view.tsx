"use client";

import { memo, useState } from "react";
import { cn } from "@/lib/utils/cn";

/**
 * Shared street-view tile used by both the compbird studio and the host CMA
 * profile. When coordinates are present it auto-loads an image from the
 * server-side proxy (`/api/compbird/streetview`), so the Google key — if any —
 * is never exposed client-side. On a 404 (no key, or no panorama at this point)
 * the <img> onError swaps to a tasteful token-driven fallback with a link-out.
 */

type StreetViewProps = {
  lat?: number | null;
  lng?: number | null;
  address?: string | null;
  className?: string;
};

function HouseGlyph({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={cn("h-6 w-6", className)}
      aria-hidden
    >
      <path
        d="M3 11.2 12 4l9 7.2M5.4 9.6V20h13.2V9.6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M9.6 20v-5.2h4.8V20"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function hasCoords(lat?: number | null, lng?: number | null): boolean {
  return (
    typeof lat === "number" &&
    Number.isFinite(lat) &&
    typeof lng === "number" &&
    Number.isFinite(lng)
  );
}

function StreetViewImpl({ lat, lng, address, className }: StreetViewProps) {
  // True once the proxy image 404s (no key / no imagery) or coords are missing.
  const coords = hasCoords(lat, lng);
  const [failed, setFailed] = useState(false);

  const showImage = coords && !failed;
  const panoHref = coords
    ? `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${lat},${lng}`
    : null;
  const alt = address ? `Street view of ${address}` : "Street view";

  if (showImage) {
    return (
      <div
        className={cn(
          "relative aspect-[4/3] overflow-hidden rounded-2xl border border-border bg-secondary/40",
          className,
        )}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`/api/compbird/streetview?lat=${lat}&lng=${lng}`}
          alt={alt}
          loading="lazy"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      </div>
    );
  }

  // Fallback tile — missing coords, no key, or no panorama at this point.
  return (
    <div
      className={cn(
        "flex aspect-[4/3] flex-col items-center justify-center gap-2 rounded-2xl border border-border bg-secondary/40 p-5 text-center",
        className,
      )}
    >
      <HouseGlyph className="text-muted-foreground" />
      <span className="cb-eyebrow text-muted-foreground">Street view</span>
      {address ? (
        <span className="max-w-[24ch] text-sm text-foreground text-balance">
          {address}
        </span>
      ) : null}
      {panoHref ? (
        <a
          href={panoHref}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-flex items-center gap-1.5 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-[var(--cb-ember,#10b981)]/40 hover:text-[var(--cb-ember-text,#0f766e)]"
        >
          Open in Street View
          <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path
              d="M6 3h7v7M13 3 4 12"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </a>
      ) : null}
      <span className="mt-0.5 text-[0.7rem] leading-snug text-muted-foreground/70">
        Inline imagery needs a Google Maps key.
      </span>
    </div>
  );
}

/** Memoized: coordinates/address are primitives, so parent-tree churn never re-fires the tile fetch effect path. */
export const StreetView = memo(StreetViewImpl);

export default StreetView;
