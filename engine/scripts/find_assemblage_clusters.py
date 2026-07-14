"""For each TOP candidate, find nearby qualifying parcels under different
ownership that could realistically be assembled into one campus.

This is a per-anchor view (not transitive union-find) so a "cluster" =
a single anchor parcel + the small handful of qualifying neighbors right
next to it. Realistic data-center assemblages are 2-5 contiguous parcels,
not whole counties.

Output: outputs/dc_assemblage_anchors_<preset>.csv
        one row per anchor parcel showing total assemblage size, owners,
        and parcel IDs.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.neighbors import BallTree

EARTH_R_MI = 3958.7613
RADIUS_MI = 0.25  # ~1320 ft — very strict adjacency
MAX_NEIGHBORS = 10  # cap on per-anchor neighbor count
TOP_N_ANCHORS = 200


def _normalize_owner(owner: str) -> str:
    s = (owner or "").upper().strip()
    s = re.sub(r"\b(LLC|L\.L\.C\.|INC|INCORPORATED|CORP|CORPORATION|"
               r"COMPANY|CO|LP|LIMITED|LTD|PARTNERS?|TRUST|TRUSTEE|"
               r"PROPERTIES|HOLDINGS|GROUP|REALTY)\b", "", s)
    s = re.sub(r"[,&]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main() -> int:
    root = Path(__file__).parent.parent

    for preset in ("piedmont", "appalachian"):
        in_path = root / "outputs" / f"all_parcels_dc_metrics_{preset}.csv"
        if not in_path.exists():
            print(f"  -- {preset}: missing")
            continue
        print(f"\n=== {preset} ===")

        with in_path.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        passed = [r for r in rows if r.get("passed_hard_filters") == "Y"]
        passed.sort(key=lambda r: -float(r.get("score_dc") or 0))
        anchors = passed[:TOP_N_ANCHORS]
        print(f"  evaluating top {len(anchors)} anchors against {len(passed):,} qualifying neighbors")

        # Build BallTree over ALL passed rows (not just anchors)
        lats = []
        lngs = []
        for r in passed:
            try:
                lats.append(float(r["lat"]))
                lngs.append(float(r["lng"]))
            except (TypeError, ValueError, KeyError):
                lats.append(np.nan)
                lngs.append(np.nan)
        lats_arr = np.array(lats)
        lngs_arr = np.array(lngs)
        valid = ~(np.isnan(lats_arr) | np.isnan(lngs_arr))
        valid_indices = np.where(valid)[0]
        if not len(valid_indices):
            continue
        tree = BallTree(np.radians(np.column_stack([lats_arr[valid], lngs_arr[valid]])),
                        metric="haversine")
        radius_rad = RADIUS_MI / EARTH_R_MI

        out_rows = []
        for anchor in anchors:
            try:
                a_lat = float(anchor["lat"])
                a_lng = float(anchor["lng"])
            except (TypeError, ValueError, KeyError):
                continue
            a_owner = _normalize_owner(anchor.get("owner", ""))
            a_pid = anchor.get("parcel_id", "")
            try:
                a_acres = float(anchor.get("acres") or 0)
            except (TypeError, ValueError):
                a_acres = 0

            nbrs_local = tree.query_radius(np.radians([[a_lat, a_lng]]), r=radius_rad)[0]
            other_owners: set[str] = set()
            other_parcels: list[dict] = []
            total_other_acres = 0.0
            for local_i in nbrs_local:
                gi = int(valid_indices[local_i])
                neighbor = passed[gi]
                n_pid = neighbor.get("parcel_id", "")
                if n_pid == a_pid:
                    continue
                n_owner = _normalize_owner(neighbor.get("owner", ""))
                if n_owner == a_owner or not n_owner:
                    continue
                try:
                    n_acres = float(neighbor.get("acres") or 0)
                except (TypeError, ValueError):
                    n_acres = 0
                other_owners.add(n_owner)
                total_other_acres += n_acres
                other_parcels.append({
                    "parcel_id": n_pid,
                    "owner": neighbor.get("owner", ""),
                    "acres": n_acres,
                    "score_dc": neighbor.get("score_dc", ""),
                })

            if not other_owners:
                continue
            # Cap printed neighbors for readability
            other_parcels.sort(key=lambda x: -x["acres"])
            top_neighbors = other_parcels[:MAX_NEIGHBORS]

            out_rows.append({
                "anchor_rank": anchors.index(anchor) + 1,
                "anchor_score": anchor.get("score_dc", ""),
                "county": anchor.get("county", ""),
                "anchor_parcel_id": a_pid,
                "anchor_owner": anchor.get("owner", ""),
                "anchor_acres": round(a_acres, 1),
                "anchor_lat": a_lat,
                "anchor_lng": a_lng,
                "n_distinct_other_owners": len(other_owners),
                "n_neighbors": len(other_parcels),
                "total_assemblage_acres": round(a_acres + total_other_acres, 1),
                "neighbor_owners": " | ".join(sorted(other_owners))[:300],
                "neighbor_parcels": "; ".join(
                    f"{n['parcel_id']}({n['owner'][:25]}, {n['acres']:.0f}ac)"
                    for n in top_neighbors
                )[:600],
            })

        out_rows.sort(key=lambda r: -r["total_assemblage_acres"])
        out_path = root / "outputs" / f"dc_assemblage_anchors_{preset}.csv"
        if out_rows:
            with out_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
                w.writeheader()
                w.writerows(out_rows)
            print(f"  wrote {len(out_rows)} assemblage anchors -> {out_path.name}")
            print(f"  top 5 by total assemblage acreage:")
            for r in out_rows[:5]:
                print(f"    rank #{r['anchor_rank']:>3} {r['county'][:11]:11s} "
                      f"anchor={r['anchor_acres']:.0f}ac assemblage={r['total_assemblage_acres']:.0f}ac "
                      f"({r['n_distinct_other_owners']}other-owners) "
                      f"anchor_owner={r['anchor_owner'][:30]}")
        else:
            print(f"  no anchors with adjacent different-ownership qualifying parcels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
