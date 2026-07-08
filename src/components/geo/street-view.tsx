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

  // Fallback — missing coords, no key, or no panorama at this point. One tidy
  // row, not a tall empty tile: muted small-print explains why there's no
  // image, the link-out (when coords exist) stays. NO eyebrow here — the
  // caller labels the section (report-view renders "Street view" above this
  // tile; a second one inside made the label print twice).
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-2xl border border-border bg-secondary/40 px-4 py-3",
        className,
      )}
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <HouseGlyph className="h-5 w-5 shrink-0 text-muted-foreground" />
        <span className="text-xs leading-snug text-muted-foreground/70">
          {coords
            ? "Inline imagery needs a Google Maps key."
            : "No coordinates on record for street-level imagery."}
        </span>
      </span>
      {panoHref ? (
        <a
          href={panoHref}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-[var(--cb-ember,#10b981)]/40 hover:text-[var(--cb-ember-text,#0f766e)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember,#10b981)]"
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
    </div>
  );
}

/** Memoized: coordinates/address are primitives, so parent-tree churn never re-fires the tile fetch effect path. */
export const StreetView = memo(StreetViewImpl);

export default StreetView;
