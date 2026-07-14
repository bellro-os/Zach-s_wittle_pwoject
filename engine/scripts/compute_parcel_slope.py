"""Compute per-parcel slope statistics from a local DEM.

For each parcel JSONL row (must have lat/lng + acres):
  1. Generate a 5×5 sampling grid sized to the parcel's acreage.
  2. At each grid point, sample DEM elevation + 4 neighbors at ~30m offsets.
  3. Compute slope (rise over run) at each point.
  4. Aggregate: mean_slope_pct, max_slope_pct, pct_under_5pct,
     pct_under_10pct, pct_under_15pct.

Adds those fields to each row and writes to --out JSONL.

Approximation note: we sample within an equivalent-area circle around the
centroid using the `acres` field. For extremely irregular parcels (long/skinny
or L-shaped) the sample area diverges from the true polygon, but for the
overwhelming majority of residential and small-acreage rural parcels in VA
this matches polygon-based sampling closely enough for "is this mostly flat?"
filtering.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge as rio_merge


METERS_PER_DEG_LAT = 111_320.0
ELEV_OFFSET_M = 30.0  # neighbor distance for slope calc
GRID_N = 5  # 5x5 = 25 sample points per parcel


def _build_vrt(dem_dir: Path) -> rasterio.io.DatasetReader:
    """Open a virtual mosaic over all DEM tiles in a directory."""
    # Match both 1 arc-second (~30m) and 1/3 arc-second (~10m) tile names.
    tiles = sorted(set(dem_dir.glob("USGS_1_n*w*.tif")) | set(dem_dir.glob("USGS_13_n*w*.tif")))
    if not tiles:
        raise RuntimeError(f"No DEM tiles found under {dem_dir}")
    print(f"  loading {len(tiles)} DEM tiles into a virtual mosaic...")
    # Open all tiles, then build an in-memory mosaic dataset via rasterio's
    # merge — this gives us a single sampleable raster across VA.
    datasets = [rasterio.open(t) for t in tiles]
    return datasets


def _sample_elevations(datasets, points: list[tuple[float, float]]) -> list[float | None]:
    """Sample elevation (meters) at a list of (lat, lng) points across multiple
    tile datasets. Returns None where the point falls outside coverage."""
    out: list[float | None] = [None] * len(points)
    # Group points by which tile contains them. The tile naming gives us
    # bounds: USGS_13_n{NN}w{WWW}.tif covers [WWW-1, WWW] lng × [NN-1, NN] lat.
    for ds in datasets:
        b = ds.bounds  # left, bottom, right, top in lng/lat
        # rasterio.sample is fastest when points are batched per dataset.
        coords = [(lng, lat) for (lat, lng) in points]
        idx_in_bounds: list[int] = []
        coords_in_bounds: list[tuple[float, float]] = []
        for i, (lng, lat) in enumerate(coords):
            if out[i] is not None:
                continue
            if b.left <= lng <= b.right and b.bottom <= lat <= b.top:
                idx_in_bounds.append(i)
                coords_in_bounds.append((lng, lat))
        if not coords_in_bounds:
            continue
        # rasterio.DatasetReader.sample yields one band-tuple per coord.
        for i, vals in zip(idx_in_bounds, ds.sample(coords_in_bounds, indexes=1)):
            v = vals[0] if len(vals) else None
            if v is None or (isinstance(v, float) and (math.isnan(v) or v < -1000)):
                continue
            out[i] = float(v)
    return out


def _grid_offsets(acres: float, n: int = GRID_N) -> list[tuple[float, float]]:
    """Return n*n (d_lat_meters, d_lng_meters) offsets covering an equivalent
    area to a parcel of `acres`."""
    area_m2 = max(acres, 0.05) * 4046.86
    radius_m = math.sqrt(area_m2 / math.pi)
    span = 2 * radius_m  # square inscribed around the equivalent circle
    step = span / max(n - 1, 1)
    half = (n - 1) / 2.0
    return [
        ((j - half) * step, (i - half) * step)
        for j in range(n)
        for i in range(n)
    ]


def _slope_pct_at(datasets, lat: float, lng: float) -> float | None:
    """Slope (% grade) at a single (lat, lng) using elevation + 4 neighbors."""
    cos_lat = math.cos(math.radians(lat))
    if cos_lat <= 0:
        return None
    d_lat = ELEV_OFFSET_M / METERS_PER_DEG_LAT
    d_lng = ELEV_OFFSET_M / (METERS_PER_DEG_LAT * cos_lat)
    pts = [
        (lat,           lng),
        (lat,           lng + d_lng),  # E
        (lat,           lng - d_lng),  # W
        (lat + d_lat,   lng),          # N
        (lat - d_lat,   lng),          # S
    ]
    z = _sample_elevations(datasets, pts)
    if any(v is None for v in z):
        return None
    _, z_e, z_w, z_n, z_s = z
    dzdx = (z_e - z_w) / (2 * ELEV_OFFSET_M)
    dzdy = (z_n - z_s) / (2 * ELEV_OFFSET_M)
    slope = math.sqrt(dzdx * dzdx + dzdy * dzdy)
    return slope * 100  # %


def compute_parcel_slope_stats(datasets, lat: float, lng: float, acres: float) -> dict:
    """Return slope statistics across a grid of GRID_N × GRID_N samples."""
    cos_lat = math.cos(math.radians(lat))
    if cos_lat <= 0:
        return {}
    offsets = _grid_offsets(acres, GRID_N)
    sample_pts: list[tuple[float, float]] = []
    for d_lat_m, d_lng_m in offsets:
        sample_pts.append((
            lat + d_lat_m / METERS_PER_DEG_LAT,
            lng + d_lng_m / (METERS_PER_DEG_LAT * cos_lat),
        ))

    slopes: list[float] = []
    for plat, plng in sample_pts:
        s = _slope_pct_at(datasets, plat, plng)
        if s is not None:
            slopes.append(s)

    if not slopes:
        return {}
    arr = np.array(slopes)
    return {
        "slope_n_samples": len(slopes),
        "slope_mean_pct": round(float(arr.mean()), 2),
        "slope_max_pct": round(float(arr.max()), 2),
        "slope_p50_pct": round(float(np.median(arr)), 2),
        "pct_under_5pct_slope": round(float((arr < 5).mean() * 100), 1),
        "pct_under_10pct_slope": round(float((arr < 10).mean() * 100), 1),
        "pct_under_15pct_slope": round(float((arr < 15).mean() * 100), 1),
    }


def process_file(in_path: Path, out_path: Path, dem_dir: Path) -> dict:
    datasets = _build_vrt(dem_dir)
    n_total = 0
    n_with_slope = 0
    t0 = time.time()
    with in_path.open("r", encoding="utf-8") as fin, \
         out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            row = json.loads(line)
            n_total += 1
            lat = row.get("lat")
            lng = row.get("lng")
            acres = row.get("acres")
            if lat is not None and lng is not None:
                # Fall back to a 0.5-acre footprint when the source doesn't
                # expose acreage. Better an approximate slope than none.
                acres_f = float(acres) if acres else 0.5
                try:
                    stats = compute_parcel_slope_stats(datasets, float(lat), float(lng), acres_f)
                except Exception:
                    stats = {}
                if stats:
                    n_with_slope += 1
                row.update(stats)
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n_total % 5000 == 0:
                rate = n_total / max(time.time() - t0, 0.001)
                print(f"    processed {n_total:,} parcels ({rate:.0f}/s, {n_with_slope:,} with slope)")

    for ds in datasets:
        ds.close()

    return {
        "rows": n_total,
        "with_slope": n_with_slope,
        "duration_s": round(time.time() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="outp", required=True)
    ap.add_argument("--dem-dir", default="data/dem")
    args = ap.parse_args()

    in_path = Path(args.inp)
    out_path = Path(args.outp)
    dem_dir = Path(args.dem_dir)
    if not in_path.exists():
        print(f"error: input {in_path} not found", file=sys.stderr)
        return 2

    print(f"slope: {in_path.name} -> {out_path.name}")
    stats = process_file(in_path, out_path, dem_dir)
    for k, v in stats.items():
        print(f"  {k:18s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
