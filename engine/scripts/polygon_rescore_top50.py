"""Re-score the Appalachian-preset top 50 with polygon-aware slope sampling.

For each candidate:
  1. Fetch the actual parcel polygon from its county's source endpoint.
  2. Densely sample points (~100) inside the polygon's bounding box,
     reject any outside the polygon (true polygon-aware coverage).
  3. Sample DEM elevations and compute slope at every interior point.
  4. Recompute pct_under_5/10/15pct_slope, mean, max from the polygon
     samples — versus the centroid-grid we used in the bulk scoring.

Output: outputs/dc_top50_appalachian_polygon_rescore.csv with original
vs polygon-based slope numbers, plus delta. Useful for spotting parcels
where the centroid-only sampling under- or overstated buildability.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx
import numpy as np
import rasterio
from shapely.geometry import Polygon as ShPolygon, Point as ShPoint
from tenacity import retry, stop_after_attempt, wait_exponential

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mls_bot.ingest.sources import SOURCES, ParcelSource

# Slope sampling — denser than the centroid-grid version.
SAMPLE_GRID_N = 12  # 12x12 = 144 candidate points per parcel before mask
ELEV_OFFSET_M = 30.0
METERS_PER_DEG_LAT = 111_320.0


# ----- Geometry fetching -----


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=20))
def _arcgis_query_polygons(client: httpx.Client, source: ParcelSource,
                           parcel_ids: list[str]) -> dict[str, list]:
    """Returns {parcel_id: rings} from an ArcGIS REST layer."""
    quoted = ",".join(f"'{p.replace(chr(39), chr(39) * 2)}'" for p in parcel_ids)
    where = f"{source.parcel_id_field} IN ({quoted})"
    r = client.post(source.url + "/query", data={
        "where": where,
        "outFields": source.parcel_id_field,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }, timeout=120)
    r.raise_for_status()
    out: dict[str, list] = {}
    for feat in r.json().get("features", []) or []:
        attrs = feat.get("attributes") or feat.get("properties") or {}
        pid = str(attrs.get(source.parcel_id_field) or "").strip()
        rings = (feat.get("geometry") or {}).get("rings") or []
        if pid and rings:
            out[pid] = rings
    return out


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=20))
def _wfs_query_polygons(client: httpx.Client, source: ParcelSource,
                        parcel_ids: list[str]) -> dict[str, list]:
    """WFS GetFeature with CQL_FILTER. Returns {parcel_id: ring_lng_lat_pairs}."""
    quoted = ",".join(f"'{p.replace(chr(39), chr(39) * 2)}'" for p in parcel_ids)
    cql = f"{source.parcel_id_field} IN ({quoted})"
    r = client.get(source.url, params={
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": source.wfs_typename,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "CQL_FILTER": cql,
    }, timeout=180)
    r.raise_for_status()
    out: dict[str, list] = {}
    data = r.json()
    src_epsg = 4326
    crs = (data.get("crs") or {}).get("properties") or {}
    name = crs.get("name") or ""
    import re
    m = re.search(r"EPSG[:/]+(\d+)", name) or re.search(r"::(\d+)", name)
    if m:
        src_epsg = int(m.group(1))
    for feat in data.get("features", []) or []:
        props = feat.get("properties") or {}
        pid = str(props.get(source.parcel_id_field) or "").strip()
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Polygon":
            coords = geom.get("coordinates") or []
        elif geom.get("type") == "MultiPolygon":
            # Flatten — take first polygon
            coords = (geom.get("coordinates") or [[]])[0]
        else:
            continue
        if pid and coords:
            out[pid] = (coords, src_epsg)
    return out


# ----- Slope sampling on a polygon -----


def _build_dem_datasets():
    dem_dir = ROOT / "data" / "dem"
    tiles = sorted(set(dem_dir.glob("USGS_1_n*w*.tif")) | set(dem_dir.glob("USGS_13_n*w*.tif")))
    return [rasterio.open(t) for t in tiles]


def _sample_elevations(datasets, points: list[tuple[float, float]]) -> list[float | None]:
    out: list[float | None] = [None] * len(points)
    coords_lnglat = [(lng, lat) for (lat, lng) in points]
    for ds in datasets:
        b = ds.bounds
        idx_in: list[int] = []
        coords_in: list[tuple[float, float]] = []
        for i, (lng, lat) in enumerate(coords_lnglat):
            if out[i] is not None:
                continue
            if b.left <= lng <= b.right and b.bottom <= lat <= b.top:
                idx_in.append(i)
                coords_in.append((lng, lat))
        if not coords_in:
            continue
        for i, vals in zip(idx_in, ds.sample(coords_in, indexes=1)):
            v = vals[0] if len(vals) else None
            if v is None or (isinstance(v, float) and (math.isnan(v) or v < -1000)):
                continue
            out[i] = float(v)
    return out


def _slope_at_point(datasets, lat: float, lng: float) -> float | None:
    cos_lat = math.cos(math.radians(lat))
    if cos_lat <= 0:
        return None
    d_lat = ELEV_OFFSET_M / METERS_PER_DEG_LAT
    d_lng = ELEV_OFFSET_M / (METERS_PER_DEG_LAT * cos_lat)
    pts = [
        (lat, lng + d_lng),  # E
        (lat, lng - d_lng),  # W
        (lat + d_lat, lng),  # N
        (lat - d_lat, lng),  # S
    ]
    z = _sample_elevations(datasets, pts)
    if any(v is None for v in z):
        return None
    z_e, z_w, z_n, z_s = z
    dzdx = (z_e - z_w) / (2 * ELEV_OFFSET_M)
    dzdy = (z_n - z_s) / (2 * ELEV_OFFSET_M)
    return math.sqrt(dzdx * dzdx + dzdy * dzdy) * 100  # %


def _generate_grid_in_polygon(poly: ShPolygon, n: int) -> list[tuple[float, float]]:
    """Regular grid of points inside a shapely polygon (in lat/lng). Returns
    (lat, lng) tuples."""
    minx, miny, maxx, maxy = poly.bounds  # x=lng, y=lat in our case
    if maxx <= minx or maxy <= miny:
        return []
    xs = np.linspace(minx, maxx, n)
    ys = np.linspace(miny, maxy, n)
    pts: list[tuple[float, float]] = []
    for y in ys:
        for x in xs:
            if poly.contains(ShPoint(x, y)):
                pts.append((float(y), float(x)))  # (lat, lng)
    return pts


def _arcgis_rings_to_shapely(rings: list) -> ShPolygon | None:
    """Rings are (lng, lat) per ArcGIS geometry. First is outer, rest are holes."""
    try:
        outer = [(float(p[0]), float(p[1])) for p in rings[0]]
        holes = []
        for ring in rings[1:]:
            holes.append([(float(p[0]), float(p[1])) for p in ring])
        poly = ShPolygon(outer, holes=holes if holes else None)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if not poly.is_empty else None
    except Exception:
        return None


def _wfs_coords_to_shapely(coords: list, src_epsg: int) -> ShPolygon | None:
    """coords = [[ [lng, lat], ... outer], [ [lng, lat], ... hole], ...]"""
    try:
        outer = [(float(p[0]), float(p[1])) for p in coords[0]]
        holes = []
        for ring in coords[1:]:
            holes.append([(float(p[0]), float(p[1])) for p in ring])
        if src_epsg != 4326:
            from pyproj import Transformer
            tr = Transformer.from_crs(f"EPSG:{src_epsg}", "EPSG:4326", always_xy=True)
            outer = [tr.transform(x, y) for (x, y) in outer]
            holes = [[tr.transform(x, y) for (x, y) in ring] for ring in holes]
        poly = ShPolygon(outer, holes=holes if holes else None)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if not poly.is_empty else None
    except Exception:
        return None


def main() -> int:
    out_path = ROOT / "outputs" / "dc_top50_appalachian_polygon_rescore.csv"
    in_path = ROOT / "outputs" / "dc_top200_appalachian.csv"

    with in_path.open("r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))[:50]
    print(f"Top 50 candidates loaded")

    # Group by county
    by_county: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_county[(r.get("county") or "").upper()].append(r)
    print(f"Counties: {dict((k, len(v)) for k, v in by_county.items())}")

    # Fetch polygons per county
    print("\nFetching polygons...")
    polys_by_pid: dict[tuple[str, str], ShPolygon] = {}
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}, follow_redirects=True) as c:
        for county, county_rows in by_county.items():
            src = SOURCES.get(county)
            if not src:
                print(f"  {county}: no source registered, skipping {len(county_rows)} rows")
                continue
            pids = [str(r.get("parcel_id") or "").strip() for r in county_rows]
            pids = [p for p in pids if p]
            if not pids:
                continue
            try:
                if src.kind == "arcgis_rest":
                    raw = _arcgis_query_polygons(c, src, pids)
                    for pid, rings in raw.items():
                        poly = _arcgis_rings_to_shapely(rings)
                        if poly:
                            polys_by_pid[(county, pid)] = poly
                elif src.kind == "geoserver_wfs":
                    raw = _wfs_query_polygons(c, src, pids)
                    for pid, (coords, src_epsg) in raw.items():
                        poly = _wfs_coords_to_shapely(coords, src_epsg)
                        if poly:
                            polys_by_pid[(county, pid)] = poly
                got = sum(1 for k in polys_by_pid if k[0] == county)
                print(f"  {county}: {got}/{len(pids)} polygons fetched")
            except Exception as e:
                print(f"  {county}: ERR {type(e).__name__}: {str(e)[:80]}")

    print(f"\nLoaded {len(polys_by_pid)} polygons total")
    if not polys_by_pid:
        print("No polygons — aborting")
        return 1

    print("\nLoading DEM...")
    datasets = _build_dem_datasets()
    print(f"  {len(datasets)} DEM tiles")

    print("\nRe-scoring slopes from polygons...")
    out_rows = []
    t0 = time.time()
    for r in rows:
        county = (r.get("county") or "").upper()
        pid = str(r.get("parcel_id") or "").strip()
        poly = polys_by_pid.get((county, pid))
        if poly is None:
            continue

        grid_pts = _generate_grid_in_polygon(poly, SAMPLE_GRID_N)
        slopes: list[float] = []
        for plat, plng in grid_pts:
            s = _slope_at_point(datasets, plat, plng)
            if s is not None:
                slopes.append(s)
        if not slopes:
            continue
        arr = np.array(slopes)

        out_rows.append({
            "rank": rows.index(r) + 1,
            "county": r.get("county"),
            "parcel_id": pid,
            "owner": r.get("owner"),
            "acres": r.get("acres"),
            "site": r.get("site"),
            "lat": r.get("lat"),
            "lng": r.get("lng"),
            "score_dc_original": r.get("score_dc"),
            # Centroid-grid sampling (what we had)
            "centroid_slope_mean": r.get("slope_mean_pct"),
            "centroid_slope_max": r.get("slope_max_pct"),
            "centroid_pct_under_5": r.get("pct_under_5pct_slope"),
            "centroid_pct_under_10": r.get("pct_under_10pct_slope"),
            "centroid_pct_under_15": r.get("pct_under_15pct_slope"),
            # Polygon-aware sampling (new, more accurate)
            "poly_n_samples": len(slopes),
            "poly_slope_mean": round(float(arr.mean()), 2),
            "poly_slope_max": round(float(arr.max()), 2),
            "poly_pct_under_5": round(float((arr < 5).mean() * 100), 1),
            "poly_pct_under_10": round(float((arr < 10).mean() * 100), 1),
            "poly_pct_under_15": round(float((arr < 15).mean() * 100), 1),
            # Delta of pct_under_10 (the buildability metric)
            "delta_pct_under_10": (
                round(float((arr < 10).mean() * 100) - float(r.get("pct_under_10pct_slope") or 0), 1)
                if r.get("pct_under_10pct_slope") not in (None, "") else ""
            ),
        })
        if len(out_rows) % 10 == 0:
            print(f"  re-scored {len(out_rows)}/{len(rows)} (in {time.time()-t0:.0f}s)")

    # Sort by polygon mean slope ascending (flattest first)
    out_rows.sort(key=lambda r: float(r.get("poly_slope_mean") or 999))

    fields = list(out_rows[0].keys())
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    for ds in datasets:
        ds.close()

    print(f"\nWrote {len(out_rows)} rows to {out_path}")
    print(f"Duration: {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
