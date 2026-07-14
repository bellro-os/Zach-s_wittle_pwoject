"""DC_SUITABILITY — score parcels for data-center development.

Filters and scoring follow the institutional spec we discussed:

  Hard filters (parcel must pass ALL):
    - acres >= min_acres                               (default 40)
    - slope_mean_pct <= max_slope_pct                  (default 8)  if slope known
    - pct_under_8pct_slope >= min_pct_buildable        (default 70) if slope known
    - miles_to_substation <= max_dist_substation_mi    (default 5)
    - max_volt at nearest substation >= min_voltage_kv (default 115)
    - owner_type != "govt_or_institution"
    - acres <= max_acres                               (optional cap)

  Soft scoring (weighted):
    - Substation proximity & voltage class             (20)
    - Buildable acreage                                (15)
    - Slope quality (pct_under_5pct_slope)             (15)
    - Wastewater proximity (cooling/discharge access)  (10)
    - Transmission line proximity                      (10)
    - Power plant proximity                            (10)
    - Opportunity zone bonus                           ( 8)
    - Acreage bonus (>100 ac for campus, >250 ac mega) ( 7)
    - Site clustering near existing data centers       ( 5)  — TODO
                                                       ----
                                                       100

The detector ranks survivors and outputs leads with rich detail for both
console display and CSV export.

Config knobs:
    jurisdiction          BLACKSBURG / county / ALL
    min_acres             40
    max_acres             None          (no upper bound)
    max_slope_pct         8
    min_pct_buildable     70            (uses pct_under_8pct_slope)
    max_dist_substation_mi 5
    min_voltage_kv        115
    require_slope_data    false         (when true, parcels lacking slope are dropped)
    substations_path      data/va_substations.jsonl
    wwtp_path             data/va_wastewater_treatment.jsonl
    transmission_path     data/va_transmission_lines.jsonl
    power_plants_path     data/va_power_plants.jsonl
    opp_zones_path        data/va_opportunity_zones.jsonl
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .base import Lead, register
from .geo import (
    haversine_miles,
    load_points,
    load_polylines,
    nearest_point_miles,
    nearest_polyline_miles,
)
from .helpers import classify_owner, filter_jurisdiction, parse_float


# Counties where the source layer's "zoning" field actually maps to a
# property-class / tax-district / land-use code rather than a true zoning
# code. Surfacing those values pollutes downstream filters (we saw Pittsylvania
# rows show "60" / "6" instead of "A-1"). Treat zoning as unknown for these.
_UNRELIABLE_ZONING_COUNTIES = {
    "PATRICK", "WISE", "FLOYD", "WYTHE", "CHARLOTTE", "BRUNSWICK",
}


def _safe_zoning(row: dict) -> str:
    county = (row.get("county") or "").upper()
    z = str(row.get("zoning") or "").strip()
    if not z or county in _UNRELIABLE_ZONING_COUNTIES:
        return ""
    return z


def _float_or_none(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --- Substations: keep voltage with each point so we can filter by voltage --

def _load_substations(path: str) -> list[tuple[float, float, float | None]]:
    out: list[tuple[float, float, float | None]] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            lat = _float_or_none(r.get("lat"))
            lng = _float_or_none(r.get("lng"))
            if lat is None or lng is None:
                continue
            v = _float_or_none(r.get("max_volt_kv"))
            out.append((lat, lng, v))
    return out


def _nearest_substation(
    lat: float, lng: float,
    subs: list[tuple[float, float, float | None]],
    min_voltage_kv: float | None = None,
) -> tuple[float | None, float | None]:
    """(miles, voltage_kv_at_nearest) — voltage None if unknown.

    If min_voltage_kv is set, only substations meeting that threshold are
    considered when picking 'nearest'."""
    if not subs:
        return None, None
    best_d = float("inf")
    best_v: float | None = None
    for plat, plng, vkv in subs:
        if min_voltage_kv is not None and (vkv is None or vkv < min_voltage_kv):
            continue
        d = haversine_miles(lat, lng, plat, plng)
        if d < best_d:
            best_d = d
            best_v = vkv
    if best_d == float("inf"):
        return None, None
    return best_d, best_v


# --- Opportunity zones: point-in-polygon -----------------------------------

def _load_opp_zone_polys(path: str) -> list[list[list[tuple[float, float]]]]:
    """Returns a list of OZ polygon-rings. Each polygon = list of rings;
    each ring = list of (lng, lat) tuples."""
    out: list[list[list[tuple[float, float]]]] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            rings_raw = r.get("rings") or []
            polygon: list[list[tuple[float, float]]] = []
            for ring in rings_raw:
                pts: list[tuple[float, float]] = []
                for pt in ring:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        try:
                            pts.append((float(pt[0]), float(pt[1])))
                        except (TypeError, ValueError):
                            continue
                if len(pts) >= 3:
                    polygon.append(pts)
            if polygon:
                out.append(polygon)
    return out


def _point_in_ring(lng: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    """Standard ray-casting; ring is (lng, lat) pairs."""
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


def _point_in_opp_zone(lat: float, lng: float,
                       polygons: list[list[list[tuple[float, float]]]]) -> bool:
    for polygon in polygons:
        if not polygon:
            continue
        # First ring is exterior; subsequent rings are holes.
        if _point_in_ring(lng, lat, polygon[0]):
            inside_hole = any(_point_in_ring(lng, lat, ring) for ring in polygon[1:])
            if not inside_hole:
                return True
    return False


# --- Scoring ---------------------------------------------------------------

def _score_substation(miles: float | None, kv: float | None) -> float:
    if miles is None:
        return 0
    base = max(0.0, 1.0 - miles / 5.0)  # full score at <=0 mi, zero at 5 mi
    volt_factor = 0.6
    if kv is not None:
        if kv >= 500: volt_factor = 1.0
        elif kv >= 230: volt_factor = 0.95
        elif kv >= 115: volt_factor = 0.85
        elif kv >= 69:  volt_factor = 0.65
    return base * volt_factor * 20


def _score_acreage(acres: float, max_for_score: float = 250) -> float:
    if acres < 40: return 0
    if acres >= max_for_score: return 15
    return 15 * (acres / max_for_score)


def _score_slope(pct_under_5: float | None) -> float:
    if pct_under_5 is None: return 0
    return 15 * (pct_under_5 / 100)


def _score_proximity(miles: float | None, ideal_max_mi: float, weight: float) -> float:
    if miles is None: return 0
    return weight * max(0.0, 1.0 - miles / ideal_max_mi)


def _score_acreage_bonus(acres: float) -> float:
    # Bonus on top of base acreage score for hyperscale-sized parcels
    if acres >= 250: return 7
    if acres >= 150: return 5
    if acres >= 100: return 3
    return 0


@register("DC_SUITABILITY")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    jurisdiction = config.get("jurisdiction", "ALL")
    min_acres = float(config.get("min_acres", 40))
    max_acres = _float_or_none(config.get("max_acres"))
    max_slope_pct = float(config.get("max_slope_pct", 8))
    min_pct_buildable = float(config.get("min_pct_buildable", 70))
    max_dist_substation_mi = float(config.get("max_dist_substation_mi", 5))
    min_voltage_kv = float(config.get("min_voltage_kv", 115))
    require_slope_data = str(config.get("require_slope_data", False)).lower() in ("true", "1", "yes")

    subs = _load_substations(str(config.get("substations_path", "data/va_substations.jsonl")))
    wwtp = load_points(str(config.get("wwtp_path", "data/va_wastewater_treatment.jsonl")))
    lines = load_polylines(str(config.get("transmission_path", "data/va_transmission_lines.jsonl")))
    plants = load_points(str(config.get("power_plants_path", "data/va_power_plants.jsonl")))
    opp_polys = _load_opp_zone_polys(str(config.get("opp_zones_path", "data/va_opportunity_zones.jsonl")))

    print(f"  loaded {len(subs)} subs, {len(wwtp)} wwtp, {len(lines)} lines, "
          f"{len(plants)} plants, {len(opp_polys)} opp_zones")

    rows = filter_jurisdiction(rows, jurisdiction)

    # Dedupe input rows on (county, parcel_id) — some county ingests double-counted
    # (Wythe + Brunswick especially). Without this, 9% of top candidates were dupes.
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in rows:
        sig = (r.get("county"), r.get("parcel_id"))
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(r)
    if len(deduped) != len(rows):
        print(f"  deduped {len(rows) - len(deduped):,} rows (kept {len(deduped):,})")
    rows = deduped

    leads: list[Lead] = []
    for r in rows:
        # --- Hard filters ---
        acres = parse_float(r.get("acres"))
        if acres is None or acres < min_acres:
            continue
        if max_acres is not None and acres > max_acres:
            continue

        otype = classify_owner(r.get("owner1"))
        if otype == "govt_or_institution":
            continue

        lat = _float_or_none(r.get("lat"))
        lng = _float_or_none(r.get("lng"))
        if lat is None or lng is None:
            continue

        slope_mean = _float_or_none(r.get("slope_mean_pct"))
        pct_under_8 = _float_or_none(r.get("pct_under_10pct_slope"))  # closest match to <=8%
        pct_under_5 = _float_or_none(r.get("pct_under_5pct_slope"))
        if require_slope_data and slope_mean is None:
            continue
        if slope_mean is not None and slope_mean > max_slope_pct:
            continue
        if pct_under_8 is not None and pct_under_8 < min_pct_buildable:
            continue

        sub_miles, sub_kv = _nearest_substation(lat, lng, subs, min_voltage_kv=None)
        sub_miles_ge_volt, sub_kv_ge_volt = _nearest_substation(lat, lng, subs, min_voltage_kv=min_voltage_kv)
        if sub_miles_ge_volt is None or sub_miles_ge_volt > max_dist_substation_mi:
            continue

        # --- Distances for scoring/display ---
        wwtp_mi = nearest_point_miles(lat, lng, wwtp) if wwtp else None
        line_mi = nearest_polyline_miles(lat, lng, lines) if lines else None
        plant_mi = nearest_point_miles(lat, lng, plants) if plants else None
        in_opp_zone = _point_in_opp_zone(lat, lng, opp_polys)

        # --- Score ---
        score = 0.0
        score += _score_substation(sub_miles_ge_volt, sub_kv_ge_volt)
        score += _score_acreage(acres)
        score += _score_slope(pct_under_5)
        score += _score_proximity(wwtp_mi, ideal_max_mi=10, weight=10)
        score += _score_proximity(line_mi, ideal_max_mi=2, weight=10)
        score += _score_proximity(plant_mi, ideal_max_mi=15, weight=10)
        if in_opp_zone:
            score += 8
        score += _score_acreage_bonus(acres)

        score = max(0, min(100, score))

        owner = (r.get("owner1") or "").strip()
        owner2 = (r.get("owner2") or "").strip()
        site = (r.get("site_addr1") or "").strip()
        mail = f"{(r.get('mail_addr1') or '').strip()}, {(r.get('mail_addr2') or '').strip()}".strip(", ")
        zoning = _safe_zoning(r)

        detail: dict = {
            "summary": (
                f"{acres:.1f}ac  |  {site or '(no addr)'}  |  {r.get('county')}  |  "
                f"sub {sub_miles_ge_volt:.1f}mi @ {sub_kv_ge_volt or '?'}kV  |  "
                f"slope {slope_mean if slope_mean is not None else '?'}%  |  score {score:.0f}"
            ),
            "score_dc": round(score, 1),
            "acres": round(acres, 2),
            "site": site,
            "county": r.get("county"),
            "jurisdiction": r.get("jurisdiction"),
            "owner": owner,
            "owner2": owner2,
            "owner_type": otype,
            "mail": mail,
            "zoning": zoning,
            "subd_name": r.get("subd_name") or "",
            "assessed_total": parse_float(r.get("assessed_total")) or "",
            "year_built": r.get("year_built") or "",
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "miles_to_sub_min_volt": round(sub_miles_ge_volt, 2) if sub_miles_ge_volt is not None else "",
            "min_volt_at_nearest_sub_kv": sub_kv_ge_volt if sub_kv_ge_volt is not None else "",
            "miles_to_any_sub": round(sub_miles, 2) if sub_miles is not None else "",
            "any_sub_voltage_kv": sub_kv if sub_kv is not None else "",
            "miles_to_wwtp": round(wwtp_mi, 2) if wwtp_mi is not None else "",
            "miles_to_transmission_line": round(line_mi, 2) if line_mi is not None else "",
            "miles_to_power_plant": round(plant_mi, 2) if plant_mi is not None else "",
            "in_opportunity_zone": in_opp_zone,
            "slope_mean_pct": slope_mean if slope_mean is not None else "",
            "pct_under_5pct_slope": pct_under_5 if pct_under_5 is not None else "",
            "pct_under_10pct_slope": pct_under_8 if pct_under_8 is not None else "",
            "parcel_id": r.get("parcel_id") or "",
        }

        leads.append(Lead(
            category="DC_SUITABILITY",
            key=str(r.get("parcel_id") or f"{r.get('county')}/{owner}@{site}"),
            score=int(round(score)),
            parcels=[r],
            detail=detail,
        ))

    leads.sort(key=lambda l: -float(l.detail.get("score_dc") or 0))
    return leads
