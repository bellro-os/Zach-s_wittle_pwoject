"""Augment v2 DC metrics CSVs with three new dimensions:

1. Utility service (primary_utility, queue_tier) — from county lookup
2. Fiber proximity (miles_to_major_highway) — distance to nearest
   interstate/US-highway/state-primary as a fiber-corridor proxy
3. Adjacency clusters — for each preset's top 500 by score, find clusters
   of parcels under different ownership within ~1 mile of each other
   that could potentially be assembled into a hyperscale-grade campus

Outputs:
  outputs/all_parcels_dc_metrics_<preset>_v3.csv  (one row per parcel)
  outputs/dc_assemblage_clusters_<preset>.csv     (one row per cluster)
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.neighbors import BallTree

EARTH_R_MI = 3958.7613


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


def _build_tree(pts):
    if len(pts) == 0:
        return None
    return BallTree(np.radians(pts), metric="haversine")


def _nearest_miles(tree, lats, lngs):
    if tree is None or len(lats) == 0:
        return np.full(len(lats), np.nan)
    pts = np.radians(np.column_stack([lats, lngs]))
    dists, _ = tree.query(pts, k=1)
    return dists[:, 0] * EARTH_R_MI


def _normalize_owner(owner: str) -> str:
    """Crude owner-key normalization for adjacency dedup. Strip common
    suffixes so "BOTTOMLEY BROTHERS" and "BOTTOMLEY BROTHERS LLC" hash same."""
    s = (owner or "").upper().strip()
    s = re.sub(r"\b(LLC|L\.L\.C\.|INC|INCORPORATED|CORP|CORPORATION|"
               r"COMPANY|CO|LP|LIMITED|LTD|PARTNERS?|TRUST|TRUSTEE|"
               r"PROPERTIES|HOLDINGS|GROUP|REALTY)\b", "", s)
    s = re.sub(r"[,&]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_clusters(rows: list[dict], radius_mi: float = 1.0,
                  min_combined_acres: float = 200.0) -> list[dict]:
    """Find groups of qualifying parcels within `radius_mi` of each other
    where the combined acreage is above `min_combined_acres` and at least
    two distinct owner-keys are involved."""
    pts = []
    for r in rows:
        try:
            pts.append((float(r["lat"]), float(r["lng"])))
        except (KeyError, TypeError, ValueError):
            pts.append((np.nan, np.nan))
    pts_arr = np.array(pts)
    valid = ~(np.isnan(pts_arr[:, 0]) | np.isnan(pts_arr[:, 1]))
    if not valid.any():
        return []
    valid_idx = np.where(valid)[0]
    tree = BallTree(np.radians(pts_arr[valid]), metric="haversine")
    radius_rad = radius_mi / EARTH_R_MI

    # Union-find clustering
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for local_i, global_i in enumerate(valid_idx):
        nbrs = tree.query_radius(
            np.radians([[pts_arr[global_i, 0], pts_arr[global_i, 1]]]),
            r=radius_rad,
        )[0]
        for local_j in nbrs:
            if local_j == local_i:
                continue
            global_j = valid_idx[local_j]
            union(global_i, int(global_j))

    cluster_to_indices: dict[int, list[int]] = defaultdict(list)
    for i in valid_idx:
        cluster_to_indices[find(int(i))].append(int(i))

    clusters: list[dict] = []
    for root, members in cluster_to_indices.items():
        if len(members) < 2:
            continue
        owners = {_normalize_owner(rows[i].get("owner", "")) for i in members}
        owners.discard("")
        if len(owners) < 2:
            continue  # all same owner — already a single tract
        total_acres = 0.0
        scores = []
        for i in members:
            try:
                total_acres += float(rows[i].get("acres") or 0)
            except (TypeError, ValueError):
                pass
            try:
                scores.append(float(rows[i].get("score_dc") or 0))
            except (TypeError, ValueError):
                pass
        if total_acres < min_combined_acres:
            continue
        # Cluster centroid
        clats = [float(rows[i]["lat"]) for i in members if rows[i].get("lat")]
        clngs = [float(rows[i]["lng"]) for i in members if rows[i].get("lng")]
        clusters.append({
            "n_parcels": len(members),
            "n_distinct_owners": len(owners),
            "total_acres": round(total_acres, 1),
            "max_score": round(max(scores), 1) if scores else 0,
            "mean_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "county": rows[members[0]].get("county", ""),
            "centroid_lat": round(sum(clats) / max(len(clats), 1), 5),
            "centroid_lng": round(sum(clngs) / max(len(clngs), 1), 5),
            "owners": " | ".join(sorted(owners))[:300],
            "parcel_ids": ", ".join(rows[i].get("parcel_id", "") for i in members)[:400],
        })
    clusters.sort(key=lambda c: -c["total_acres"])
    return clusters


def main() -> int:
    root = Path(__file__).parent.parent

    # 1. Load utility-by-county lookup
    util_path = root / "data" / "va_utility_by_county.json"
    util_lookup = json.loads(util_path.read_text(encoding="utf-8"))

    # 2. Build fiber-proxy BallTree from highway vertices
    print("Loading highway proxy...")
    hwy_pts = _load_polyline_vertices(root / "data" / "va_fiber_proxy.jsonl")
    print(f"  {len(hwy_pts):,} highway vertices")
    tree_hwy = _build_tree(hwy_pts)

    # 3. Augment each preset CSV
    for preset in ("piedmont", "appalachian"):
        in_path = root / "outputs" / f"all_parcels_dc_metrics_{preset}.csv"
        out_path = root / "outputs" / f"all_parcels_dc_metrics_{preset}_v3.csv"
        cluster_path = root / "outputs" / f"dc_assemblage_clusters_{preset}.csv"
        if not in_path.exists():
            print(f"  -- {preset}: missing input {in_path.name}")
            continue
        print(f"\n=== {preset} ===")

        with in_path.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        print(f"  {len(rows):,} input rows")

        # Collect lat/lng arrays
        lats = np.array([float(r["lat"]) if r.get("lat") not in (None, "") else np.nan
                         for r in rows])
        lngs = np.array([float(r["lng"]) if r.get("lng") not in (None, "") else np.nan
                         for r in rows])
        valid = ~(np.isnan(lats) | np.isnan(lngs))

        # Highway distances (vectorized)
        hwy_mi = np.full(len(rows), np.nan)
        if tree_hwy is not None and valid.any():
            d = _nearest_miles(tree_hwy, lats[valid], lngs[valid])
            hwy_mi[valid] = d

        # Write augmented CSV
        new_fields = list(rows[0].keys()) + [
            "primary_utility", "secondary_utility", "queue_tier",
            "miles_to_major_highway",
        ]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=new_fields)
            w.writeheader()
            for i, r in enumerate(rows):
                county = (r.get("county") or "").upper()
                util = util_lookup.get(county, {})
                r_out = dict(r)
                r_out["primary_utility"] = util.get("primary", "")
                r_out["secondary_utility"] = util.get("secondary", "") or ""
                r_out["queue_tier"] = util.get("queue_tier", "")
                r_out["miles_to_major_highway"] = (
                    round(float(hwy_mi[i]), 2) if not np.isnan(hwy_mi[i]) else ""
                )
                w.writerow(r_out)
        print(f"  wrote {out_path.name}")

        # 4. Adjacency clusters — only on the passed-filter rows
        passed = [r for r in rows if r.get("passed_hard_filters") == "Y"]
        # Add hwy_mi back for the passed rows
        passed_with_idx = [(i, r) for i, r in enumerate(rows)
                           if r.get("passed_hard_filters") == "Y"]
        passed_rows = [r for _, r in passed_with_idx]
        # Convert lat/lng strings to float for clustering
        for r in passed_rows:
            try:
                r["lat"] = float(r["lat"])
                r["lng"] = float(r["lng"])
            except (TypeError, ValueError, KeyError):
                pass

        clusters = find_clusters(passed_rows, radius_mi=1.0, min_combined_acres=200.0)
        print(f"  found {len(clusters)} assemblage clusters (>=2 owners, >=200 ac total, within 1 mi)")
        if clusters:
            with cluster_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(clusters[0].keys()))
                w.writeheader()
                w.writerows(clusters)
            print(f"  wrote {cluster_path.name}")
            print(f"  top 5 by combined acreage:")
            for c in clusters[:5]:
                print(f"    {c['county']:14s} {c['n_parcels']:>2}p {c['total_acres']:>7.0f}ac "
                      f"{c['n_distinct_owners']}owner  ({c['owners'][:80]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
