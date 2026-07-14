"""Fetch major VA highways as a fiber-corridor proxy.

Long-haul fiber in VA broadly follows interstates and US highways. Since
HIFLD's fiber dataset is security-restricted, we use OpenStreetMap via
Overpass API to grab motorway + trunk + primary highways (which roughly
correspond to interstates + US highways + state primaries).

Output: data/va_fiber_proxy.jsonl  (polylines with road type/name)

Caveat: this is a proxy. Real fiber proximity requires carrier route maps
which aren't public. But "within 1 mile of an interstate" is a reasonable
filter for "has fiber backbone access" in VA.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx


OVERPASS = "https://overpass-api.de/api/interpreter"

# Virginia bbox: south, west, north, east
BBOX = (36.5, -83.7, 39.5, -75.2)

# motorway = interstates; trunk = US/State limited-access; primary = major US/State
QUERY = f"""
[out:json][timeout:180];
(
  way["highway"~"^(motorway|trunk|primary)$"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom;
""".strip()


def main() -> int:
    out = Path("data/va_fiber_proxy.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Querying Overpass for VA highways (bbox {BBOX})...")
    t0 = time.time()
    with httpx.Client(timeout=300, headers={"User-Agent": "mls-bot/0.1 site-prospecting"}) as c:
        r = c.post(OVERPASS, data={"data": QUERY})
        r.raise_for_status()
        data = r.json()

    elements = data.get("elements", [])
    print(f"  got {len(elements):,} ways in {time.time()-t0:.0f}s")

    n = 0
    with out.open("w", encoding="utf-8") as f:
        for el in elements:
            tags = el.get("tags", {})
            geom = el.get("geometry") or []
            if len(geom) < 2:
                continue
            # OSM gives geometry as list of {lat, lon}; convert to (lng, lat)
            paths = [[[g["lon"], g["lat"]] for g in geom]]
            row = {
                "osm_id": el.get("id"),
                "highway": tags.get("highway"),
                "name": tags.get("name") or tags.get("ref"),
                "ref": tags.get("ref"),
                "lanes": tags.get("lanes"),
                "paths": paths,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1

    print(f"  wrote {n:,} VA highway segments to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
