"""V2 of the bulk DC parcel enrichment.

Adds, on top of v1:
  - Dedupe on (county, parcel_id)
  - FEMA SFHA flood-zone hard filter (and `in_floodplain` field)
  - "miles_to_nearest_residential" — distance from each parcel to the
    nearest small built-on parcel (proxy for VA setback compliance)
  - Two scoring presets: piedmont (strict) and appalachian (relaxed slope,
    favors larger parcels that can absorb internal grading)
  - Zoning sanity (mask out values from counties with bad source mapping)

Outputs:
  outputs/all_parcels_dc_metrics_piedmont.csv
  outputs/all_parcels_dc_metrics_appalachian.csv

Same row-per-parcel structure as v1 plus the new fields, plus per-preset
score and pass/fail flags.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree
from sklearn.neighbors import BallTree

EARTH_R_MI = 3958.7613


COUNTIES = [
    "montgomery", "roanoke", "franklin", "floyd", "giles", "carroll",
    "washington", "bland", "lee", "wise", "wythe", "patrick",
    "tazewell", "pulaski", "henry", "craig", "smyth", "buchanan",
    "halifax", "mecklenburg", "brunswick", "lunenburg", "charlotte",
    "pittsylvania",
]

UNRELIABLE_ZONING_COUNTIES = {
    "PATRICK", "WISE", "FLOYD", "WYTHE", "CHARLOTTE", "BRUNSWICK",
}


# ---------- regex owner classifier (lifted to avoid circular import) ----------

_ENTITY = re.compile(r"\b(LLC|L\.L\.C\.|INC|INCORPORATED|CORP|CORPORATION|"
                     r"COMPANY|CO\b|LP\b|LIMITED|LTD|PARTNERS|TRUST|TRUSTEE|"
                     r"PROPERTIES|HOLDINGS|GROUP|REALTY|ASSOCIATES|ENTERPRISES|"
                     r"INVESTMENTS|VENTURES|CAPITAL|EQUITY|HOMES|BUILDERS|"
                     r"TIMBER|LUMBER|FARMS|RANCH)\b", re.I)
_GOVT = re.compile(r"\b(USA|UNITED STATES|COMMONWEALTH OF VIRGINIA|VDOT|VPI|"
                   r"VIRGINIA TECH|TOWN OF|CITY OF|COUNTY OF|COUNTY \w+|BOARD OF "
                   r"SUPERVISORS|CHURCH|CEMETERY|SCHOOL BOARD|HOA|HOMEOWNERS "
                   r"ASSOC|FIRE DEPT|FELLOWSHIP|HABITAT FOR|FRATERNITY|"
                   r"SORORITY|HILLEL|ALUMNI ASSOC|PARK AUTHORITY|UTILITY|"
                   r"AUTHORITY|FOUNDATION|MINISTRY|PRESBYTERY|DIOCESE|MASONIC)"
                   r"\b", re.I)


def _classify(owner) -> str:
    if not owner:
        return "unknown"
    s = str(owner).upper()
    if _GOVT.search(s):
        return "govt_or_institution"
    if _ENTITY.search(s):
        return "entity"
    return "person"


# ---------- io helpers ----------

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
    return BallTree(np.radians(pts), metric="haversine")


def _nearest_miles(tree, lats, lngs):
    if tree is None or len(lats) == 0:
        return np.full(len(lats), np.nan), np.full(len(lats), -1, dtype=int)
    pts = np.radians(np.column_stack([lats, lngs]))
    dists, idx = tree.query(pts, k=1)
    return dists[:, 0] * EARTH_R_MI, idx[:, 0]


# ---------- FEMA flood polygons via shapely STRtree ----------

def _build_flood_index(path: Path):
    if not path.exists():
        return None, None
    print(f"  building flood STRtree from {path.name}...")
    polys: list[Polygon] = []
    bounds: list[tuple[float, float, float, float]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            rings = r.get("rings") or []
            if not rings:
                continue
            try:
                outer = [(float(p[0]), float(p[1])) for p in rings[0]
                         if isinstance(p, (list, tuple)) and len(p) >= 2]
                if len(outer) < 3:
                    continue
                holes = []
                for ring in rings[1:]:
                    h = [(float(p[0]), float(p[1])) for p in ring
                         if isinstance(p, (list, tuple)) and len(p) >= 2]
                    if len(h) >= 3:
                        holes.append(h)
                poly = Polygon(outer, holes=holes if holes else None)
            except Exception:
                continue
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            polys.append(poly)
            bounds.append(poly.bounds)
    print(f"    loaded {len(polys):,} flood polygons")
    if not polys:
        return None, None
    tree = STRtree(polys)
    return tree, polys


def _point_in_floodplain(tree: STRtree, polys: list[Polygon],
                        lat: float, lng: float) -> bool:
    pt = Point(lng, lat)
    candidates = tree.query(pt)  # numpy array of polygon indices
    for idx in candidates:
        if polys[int(idx)].contains(pt):
            return True
    return False


# ---------- residential parcel index ----------

def _gather_residential_parcels(root: Path, county_files: list[str]):
    """Find all parcels that look like residential (small + built-on) so we can
    measure setback distance. Returns a (lat, lng) numpy array."""
    pts: list[tuple[float, float]] = []
    for county in county_files:
        p = root / f"data/{county}_county_parcels_slope.jsonl"
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                acres = r.get("acres")
                bldg = r.get("assessed_bldg")
                yb = r.get("year_built")
                # Residential proxy: built-on AND small lot
                has_bldg = (
                    (isinstance(bldg, (int, float)) and bldg > 0)
                    or (isinstance(yb, (int, float)) and yb > 1800)
                )
                if not has_bldg:
                    continue
                a = float(acres) if isinstance(acres, (int, float)) else None
                if a is not None and a > 5:
                    continue  # too large to be a typical residential lot
                lat, lng = r.get("lat"), r.get("lng")
                if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                    pts.append((float(lat), float(lng)))
    print(f"  identified {len(pts):,} residential-proxy parcels")
    return np.array(pts, dtype=np.float64) if pts else np.zeros((0, 2))


# ---------- opportunity zones ----------

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
                xs = [pt[0] for pt in polygon[0]]
                ys = [pt[1] for pt in polygon[0]]
                polys.append(((min(xs), min(ys), max(xs), max(ys)), polygon))
    return polys


def _point_in_ring(lng: float, lat: float, ring) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        ):
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


# ---------- scoring ----------

def _score_substation(miles: float, kv) -> float:
    if math.isnan(miles):
        return 0
    base = max(0.0, 1.0 - miles / 5.0)
    volt_factor = 0.6
    if kv is not None and not (isinstance(kv, float) and math.isnan(kv)):
        if kv >= 500: volt_factor = 1.0
        elif kv >= 230: volt_factor = 0.95
        elif kv >= 115: volt_factor = 0.85
        elif kv >= 69:  volt_factor = 0.65
    return base * volt_factor * 20


def _score_acreage(acres: float, max_for_score: float = 250) -> float:
    if acres < 40:
        return 0
    if acres >= max_for_score:
        return 15
    return 15 * (acres / max_for_score)


def _score_slope(pct_under_5) -> float:
    if pct_under_5 is None:
        return 0
    return 15 * (pct_under_5 / 100)


def _score_proximity(miles: float, ideal_max_mi: float, weight: float) -> float:
    if math.isnan(miles):
        return 0
    return weight * max(0.0, 1.0 - miles / ideal_max_mi)


def _score_acreage_bonus(acres: float, big_bonus: bool = False) -> float:
    if big_bonus:
        # Appalachian preset: reward bigger parcels that can absorb grading
        if acres >= 500: return 12
        if acres >= 250: return 9
        if acres >= 150: return 6
        if acres >= 100: return 3
        return 0
    if acres >= 250: return 7
    if acres >= 150: return 5
    if acres >= 100: return 3
    return 0


PRESETS = {
    "piedmont": {
        "min_acres": 40, "max_slope": 8, "min_pct_under_8": 70,
        "max_dist_sub_mi": 5, "min_voltage_kv": 115, "big_acreage_bonus": False,
    },
    "appalachian": {
        "min_acres": 60, "max_slope": 15, "min_pct_under_8": 50,
        "max_dist_sub_mi": 5, "min_voltage_kv": 115, "big_acreage_bonus": True,
    },
}


def _hard_filter_failures(preset: dict, acres, owner_type, slope_mean, pct_under_8,
                          sub_kv_mi, in_flood: bool):
    fails: list[str] = []
    if acres is None or acres < preset["min_acres"]:
        fails.append(f"acres<{preset['min_acres']}")
    if owner_type == "govt_or_institution":
        fails.append("owner_govt")
    if slope_mean is not None and slope_mean > preset["max_slope"]:
        fails.append(f"slope>{preset['max_slope']}%")
    if pct_under_8 is not None and pct_under_8 < preset["min_pct_under_8"]:
        fails.append(f"buildable<{preset['min_pct_under_8']}%")
    if math.isnan(sub_kv_mi) or sub_kv_mi > preset["max_dist_sub_mi"]:
        fails.append(f"sub>{preset['max_dist_sub_mi']}mi")
    if in_flood:
        fails.append("in_floodplain")
    return fails


# ---------- output schema ----------

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
    "miles_to_nearest_residential",
    "in_opportunity_zone", "in_floodplain",
    "score_dc",
    "passed_hard_filters", "failed_reasons",
]


def main() -> int:
    root = Path(__file__).parent.parent
    out_dir = root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

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

    flood_tree, flood_polys = _build_flood_index(root / "data" / "va_flood_zones.jsonl")
    res_pts = _gather_residential_parcels(root, COUNTIES)

    tree_subs_all = _build_tree(subs_pts)
    subs_115 = subs_pts[subs_kv >= 115]
    subs_kv_115 = subs_kv[subs_kv >= 115]
    tree_subs_115 = _build_tree(subs_115)
    tree_wwtp = _build_tree(wwtp_pts)
    tree_plants = _build_tree(plant_pts)
    tree_lines = _build_tree(line_pts)
    tree_res = _build_tree(res_pts)

    out_files: dict[str, csv.DictWriter] = {}
    file_handles: dict[str, object] = {}
    for preset_name in PRESETS:
        path = out_dir / f"all_parcels_dc_metrics_{preset_name}.csv"
        f = path.open("w", encoding="utf-8", newline="")
        file_handles[preset_name] = f
        w = csv.DictWriter(f, fieldnames=COLUMNS + ["preset"])
        w.writeheader()
        out_files[preset_name] = w

    t0 = time.time()
    n_total = 0
    n_passed = {p: 0 for p in PRESETS}

    seen: set[tuple] = set()  # global dedupe

    for county in COUNTIES:
        in_path = root / f"data/{county}_county_parcels_slope.jsonl"
        if not in_path.exists():
            print(f"  -- {county}: missing slope file")
            continue
        t_county = time.time()

        rows: list[dict] = []
        lats: list[float] = []
        lngs: list[float] = []
        with in_path.open("r", encoding="utf-8") as fin:
            for line in fin:
                if not line.strip():
                    continue
                r = json.loads(line)
                sig = (r.get("county"), r.get("parcel_id"))
                if sig in seen:
                    continue
                seen.add(sig)
                rows.append(r)
                lats.append(r.get("lat") if isinstance(r.get("lat"), (int, float)) else float("nan"))
                lngs.append(r.get("lng") if isinstance(r.get("lng"), (int, float)) else float("nan"))

        if not rows:
            print(f"  -- {county}: empty after dedupe")
            continue

        lats_arr = np.array(lats, dtype=np.float64)
        lngs_arr = np.array(lngs, dtype=np.float64)
        valid = ~(np.isnan(lats_arr) | np.isnan(lngs_arr))

        sub_mi = np.full(len(rows), np.nan)
        sub_kv = np.full(len(rows), np.nan)
        sub_kv_mi = np.full(len(rows), np.nan)
        sub_kv_atv = np.full(len(rows), np.nan)
        wwtp_mi = np.full(len(rows), np.nan)
        line_mi = np.full(len(rows), np.nan)
        plant_mi = np.full(len(rows), np.nan)
        res_mi = np.full(len(rows), np.nan)

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
            if tree_res is not None:
                d, _ = _nearest_miles(tree_res, vlat, vlng)
                res_mi[valid] = d

        for i, r in enumerate(rows):
            n_total += 1
            acres_raw = r.get("acres")
            acres_f = float(acres_raw) if isinstance(acres_raw, (int, float)) else None
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
            in_flood = False
            if valid[i]:
                lat_v = float(lats_arr[i])
                lng_v = float(lngs_arr[i])
                if opp_polys:
                    in_oz = _in_any_opp_zone(lat_v, lng_v, opp_polys)
                if flood_tree is not None:
                    in_flood = _point_in_floodplain(flood_tree, flood_polys,
                                                    lat_v, lng_v)

            county_u = (r.get("county") or "").upper()
            zoning = "" if county_u in UNRELIABLE_ZONING_COUNTIES else \
                     str(r.get("zoning") or "").strip()

            base_score_components = (
                _score_substation(sub_kv_mi[i],
                                  sub_kv_atv[i] if not math.isnan(sub_kv_atv[i]) else None)
                + _score_slope(pct5_f)
                + _score_proximity(wwtp_mi[i], 10, 10)
                + _score_proximity(line_mi[i], 2, 10)
                + _score_proximity(plant_mi[i], 15, 10)
                + (8 if in_oz else 0)
            )
            if acres_f is not None:
                base_score_components += _score_acreage(acres_f)

            base_row = {
                "county": r.get("county") or "",
                "parcel_id": r.get("parcel_id") or "",
                "jurisdiction": r.get("jurisdiction") or "",
                "site": r.get("site_addr1") or "",
                "owner": owner,
                "owner2": r.get("owner2") or "",
                "owner_type": otype,
                "mail_addr1": r.get("mail_addr1") or "",
                "mail_addr2": r.get("mail_addr2") or "",
                "zoning": zoning,
                "subd_name": r.get("subd_name") or "",
                "year_built": r.get("year_built") or "",
                "assessed_total": r.get("assessed_total") or "",
                "assessed_land": r.get("assessed_land") or "",
                "assessed_bldg": r.get("assessed_bldg") or "",
                "last_sale_date": r.get("last_sale_date") or "",
                "last_sale_price": r.get("last_sale_price") or "",
                "acres": acres_f if acres_f is not None else "",
                "lat": float(lats_arr[i]) if valid[i] else "",
                "lng": float(lngs_arr[i]) if valid[i] else "",
                "slope_mean_pct": slope_mean if slope_mean is not None else "",
                "slope_max_pct": slope_max if slope_max is not None else "",
                "pct_under_5pct_slope": pct5 if pct5 is not None else "",
                "pct_under_10pct_slope": pct8 if pct8 is not None else "",
                "pct_under_15pct_slope": pct15 if pct15 is not None else "",
                "miles_to_sub_min_volt":
                    round(float(sub_kv_mi[i]), 2) if not math.isnan(sub_kv_mi[i]) else "",
                "min_volt_at_nearest_sub_kv":
                    int(sub_kv_atv[i]) if not math.isnan(sub_kv_atv[i]) and sub_kv_atv[i] > 0 else "",
                "miles_to_any_sub":
                    round(float(sub_mi[i]), 2) if not math.isnan(sub_mi[i]) else "",
                "any_sub_voltage_kv":
                    int(sub_kv[i]) if not math.isnan(sub_kv[i]) and sub_kv[i] > 0 else "",
                "miles_to_wwtp":
                    round(float(wwtp_mi[i]), 2) if not math.isnan(wwtp_mi[i]) else "",
                "miles_to_transmission_line":
                    round(float(line_mi[i]), 2) if not math.isnan(line_mi[i]) else "",
                "miles_to_power_plant":
                    round(float(plant_mi[i]), 2) if not math.isnan(plant_mi[i]) else "",
                "miles_to_nearest_residential":
                    round(float(res_mi[i]), 2) if not math.isnan(res_mi[i]) else "",
                "in_opportunity_zone": "Y" if in_oz else "N",
                "in_floodplain": "Y" if in_flood else "N",
            }

            for preset_name, preset in PRESETS.items():
                acreage_score = _score_acreage(acres_f) if acres_f is not None else 0
                acreage_bonus = _score_acreage_bonus(
                    acres_f or 0, big_bonus=preset["big_acreage_bonus"]
                )
                score = base_score_components + acreage_bonus
                # acreage already in base_score_components; bonus stacks on top
                score = max(0, min(100, score))

                fails = _hard_filter_failures(
                    preset, acres_f, otype, slope_mean_f, pct8_f,
                    sub_kv_mi[i], in_flood,
                )
                passed = not fails
                if passed:
                    n_passed[preset_name] += 1

                row_out = dict(base_row)
                row_out["score_dc"] = round(score, 1)
                row_out["passed_hard_filters"] = "Y" if passed else "N"
                row_out["failed_reasons"] = ";".join(fails)
                row_out["preset"] = preset_name
                out_files[preset_name].writerow(row_out)

        print(f"  OK {county:14s} {len(rows):>6} parcels in {time.time()-t_county:.1f}s "
              f"(running total {n_total:,})")

    for f in file_handles.values():
        f.close()

    print(f"\n  Total rows per preset: {n_total:,}")
    for p in PRESETS:
        print(f"  {p:14s} passed: {n_passed[p]:,}")
    print(f"  Outputs:")
    for p in PRESETS:
        print(f"    outputs/all_parcels_dc_metrics_{p}.csv")
    print(f"  Duration: {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
