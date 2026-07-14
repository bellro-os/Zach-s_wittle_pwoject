"""Neighbor-of-recent-sale outreach.

For each closed sale in the last N days, generate a list of nearby
non-listed owners to contact. Pitch: "Your neighbor at <addr> sold for
<price>. The market in <subdivision> is moving. Here's what your home
could be worth."

Selection rules per triggering sale:
  - Same subdivision (preferred)  OR  within 0.5 mi (haversine)
  - Not currently Active/Pending in MLS
  - Not contacted in the last 90 days (per outreach_log.csv)
  - Has a seller_score row >= min_score (default 30)
  - Cap at K neighbors per triggering sale (default 5)

Output: outputs/mls_analytics/leads/neighbor_outreach.csv
        (one row per neighbor, grouped by triggering_sale_listing_id)
"""

from __future__ import annotations

import csv
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from .db import connect


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
    s = str(v).strip()
    if s.lower() in ("none", "nan", "<na>"):
        return ""
    return s


def _f(v) -> float:
    try:
        f = float(v)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


OUT_PATH = Path("outputs/mls_analytics/leads/neighbor_outreach.csv")
SCORES_CSV = Path("outputs/mls_analytics/leads/seller_scores.csv")
OUTREACH_LOG = Path("data/outreach_log.csv")


def _load_seller_scores() -> dict[tuple[str, str], dict]:
    """Return {(parcel_id, county): row} for fast lookup."""
    if not SCORES_CSV.exists():
        return {}
    out: dict[tuple[str, str], dict] = {}
    with SCORES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            pid = (r.get("parcel_id") or "").strip()
            county = (r.get("county") or "").strip().upper()
            if pid:
                out[(pid, county)] = r
    return out


def _recent_contacts(within_days: int = 90) -> set[tuple[str, str]]:
    """Set of (parcel_id, county_upper) contacted in last N days (any outcome
    other than 'interested'/'hot' which we'd still leave room to re-touch)."""
    if not OUTREACH_LOG.exists():
        return set()
    today = date.today()
    out: set[tuple[str, str]] = set()
    with OUTREACH_LOG.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            pid = (r.get("parcel_id") or "").strip()
            if pid.startswith("#") or not pid:
                continue
            cd = (r.get("contact_date") or "").strip()
            try:
                d = date.fromisoformat(cd[:10])
            except Exception:
                continue
            if (today - d).days <= within_days:
                out.add((pid, (r.get("county") or "").strip().upper()))
    return out


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _suggested_text(triggering_addr: str, sold_price: float, subdivision: str) -> str:
    parts = ["Hi neighbor —"]
    if subdivision:
        parts.append(f"Your neighbor at {triggering_addr} just sold; {subdivision} is active right now.")
    else:
        parts.append(f"Your neighbor at {triggering_addr} just sold.")
    if sold_price and sold_price > 0:
        parts.append(f"Closing price: ${sold_price:,.0f}.")
    parts.append("Curious what your home would bring in this market? I can have a written estimate to you in 48 hours, no charge.")
    return " ".join(parts)


