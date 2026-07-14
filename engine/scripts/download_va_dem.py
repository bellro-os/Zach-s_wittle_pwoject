"""Download USGS 3DEP 1/3 arc-second DEM tiles covering Virginia.

Tile naming: USGS_13_n{NN}w{WWW}.tif covers the 1° square from
(NN-1)°N to NN°N latitude and (WWW-1)°W to WWW°W longitude. So the file
n38w080 covers 37-38°N, 79-80°W.

Source: USGS S3 staged products (no auth, no rate limit).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


# Latitude tile NORTHERN edges + longitude WESTERN edges to cover Virginia.
# VA spans 36.5-39.5°N and 75.2-83.7°W → tile names are the *upper-left* corner.
LAT_NORTH_EDGES = [37, 38, 39, 40]   # covers 36-37, 37-38, 38-39, 39-40
LON_WEST_EDGES  = [76, 77, 78, 79, 80, 81, 82, 83, 84]


def tile_url(lat_n: int, lon_w: int) -> str:
    """USGS 3DEP 1 arc-second (~30m) tile. 1/3 arc-second tiles exist too
    but are ~9x larger (486 MB vs 54 MB each); 30m is plenty for slope
    filtering at parcel scale."""
    coord = f"n{lat_n:02d}w{lon_w:03d}"
    return (
        f"https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/TIFF/"
        f"current/{coord}/USGS_1_{coord}.tif"
    )


def fetch(client: httpx.Client, url: str, dest: Path) -> tuple[Path, str, int]:
    if dest.exists() and dest.stat().st_size > 0:
        return dest, "cached", dest.stat().st_size
    try:
        with client.stream("GET", url, timeout=300) as r:
            if r.status_code == 404:
                return dest, "missing", 0
            r.raise_for_status()
            tmp = dest.with_suffix(".tmp")
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
            tmp.rename(dest)
            return dest, "downloaded", dest.stat().st_size
    except Exception as e:
        return dest, f"error: {type(e).__name__} {str(e)[:60]}", 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/dem", help="Where to write tiles")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    targets: list[tuple[Path, str]] = []
    for lat_n in LAT_NORTH_EDGES:
        for lon_w in LON_WEST_EDGES:
            url = tile_url(lat_n, lon_w)
            dest = out_dir / Path(url).name
            targets.append((dest, url))

    total_bytes = 0
    t0 = time.time()
    with httpx.Client() as client, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fetch, client, url, dest): (dest, url) for dest, url in targets}
        for fut in as_completed(futures):
            dest, status, size = fut.result()
            total_bytes += size
            mark = "OK" if status in ("cached", "downloaded") else ".."
            print(f"  {mark} {dest.name:40s} {status:14s} {size/1e6:7.1f} MB")

    print(f"\nTotal: {total_bytes/1e9:.2f} GB in {time.time()-t0:.0f}s, dir={out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
