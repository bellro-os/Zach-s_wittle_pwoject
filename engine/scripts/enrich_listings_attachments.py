"""Attach low-effort enrichments to listings_plus_deeds.jsonl in place.

  parcel_slope_pct      mean slope % from data/<county>_parcels_slope.jsonl
                        (joins on parcel_id; falls back to None when absent)
  photo_count           count of photos from data/mls/listings_media.jsonl
  first_photo_url       URL of the first photo

This script is idempotent — re-running re-stamps the fields with current values.

Run:
    PYTHONPATH=src python scripts/enrich_listings_attachments.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path


LISTINGS_PATH = Path("data/mls/listings_plus_deeds.jsonl")
MEDIA_PATH = Path("data/mls/listings_media.jsonl")

SLOPE_FILES = [
    "data/montgomery_county_parcels_slope.jsonl",
    "data/floyd_county_parcels_slope.jsonl",
    "data/giles_county_parcels_slope.jsonl",
    "data/pulaski_county_parcels_slope.jsonl",
    "data/roanoke_county_parcels_slope.jsonl",
    "data/carroll_county_parcels_slope.jsonl",
    "data/wythe_county_parcels_slope.jsonl",
    "data/bland_county_parcels_slope.jsonl",
    "data/buchanan_county_parcels_slope.jsonl",
    "data/charlotte_county_parcels_slope.jsonl",
    "data/craig_county_parcels_slope.jsonl",
    "data/brunswick_county_parcels_slope.jsonl",
]


def build_slope_index() -> dict[str, float]:
    """Map parcel_id -> slope_mean_pct across all county slope files."""
    out: dict[str, float] = {}
    for fname in SLOPE_FILES:
        p = Path(fname)
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                pid = (r.get("parcel_id") or "").strip()
                if not pid:
                    continue
                slope = r.get("slope_mean_pct")
                if slope is None:
                    continue
                try:
                    out[pid] = float(slope)
                except (TypeError, ValueError):
                    continue
    return out


def build_media_index() -> dict[str, dict]:
    """Map listing_id -> {photo_count, first_photo_url}."""
    out: dict[str, dict] = {}
    if not MEDIA_PATH.exists():
        return out
    with MEDIA_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lid = r.get("listing_id")
            if not lid:
                continue
            photos = r.get("photos") or []
            urls = [p.get("url") for p in photos if p.get("url")]
            out[lid] = {
                "photo_count": len(urls),
                "first_photo_url": urls[0] if urls else "",
            }
    return out


def main() -> int:
    if not LISTINGS_PATH.exists():
        print(f"!! {LISTINGS_PATH} missing — run merge-deeds first")
        return 1

    print(f"loading slope index from {len(SLOPE_FILES)} county files ...")
    slope = build_slope_index()
    print(f"  {len(slope):,} parcels with slope data")

    print(f"loading media index from {MEDIA_PATH} ...")
    media = build_media_index()
    print(f"  {len(media):,} listings with media")

    started = time.time()
    n = n_slope = n_photos = 0
    tmp = LISTINGS_PATH.with_suffix(".jsonl.tmp")
    with LISTINGS_PATH.open("r", encoding="utf-8") as src, \
         tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            try:
                r = json.loads(line)
            except Exception:
                dst.write(line)
                continue
            n += 1
            pid = (r.get("parcel_id") or "").strip()
            slope_pct = slope.get(pid) if pid else None
            r["parcel_slope_pct"] = round(slope_pct, 2) if slope_pct is not None else None
            if slope_pct is not None:
                n_slope += 1
            lid = r.get("listing_id")
            m = media.get(lid)
            if m:
                r["photo_count"] = m["photo_count"]
                r["first_photo_url"] = m["first_photo_url"]
                n_photos += 1
            else:
                r.setdefault("photo_count", 0)
                r.setdefault("first_photo_url", "")
            dst.write(json.dumps(r) + "\n")
    tmp.replace(LISTINGS_PATH)
    print(f"  wrote {n:,} listings  |  slope-attached: {n_slope:,}  |  photo-attached: {n_photos:,}  ({time.time()-started:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
