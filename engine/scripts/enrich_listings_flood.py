"""Flood-zone overlay for MLS listings.

For every listing with valid lat/lng, runs a point-in-polygon test against
data/va_flood_zones.jsonl (24k FEMA NFHL polygons) and stamps:
  in_floodplain  — True if the point is in any FEMA flood polygon
  flood_zone     — the zone code (AE, A, X, etc.) or empty
  flood_subtype  — e.g. FLOODWAY, AREA OF MINIMAL FLOOD HAZARD

X / X500 zones (minimal hazard) are reported but not flagged as `in_floodplain=True`.
Only A* / V* zones (1% annual chance flood) trigger the flag.

Augments data/mls/listings_plus_deeds.jsonl in place. Idempotent.

Run:
    PYTHONPATH=src python scripts/enrich_listings_flood.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree


FLOOD_PATH = Path("data/va_flood_zones.jsonl")
LISTINGS_PATH = Path("data/mls/listings_plus_deeds.jsonl")

# Zones that count as "in the floodplain" for our flag (FEMA Special Flood Hazard Area).
SFHA_ZONES = {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE"}


def _build_index() -> tuple[STRtree, list[dict]]:
    """Build STRtree of flood polygons. Returns (tree, attrs_list)."""
    polygons: list[Polygon] = []
    attrs: list[dict] = []
    print(f"loading {FLOOD_PATH} ...")
    with FLOOD_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rings = rec.get("rings") or []
            if not rings:
                continue
            try:
                # First ring is exterior; remaining are holes
                if len(rings) == 1:
                    poly = Polygon(rings[0])
                else:
                    poly = Polygon(rings[0], holes=rings[1:])
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_empty:
                    continue
            except Exception:
                continue
            polygons.append(poly)
            attrs.append({
                "fld_zone": rec.get("fld_zone") or "",
                "zone_subtype": rec.get("zone_subtype") or "",
            })
    print(f"  {len(polygons):,} flood polygons loaded")
    print(f"  building STRtree ...")
    tree = STRtree(polygons)
    return tree, attrs


def _classify(point: Point, tree: STRtree, polygons_attrs: list[dict],
              polygons: list[Polygon]) -> dict:
    """Return {in_floodplain, flood_zone, flood_subtype} for a point."""
    candidates = tree.query(point)
    for idx in candidates:
        i = int(idx)
        if polygons[i].contains(point) or polygons[i].covers(point):
            attrs = polygons_attrs[i]
            zone = attrs["fld_zone"]
            return {
                "in_floodplain": zone in SFHA_ZONES,
                "flood_zone": zone,
                "flood_subtype": attrs["zone_subtype"],
            }
    return {"in_floodplain": False, "flood_zone": "", "flood_subtype": ""}


def main() -> int:
    if not FLOOD_PATH.exists():
        print(f"!! {FLOOD_PATH} missing")
        return 1
    if not LISTINGS_PATH.exists():
        print(f"!! {LISTINGS_PATH} missing — run merge-deeds first")
        return 1

    # Build index ONCE
    polygons: list[Polygon] = []
    attrs: list[dict] = []
    print(f"loading {FLOOD_PATH} ...")
    with FLOOD_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rings = rec.get("rings") or []
            if not rings:
                continue
            try:
                if len(rings) == 1:
                    poly = Polygon(rings[0])
                else:
                    poly = Polygon(rings[0], holes=rings[1:])
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_empty:
                    continue
            except Exception:
                continue
            polygons.append(poly)
            attrs.append({
                "fld_zone": rec.get("fld_zone") or "",
                "zone_subtype": rec.get("zone_subtype") or "",
            })
    print(f"  {len(polygons):,} polygons")
    tree = STRtree(polygons)
    print(f"  STRtree ready")

    # Stream-process listings; write to .tmp then rename
    started = time.time()
    n_total = n_geo = n_in_sfha = n_in_x = 0
    tmp = LISTINGS_PATH.with_suffix(".jsonl.tmp")
    with LISTINGS_PATH.open("r", encoding="utf-8") as src, \
         tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            try:
                r = json.loads(line)
            except Exception:
                dst.write(line)
                continue
            n_total += 1
            lat = r.get("latitude")
            lng = r.get("longitude")
            try:
                lat = float(lat) if lat else None
                lng = float(lng) if lng else None
            except (TypeError, ValueError):
                lat = lng = None
            if lat and lng and -180 < lng < 180 and -90 < lat < 90:
                n_geo += 1
                cls = _classify(Point(lng, lat), tree, attrs, polygons)
                r["in_floodplain"] = cls["in_floodplain"]
                r["flood_zone"] = cls["flood_zone"]
                r["flood_subtype"] = cls["flood_subtype"]
                if cls["in_floodplain"]:
                    n_in_sfha += 1
                elif cls["flood_zone"]:
                    n_in_x += 1
            else:
                r["in_floodplain"] = None
                r["flood_zone"] = ""
                r["flood_subtype"] = ""
            dst.write(json.dumps(r, default=str) + "\n")
            if n_total % 5000 == 0:
                rate = n_total / (time.time() - started + 1)
                print(f"    {n_total} rows ({rate:.0f}/s)")

    tmp.replace(LISTINGS_PATH)
    print()
    print(f"=== flood enrichment complete ===")
    print(f"  total listings: {n_total:,}")
    print(f"  with lat/lng:   {n_geo:,} ({n_geo/n_total*100:.1f}%)")
    print(f"  in SFHA (A/AE/V): {n_in_sfha:,}")
    print(f"  in X-zone (mapped, low risk): {n_in_x:,}")
    print(f"  elapsed: {time.time()-started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
