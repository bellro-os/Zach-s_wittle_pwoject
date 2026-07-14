"""Per-listing commute scoring to NRV employment hubs.

Computes approximate drive minutes (haversine * road_factor / avg_mph) from
each listing's lat/lng to:
    drive_min_vt              — Virginia Tech campus
    drive_min_downtown_bburg  — downtown Blacksburg
    drive_min_carilion        — Carilion Roanoke Memorial Hospital
    drive_min_radford         — downtown Radford
    drive_min_pulaski         — downtown Pulaski

Approximate (no real routing engine), but consistent enough for relative
comparison + filtering. Augments data/mls/listings_plus_deeds.jsonl in place.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mls_bot.leadgen.geo import (  # noqa: E402
    REFERENCE_POINTS, haversine_miles, drive_minutes_approx,
    DEFAULT_ROAD_FACTOR, DEFAULT_AVG_MPH,
)


LISTINGS_PATH = Path("data/mls/listings_plus_deeds.jsonl")

HUBS = [
    ("vt",                "VT"),
    ("downtown_bburg",    "DOWNTOWN_BLACKSBURG"),
    ("carilion",          "CARILION_ROANOKE"),
    ("christiansburg",    "CHRISTIANSBURG"),
    ("radford",           "RADFORD"),
    ("pulaski",           "PULASKI"),
]


def main() -> int:
    if not LISTINGS_PATH.exists():
        print(f"!! {LISTINGS_PATH} missing")
        return 1

    started = time.time()
    n_total = n_geo = 0
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
            try:
                lat = float(r.get("latitude") or 0)
                lng = float(r.get("longitude") or 0)
            except (TypeError, ValueError):
                lat = lng = 0
            if -90 < lat < 90 and -180 < lng < 180 and (lat or lng):
                n_geo += 1
                for col, hub_name in HUBS:
                    h_lat, h_lng = REFERENCE_POINTS[hub_name]
                    miles = haversine_miles(lat, lng, h_lat, h_lng)
                    # Tiered speed: in-town (<5mi) is slower, longer drives are
                    # mostly highway (faster). Mixed-network calibration.
                    if miles < 5:
                        avg_mph = 25
                    elif miles < 15:
                        avg_mph = 38
                    else:
                        avg_mph = 50
                    minutes = drive_minutes_approx(miles, factor=DEFAULT_ROAD_FACTOR, avg_mph=avg_mph)
                    r[f"drive_min_{col}"] = round(minutes, 1)
                    r[f"miles_to_{col}"] = round(miles, 2)
            else:
                for col, _ in HUBS:
                    r[f"drive_min_{col}"] = None
                    r[f"miles_to_{col}"] = None
            dst.write(json.dumps(r, default=str) + "\n")

    tmp.replace(LISTINGS_PATH)
    print(f"=== commute enrichment complete ===")
    print(f"  total listings: {n_total:,}")
    print(f"  with lat/lng:   {n_geo:,}")
    print(f"  hubs scored:    {len(HUBS)}")
    print(f"  elapsed: {time.time()-started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
