"""Fetch all VA Special Flood Hazard Area (SFHA) polygons from FEMA NFHL.

DFIRM_ID starts with 51 for Virginia. SFHA_TF='T' filters to the regulatory
100-year floodplain (FEMA zones A, AE, AH, AO, V, VE) and excludes Zone X
("low risk") which doesn't trigger insurance requirements.

Output: data/va_flood_zones.jsonl  (~30k polygons, ~30 MB)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28"
WHERE = "DFIRM_ID LIKE '51%' AND SFHA_TF='T'"
PAGE_SIZE = 500  # FEMA's NFHL claims max 2000 but returns 500-server-error above 500


@retry(stop=stop_after_attempt(6), wait=wait_exponential(min=3, max=60))
def _query(client: httpx.Client, url: str, params: dict) -> dict:
    # POST avoids URL length issues and seems more reliable for NFHL
    r = client.post(url, data=params, timeout=300)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/va_flood_zones.jsonl")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    n = 0
    offset = 0
    consecutive_empty = 0
    MAX_EMPTY = 5  # stop after 5 consecutive empty pages — FEMA has bugs at specific offsets
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}) as c, \
         out.open("w", encoding="utf-8") as f:
        while True:
            data = _query(c, NFHL + "/query", {
                "where": WHERE,
                "outFields": "FLD_ZONE,ZONE_SUBTY,STATIC_BFE,DFIRM_ID",
                "outSR": "4326",
                "f": "json",
                "returnGeometry": "true",
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
            })
            feats = data.get("features", []) or []
            err = data.get("error")
            if not feats:
                consecutive_empty += 1
                if consecutive_empty >= MAX_EMPTY:
                    break
                # Skip over this bad offset; FEMA has glitches at specific
                # offsets (e.g. 3500) that return empty even though more
                # data exists at later offsets.
                if err:
                    print(f"  skipping bad offset {offset} (FEMA error)")
                offset += PAGE_SIZE
                continue
            consecutive_empty = 0
            for feat in feats:
                attrs = feat.get("attributes") or {}
                geom = feat.get("geometry") or {}
                rings = geom.get("rings") or []
                if not rings:
                    continue
                row = {
                    "fld_zone": attrs.get("FLD_ZONE"),
                    "zone_subtype": attrs.get("ZONE_SUBTY"),
                    "static_bfe": attrs.get("STATIC_BFE"),
                    "dfirm_id": attrs.get("DFIRM_ID"),
                    "rings": rings,  # native (lng, lat) polygon rings
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
            offset += len(feats)
            if n % 1000 < PAGE_SIZE:
                print(f"  {n:,} polygons written...")
            # FEMA NFHL occasionally returns short pages even mid-stream; only
            # stop when an empty page comes back.

    print(f"\n  wrote {n:,} VA SFHA polygons to {out}")
    print(f"  duration: {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
