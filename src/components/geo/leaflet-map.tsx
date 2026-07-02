"use client";

import { memo, useEffect, useRef } from "react";
import "leaflet/dist/leaflet.css";
import { cn } from "@/lib/utils/cn";

/**
 * Shared OpenStreetMap map used by both the compbird studio and the host CMA
 * profile. No API key, no default marker images (those break under bundlers) —
 * markers are token-driven L.divIcon HTML so the pins read on either theme.
 *
 * SSR-safe: leaflet (which touches window/document at import time) is imported
 * DYNAMICALLY inside the effect, so it never runs during server render. Only the
 * stylesheet is imported statically, which is inert on the server.
 */

export type GeoMapPoint = {
  lat: number;
  lng: number;
  kind: "subject" | "comp";
  /** Tooltip text (e.g. an address or comp label). */
  label?: string;
  /** Atypical/flagged comp sale — rendered with the negative-toned marker so the
   *  legend's "Atypical" row is truthful. */
  atypical?: boolean;
};

type LeafletMapProps = {
  points: GeoMapPoint[];
  /** Pixel height of the map canvas. Default 280. */
  height?: number;
  className?: string;
};

/** A point is only mappable if both coordinates are finite numbers. */
function isMappable(p: GeoMapPoint): boolean {
  return Number.isFinite(p.lat) && Number.isFinite(p.lng);
}

function LeafletMapImpl({ points, height = 280, className }: LeafletMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mappable = points.filter(isMappable);

  // Explicit re-init signature: the tear-down/rebuild effect re-runs only when
  // the PLOTTED data actually changes — not when a parent re-render hands us a
  // fresh-but-equal points array (which JSON.stringify over raw objects also
  // caught, but by serializing every field of every render's objects).
  const sig = mappable
    .map((p) => `${p.lat},${p.lng},${p.kind},${p.atypical ? 1 : 0},${p.label ?? ""}`)
    .join("|");

  useEffect(() => {
    // Nothing to plot — the graceful box renders instead (see JSX below).
    if (!containerRef.current || mappable.length === 0) return;

    let cancelled = false;
    // The leaflet map instance is created async; keep a handle for cleanup.
    let map: import("leaflet").Map | null = null;

    (async () => {
      // Dynamic import: leaflet reads `window`/`document` at module load, so it
      // must never be pulled in during SSR.
      const L = (await import("leaflet")).default;
      if (cancelled || !containerRef.current) return;

      map = L.map(containerRef.current, {
        scrollWheelZoom: false,
        attributionControl: true,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
        maxZoom: 19,
      }).addTo(map);

      // Build HTML pins (no image assets). Colors come from CSS tokens so the
      // same marker reads on the paper (host CMA) and instrument (compbird) surfaces.
      const subjectIcon = L.divIcon({
        className: "",
        html:
          `<span style="display:block;width:18px;height:18px;border-radius:9999px;` +
          `background:var(--cb-ember,#10b981);` +
          `border:2px solid var(--background,#ffffff);` +
          `box-shadow:0 1px 6px rgba(0,0,0,0.35);"></span>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      });
      const compIcon = L.divIcon({
        className: "",
        html:
          `<span style="display:block;width:10px;height:10px;border-radius:9999px;` +
          `background:var(--muted-foreground,#64748b);` +
          `border:1.5px solid var(--background,#ffffff);` +
          `box-shadow:0 1px 4px rgba(0,0,0,0.3);"></span>`,
        iconSize: [10, 10],
        iconAnchor: [5, 5],
      });
      // Atypical comps get the negative-toned dot so they're visibly flagged on
      // the map (matching the legend + the "atypical sales are flagged" pitch).
      const atypicalIcon = L.divIcon({
        className: "",
        html:
          `<span style="display:block;width:11px;height:11px;border-radius:9999px;` +
          `background:var(--negative,#ef4444);` +
          `border:1.5px solid var(--background,#ffffff);` +
          `box-shadow:0 1px 4px rgba(0,0,0,0.3);"></span>`,
        iconSize: [11, 11],
        iconAnchor: [5.5, 5.5],
      });

      const latLngs: [number, number][] = [];
      for (const p of mappable) {
        const icon =
          p.kind === "subject" ? subjectIcon : p.atypical ? atypicalIcon : compIcon;
        // Subject pins sit above comp dots.
        const marker = L.marker([p.lat, p.lng], {
          icon,
          zIndexOffset: p.kind === "subject" ? 1000 : 0,
        }).addTo(map);
        if (p.label) {
          marker.bindTooltip(p.label, { direction: "top", offset: [0, -6] });
        }
        latLngs.push([p.lat, p.lng]);
      }

      if (latLngs.length === 1) {
        map.setView(latLngs[0], 15);
      } else {
        map.fitBounds(latLngs, { padding: [32, 32], maxZoom: 16 });
      }

      // Tiles can render before the container has its final size; nudge leaflet
      // to recompute once layout settles.
      requestAnimationFrame(() => map?.invalidateSize());
    })();

    return () => {
      cancelled = true;
      if (map) {
        map.remove();
        map = null;
      }
    };
    // Re-init when the set of mapped coordinates changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  if (mappable.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center rounded-2xl border border-border bg-secondary/40 text-sm text-muted-foreground",
          className,
        )}
        style={{ height }}
      >
        No mapped coordinates
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      role="group"
      aria-label="Interactive map of the subject and comparable properties. Each address is also listed in the comparables table."
      className={cn("overflow-hidden rounded-2xl border border-border", className)}
      style={{ height }}
    />
  );
}

/** Memoized: the map only re-renders when its own props change, so parent-tree
 *  churn (e.g. a comp toggle recompute in the studio) never touches it. */
export const LeafletMap = memo(LeafletMapImpl);

export default LeafletMap;
