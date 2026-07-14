"""Fetch concrete batch plants in VA from OpenStreetMap via Overpass API.

Queries multiple tag patterns to catch facilities tagged consistently
(industrial=concrete_plant) and those tagged only by name. Concrete needs
to be poured within ~90 min of mixing, so distance from a candidate
parcel to the nearest plant is a real construction-logistics metric.

Output: data/va_concrete_plants.jsonl
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx


OVERPASS = "https://overpass-api.de/api/interpreter"

# Virginia bbox (matches va_fiber_proxy.jsonl bbox).
BBOX = (36.5, -83.7, 39.5, -75.2)
S, W, N, E = BBOX

QUERY = f"""
[out:json][timeout:120];
(
  node["industrial"="concrete_plant"]({S},{W},{N},{E});
  way["industrial"="concrete_plant"]({S},{W},{N},{E});
  node["man_made"="works"]["product"~"concrete|cement",i]({S},{W},{N},{E});
  way["man_made"="works"]["product"~"concrete|cement",i]({S},{W},{N},{E});
  node["name"~"ready[- ]?mix|concrete plant|batch plant",i]({S},{W},{N},{E});
  way["name"~"ready[- ]?mix|concrete plant|batch plant",i]({S},{W},{N},{E});
  node["name"~"\\\\bconcrete\\\\b",i]["industrial"]({S},{W},{N},{E});
  way["name"~"\\\\bconcrete\\\\b",i]["industrial"]({S},{W},{N},{E});
);
out center;
""".strip()


def main() -> int:
    out = Path("data/va_concrete_plants.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Querying Overpass for VA concrete plants (bbox {BBOX})...")
    t0 = time.time()
    with httpx.Client(timeout=180,
                      headers={"User-Agent": "mls-bot/0.1 site-prospecting"}) as c:
        r = c.post(OVERPASS, data={"data": QUERY})
        r.raise_for_status()
        data = r.json()

    elements = data.get("elements", []) or []
    print(f"  got {len(elements)} elements in {time.time()-t0:.0f}s")

    n = 0
    seen: set[tuple[float, float]] = set()
    with out.open("w", encoding="utf-8") as f:
        for el in elements:
            tags = el.get("tags", {}) or {}
            if el["type"] == "node":
                lat = el.get("lat"); lng = el.get("lon")
            else:
                center = el.get("center") or {}
                lat = center.get("lat"); lng = center.get("lon")
            if lat is None or lng is None:
                continue
            # Dedupe near-identical points (within ~10 m)
            key = (round(float(lat), 4), round(float(lng), 4))
            if key in seen:
                continue
            seen.add(key)
            row = {
                "osm_id": el.get("id"),
                "osm_type": el.get("type"),
                "name": tags.get("name") or "",
                "operator": tags.get("operator") or "",
                "industrial": tags.get("industrial") or "",
                "man_made": tags.get("man_made") or "",
                "product": tags.get("product") or "",
                "addr_city": tags.get("addr:city") or "",
                "addr_state": tags.get("addr:state") or "",
                "lat": float(lat),
                "lng": float(lng),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1

    print(f"  wrote {n} concrete plants to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
