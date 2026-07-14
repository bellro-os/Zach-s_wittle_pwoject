"""Fetch supporting layers needed for data-center site scoring.

Three nationwide HIFLD/AGOL layers, filtered to Virginia:
  - Electric Substations (point) — name, voltage class, owner, status
  - Power Plants (point)         — generation source, capacity (MW), fuel type
  - Opportunity Zones (polygon)  — federal qualified opportunity zone tracts

Output: data/va_substations.jsonl, data/va_power_plants.jsonl,
        data/va_opportunity_zones.jsonl

For each layer we keep a representative (lat, lng) plus the original geometry,
so downstream code can run nearest-point queries via mls_bot.leadgen.geo.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


HIFLD_SUBSTATIONS = (
    "https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/"
    "Substations/FeatureServer/0"
)
HIFLD_POWER_PLANTS = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
    "Power_Plants_in_the_US/FeatureServer/0"
)
HIFLD_OPP_ZONES = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
    "Opportunity_Zones_1/FeatureServer/0"
)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=20))
def _query(client: httpx.Client, url: str, params: dict) -> dict:
    r = client.get(url, params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def _paginate(client: httpx.Client, url: str, where: str,
              out_fields: str, return_geometry: bool) -> Iterable[dict]:
    page_size = 1000
    offset = 0
    while True:
        params = {
            "where": where, "outFields": out_fields,
            "f": "json", "outSR": "4326",
            "returnGeometry": "true" if return_geometry else "false",
            "resultOffset": offset, "resultRecordCount": page_size,
        }
        data = _query(client, url + "/query", params)
        feats = data.get("features", []) or []
        if not feats:
            return
        for f in feats:
            yield f
        if len(feats) < page_size:
            return
        offset += len(feats)


def fetch_substations(out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}) as c, \
         out_path.open("w", encoding="utf-8") as f:
        for feat in _paginate(c, HIFLD_SUBSTATIONS,
                              where="STATE='VA'",
                              out_fields="ID,NAME,CITY,COUNTY,TYPE,STATUS,LATITUDE,LONGITUDE,LINES,MAX_VOLT,MIN_VOLT",
                              return_geometry=True):
            attrs = feat.get("attributes") or {}
            geom = feat.get("geometry") or {}
            lat = attrs.get("LATITUDE") or geom.get("y")
            lng = attrs.get("LONGITUDE") or geom.get("x")
            if lat is None or lng is None:
                continue
            row = {
                "id": attrs.get("ID"),
                "name": attrs.get("NAME"),
                "city": attrs.get("CITY"),
                "county": attrs.get("COUNTY"),
                "type": attrs.get("TYPE"),
                "status": attrs.get("STATUS"),
                "lines": attrs.get("LINES"),
                "max_volt_kv": attrs.get("MAX_VOLT"),
                "min_volt_kv": attrs.get("MIN_VOLT"),
                "lat": float(lat),
                "lng": float(lng),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def fetch_power_plants(out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}) as c, \
         out_path.open("w", encoding="utf-8") as f:
        for feat in _paginate(c, HIFLD_POWER_PLANTS,
                              where="State='Virginia'",
                              out_fields="*",
                              return_geometry=True):
            attrs = feat.get("attributes") or {}
            geom = feat.get("geometry") or {}
            lat = geom.get("y")
            lng = geom.get("x")
            if lat is None or lng is None:
                continue
            row = {
                "plant_code": attrs.get("Plant_Code"),
                "plant_name": attrs.get("Plant_Name"),
                "utility_name": attrs.get("Utility_Na") or attrs.get("Utility_Name"),
                "sector": attrs.get("sector_nam"),
                "street": attrs.get("Street_Add") or attrs.get("Street_Address"),
                "city": attrs.get("City"),
                "county": attrs.get("County"),
                "primary_source": attrs.get("PrimSource"),
                "source_desc": attrs.get("source_des") or attrs.get("Source_desc"),
                "total_mw": attrs.get("Total_MW"),
                "natgas_mw": attrs.get("NG_MW"),
                "coal_mw": attrs.get("Coal_MW"),
                "wind_mw": attrs.get("Wind_MW"),
                "solar_mw": attrs.get("Solar_MW"),
                "nuclear_mw": attrs.get("Nuclear_MW"),
                "hydro_mw": attrs.get("Hydro_MW"),
                "lat": float(lat),
                "lng": float(lng),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def fetch_opportunity_zones(out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}) as c, \
         out_path.open("w", encoding="utf-8") as f:
        for feat in _paginate(c, HIFLD_OPP_ZONES,
                              where="STATENAME='Virginia'",
                              out_fields="CENSUSTRAC,STATENAME,COUNTYNAME",
                              return_geometry=True):
            attrs = feat.get("attributes") or {}
            geom = feat.get("geometry") or {}
            rings = geom.get("rings") or []
            if not rings:
                continue
            row = {
                "tract": attrs.get("CENSUSTRAC"),
                "state": attrs.get("STATENAME"),
                "county": attrs.get("COUNTYNAME"),
                "rings": rings,  # native (lng, lat) polygon
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--substations-out", default="data/va_substations.jsonl")
    ap.add_argument("--power-plants-out", default="data/va_power_plants.jsonl")
    ap.add_argument("--opp-zones-out", default="data/va_opportunity_zones.jsonl")
    ap.add_argument("--skip", action="append", default=[],
                    help="Skip a layer: substations | power_plants | opp_zones")
    args = ap.parse_args()

    t0 = time.time()
    if "substations" not in args.skip:
        print(f"Fetching VA substations -> {args.substations_out}")
        n = fetch_substations(Path(args.substations_out))
        print(f"  wrote {n:,} substations")

    if "power_plants" not in args.skip:
        print(f"Fetching VA power plants -> {args.power_plants_out}")
        n = fetch_power_plants(Path(args.power_plants_out))
        print(f"  wrote {n:,} power plants")

    if "opp_zones" not in args.skip:
        print(f"Fetching VA opportunity zones -> {args.opp_zones_out}")
        n = fetch_opportunity_zones(Path(args.opp_zones_out))
        print(f"  wrote {n:,} opportunity zones")

    print(f"\nTotal: {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
