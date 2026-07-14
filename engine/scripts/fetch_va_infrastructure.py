"""Fetch VA infrastructure layers for parcel-proximity analysis.

Two datasets:
  - Power transmission lines (HIFLD federal layer, filtered to a VA bbox).
    Stored as polylines in EPSG:4326 — one JSONL row per line segment with
    voltage, owner, status, and a list of (lat, lng) vertices.

  - Wastewater treatment facilities (VADEQ VPDES Outfalls). Each outfall
    is a permitted discharge point; many sites have multiple outfalls.
    We filter to FAC_NAME values that look like treatment plants (WWTP,
    sewage, treatment plant, water reclamation facility, etc.) so that
    "distance to nearest WWTP" doesn't get polluted by industrial
    discharge points.

Outputs:
  data/va_transmission_lines.jsonl
  data/va_wastewater_treatment.jsonl

Each row also stores a representative (lat, lng) — line midpoint or
point geometry — so consumers can compute distance with the existing
haversine helpers in mls_bot.leadgen.geo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


VA_BBOX = {  # rough Virginia bounding box, EPSG:4326
    "xmin": -83.7, "ymin": 36.5, "xmax": -75.2, "ymax": 39.5,
}

HIFLD_TRANSMISSION = (
    "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
    "Electric_Power_Transmission_Lines/FeatureServer/0"
)

VADEQ_VPDES_OUTFALLS = (
    "https://gisdata.deq.virginia.gov/arcgis/rest/services/"
    "public/EDMA/MapServer/119"
)

# Filter VPDES to facility names that look like wastewater treatment plants.
# (VPDES also permits cooling-water discharges from power plants, ammunition
# plants, etc., and drinking-water-plant filter-backwash — these are not
# "wastewater treatment plants" the way a homeowner would think of them.)
WASTEWATER_PATTERNS = re.compile(
    r"\b(WWTP|STP|WRF|WPCP|WPCF|"
    r"WASTE\s*WATER|WASTEWATER|"
    r"SEWAGE|SEWER|SANIT|SANITATION|"
    r"WATER\s*RECLAMATION|"
    r"SEWER\s+AUTHORITY|SANITATION\s+DISTRICT)\b",
    re.IGNORECASE,
)
# Explicitly exclude drinking-water plants that may match the broader
# wastewater regex via "TREATMENT PLANT" / "WATER TREATMENT".
DRINKING_WATER_PATTERNS = re.compile(
    r"\b(WATER\s+TREATMENT\s+(PLANT|FACILITY|WORKS)|"
    r"WTP\b|DRINKING\s+WATER|POTABLE|FILTER\s+PLANT)\b",
    re.IGNORECASE,
)


def _is_wastewater(fac_name: str) -> bool:
    if not fac_name:
        return False
    if DRINKING_WATER_PATTERNS.search(fac_name):
        return False
    return bool(WASTEWATER_PATTERNS.search(fac_name))


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=20))
def _fetch_page(client: httpx.Client, url: str, params: dict) -> dict:
    r = client.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def _polyline_midpoint(geom: dict) -> tuple[float, float] | None:
    """Mid-vertex of the longest path. Good enough for proximity scoring."""
    paths = geom.get("paths") or geom.get("coordinates") or []
    if not paths:
        return None
    longest = max(paths, key=len)
    if not longest:
        return None
    mid = longest[len(longest) // 2]
    if isinstance(mid, (list, tuple)) and len(mid) >= 2:
        return float(mid[1]), float(mid[0])  # (lat, lng) from (x=lng, y=lat)
    return None


def fetch_transmission_lines(out_path: Path) -> int:
    """Pull HIFLD transmission lines that intersect the VA bbox."""
    bbox = f'{VA_BBOX["xmin"]},{VA_BBOX["ymin"]},{VA_BBOX["xmax"]},{VA_BBOX["ymax"]}'
    base_params = {
        "where": "1=1",
        "geometry": bbox,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outSR": "4326",
        "outFields": "OBJECTID,ID,TYPE,STATUS,OWNER,VOLTAGE,VOLT_CLASS,SUB_1,SUB_2",
        "f": "json",
        "returnGeometry": "true",
        "resultRecordCount": 1000,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}) as c, \
         out_path.open("w", encoding="utf-8") as f:
        offset = 0
        while True:
            params = dict(base_params, resultOffset=offset)
            data = _fetch_page(c, HIFLD_TRANSMISSION + "/query", params)
            feats = data.get("features", []) or []
            if not feats:
                break
            for feat in feats:
                attrs = feat.get("attributes") or {}
                geom = feat.get("geometry") or {}
                paths = geom.get("paths") or []
                # Drop pure-vertical-stub features that have no real geometry.
                if not paths or all(len(p) < 2 for p in paths):
                    continue
                mid = _polyline_midpoint(geom)
                row = {
                    "id": attrs.get("ID") or attrs.get("OBJECTID"),
                    "type": attrs.get("TYPE"),
                    "status": attrs.get("STATUS"),
                    "owner": attrs.get("OWNER"),
                    "voltage": attrs.get("VOLTAGE"),
                    "voltage_class": attrs.get("VOLT_CLASS"),
                    "sub_1": attrs.get("SUB_1"),
                    "sub_2": attrs.get("SUB_2"),
                    "mid_lat": mid[0] if mid else None,
                    "mid_lng": mid[1] if mid else None,
                    "paths": paths,  # native (lng, lat) vertex lists
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
            offset += len(feats)
            if len(feats) < base_params["resultRecordCount"]:
                break
    return n


def fetch_wastewater_treatment(out_path: Path) -> tuple[int, int]:
    """Pull VADEQ VPDES outfalls statewide; filter to treatment-plant facilities.

    Returns (total_outfalls_fetched, treatment_outfalls_kept).
    """
    base_params = {
        "where": "1=1",
        "outFields": "*",
        "outSR": "4326",
        "f": "json",
        "returnGeometry": "true",
        "resultRecordCount": 1000,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    kept = 0
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}) as c, \
         out_path.open("w", encoding="utf-8") as f:
        offset = 0
        while True:
            params = dict(base_params, resultOffset=offset)
            data = _fetch_page(c, VADEQ_VPDES_OUTFALLS + "/query", params)
            feats = data.get("features", []) or []
            if not feats:
                break
            for feat in feats:
                total += 1
                attrs = feat.get("attributes") or {}
                fac_name = attrs.get("FAC_NAME") or ""
                if not _is_wastewater(fac_name):
                    continue
                geom = feat.get("geometry") or {}
                lat = geom.get("y")
                lng = geom.get("x")
                if lat is None or lng is None:
                    continue
                row = {
                    "outfall_id": attrs.get("OUTFALL_ID") or attrs.get("OUTFALLNO"),
                    "permit_no": attrs.get("VAP_PMT_NO"),
                    "permit_type": attrs.get("VAP_TYPE"),
                    "facility_name": fac_name,
                    "major_minor": attrs.get("VAP_MAJOR_MINOR"),
                    "lat": float(lat),
                    "lng": float(lng),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                kept += 1
            offset += len(feats)
            if len(feats) < base_params["resultRecordCount"]:
                break
    return total, kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines-out", default="data/va_transmission_lines.jsonl")
    ap.add_argument("--wwtp-out", default="data/va_wastewater_treatment.jsonl")
    ap.add_argument("--skip-lines", action="store_true")
    ap.add_argument("--skip-wwtp", action="store_true")
    args = ap.parse_args()

    if not args.skip_lines:
        print(f"Fetching transmission lines (VA bbox) -> {args.lines_out}")
        n = fetch_transmission_lines(Path(args.lines_out))
        print(f"  wrote {n:,} lines")

    if not args.skip_wwtp:
        print(f"Fetching VPDES outfalls (filtering to treatment plants) -> {args.wwtp_out}")
        total, kept = fetch_wastewater_treatment(Path(args.wwtp_out))
        print(f"  fetched {total:,} outfalls; kept {kept:,} treatment-plant outfalls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
