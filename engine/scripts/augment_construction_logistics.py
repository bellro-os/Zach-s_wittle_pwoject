"""Add construction-logistics metrics to the master CSV and v3 preset CSVs.

Two new columns:
  - miles_to_interstate     — nearest motorway (= US Interstate) vertex
                              [important for heavy-haul truck routes]
  - miles_to_concrete_plant — nearest OSM-tagged concrete batch plant
                              [DC slab pours need plant within ~30 min drive]

Also writes data/va_interstates.jsonl as a derivative of va_fiber_proxy.jsonl
so the webmap can show interstates separately from "any major highway."

Existing CSVs that already have data are augmented in-place by writing
*_v3plus.csv variants alongside them — original files are not modified.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.neighbors import BallTree

EARTH_R_MI = 3958.7613
ROOT = Path(__file__).parent.parent


# --- Build interstates-only file from existing fiber proxy ---

def derive_interstates() -> Path:
    src = ROOT / "data" / "va_fiber_proxy.jsonl"
    dst = ROOT / "data" / "va_interstates.jsonl"
    n = 0
    with src.open("r", encoding="utf-8") as fin, \
         dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            r = json.loads(line)
            if (r.get("highway") or "").lower() != "motorway":
                continue
            fout.write(line if line.endswith("\n") else line + "\n")
            n += 1
    print(f"  wrote {n:,} interstate segments to {dst.name}")
    return dst


def _load_polyline_vertices(path: Path):
    pts: list[tuple[float, float]] = []
    if not path.exists():
        return np.zeros((0, 2))
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            for path_pts in r.get("paths") or []:
                for p in path_pts:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        try:
                            pts.append((float(p[1]), float(p[0])))
                        except (TypeError, ValueError):
                            continue
    return np.array(pts, dtype=np.float64)


def _load_points(path: Path):
    pts: list[tuple[float, float]] = []
    extras: list[dict] = []
    if not path.exists():
        return np.zeros((0, 2)), []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            try:
                pts.append((float(r["lat"]), float(r["lng"])))
            except (KeyError, TypeError, ValueError):
                continue
            extras.append(r)
    return np.array(pts, dtype=np.float64), extras


def _build_tree(pts):
    if len(pts) == 0:
        return None
    return BallTree(np.radians(pts), metric="haversine")


def _nearest_miles(tree, lats, lngs):
    if tree is None or len(lats) == 0:
        return np.full(len(lats), np.nan), np.full(len(lats), -1, dtype=int)
    pts = np.radians(np.column_stack([lats, lngs]))
    dists, idx = tree.query(pts, k=1)
    return dists[:, 0] * EARTH_R_MI, idx[:, 0]


def augment_csv(in_path: Path, out_path: Path, tree_int, tree_cnc, plant_extras):
    if not in_path.exists():
        print(f"  -- {in_path.name}: missing, skip")
        return 0
    print(f"  reading {in_path.name}...")
    with in_path.open("r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        original_fields = list(rows[0].keys()) if rows else []
    if not rows:
        return 0

    lats = np.array([float(r["lat"]) if r.get("lat") not in (None, "") else np.nan for r in rows])
    lngs = np.array([float(r["lng"]) if r.get("lng") not in (None, "") else np.nan for r in rows])
    valid = ~(np.isnan(lats) | np.isnan(lngs))

    int_mi = np.full(len(rows), np.nan)
    cnc_mi = np.full(len(rows), np.nan)
    cnc_idx = np.full(len(rows), -1, dtype=int)
    if valid.any():
        d, _ = _nearest_miles(tree_int, lats[valid], lngs[valid]); int_mi[valid] = d
        d, idx = _nearest_miles(tree_cnc, lats[valid], lngs[valid])
        cnc_mi[valid] = d
        cnc_idx[valid] = idx

    new_fields = original_fields + ["miles_to_interstate",
                                     "miles_to_concrete_plant",
                                     "nearest_concrete_plant"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=new_fields)
        w.writeheader()
        for i, r in enumerate(rows):
            r2 = dict(r)
            r2["miles_to_interstate"] = (
                round(float(int_mi[i]), 2) if not np.isnan(int_mi[i]) else ""
            )
            r2["miles_to_concrete_plant"] = (
                round(float(cnc_mi[i]), 2) if not np.isnan(cnc_mi[i]) else ""
            )
            if cnc_idx[i] >= 0 and cnc_idx[i] < len(plant_extras):
                p = plant_extras[int(cnc_idx[i])]
                r2["nearest_concrete_plant"] = (
                    p.get("name") or p.get("operator") or "(unnamed)"
                )
            else:
                r2["nearest_concrete_plant"] = ""
            w.writerow(r2)
    print(f"    wrote {len(rows):,} rows to {out_path.name}")
    return len(rows)


def main() -> int:
    print("Deriving interstates from fiber proxy...")
    derive_interstates()

    print("Loading lookup trees...")
    int_pts = _load_polyline_vertices(ROOT / "data" / "va_interstates.jsonl")
    cnc_pts, cnc_extras = _load_points(ROOT / "data" / "va_concrete_plants.jsonl")
    print(f"  interstate vertices: {len(int_pts):,}")
    print(f"  concrete plants: {len(cnc_pts)}")
    tree_int = _build_tree(int_pts)
    tree_cnc = _build_tree(cnc_pts)

    print("Augmenting v3 preset CSVs...")
    targets = [
        ("outputs/all_parcels_dc_metrics_piedmont_v3.csv",
         "outputs/all_parcels_dc_metrics_piedmont_v3plus.csv"),
        ("outputs/all_parcels_dc_metrics_appalachian_v3.csv",
         "outputs/all_parcels_dc_metrics_appalachian_v3plus.csv"),
        ("outputs/all_parcels_dc_metrics_hyperscale_v3.csv",
         "outputs/all_parcels_dc_metrics_hyperscale_v3plus.csv"),
        ("outputs/all_parcels_dc_master.csv",
         "outputs/all_parcels_dc_master_v2.csv"),
        ("outputs/dc_master_qualifying.csv",
         "outputs/dc_master_qualifying_v2.csv"),
        ("outputs/dc_master_top200.csv",
         "outputs/dc_master_top200_v2.csv"),
        ("outputs/dc_master_top1000.csv",
         "outputs/dc_master_top1000_v2.csv"),
        ("outputs/dc_master_hyperscale_qualifying.csv",
         "outputs/dc_master_hyperscale_qualifying_v2.csv"),
        ("outputs/dc_master_piedmont_qualifying.csv",
         "outputs/dc_master_piedmont_qualifying_v2.csv"),
        ("outputs/dc_master_appalachian_qualifying.csv",
         "outputs/dc_master_appalachian_qualifying_v2.csv"),
    ]

    t0 = time.time()
    total = 0
    for in_rel, out_rel in targets:
        n = augment_csv(ROOT / in_rel, ROOT / out_rel, tree_int, tree_cnc, cnc_extras)
        total += n
    print(f"\n  Augmented {total:,} rows total in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
