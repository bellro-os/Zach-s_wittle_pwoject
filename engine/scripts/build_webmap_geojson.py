"""Build GeoJSON files for the DC webmap from v3 CSVs and infra JSONLs.

Outputs go to outputs/dc_webmap/data/. Each layer is a separate GeoJSON
FeatureCollection so the webmap can lazy-load only what the user toggles on.

Key transforms:
  - ArcGIS ring winding (clockwise outer / counter-clockwise inner) is
    converted to GeoJSON spec (counter-clockwise outer / clockwise inner)
    so polygon-with-hole rendering works correctly.
  - All string properties are stored as-is; the JS layer escapes HTML at
    popup-render time to avoid double-encoding when copying parcel data.
  - Highways are filtered to interstates + US highways only (skip primary
    state routes) to keep file size manageable.
  - Flood zones are clipped to areas near qualifying parcels — full state
    flood layer is 922 MB which is impractical to ship to the browser.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString as ShLineString
from sklearn.neighbors import BallTree


ROOT = Path(__file__).parent.parent
DATA_OUT = ROOT / "outputs" / "dc_webmap" / "data"
EARTH_R_MI = 3958.7613


def _signed_area(ring: list[tuple[float, float]]) -> float:
    """Shoelace signed area. Positive = counter-clockwise (GeoJSON outer)."""
    n = len(ring)
    s = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        s += (x2 - x1) * (y2 + y1)
    return -s / 2.0  # positive when CCW


def _ensure_winding(rings: list, outer_ccw: bool = True) -> list:
    """Force first ring to CCW (outer) and remaining rings to CW (holes).
    GeoJSON RFC 7946 spec — MapLibre rendering depends on it."""
    if not rings:
        return rings
    fixed = []
    for i, ring in enumerate(rings):
        # ring is list of [x, y] pairs
        ring_t = [(float(p[0]), float(p[1])) for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(ring_t) < 3:
            continue
        area = _signed_area(ring_t)
        is_ccw = area > 0
        want_ccw = (i == 0) if outer_ccw else False
        if is_ccw != want_ccw:
            ring_t = list(reversed(ring_t))
        fixed.append([[x, y] for (x, y) in ring_t])
    return fixed


def _safe_str(v) -> str:
    if v is None:
        return ""
    return str(v)


def _safe_num(v):
    """Return float or None — never NaN."""
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(v):
    f = _safe_num(v)
    return int(f) if f is not None else None


# ---------- candidate parcels (one per preset) ----------

CAND_FIELDS = [
    "county", "parcel_id", "site", "owner", "owner2", "owner_type",
    "mail_addr1", "mail_addr2", "zoning", "subd_name",
    "year_built", "assessed_total", "acres",
    "slope_mean_pct", "slope_max_pct",
    "pct_under_5pct_slope", "pct_under_10pct_slope", "pct_under_15pct_slope",
    "miles_to_sub_min_volt", "min_volt_at_nearest_sub_kv",
    "miles_to_any_sub", "any_sub_voltage_kv",
    "miles_to_wwtp", "miles_to_nearest_residential",
    "miles_to_major_highway", "miles_to_existing_dc",
    "miles_to_interstate", "miles_to_concrete_plant", "nearest_concrete_plant",
    "in_opportunity_zone", "in_floodplain",
    "primary_utility", "queue_tier", "tax_tier_score",
    "score_dc",
]


def build_candidates(preset: str) -> dict:
    # Use the v3plus CSV (with construction-logistics columns) if available;
    # fall back to v3 otherwise.
    plus_path = ROOT / "outputs" / f"all_parcels_dc_metrics_{preset}_v3plus.csv"
    base_path = ROOT / "outputs" / f"all_parcels_dc_metrics_{preset}_v3.csv"
    in_path = plus_path if plus_path.exists() else base_path
    feats: list[dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("passed_hard_filters") != "Y":
                continue
            lat = _safe_num(r.get("lat"))
            lng = _safe_num(r.get("lng"))
            if lat is None or lng is None:
                continue
            props = {k: r.get(k, "") for k in CAND_FIELDS}
            # Numeric coercions for the JS layer (avoids "0.45" string vs 0.45 number issues)
            props["score_dc"] = _safe_num(r.get("score_dc"))
            props["acres"] = _safe_num(r.get("acres"))
            props["min_volt_at_nearest_sub_kv"] = _safe_int(r.get("min_volt_at_nearest_sub_kv"))
            props["miles_to_sub_min_volt"] = _safe_num(r.get("miles_to_sub_min_volt"))
            props["miles_to_nearest_residential"] = _safe_num(r.get("miles_to_nearest_residential"))
            props["miles_to_major_highway"] = _safe_num(r.get("miles_to_major_highway"))
            props["miles_to_existing_dc"] = _safe_num(r.get("miles_to_existing_dc"))
            props["pct_under_10pct_slope"] = _safe_num(r.get("pct_under_10pct_slope"))
            props["slope_mean_pct"] = _safe_num(r.get("slope_mean_pct"))
            props["tax_tier_score"] = _safe_int(r.get("tax_tier_score"))
            props["miles_to_interstate"] = _safe_num(r.get("miles_to_interstate"))
            props["miles_to_concrete_plant"] = _safe_num(r.get("miles_to_concrete_plant"))
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": props,
            })
    feats.sort(key=lambda f: -(f["properties"].get("score_dc") or 0))
    return {"type": "FeatureCollection", "features": feats}


# ---------- substations ----------

def build_substations() -> dict:
    in_path = ROOT / "data" / "va_substations.jsonl"
    feats: list[dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            lat = _safe_num(r.get("lat"))
            lng = _safe_num(r.get("lng"))
            if lat is None or lng is None:
                continue
            kv = _safe_num(r.get("max_volt_kv"))
            if kv is None or kv < 115:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "name": _safe_str(r.get("name")),
                    "city": _safe_str(r.get("city")),
                    "county": _safe_str(r.get("county")),
                    "max_volt_kv": int(kv),
                    "min_volt_kv": _safe_int(r.get("min_volt_kv")),
                    "type": _safe_str(r.get("type")),
                },
            })
    return {"type": "FeatureCollection", "features": feats}


# ---------- transmission lines ----------

def build_transmission_lines() -> dict:
    in_path = ROOT / "data" / "va_transmission_lines.jsonl"
    feats: list[dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            kv = _safe_num(r.get("voltage"))
            paths = r.get("paths") or []
            for path_pts in paths:
                coords = []
                for p in path_pts:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        x = _safe_num(p[0]); y = _safe_num(p[1])
                        if x is not None and y is not None:
                            coords.append([x, y])
                if len(coords) < 2:
                    continue
                feats.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "voltage": int(kv) if kv is not None else None,
                        "owner": _safe_str(r.get("owner")),
                        "type": _safe_str(r.get("type")),
                    },
                })
    return {"type": "FeatureCollection", "features": feats}


# ---------- existing DCs ----------

def build_concrete_plants() -> dict:
    in_path = ROOT / "data" / "va_concrete_plants.jsonl"
    feats: list[dict] = []
    if not in_path.exists():
        return {"type": "FeatureCollection", "features": feats}
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            lat = _safe_num(r.get("lat"))
            lng = _safe_num(r.get("lng"))
            if lat is None or lng is None:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "name": _safe_str(r.get("name")) or "(unnamed concrete plant)",
                    "operator": _safe_str(r.get("operator")),
                    "city": _safe_str(r.get("addr_city")),
                },
            })
    return {"type": "FeatureCollection", "features": feats}


def build_interstates() -> dict:
    """Subset of fiber proxy filtered to motorway only — represents the
    Interstate Highway System routes (I-81, I-95, I-64, I-77, I-66, etc.).
    Used as the heavy-haul / construction-equipment access metric."""
    in_path = ROOT / "data" / "va_interstates.jsonl"
    feats: list[dict] = []
    if not in_path.exists():
        return {"type": "FeatureCollection", "features": feats}
    SIMPLIFY_TOL = 0.0005
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            paths = r.get("paths") or []
            for path_pts in paths:
                coords = []
                for p in path_pts:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        x = _safe_num(p[0]); y = _safe_num(p[1])
                        if x is not None and y is not None:
                            coords.append((x, y))
                if len(coords) < 2:
                    continue
                try:
                    line_geom = ShLineString(coords).simplify(SIMPLIFY_TOL, preserve_topology=False)
                    simplified = list(line_geom.coords)
                except Exception:
                    simplified = coords
                if len(simplified) < 2:
                    continue
                feats.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [[x, y] for (x, y) in simplified]},
                    "properties": {
                        "ref": _safe_str(r.get("ref")),
                        "name": _safe_str(r.get("name")),
                    },
                })
    return {"type": "FeatureCollection", "features": feats}


def build_existing_dcs() -> dict:
    in_path = ROOT / "data" / "va_existing_dc.jsonl"
    feats: list[dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            lat = _safe_num(r.get("lat"))
            lng = _safe_num(r.get("lng"))
            if lat is None or lng is None:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "name": _safe_str(r.get("name")),
                    "city": _safe_str(r.get("city")),
                    "operator": _safe_str(r.get("operator")),
                    "status": _safe_str(r.get("status")),
                    "campus_acres": _safe_int(r.get("campus_acres")),
                },
            })
    return {"type": "FeatureCollection", "features": feats}


# ---------- opportunity zones ----------

def build_opp_zones() -> dict:
    in_path = ROOT / "data" / "va_opportunity_zones.jsonl"
    feats: list[dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            rings = r.get("rings") or []
            if not rings:
                continue
            # ArcGIS rings: outer is CW, holes are CCW. GeoJSON spec is opposite.
            fixed_rings = _ensure_winding(rings, outer_ccw=True)
            if not fixed_rings:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": fixed_rings},
                "properties": {
                    "tract": _safe_str(r.get("tract")),
                    "state": _safe_str(r.get("state")),
                    "county": _safe_str(r.get("county")),
                },
            })
    return {"type": "FeatureCollection", "features": feats}


# ---------- wastewater ----------

def build_wastewater() -> dict:
    in_path = ROOT / "data" / "va_wastewater_treatment.jsonl"
    feats: list[dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            lat = _safe_num(r.get("lat"))
            lng = _safe_num(r.get("lng"))
            if lat is None or lng is None:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "facility_name": _safe_str(r.get("facility_name")),
                    "permit_no": _safe_str(r.get("permit_no")),
                },
            })
    return {"type": "FeatureCollection", "features": feats}


# ---------- highways (interstates + US only) ----------

def build_highways() -> dict:
    """Interstates + US trunk routes only (skip 'primary' state routes), with
    Douglas-Peucker simplification (tolerance ~50m) to keep file size sane.
    Adjacent OSM segments aren't merged but simplification still cuts the
    feature count by ~3x."""
    in_path = ROOT / "data" / "va_fiber_proxy.jsonl"
    feats: list[dict] = []
    SIMPLIFY_TOL = 0.0005  # ~50 m at VA latitude
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            hwy = (r.get("highway") or "").lower()
            if hwy not in ("motorway", "motorway_link", "trunk"):
                continue
            paths = r.get("paths") or []
            for path_pts in paths:
                coords = []
                for p in path_pts:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        x = _safe_num(p[0]); y = _safe_num(p[1])
                        if x is not None and y is not None:
                            coords.append((x, y))
                if len(coords) < 2:
                    continue
                # Douglas-Peucker simplify — tolerance in degrees
                try:
                    line_geom = ShLineString(coords).simplify(SIMPLIFY_TOL, preserve_topology=False)
                    simplified = list(line_geom.coords)
                except Exception:
                    simplified = coords
                if len(simplified) < 2:
                    continue
                feats.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [[x, y] for (x, y) in simplified]},
                    "properties": {
                        "name": _safe_str(r.get("name")),
                        "ref": _safe_str(r.get("ref")),
                        "highway": hwy,
                    },
                })
    return {"type": "FeatureCollection", "features": feats}


# ---------- flood zones (clipped to candidate areas) ----------

def build_flood_zones(candidate_features: list[dict], buffer_mi: float = 5) -> dict:
    """Keep only flood polygons within `buffer_mi` of any candidate to keep
    file size manageable. The full VA SFHA layer is 922 MB."""
    in_path = ROOT / "data" / "va_flood_zones.jsonl"
    if not in_path.exists():
        return {"type": "FeatureCollection", "features": []}

    # Build BallTree over candidate centroids
    cand_pts = []
    for f in candidate_features:
        coords = (f.get("geometry") or {}).get("coordinates")
        if coords and len(coords) == 2:
            cand_pts.append((coords[1], coords[0]))  # lat, lng
    if not cand_pts:
        return {"type": "FeatureCollection", "features": []}

    tree = BallTree(np.radians(np.array(cand_pts)), metric="haversine")
    radius_rad = buffer_mi / EARTH_R_MI

    feats: list[dict] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            rings = r.get("rings") or []
            if not rings:
                continue
            outer = rings[0]
            # Use first vertex as polygon's representative point for the buffer test
            try:
                lng = float(outer[0][0]); lat = float(outer[0][1])
            except (IndexError, TypeError, ValueError):
                continue
            nbrs = tree.query_radius(np.radians([[lat, lng]]), r=radius_rad, count_only=True)
            if not nbrs[0]:
                continue
            fixed_rings = _ensure_winding(rings, outer_ccw=True)
            if not fixed_rings:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": fixed_rings},
                "properties": {
                    "fld_zone": _safe_str(r.get("fld_zone")),
                    "zone_subtype": _safe_str(r.get("zone_subtype")),
                },
            })
    return {"type": "FeatureCollection", "features": feats}


# ---------- main ----------

def main() -> int:
    DATA_OUT.mkdir(parents=True, exist_ok=True)

    print("Building candidate GeoJSONs...")
    all_cand_pts: list[dict] = []
    for preset in ("piedmont", "appalachian", "hyperscale"):
        gj = build_candidates(preset)
        path = DATA_OUT / f"candidates_{preset}.geojson"
        path.write_text(json.dumps(gj), encoding="utf-8")
        size_mb = path.stat().st_size / 1e6
        print(f"  candidates_{preset}: {len(gj['features']):,} features, {size_mb:.1f} MB")
        all_cand_pts.extend(gj["features"])

    print("Building infra GeoJSONs...")
    layers = {
        "substations": build_substations,
        "transmission_lines": build_transmission_lines,
        "existing_dcs": build_existing_dcs,
        "concrete_plants": build_concrete_plants,
        "opp_zones": build_opp_zones,
        "wastewater": build_wastewater,
        "highways": build_highways,
        "interstates": build_interstates,
    }
    for name, fn in layers.items():
        gj = fn()
        path = DATA_OUT / f"{name}.geojson"
        path.write_text(json.dumps(gj), encoding="utf-8")
        size_mb = path.stat().st_size / 1e6
        print(f"  {name}: {len(gj['features']):,} features, {size_mb:.1f} MB")

    # Flood zones polygon layer omitted by design.
    # Reasoning: VA SFHA polygons total 200+ MB even after candidate-area
    # clipping — too heavy for a browser layer. The `in_floodplain` flag
    # on each candidate already does the filtering work via the sidebar
    # toggle, so we don't need to draw the polygons themselves.
    # Re-enable by uncommenting if a county-scale flood overlay is needed.

    print(f"\nAll GeoJSON written to {DATA_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
