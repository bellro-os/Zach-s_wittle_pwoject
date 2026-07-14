"""Add lat/lng centroids to an existing parcel JSONL.

Reads --in JSONL, queries the county's geometry endpoint, and writes
--out JSONL with `lat` and `lng` fields. Dispatches based on source.kind:

- arcgis_rest: batched WHERE id IN (...) queries to the REST layer
- geoserver_wfs: one-shot GetFeature for the whole layer, then join locally

For WFS layers whose native SRS is Web Mercator (EPSG:3857), the conversion
to WGS84 (lat/lng) happens locally — no pyproj dependency.

    python scripts/enrich_coords.py --source MONTGOMERY \\
        --in data/montgomery_county_parcels.jsonl \\
        --out data/montgomery_county_parcels_geo.jsonl

Safe to re-run — idempotent.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import httpx
from pyproj import Transformer
from tenacity import retry, stop_after_attempt, wait_exponential

from mls_bot.ingest.sources import get as get_source


BATCH_SIZE = 100  # PARCEL_IDs per REST query
_TRANSFORMER_CACHE: dict[int, Transformer] = {}


def _is_lonlat(x: float, y: float) -> bool:
    return abs(x) <= 180 and abs(y) <= 90


def _to_4326(x: float, y: float, src_epsg: int) -> tuple[float, float]:
    """Reproject (x, y) from src_epsg to WGS84 lat/lng."""
    if src_epsg == 4326:
        return y, x
    tr = _TRANSFORMER_CACHE.get(src_epsg)
    if tr is None:
        tr = Transformer.from_crs(f"EPSG:{src_epsg}", "EPSG:4326", always_xy=True)
        _TRANSFORMER_CACHE[src_epsg] = tr
    lng, lat = tr.transform(x, y)
    return lat, lng


def _centroid(geom: Any, src_epsg: int = 4326) -> tuple[float | None, float | None]:
    """Arithmetic mean of all coord pairs, returned as (lat, lng).

    Handles both geoJSON (`coordinates`) and ESRI JSON (`rings`/`paths`).
    Auto-detects Web Mercator and converts."""
    if not geom:
        return None, None
    xs: list[float] = []
    ys: list[float] = []

    def walk(item: Any) -> None:
        if isinstance(item, (list, tuple)):
            if (
                len(item) >= 2
                and isinstance(item[0], (int, float))
                and isinstance(item[1], (int, float))
                and not isinstance(item[0], bool)
            ):
                xs.append(float(item[0]))
                ys.append(float(item[1]))
                return
            for sub in item:
                walk(sub)

    walk(geom.get("coordinates"))
    walk(geom.get("rings"))
    walk(geom.get("paths"))
    walk(geom.get("points"))
    if not xs:
        return None, None

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    if src_epsg == 4326 and _is_lonlat(x_mean, y_mean):
        return y_mean, x_mean
    try:
        return _to_4326(x_mean, y_mean, src_epsg)
    except Exception:
        return None, None


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
def _fetch_rest_batch(client: httpx.Client, url: str, id_field: str, ids: list[str]) -> list[dict]:
    quoted = ",".join(f"'{p.replace(chr(39), chr(39) * 2)}'" for p in ids)
    # POST avoids URL-length limits when batches push past ~2KB.
    r = client.post(
        f"{url}/query",
        data={
            "where": f"{id_field} IN ({quoted})",
            "outFields": id_field,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("features", []) or []


def _enrich_arcgis_rest(client: httpx.Client, src_cfg, unique_ids: list[str]) -> dict[str, tuple[float, float]]:
    coords: dict[str, tuple[float, float]] = {}
    total_batches = (len(unique_ids) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(total_batches):
        chunk = unique_ids[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        feats = _fetch_rest_batch(client, src_cfg.url, src_cfg.parcel_id_field, chunk)
        for feat in feats:
            attrs = feat.get("attributes") or feat.get("properties") or {}
            pid = attrs.get(src_cfg.parcel_id_field)
            if pid is None:
                continue
            lat, lng = _centroid(feat.get("geometry"))
            if lat is not None and lng is not None:
                coords[str(pid).strip()] = (lat, lng)
        if (i + 1) % 20 == 0 or (i + 1) == total_batches:
            print(f"  batch {i + 1}/{total_batches}: {len(coords):,} / {len(unique_ids):,} parcels have coords")
    return coords


def _detect_epsg(crs: dict | None) -> int:
    """Pull an EPSG code out of a GeoJSON crs object. Default 4326."""
    if not crs:
        return 4326
    name = (crs.get("properties") or {}).get("name") or ""
    m = re.search(r"EPSG[:\\/]+(\d+)", name) or re.search(r"::(\d+)$", name)
    if m:
        return int(m.group(1))
    return 4326


def _enrich_wfs(client: httpx.Client, src_cfg) -> dict[str, tuple[float, float]]:
    """Single-shot fetch of the whole layer; reproject locally if not 4326."""
    print(f"  fetching all features from WFS layer {src_cfg.wfs_typename!r}...")
    # Try to get the data already projected to 4326. Some old GeoServers
    # reject this — fall back to native projection + pyproj reprojection.
    r = client.get(
        src_cfg.url,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": src_cfg.wfs_typename,
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
        },
        timeout=600,
    )
    if r.status_code != 200 or not r.text.lstrip().startswith("{"):
        print("  srsName=EPSG:4326 rejected; refetching in native SRS")
        r = client.get(
            src_cfg.url,
            params={
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": src_cfg.wfs_typename,
                "outputFormat": "application/json",
            },
            timeout=600,
        )
        r.raise_for_status()
    data = r.json()
    src_epsg = _detect_epsg(data.get("crs"))
    feats = data.get("features", []) or []
    print(f"  WFS returned {len(feats):,} features (native EPSG:{src_epsg}); computing centroids...")

    coords: dict[str, tuple[float, float]] = {}
    pid_field = src_cfg.parcel_id_field
    for feat in feats:
        props = feat.get("properties") or feat.get("attributes") or {}
        pid = props.get(pid_field)
        if pid is None or pid == "":
            continue
        lat, lng = _centroid(feat.get("geometry"), src_epsg=src_epsg)
        if lat is not None and lng is not None:
            coords[str(pid).strip()] = (lat, lng)
    return coords


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="outp", required=True)
    args = ap.parse_args()

    src_cfg = get_source(args.source)
    src = Path(args.inp)
    dst = Path(args.outp)
    if not src.exists():
        print(f"error: {src} does not exist", file=sys.stderr)
        return 2

    rows: list[dict] = []
    parcel_ids: list[str] = []
    with src.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            rows.append(row)
            pid = row.get("parcel_id")
            if pid:
                parcel_ids.append(pid)

    unique_ids = sorted(set(parcel_ids))
    print(f"source: {args.source}  kind={src_cfg.kind}  id_field={src_cfg.parcel_id_field}")
    print(f"loaded {len(rows):,} rows, {len(unique_ids):,} distinct parcel_ids")

    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}, follow_redirects=True) as client:
        if src_cfg.kind == "geoserver_wfs":
            coords = _enrich_wfs(client, src_cfg)
        else:
            coords = _enrich_arcgis_rest(client, src_cfg, unique_ids)

    dst.parent.mkdir(parents=True, exist_ok=True)
    missing = 0
    with dst.open("w", encoding="utf-8") as f:
        for row in rows:
            pid = (row.get("parcel_id") or "").strip()
            latlng = coords.get(pid)
            if latlng:
                row["lat"], row["lng"] = latlng
            else:
                row.setdefault("lat", None)
                row.setdefault("lng", None)
                missing += 1
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"wrote {len(rows):,} rows to {dst}")
    print(f"  centroids found for {len(rows) - missing:,}, missing {missing:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
