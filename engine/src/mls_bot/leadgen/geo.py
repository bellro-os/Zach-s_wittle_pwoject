"""Geographic helpers — distance filtering against a reference point.

Straight-line (haversine) distance is good enough for filtering to "within
N miles of VT campus" or similar. Real drive-time routing stays out of scope
until it's warranted.

Calibration note: in-town Blacksburg, straight-line miles * 1.6 + a bit ≈
drive minutes (at 30 mph avg). Rural-edge parcels (Brush Mountain, Ellett
Valley) will over-qualify because terrain forces indirect routes.
"""

from __future__ import annotations

import math
from typing import Final


# Virginia Tech campus center — Burruss Hall / Drillfield.
VT_CAMPUS: Final[tuple[float, float]] = (37.2284, -80.4234)

REFERENCE_POINTS: dict[str, tuple[float, float]] = {
    "VT": VT_CAMPUS,
    "DOWNTOWN_BLACKSBURG": (37.2296, -80.4139),   # corner of Main & Roanoke
    "CHRISTIANSBURG": (37.1299, -80.4089),        # town center
    "CARILION_ROANOKE": (37.2700, -79.9420),      # Carilion Roanoke Memorial Hospital
    "RADFORD": (37.1318, -80.5764),               # downtown Radford
    "PULASKI": (37.0526, -80.7704),               # downtown Pulaski
}

# Conversion factor: straight-line miles -> driving miles (accounts for road
# network indirection). Blacksburg averages around 1.5-1.7; rural edges higher.
DEFAULT_ROAD_FACTOR: Final[float] = 1.6
# Average in-town speed used when converting to minutes.
DEFAULT_AVG_MPH: Final[float] = 30.0


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles."""
    r_earth = 3958.7613  # miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r_earth * math.asin(math.sqrt(a))


def drive_minutes_approx(
    straight_miles: float,
    factor: float = DEFAULT_ROAD_FACTOR,
    avg_mph: float = DEFAULT_AVG_MPH,
) -> float:
    """Straight-line miles -> approximate driving minutes."""
    return (straight_miles * factor) / avg_mph * 60


def miles_to_reference(row: dict, ref_lat: float, ref_lng: float) -> float | None:
    """Compute straight-line miles from a parcel row to (ref_lat, ref_lng).
    Returns None if the row has no lat/lng."""
    lat = row.get("lat")
    lng = row.get("lng")
    if lat is None or lng is None:
        return None
    try:
        return haversine_miles(float(lat), float(lng), ref_lat, ref_lng)
    except (TypeError, ValueError):
        return None


def resolve_reference(config: dict) -> tuple[float, float]:
    """Pick the reference point from a detector config dict.

    Precedence: explicit lat/lng > named reference > VT campus default.
    """
    lat = config.get("reference_lat")
    lng = config.get("reference_lng")
    if lat is not None and lng is not None:
        try:
            return float(lat), float(lng)
        except (TypeError, ValueError):
            pass
    name = str(config.get("reference", "VT")).upper()
    return REFERENCE_POINTS.get(name, VT_CAMPUS)


# ---------------------------------------------------------------------------
# Proximity to point/line collections — used to score parcels against
# infrastructure datasets (transmission lines, wastewater plants, etc.).

import json as _json
from pathlib import Path as _Path


def load_points(path: str | _Path,
                lat_field: str = "lat",
                lng_field: str = "lng") -> list[tuple[float, float]]:
    """Read a JSONL of point features into a list of (lat, lng) tuples.
    Rows missing either coord are skipped."""
    pts: list[tuple[float, float]] = []
    with _Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = _json.loads(line)
            lat = r.get(lat_field)
            lng = r.get(lng_field)
            if lat is None or lng is None:
                continue
            try:
                pts.append((float(lat), float(lng)))
            except (TypeError, ValueError):
                continue
    return pts


def load_polylines(path: str | _Path,
                   paths_field: str = "paths") -> list[list[tuple[float, float]]]:
    """Read a JSONL of polyline features (e.g. transmission lines).

    Each row's `paths` field is `[[[lng, lat], ...], ...]` (ESRI/GeoJSON
    convention). Returns a flat list of vertex sequences in (lat, lng) order.
    """
    out: list[list[tuple[float, float]]] = []
    with _Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = _json.loads(line)
            for path_pts in r.get(paths_field) or []:
                seq: list[tuple[float, float]] = []
                for pt in path_pts:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        try:
                            seq.append((float(pt[1]), float(pt[0])))
                        except (TypeError, ValueError):
                            continue
                if len(seq) >= 2:
                    out.append(seq)
    return out


def nearest_point_miles(parcel_lat: float, parcel_lng: float,
                        points: list[tuple[float, float]]) -> float | None:
    """Straight-line miles from a parcel to the nearest point in a collection."""
    if not points:
        return None
    best = float("inf")
    for plat, plng in points:
        d = haversine_miles(parcel_lat, parcel_lng, plat, plng)
        if d < best:
            best = d
    return best if best != float("inf") else None


def _segment_distance_miles(plat: float, plng: float,
                            a_lat: float, a_lng: float,
                            b_lat: float, b_lng: float) -> float:
    """Approx perpendicular distance from (plat, plng) to the segment a→b.

    Uses an equirectangular projection at the parcel's latitude — accurate
    to a fraction of a percent at parcel-to-line distances under ~50 mi.
    """
    # Convert to a local x-y plane in miles, x = east, y = north.
    cos_lat = math.cos(math.radians(plat))
    miles_per_deg_lat = 69.0  # ~constant
    def to_xy(lt: float, lg: float) -> tuple[float, float]:
        return (lg - plng) * miles_per_deg_lat * cos_lat, (lt - plat) * miles_per_deg_lat
    px, py = 0.0, 0.0
    ax, ay = to_xy(a_lat, a_lng)
    bx, by = to_xy(b_lat, b_lng)
    dx, dy = bx - ax, by - ay
    seg_sq = dx * dx + dy * dy
    if seg_sq == 0:
        return math.hypot(ax, ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_sq
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx, cy)


def nearest_polyline_miles(parcel_lat: float, parcel_lng: float,
                           polylines: list[list[tuple[float, float]]]) -> float | None:
    """Straight-line miles from a parcel to the nearest polyline segment."""
    if not polylines:
        return None
    best = float("inf")
    for seq in polylines:
        for i in range(len(seq) - 1):
            a_lat, a_lng = seq[i]
            b_lat, b_lng = seq[i + 1]
            d = _segment_distance_miles(parcel_lat, parcel_lng,
                                        a_lat, a_lng, b_lat, b_lng)
            if d < best:
                best = d
    return best if best != float("inf") else None