def build_neighbor_outreach(
    *,
    sale_lookback_days: int = 14,
    radius_miles: float = 0.5,
    max_neighbors_per_sale: int = 5,
    min_seller_score: int = 30,
) -> int:
    """Build the neighbor-outreach CSV. Returns row count written."""
    con = connect()

    # 1. Recent closed sales
    sales = con.execute(f"""
        SELECT
            listing_id, address, UPPER(TRIM(city)) AS city, UPPER(TRIM(county)) AS county,
            subdivision, _class,
            TRY_CAST(close_date AS DATE) AS close_date,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            TRY_CAST(feed_dom AS INT) AS dom,
            TRY_CAST(latitude AS DOUBLE) AS lat,
            TRY_CAST(longitude AS DOUBLE) AS lon
        FROM listings
        WHERE status_category = 'Closed'
          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '{sale_lookback_days} days'
          AND TRY_CAST(sold_price AS DOUBLE) > 0
    """).fetchdf().to_dict(orient="records")

    if not sales:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text("triggering_sale_listing_id,neighbor_parcel_id,neighbor_owner\n",
                            encoding="utf-8-sig")
        return 0

    # 2. Parcels currently in market (exclude as neighbors)
    active_pids = {r[0] for r in con.execute(
        "SELECT DISTINCT parcel_id FROM listings WHERE status_category IN ('Active','Pending') AND parcel_id IS NOT NULL"
    ).fetchall() if r[0]}

    # 3. All known parcels with their best-available feature row from listings
    #    (most-recent listing record per parcel — gives us address + owner + lat/lon)
    parcel_universe = con.execute("""
        WITH ranked AS (
          SELECT
            parcel_id, county, address, city,
            subdivision, _class,
            parcel_owner1 AS owner,
            TRY_CAST(parcel_assessed_total AS DOUBLE) AS assessed,
            TRY_CAST(latitude AS DOUBLE) AS lat,
            TRY_CAST(longitude AS DOUBLE) AS lon,
            TRY_CAST(year_built AS INT) AS year_built,
            ROW_NUMBER() OVER (
              PARTITION BY parcel_id
              ORDER BY list_date DESC NULLS LAST
            ) AS rn
          FROM listings
          WHERE parcel_id IS NOT NULL AND parcel_id != ''
        )
        SELECT * FROM ranked WHERE rn = 1
    """).fetchdf().to_dict(orient="records")

    # Index parcels by subdivision for fast lookup
    by_subdiv: dict[str, list[dict]] = {}
    parcels_with_geo: list[dict] = []
    for p in parcel_universe:
        sub = _s(p.get("subdivision")).upper()
        if sub:
            by_subdiv.setdefault(sub, []).append(p)
        if _f(p.get("lat")) and _f(p.get("lon")):
            parcels_with_geo.append(p)

    scores = _load_seller_scores()
    suppress = _recent_contacts(within_days=90)

    out_rows = []
    for sale in sales:
        triggering_subdiv = _s(sale.get("subdivision")).upper()
        triggering_addr = _s(sale.get("address"))
        sold_price = _f(sale.get("sold_price"))
        sale_lat = _f(sale.get("lat")) or None
        sale_lon = _f(sale.get("lon")) or None
        triggering_pid = None  # we don't expose it; just for self-exclusion

        # Get triggering parcel id (so we don't pitch the seller themselves)
        try:
            r = con.execute(
                "SELECT parcel_id FROM listings WHERE listing_id = ? LIMIT 1",
                [sale.get("listing_id")]
            ).fetchone()
            if r:
                triggering_pid = r[0]
        except Exception:
            triggering_pid = None

        # --- candidate set ---
        candidates: list[tuple[float, dict]] = []   # (priority, parcel)

        if triggering_subdiv and triggering_subdiv in by_subdiv:
            for p in by_subdiv[triggering_subdiv]:
                if p.get("parcel_id") == triggering_pid:
                    continue
                candidates.append((0.0, p))   # subdivision-match: priority 0 (best)
        elif sale_lat and sale_lon:
            # radius fallback
            for p in parcels_with_geo:
                if p.get("parcel_id") == triggering_pid:
                    continue
                d = _haversine_miles(float(sale_lat), float(sale_lon),
                                     float(p["lat"]), float(p["lon"]))
                if d <= radius_miles:
                    candidates.append((d, p))

        # --- filter + score ---
        scored: list[tuple[int, dict, float]] = []   # (seller_score, parcel, distance/0)
        for prio, p in candidates:
            pid = _s(p.get("parcel_id"))
            county = _s(p.get("county")).upper()
            if not pid or pid in active_pids:
                continue
            if (pid, county) in suppress:
                continue
            score_row = scores.get((pid, county))
            try:
                ss = int(float(score_row.get("score", 0))) if score_row else 0
            except (TypeError, ValueError):
                ss = 0
            if ss < min_seller_score:
                continue
            scored.append((ss, p, prio))

        # rank: higher seller_score first, then closer (lower prio)
        scored.sort(key=lambda x: (-x[0], x[2]))
        for ss, p, prio in scored[:max_neighbors_per_sale]:
            score_row = scores.get((_s(p.get("parcel_id")), _s(p.get("county")).upper())) or {}
            assessed = _f(p.get("assessed"))
            year_built = int(_f(p.get("year_built"))) or ""
            dom = int(_f(sale.get("dom"))) or ""
            out_rows.append({
                "triggering_sale_listing_id": _s(sale.get("listing_id")),
                "triggering_sale_address": triggering_addr,
                "triggering_sale_city": _s(sale.get("city")),
                "triggering_sale_subdivision": _s(sale.get("subdivision")),
                "triggering_sale_close_date": str(sale.get("close_date") or "")[:10],
                "triggering_sale_price": int(sold_price) if sold_price else "",
                "triggering_sale_dom": dom,
                "neighbor_parcel_id": _s(p.get("parcel_id")),
                "neighbor_county": _s(p.get("county")),
                "neighbor_owner": _s(p.get("owner")),
                "neighbor_address": _s(p.get("address")),
                "neighbor_subdivision": _s(p.get("subdivision")),
                "neighbor_year_built": year_built,
                "neighbor_assessed": int(assessed) if assessed else "",
                "neighbor_seller_score": ss,
                "distance_miles": round(prio, 2) if prio > 0 else 0,
                "match_type": "subdivision" if prio == 0 else "radius",
                "scc_lookup_url": (score_row.get("scc_lookup_url") or ""),
                "whitepages_url": (score_row.get("whitepages_url") or ""),
                "true_people_url": (score_row.get("true_people_url") or ""),
                "suggested_mailer_text": _suggested_text(
                    triggering_addr, sold_price, _s(sale.get("subdivision")),
                ),
            })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not out_rows:
        OUT_PATH.write_text(
            "triggering_sale_listing_id,neighbor_parcel_id,neighbor_owner\n",
            encoding="utf-8-sig",
        )
        return 0
    with OUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    return len(out_rows)
