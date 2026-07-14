"""V3 of the bulk DC parcel enrichment — drives off config/dc_scoring.yaml.

Adds, on top of v2:
  - Highway proximity (fiber-corridor proxy) scoring
  - Setback compliance scoring (residential distance gradient)
  - Queue tier scoring (utility lookup)
  - Existing data center cluster bonus
  - County tax-incentive bonus
  - Bad-acreage filter (drops corrupt source rows)
  - Drops the unused power_plant_proximity / transmission_line_proximity
    weights from the scoring (still computed for output, just zeroed)

All weights live in config/dc_scoring.yaml — change weights without
touching code. New presets: piedmont, appalachian, hyperscale.

Outputs:
  outputs/all_parcels_dc_metrics_<preset>_v3.csv
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
import yaml
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


# ---------- owner classifier (lifted from helpers) ----------

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


# ---------- FEMA flood polygons ----------

def _build_flood_index(path: Path):
    if not path.exists():
        return None, None
    print(f"  building flood STRtree from {path.name}...")
    polys: list[Polygon] = []
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
    print(f"    loaded {len(polys):,} flood polygons")
    if not polys:
        return None, None
    return STRtree(polys), polys


def _point_in_floodplain(tree: STRtree, polys: list[Polygon],
                         lat: float, lng: float) -> bool:
    pt = Point(lng, lat)
    for idx in tree.query(pt):
        if polys[int(idx)].contains(pt):
            return True
    return False


# ---------- residential parcel index ----------

def _gather_residential_parcels(root: Path) -> np.ndarray:
    pts: list[tuple[float, float]] = []
    for county in COUNTIES:
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
                has_bldg = (
                    (isinstance(bldg, (int, float)) and bldg > 0)
                    or (isinstance(yb, (int, float)) and yb > 1800)
                )
                if not has_bldg:
                    continue
                a = float(acres) if isinstance(acres, (int, float)) else None
                if a is not None and a > 5:
                    continue
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

def _voltage_factor(kv, voltage_table: dict) -> float:
    if kv is None or (isinstance(kv, float) and math.isnan(kv)):
        return float(voltage_table.get("default", 0.4))
    for thr in (500, 230, 138, 115):
        if kv >= thr and thr in voltage_table:
            return float(voltage_table[thr])
    return float(voltage_table.get("default", 0.4))


def _score_substation(miles, kv, weight, max_mi, voltage_table) -> float:
    if math.isnan(miles):
        return 0.0
    base = max(0.0, 1.0 - miles / max_mi)
    return base * _voltage_factor(kv, voltage_table) * weight


def _score_capacity_proxy(cap: float, weight: float) -> float:
    """Bands: 0..200=quartile bottom, 200..500=median, 500..1000=high, >1000=hyper."""
    if not cap or math.isnan(cap):
        return 0.0
    if cap >= 1000: return weight
    if cap >= 500:  return weight * 0.75
    if cap >= 300:  return weight * 0.5
    if cap >= 150:  return weight * 0.25
    return 0.0


def _score_queue_penalty(queue_mw: float, weight: float) -> float:
    """Inverse score: a quiet substation gets full weight; heavily-queued sub gets 0.
    Empirical PJM thresholds: <1GW = light, 1-3GW = moderate, >3GW = saturated."""
    if queue_mw is None or queue_mw <= 0:
        return weight   # unknown => give benefit of doubt
    if queue_mw >= 3000: return 0.0
    if queue_mw >= 1000: return weight * 0.4
    if queue_mw >= 250:  return weight * 0.7
    return weight


def _score_water_proximity(total_mgd_5mi: float, weight: float) -> float:
    """Cumulative permitted MGD within 5mi indicates basin can support large draws."""
    if not total_mgd_5mi:
        return 0.0
    if total_mgd_5mi >= 10: return weight
    if total_mgd_5mi >= 3:  return weight * 0.7
    if total_mgd_5mi >= 1:  return weight * 0.4
    return weight * 0.1


def _score_wastewater_residual(residual_mgd: float, weight: float) -> float:
    """Nearest WWTP residual headroom (permitted - avg discharge)."""
    if not residual_mgd or residual_mgd <= 0:
        return 0.0
    if residual_mgd >= 5: return weight
    if residual_mgd >= 1: return weight * 0.6
    return weight * 0.3


def _score_fiber_carriers(carrier_count: int, weight: float) -> float:
    if not carrier_count:
        return 0.0
    if carrier_count >= 3: return weight
    if carrier_count == 2: return weight * 0.7
    return weight * 0.4


def _score_acreage(acres: float, weight: float, min_ac: float, max_ac: float) -> float:
    if acres is None or acres < min_ac:
        return 0.0
    if acres >= max_ac:
        return weight
    return weight * (acres - min_ac) / (max_ac - min_ac)


def _score_pct_metric(value, weight: float) -> float:
    if value is None:
        return 0.0
    return weight * float(value) / 100.0


def _score_proximity(miles, full_mi: float, zero_mi: float, weight: float) -> float:
    if math.isnan(miles):
        return 0.0
    if miles <= full_mi:
        return weight
    if miles >= zero_mi:
        return 0.0
    return weight * (zero_mi - miles) / (zero_mi - full_mi)


def _score_setback(res_mi, weight: float, min_ft: float, full_ft: float) -> float:
    """0 below min_ft, full credit above full_ft, gradient between."""
    if math.isnan(res_mi):
        return 0.0
    res_ft = res_mi * 5280
    if res_ft < min_ft:
        return 0.0
    if res_ft >= full_ft:
        return weight
    return weight * (res_ft - min_ft) / (full_ft - min_ft)


def _score_queue_tier(tier: str, points_table: dict) -> float:
    return float(points_table.get(tier, 0))


def _hard_filter_failures(preset: dict, acres, owner_type, slope_mean,
                          pct_under_8, sub_kv_mi, in_flood: bool, res_mi):
    h = preset["hard"]
    fails: list[str] = []
    if acres is None or acres < h["min_acres"]:
        fails.append(f"acres<{h['min_acres']}")
    if h.get("max_acres") and acres is not None and acres > h["max_acres"]:
        fails.append(f"acres>{h['max_acres']}_corrupt")
    if owner_type in h.get("forbid_owner_types", []):
        fails.append(f"owner_{owner_type}")
    if slope_mean is not None and slope_mean > h["max_slope_pct"]:
        fails.append(f"slope>{h['max_slope_pct']}%")
    if pct_under_8 is not None and pct_under_8 < h["min_pct_under_8"]:
        fails.append(f"buildable<{h['min_pct_under_8']}%")
    if math.isnan(sub_kv_mi) or sub_kv_mi > h["max_dist_substation_mi"]:
        fails.append(f"sub>{h['max_dist_substation_mi']}mi")
    if h.get("forbid_floodplain") and in_flood:
        fails.append("in_floodplain")
    if h.get("min_dist_residential_mi") is not None and not math.isnan(res_mi):
        if res_mi < h["min_dist_residential_mi"]:
            fails.append(f"res<{h['min_dist_residential_mi']}mi")
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
    "nearest_sub_lines", "nearest_sub_capacity_proxy",
    "nearest_sub_pjm_queue_mw", "regional_supply_pressure",
    "water_mgd_within_5mi", "wwtp_permitted_mgd", "wwtp_residual_mgd",
    "fiber_carrier_count",
    "miles_to_wwtp", "miles_to_nearest_residential",
    "miles_to_major_highway", "miles_to_existing_dc",
    "in_opportunity_zone", "in_floodplain",
    "primary_utility", "queue_tier",
    "tax_tier_score",
    "score_dc",
    "passed_hard_filters", "failed_reasons", "preset",
]


def main() -> int:
    root = Path(__file__).parent.parent
    out_dir = root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load YAML config
    cfg = yaml.safe_load((root / "config" / "dc_scoring.yaml").read_text(encoding="utf-8"))
    presets = cfg["presets"]
    voltage_table = cfg["voltage_factor"]
    queue_points = cfg["queue_tier_points"]

    # Load utility + tax tables
    util_lookup = json.loads((root / "data" / "va_utility_by_county.json").read_text(encoding="utf-8"))
    tax_lookup = json.loads((root / "data" / "va_dc_tax_rates.json").read_text(encoding="utf-8"))

    print("Loading infra layers...")
    subs_pts, subs_extra = _load_points(root / "data" / "va_substations.jsonl")
    # HIFLD encodes "unknown" as -999999 — coerce those to 0 so they don't break math.
    _kv_raw = np.array([float(e.get("max_volt_kv") or 0) for e in subs_extra])
    _ln_raw = np.array([float(e.get("lines") or 0) for e in subs_extra])
    subs_kv = np.where(_kv_raw == -999999, 0.0, _kv_raw)
    subs_lines = np.where(_ln_raw == -999999, 0.0, _ln_raw)
    # Capacity proxy: voltage * sqrt(line count). Discriminates between
    # a 1-line 115kV sub (115) and a 6-line 230kV sub (~564). Treats unknown
    # line count (0) as if there's at least 1 line so we don't zero-out kv-only rows.
    subs_cap_proxy = subs_kv * np.sqrt(np.maximum(subs_lines, 1.0))
    wwtp_pts, _ = _load_points(root / "data" / "va_wastewater_treatment.jsonl")
    hwy_pts = _load_polyline_vertices(root / "data" / "va_fiber_proxy.jsonl")
    dc_pts, _ = _load_points(root / "data" / "va_existing_dc.jsonl")
    opp_polys = _load_opp_zone_polys(root / "data" / "va_opportunity_zones.jsonl")
    print(f"  subs: {len(subs_pts)}, wwtp: {len(wwtp_pts)}, "
          f"hwy_verts: {len(hwy_pts)}, existing_DCs: {len(dc_pts)}, "
          f"opp_zones: {len(opp_polys)}")

    flood_tree, flood_polys = _build_flood_index(root / "data" / "va_flood_zones.jsonl")
    res_pts = _gather_residential_parcels(root)

    # Tier-13 capacity sources (degrade gracefully if JSONLs are empty/missing)
    print("Loading Tier-13 capacity sources...")
    import sys as _sys
    _sys.path.insert(0, str(root / "src"))
    from mls_bot.analytics.dc_capacity import (
        load_pjm_queue_by_sub, regional_supply_pressure, supply_pressure_points,
        load_water_points, load_vpdes_points, load_fiber_points, canon_sub_name,
    )
    pjm_by_sub = load_pjm_queue_by_sub()
    water_xy, water_mgd = load_water_points()
    vpdes_xy, vpdes_perm, vpdes_resid = load_vpdes_points()
    fiber_xy, fiber_provs = load_fiber_points()
    print(f"  pjm_queue subs: {len(pjm_by_sub)}, water_pts: {len(water_xy)}, "
          f"vpdes_pts: {len(vpdes_xy)}, fiber_pts: {len(fiber_xy)}")

    tree_water = _build_tree(water_xy) if len(water_xy) else None
    tree_vpdes = _build_tree(vpdes_xy) if len(vpdes_xy) else None
    tree_fiber = _build_tree(fiber_xy) if len(fiber_xy) else None

    tree_subs_all = _build_tree(subs_pts)
    subs_115 = subs_pts[subs_kv >= 115]
    subs_kv_115 = subs_kv[subs_kv >= 115]
    tree_subs_115 = _build_tree(subs_115)
    tree_wwtp = _build_tree(wwtp_pts)
    tree_hwy = _build_tree(hwy_pts)
    tree_dc = _build_tree(dc_pts)
    tree_res = _build_tree(res_pts)

    # Open one CSV per preset
    out_files: dict[str, csv.DictWriter] = {}
    file_handles: dict[str, object] = {}
    for preset_name in presets:
        path = out_dir / f"all_parcels_dc_metrics_{preset_name}_v3.csv"
        f = path.open("w", encoding="utf-8", newline="")
        file_handles[preset_name] = f
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        out_files[preset_name] = w

    t0 = time.time()
    n_total = 0
    n_passed = {p: 0 for p in presets}
    seen: set[tuple] = set()

    for county in COUNTIES:
        in_path = root / f"data/{county}_county_parcels_slope.jsonl"
        if not in_path.exists():
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
            continue

        lats_arr = np.array(lats, dtype=np.float64)
        lngs_arr = np.array(lngs, dtype=np.float64)
        valid = ~(np.isnan(lats_arr) | np.isnan(lngs_arr))

        # Vectorized distances
        sub_mi = np.full(len(rows), np.nan)
        sub_kv = np.full(len(rows), np.nan)
        sub_kv_mi = np.full(len(rows), np.nan)
        sub_kv_atv = np.full(len(rows), np.nan)
        sub_lines_at = np.full(len(rows), np.nan)
        sub_cap_proxy = np.full(len(rows), np.nan)
        nearest_sub_name = ["" for _ in range(len(rows))]
        water_mgd_5mi = np.zeros(len(rows))
        wwtp_residual = np.full(len(rows), np.nan)
        wwtp_permitted = np.full(len(rows), np.nan)
        fiber_count = np.zeros(len(rows), dtype=int)
        wwtp_mi = np.full(len(rows), np.nan)
        hwy_mi = np.full(len(rows), np.nan)
        dc_mi = np.full(len(rows), np.nan)
        res_mi = np.full(len(rows), np.nan)

        if valid.any():
            vlat = lats_arr[valid]; vlng = lngs_arr[valid]
            if tree_subs_all is not None:
                d, idx = _nearest_miles(tree_subs_all, vlat, vlng)
                sub_mi[valid] = d
                sub_kv[valid] = subs_kv[idx]
                sub_lines_at[valid] = subs_lines[idx]
                sub_cap_proxy[valid] = subs_cap_proxy[idx]
                # Capture nearest substation name for PJM-queue cross-reference
                v_idx_iter = iter(np.where(valid)[0])
                for sub_i in idx:
                    row_i = next(v_idx_iter)
                    nearest_sub_name[row_i] = canon_sub_name(subs_extra[int(sub_i)].get("name"))
            # Water withdrawals: cumulative permitted MGD within 5 mi
            if tree_water is not None and len(water_xy):
                # haversine query_radius returns indices within radius (radians)
                EARTH_R = 3958.7613
                radius_rad = 5.0 / EARTH_R
                neigh = tree_water.query_radius(np.radians(np.column_stack([vlat, vlng])), r=radius_rad)
                row_iter = iter(np.where(valid)[0])
                for nbrs in neigh:
                    row_i = next(row_iter)
                    if len(nbrs):
                        water_mgd_5mi[row_i] = float(water_mgd[nbrs].sum())
            # VPDES nearest WWTP
            if tree_vpdes is not None and len(vpdes_xy):
                d, idx = _nearest_miles(tree_vpdes, vlat, vlng)
                row_iter = iter(np.where(valid)[0])
                for sub_i, dist in zip(idx, d):
                    row_i = next(row_iter)
                    wwtp_permitted[row_i] = float(vpdes_perm[int(sub_i)])
                    wwtp_residual[row_i] = float(vpdes_resid[int(sub_i)])
            # Fiber: distinct provider count within 1 mi
            if tree_fiber is not None and len(fiber_xy):
                EARTH_R = 3958.7613
                radius_rad = 1.0 / EARTH_R
                neigh = tree_fiber.query_radius(np.radians(np.column_stack([vlat, vlng])), r=radius_rad)
                row_iter = iter(np.where(valid)[0])
                for nbrs in neigh:
                    row_i = next(row_iter)
                    if len(nbrs):
                        fiber_count[row_i] = len({fiber_provs[i] for i in nbrs})
            if tree_subs_115 is not None:
                d, idx = _nearest_miles(tree_subs_115, vlat, vlng)
                sub_kv_mi[valid] = d
                sub_kv_atv[valid] = subs_kv_115[idx]
            if tree_wwtp is not None:
                d, _ = _nearest_miles(tree_wwtp, vlat, vlng); wwtp_mi[valid] = d
            if tree_hwy is not None:
                d, _ = _nearest_miles(tree_hwy, vlat, vlng); hwy_mi[valid] = d
            if tree_dc is not None:
                d, _ = _nearest_miles(tree_dc, vlat, vlng); dc_mi[valid] = d
            if tree_res is not None:
                d, _ = _nearest_miles(tree_res, vlat, vlng); res_mi[valid] = d

        for i, r in enumerate(rows):
            n_total += 1
            acres_raw = r.get("acres")
            acres_f = float(acres_raw) if isinstance(acres_raw, (int, float)) else None
            slope_mean = r.get("slope_mean_pct")
            pct8 = r.get("pct_under_10pct_slope")  # closest to <=8% threshold
            slope_mean_f = float(slope_mean) if isinstance(slope_mean, (int, float)) else None
            pct8_f = float(pct8) if isinstance(pct8, (int, float)) else None

            owner = r.get("owner1") or ""
            otype = _classify(owner)
            in_oz = False
            in_flood = False
            if valid[i]:
                lat_v, lng_v = float(lats_arr[i]), float(lngs_arr[i])
                if opp_polys:
                    in_oz = _in_any_opp_zone(lat_v, lng_v, opp_polys)
                if flood_tree is not None:
                    in_flood = _point_in_floodplain(flood_tree, flood_polys, lat_v, lng_v)

            county_u = (r.get("county") or "").upper()
            zoning = "" if county_u in UNRELIABLE_ZONING_COUNTIES else \
                     str(r.get("zoning") or "").strip()

            util = util_lookup.get(county_u, {})
            tax = tax_lookup.get(county_u, {})
            queue_tier = util.get("queue_tier", "")
            primary_utility = util.get("primary", "")

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
                "slope_max_pct": r.get("slope_max_pct") or "",
                "pct_under_5pct_slope": r.get("pct_under_5pct_slope") or "",
                "pct_under_10pct_slope": pct8 if pct8 is not None else "",
                "pct_under_15pct_slope": r.get("pct_under_15pct_slope") or "",
                "miles_to_sub_min_volt":
                    round(float(sub_kv_mi[i]), 2) if not math.isnan(sub_kv_mi[i]) else "",
                "min_volt_at_nearest_sub_kv":
                    int(sub_kv_atv[i]) if not math.isnan(sub_kv_atv[i]) and sub_kv_atv[i] > 0 else "",
                "miles_to_any_sub":
                    round(float(sub_mi[i]), 2) if not math.isnan(sub_mi[i]) else "",
                "any_sub_voltage_kv":
                    int(sub_kv[i]) if not math.isnan(sub_kv[i]) and sub_kv[i] > 0 else "",
                "nearest_sub_lines":
                    int(sub_lines_at[i]) if not math.isnan(sub_lines_at[i]) and sub_lines_at[i] > 0 else "",
                "nearest_sub_capacity_proxy":
                    round(float(sub_cap_proxy[i]), 0) if not math.isnan(sub_cap_proxy[i]) and sub_cap_proxy[i] > 0 else "",
                "nearest_sub_pjm_queue_mw":
                    round((pjm_by_sub.get(nearest_sub_name[i]) or {}).get("queue_mw", 0.0), 1)
                    if nearest_sub_name[i] else "",
                "regional_supply_pressure":
                    regional_supply_pressure(r.get("county") or "") if valid[i] else "",
                "water_mgd_within_5mi":
                    round(float(water_mgd_5mi[i]), 2) if water_mgd_5mi[i] > 0 else "",
                "wwtp_permitted_mgd":
                    round(float(wwtp_permitted[i]), 2) if not math.isnan(wwtp_permitted[i]) and wwtp_permitted[i] > 0 else "",
                "wwtp_residual_mgd":
                    round(float(wwtp_residual[i]), 2) if not math.isnan(wwtp_residual[i]) else "",
                "fiber_carrier_count":
                    int(fiber_count[i]) if fiber_count[i] > 0 else "",
                "miles_to_wwtp":
                    round(float(wwtp_mi[i]), 2) if not math.isnan(wwtp_mi[i]) else "",
                "miles_to_nearest_residential":
                    round(float(res_mi[i]), 2) if not math.isnan(res_mi[i]) else "",
                "miles_to_major_highway":
                    round(float(hwy_mi[i]), 2) if not math.isnan(hwy_mi[i]) else "",
                "miles_to_existing_dc":
                    round(float(dc_mi[i]), 2) if not math.isnan(dc_mi[i]) else "",
                "in_opportunity_zone": "Y" if in_oz else "N",
                "in_floodplain": "Y" if in_flood else "N",
                "primary_utility": primary_utility,
                "queue_tier": queue_tier,
                "tax_tier_score": tax.get("tier_score", 0),
            }

            for preset_name, preset in presets.items():
                soft = preset["soft"]

                score = 0.0
                # Substation × voltage
                if soft.get("substation_voltage_distance"):
                    score += _score_substation(
                        sub_kv_mi[i],
                        sub_kv_atv[i] if not math.isnan(sub_kv_atv[i]) else None,
                        soft["substation_voltage_distance"],
                        preset["hard"]["max_dist_substation_mi"],
                        voltage_table,
                    )
                # Acreage
                if acres_f is not None:
                    score += _score_acreage(
                        acres_f, soft.get("acreage", 0),
                        cfg["acreage_min"], cfg["acreage_max_for_full_score"],
                    )
                    if soft.get("hyperscale_acreage_bonus", 0) and acres_f >= 250:
                        score += soft["hyperscale_acreage_bonus"]
                # Slope under 8%
                score += _score_pct_metric(pct8_f, soft.get("slope_pct_under_8", 0))
                # Highway proximity
                score += _score_proximity(
                    hwy_mi[i], cfg["highway_full_credit_mi"],
                    cfg["highway_zero_credit_mi"], soft.get("highway_proximity", 0),
                )
                # Setback compliance
                score += _score_setback(
                    res_mi[i], soft.get("setback_compliance", 0),
                    cfg["setback_min_ft"], cfg["setback_full_credit_ft"],
                )
                # Queue tier
                score += min(
                    _score_queue_tier(queue_tier, queue_points),
                    soft.get("queue_tier", 0),
                )
                # OZ
                if in_oz and soft.get("opportunity_zone", 0):
                    score += soft["opportunity_zone"]
                # Wastewater (de-emphasized)
                score += _score_proximity(
                    wwtp_mi[i], cfg["wastewater_full_credit_mi"],
                    cfg["wastewater_zero_credit_mi"], soft.get("wastewater_proximity", 0),
                )
                # Existing DC cluster
                score += _score_proximity(
                    dc_mi[i], cfg["existing_dc_full_credit_mi"],
                    cfg["existing_dc_zero_credit_mi"], soft.get("existing_dc_cluster", 0),
                )
                # Tax incentive
                tax_score = tax.get("tier_score", 0)
                if soft.get("tax_incentive", 0):
                    score += min(tax_score, soft["tax_incentive"])

                # ---------- Tier-13 capacity signals ----------
                if soft.get("substation_capacity_proxy"):
                    score += _score_capacity_proxy(
                        sub_cap_proxy[i] if not math.isnan(sub_cap_proxy[i]) else 0,
                        soft["substation_capacity_proxy"],
                    )
                if soft.get("pjm_queue_density"):
                    queue_mw = (pjm_by_sub.get(nearest_sub_name[i]) or {}).get("queue_mw", 0.0)
                    score += _score_queue_penalty(queue_mw, soft["pjm_queue_density"])
                if soft.get("regional_supply_pressure"):
                    label = regional_supply_pressure(r.get("county") or "")
                    score += supply_pressure_points(label, soft["regional_supply_pressure"])
                if soft.get("water_withdrawal_proximity"):
                    score += _score_water_proximity(
                        float(water_mgd_5mi[i]), soft["water_withdrawal_proximity"]
                    )
                if soft.get("wastewater_residual_mgd"):
                    score += _score_wastewater_residual(
                        float(wwtp_residual[i]) if not math.isnan(wwtp_residual[i]) else 0,
                        soft["wastewater_residual_mgd"],
                    )
                if soft.get("fiber_carrier_count"):
                    score += _score_fiber_carriers(
                        int(fiber_count[i]), soft["fiber_carrier_count"]
                    )

                score = max(0, min(100, score))
                fails = _hard_filter_failures(
                    preset, acres_f, otype, slope_mean_f, pct8_f,
                    sub_kv_mi[i], in_flood, res_mi[i],
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
    for p in presets:
        print(f"  {p:14s} passed: {n_passed[p]:,}")
    print(f"  Outputs:")
    for p in presets:
        print(f"    outputs/all_parcels_dc_metrics_{p}_v3.csv")
    print(f"  Duration: {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
