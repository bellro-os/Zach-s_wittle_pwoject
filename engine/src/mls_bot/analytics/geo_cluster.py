"""Geographic clustering helpers for the dashboard door-knock workflow.

Currently exposes one function — `order_walking_route()` — which orders
a list of parcels into a nearest-neighbor walking sequence starting
from the highest-score parcel.

Coordinates are pulled from the listings table via DuckDB. Parcels with
no coordinate data fall to the end of the route.
"""

from __future__ import annotations

import math


EARTH_R_MI = 3958.7613


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_MI * math.asin(math.sqrt(a))


def _fetch_coords(parcel_ids: list[str]) -> dict[str, tuple[float, float]]:
    """Return {parcel_id: (lat, lng)} from the listings table."""
    if not parcel_ids:
        return {}
    try:
        from mls_bot.analytics.db import connect
    except ImportError:
        return {}
    safe = ",".join(
        f"'{pid.replace(chr(39), chr(39) + chr(39))}'" for pid in parcel_ids
    )
    con = connect()
    rows = con.execute(f"""
        WITH ranked AS (
            SELECT parcel_id,
                   TRY_CAST(latitude AS DOUBLE)  AS lat,
                   TRY_CAST(longitude AS DOUBLE) AS lng,
                   ROW_NUMBER() OVER (
                       PARTITION BY parcel_id
                       ORDER BY list_date DESC NULLS LAST
                   ) AS rn
            FROM listings
            WHERE parcel_id IN ({safe})
        )
        SELECT parcel_id, lat, lng FROM ranked WHERE rn = 1
    """).fetchall()
    out: dict[str, tuple[float, float]] = {}
    for pid, lat, lng in rows:
        if lat is None or lng is None:
            continue
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError):
            continue
        if math.isnan(lat_f) or math.isnan(lng_f):
            continue
        out[pid] = (lat_f, lng_f)
    return out


def order_walking_route(parcels: list[dict]) -> list[dict]:
    """Order parcels by nearest-neighbor walking traversal.

    Input: list of dicts each with at least 'parcel_id' (other fields
    pass through unchanged). Output: same list re-ordered into walking
    sequence, with 'lat'/'lng'/'route_order' added. Parcels with no
    coordinate data are appended at the end with route_order suffix.
    """
    if not parcels:
        return []
    coords = _fetch_coords([p["parcel_id"] for p in parcels if p.get("parcel_id")])
    with_coords: list[dict] = []
    without_coords: list[dict] = []
    for p in parcels:
        c = coords.get(p.get("parcel_id", ""))
        if c is None:
            without_coords.append(dict(p))
            continue
        copy = dict(p)
        copy["lat"], copy["lng"] = c
        with_coords.append(copy)
    if not with_coords:
        return [dict(p, route_order=i + 1) for i, p in enumerate(parcels)]
    # Start at highest-score parcel (or first if no score)
    start = max(range(len(with_coords)),
                key=lambda i: with_coords[i].get("score", 0))
    ordered = [with_coords.pop(start)]
    while with_coords:
        last = ordered[-1]
        best_i = 0
        best_d = float("inf")
        for i, p in enumerate(with_coords):
            d = _haversine_mi(last["lat"], last["lng"], p["lat"], p["lng"])
            if d < best_d:
                best_d = d
                best_i = i
        chosen = with_coords.pop(best_i)
        chosen["_dist_from_prev"] = best_d
        ordered.append(chosen)
    ordered.extend(without_coords)
    for i, p in enumerate(ordered, start=1):
        p["route_order"] = i
    return ordered
