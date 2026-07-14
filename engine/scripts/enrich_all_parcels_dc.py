"""Bulk-enrich every scanned parcel (744k+) with DC-suitability metrics.

Unlike the DC_SUITABILITY detector — which only emits *passed* parcels — this
script writes a row for **every** parcel across all 24 county slope JSONLs.
Includes every distance, every slope stat, the composite score, and a
hard-filter pass/fail breakdown.

Vectorized via sklearn.BallTree (haversine metric) for sub-second per-county
nearest-neighbor queries. Polyline distance is approximated as nearest-vertex
distance (close to perpendicular-to-segment for transmission-line scale).

Output: outputs/all_parcels_dc_metrics.csv (one row per parcel)
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


COUNTIES = [
    "montgomery", "roanoke", "franklin", "floyd", "giles", "carroll",
    "washington", "bland", "lee", "wise", "wythe", "patrick",
    "tazewell", "pulaski", "henry", "craig", "smyth", "buchanan",
    "halifax", "mecklenburg", "brunswick", "lunenburg", "charlotte",
    "pittsylvania",
]


def _load_points(path: Path, lat_field="lat", lng_field="lng"):
    pts: list[tuple[float, float]] = []
    extras: list[dict] = []
    if not path.exists():
        return np.zeros((0, 2)), []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            lat = r.get(lat_field)
            lng = r.get(lng_field)
            if lat is None or lng is None:
                continue
            try:
                pts.append((float(lat), float(lng)))
            except (TypeError, ValueError):
                continue
            extras.append(r)
    return np.array(pts, dtype=np.float64), extras


def _load_polyline_vertices(path: Path):
    """Flatten all polyline vertices into one (lat, lng) array."""
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


def _build_tree(pts: np.ndarray):
    if len(pts) == 0:
        return None
    rad = np.radians(pts)
    return BallTree(rad, metric="haversine")


def _nearest_miles(tree, lats, lngs):
    """Vectorized nearest-point distance in miles."""
    if tree is None or len(lats) == 0:
        return np.full(len(lats), np.nan), np.full(len(lats), -1, dtype=int)
    pts = np.radians(np.column_stack([lats, lngs]))
    dists, idx = tree.query(pts, k=1)
    return dists[:, 0] * EARTH_R_MI, idx[:, 0]


def _load_opp_zone_polys(path: Path):
    polys = []
    if not path.exists():
        return polys
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            rings_raw = r.get("rings") or []
            polygon = []
            for ring in rings_raw:
                pts = [(float(p[0]), float(p[1])) for p in ring
                       if isinstance(p, (list, tuple)) and len(p) >= 2]
                if len(pts) >= 3:
                    polygon.append(pts)
            if polygon:
                # Bounding box for fast pre-screen
                xs = [pt[0] for pt in polygon[0]]
                ys = [pt[1] for pt in polygon[0]]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                polys.append((bbox, polygon))
    return polys


def _point_in_ring(lng: float, lat: float, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def _in_any_opp_zone(lat: float, lng: float, polys) -> bool:
    for bbox, polygon in polys:
        if not (bbox[0] <= lng <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            continue
        if _point_in_ring(lng, lat, polygon[0]):
            if not any(_point_in_ring(lng, lat, ring) for ring in polygon[1:]):
                return True
    return False


def _score_substation(miles: float, kv: float | None) -> float:
    if math.isnan(miles):
        return 0
    base = max(0.0, 1.0 - miles / 5.0)
    volt_factor = 0.6
    if kv is not None and not math.isnan(kv):
        if kv >= 500: volt_factor = 1.0
        elif kv >= 230: volt_factor = 0.95
        elif kv >= 115: volt_factor = 0.85
        elif kv >= 69:  volt_factor = 0.65
    return base * volt_factor * 20


def _score_acreage(acres: float) -> float:
    if acres < 40: return 0
    if acres >= 250: return 15
    return 15 * (acres / 250)


def _score_slope(pct_under_5: float | None) -> float:
    if pct_under_5 is None: return 0
    return 15 * (pct_under_5 / 100)


def _score_proximity(miles: float, ideal_max_mi: float, weight: float) -> float:
    if math.isnan(miles): return 0
    return weight * max(0.0, 1.0 - miles / ideal_max_mi)


def _score_acreage_bonus(acres: float) -> float:
    if acres >= 250: return 7
    if acres >= 150: return 5
    if acres >= 100: return 3
    return 0


def _hard_filter_failures(acres, owner_type, slope_mean, pct_under_8,
                          sub_kv_mi, sub_kv) -> list[str]:
    fails: list[str] = []
    if acres is None or acres < 40:
        fails.append("acres<40")
    if owner_type == "govt_or_institution":
        fails.append("owner_govt")
    if slope_mean is not None and slope_mean > 8:
        fails.append("slope>8%")
    if pct_under_8 is not None and pct_under_8 < 70:
        fails.append("buildable<70%")
    if math.isnan(sub_kv_mi) or sub_kv_mi > 5:
        fails.append("sub>5mi")
    return fails


# Owner classification (lifted from helpers — small enough to inline)
import re as _re
_ENTITY = _re.compile(r"\b(LLC|L\.L\.C\.|INC|INCORPORATED|CORP|CORPORATION|"
                       r"COMPANY|CO\b|LP\b|LIMITED|LTD|PARTNERS|TRUST|TRUSTEE|"
                       r"PROPERTIES|HOLDINGS|GROUP|REALTY|ASSOCIATES|ENTERPRISES|"
                       r"INVESTMENTS|VENTURES|CAPITAL|EQUITY|HOMES|BUILDERS)\b", _re.I)
_GOVT = _re.compile(r"\b(USA|UNITED STATES|COMMONWEALTH OF VIRGINIA|VDOT|VPI|"
                     r"VIRGINIA TECH|TOWN OF|CITY OF|COUNTY OF|COUNTY \w+|BOARD OF "
                     r"SUPERVISORS|CHURCH|CEMETERY|SCHOOL BOARD|HOA|HOMEOWNERS "
                     r"ASSOC|FIRE DEPT|FELLOWSHIP|HABITAT FOR|FRATERNITY|"
                     r"SORORITY|HILLEL|ALUMNI ASSOC|PARK AUTHORITY|UTILITY|"
                     r"AUTHORITY)\b", _re.I)


def _classify(owner: str | None) -> str:
    if not owner:
        return "unknown"
    s = str(owner).upper()
    if _GOVT.search(s):
        return "govt_or_institution"
    if _ENTITY.search(s):
        return "entity"
    return "person"


COLUMNS = [
    "county", "parcel_id", "jurisdiction", "site", "owner", "owner2",
    "owner_type", "mail_addr1", "mail_addr2", "zoning", "subd_name",
    "year_built", "assessed_total", "assessed_land", "assessed_bldg",
    "last_sale_date", "last_sale_price", "acres", "lat", "lng",
    "slope_mean_pct", "slope_max_pct", "pct_under_5pct_slope",
    "pct_under_10pct_slope", "pct_under_15pct_slope",
    "miles_to_sub_min_volt", "min_volt_at_nearest_sub_kv",
    "miles_to_any_sub", "any_sub_voltage_kv",
    "miles_to_wwtp", "miles_to_transmission_line", "miles_to_power_plant",
    "in_opportunity_zone", "score_dc",
    "passed_hard_filters", "failed_reasons",
]


def main() -> int:
    root = Path(__file__).parent.parent
    out_path = root / "outputs" / "all_parcels_dc_metrics.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Loading infra layers...")
    subs_pts, subs_extra = _load_points(root / "data" / "va_substations.jsonl")
    subs_kv = np.array([float(e.get("max_volt_kv") or 0) for e in subs_extra])
    wwtp_pts, _ = _load_points(root / "data" / "va_wastewater_treatment.jsonl")
    plant_pts, _ = _load_points(root / "data" / "va_power_plants.jsonl")
    line_pts = _load_polyline_vertices(root / "data" / "va_transmission_lines.jsonl")
    opp_polys = _load_opp_zone_polys(root / "data" / "va_opportunity_zones.jsonl")
    print(f"  subs: {len(subs_pts)}, wwtp: {len(wwtp_pts)}, "
          f"plants: {len(plant_pts)}, line_verts: {len(line_pts)}, "
          f"opp_zones: {len(opp_polys)}")

    tree_subs_all = _build_tree(subs_pts)
    # Substations meeting min_voltage_kv = 115
    subs_115 = subs_pts[subs_kv >= 115]
    subs_kv_115 = subs_kv[subs_kv >= 115]
    tree_subs_115 = _build_tree(subs_115)
    tree_wwtp = _build_tree(wwtp_pts)
    tree_plants = _build_tree(plant_pts)
    tree_lines = _build_tree(line_pts)

    t0 = time.time()
    n_total = 0
    n_passed = 0

    with out_path.open("w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=COLUMNS)
        writer.writeheader()

        for county in COUNTIES:
            in_path = root / f"data/{county}_county_parcels_slope.jsonl"
            if not in_path.exists():
                print(f"  -- {county}: missing slope file")
                continue
            t_county = time.time()

            # First pass — collect parcel coordinates and metadata
            rows: list[dict] = []
            lats: list[float] = []
            lngs: list[float] = []
            with in_path.open("r", encoding="utf-8") as fin:
                for line in fin:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    rows.append(r)
                    lats.append(r.get("lat") if isinstance(r.get("lat"), (int, float)) else float("nan"))
                    lngs.append(r.get("lng") if isinstance(r.get("lng"), (int, float)) else float("nan"))

            lats_arr = np.array(lats, dtype=np.float64)
            lngs_arr = np.array(lngs, dtype=np.float64)
            valid = ~(np.isnan(lats_arr) | np.isnan(lngs_arr))

            # Vectorized nearest-neighbor distances
            sub_mi = np.full(len(rows), np.nan)
            sub_kv = np.full(len(rows), np.nan)
            sub_kv_mi = np.full(len(rows), np.nan)
            sub_kv_atv = np.full(len(rows), np.nan)
            wwtp_mi = np.full(len(rows), np.nan)
            line_mi = np.full(len(rows), np.nan)
            plant_mi = np.full(len(rows), np.nan)

            if valid.any():
                vlat = lats_arr[valid]
                vlng = lngs_arr[valid]

                if tree_subs_all is not None:
                    d, idx = _nearest_miles(tree_subs_all, vlat, vlng)
                    sub_mi[valid] = d
                    sub_kv[valid] = subs_kv[idx]

                if tree_subs_115 is not None:
                    d, idx = _nearest_miles(tree_subs_115, vlat, vlng)
                    sub_kv_mi[valid] = d
                    sub_kv_atv[valid] = subs_kv_115[idx]

                if tree_wwtp is not None:
                    d, _ = _nearest_miles(tree_wwtp, vlat, vlng)
                    wwtp_mi[valid] = d

                if tree_lines is not None:
                    d, _ = _nearest_miles(tree_lines, vlat, vlng)
                    line_mi[valid] = d

                if tree_plants is not None:
                    d, _ = _nearest_miles(tree_plants, vlat, vlng)
                    plant_mi[valid] = d

            # Per-row finalization (opp zone, scoring, hard filters)
            for i, r in enumerate(rows):
                n_total += 1
                acres = r.get("acres")
                acres_f = float(acres) if isinstance(acres, (int, float)) else None
                slope_mean = r.get("slope_mean_pct")
                slope_max = r.get("slope_max_pct")
                pct5 = r.get("pct_under_5pct_slope")
                pct8 = r.get("pct_under_10pct_slope")
                pct15 = r.get("pct_under_15pct_slope")
                slope_mean_f = float(slope_mean) if isinstance(slope_mean, (int, float)) else None
                pct8_f = float(pct8) if isinstance(pct8, (int, float)) else None
                pct5_f = float(pct5) if isinstance(pct5, (int, float)) else None

                owner = r.get("owner1") or ""
                otype = _classify(owner)

                in_oz = False
                if valid[i] and opp_polys:
                    in_oz = _in_any_opp_zone(lats_arr[i], lngs_arr[i], opp_polys)

                # Score
                score = 0.0
                if acres_f is not None:
                    score += _score_substation(sub_kv_mi[i], sub_kv_atv[i] if not math.isnan(sub_kv_atv[i]) else None)
                    score += _score_acreage(acres_f)
                    score += _score_slope(pct5_f)
                    score += _score_proximity(wwtp_mi[i], 10, 10)
                    score += _score_proximity(line_mi[i], 2, 10)
                    score += _score_proximity(plant_mi[i], 15, 10)
                    if in_oz:
                        score += 8
                    score += _score_acreage_bonus(acres_f)
                score = max(0, min(100, score))

                fails = _hard_filter_failures(acres_f, otype, slope_mean_f, pct8_f,
                                              sub_kv_mi[i], sub_kv_atv[i])
                passed = not fails
                if passed:
                    n_passed += 1

                writer.writerow({
                    "county": r.get("county") or "",
                    "parcel_id": r.get("parcel_id") or "",
                    "jurisdiction": r.get("jurisdiction") or "",
                    "site": r.get("site_addr1") or "",
                    "owner": owner,
                    "owner2": r.get("owner2") or "",
                    "owner_type": otype,
                    "mail_addr1": r.get("mail_addr1") or "",
                    "mail_addr2": r.get("mail_addr2") or "",
                    "zoning": str(r.get("zoning") or ""),
                    "subd_name": r.get("subd_name") or "",
                    "year_built": r.get("year_built") or "",
                    "assessed_total": r.get("assessed_total") or "",
                    "assessed_land": r.get("assessed_land") or "",
                    "assessed_bldg": r.get("assessed_bldg") or "",
                    "last_sale_date": r.get("last_sale_date") or "",
                    "last_sale_price": r.get("last_sale_price") or "",
                    "acres": acres_f if acres_f is not None else "",
                    "lat": lats_arr[i] if valid[i] else "",
                    "lng": lngs_arr[i] if valid[i] else "",
                    "slope_mean_pct": slope_mean if slope_mean is not None else "",
                    "slope_max_pct": slope_max if slope_max is not None else "",
                    "pct_under_5pct_slope": pct5 if pct5 is not None else "",
                    "pct_under_10pct_slope": pct8 if pct8 is not None else "",
                    "pct_under_15pct_slope": pct15 if pct15 is not None else "",
                    "miles_to_sub_min_volt": round(float(sub_kv_mi[i]), 2) if not math.isnan(sub_kv_mi[i]) else "",
                    "min_volt_at_nearest_sub_kv": int(sub_kv_atv[i]) if not math.isnan(sub_kv_atv[i]) and sub_kv_atv[i] > 0 else "",
                    "miles_to_any_sub": round(float(sub_mi[i]), 2) if not math.isnan(sub_mi[i]) else "",
                    "any_sub_voltage_kv": int(sub_kv[i]) if not math.isnan(sub_kv[i]) and sub_kv[i] > 0 else "",
                    "miles_to_wwtp": round(float(wwtp_mi[i]), 2) if not math.isnan(wwtp_mi[i]) else "",
                    "miles_to_transmission_line": round(float(line_mi[i]), 2) if not math.isnan(line_mi[i]) else "",
                    "miles_to_power_plant": round(float(plant_mi[i]), 2) if not math.isnan(plant_mi[i]) else "",
                    "in_opportunity_zone": "Y" if in_oz else "N",
                    "score_dc": round(score, 1),
                    "passed_hard_filters": "Y" if passed else "N",
                    "failed_reasons": ";".join(fails),
                })

            print(f"  OK {county:14s} {len(rows):>6} parcels in {time.time()-t_county:.1f}s "
                  f"(running total {n_total:,})")

    print(f"\n  Total rows:     {n_total:,}")
    print(f"  Passed filter:  {n_passed:,}")
    print(f"  Output:         {out_path}")
    print(f"  Duration:       {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
