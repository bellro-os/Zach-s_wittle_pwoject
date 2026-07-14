"""Expired-listing watchlist — owners whose listings recently came off market without selling.

These are immediately actionable — a "here's why it didn't sell + here's the new strategy"
pitch is one of the highest-conversion outreach types in residential. We score each parcel
by re-list propensity:

    +20  recent expiry (within 7 days)
    +15  multiple prior expirations on same parcel
    +10  cut a meaningful amount off original (>10%)
    +10  high estimated equity

Output: outputs/mls_analytics/leads/expired_watchlist.csv

Auto-runs in mls-daily.
"""

from __future__ import annotations

import csv
import re
import urllib.parse as _up
from pathlib import Path

from .db import connect


OUT_PATH = Path("outputs/mls_analytics/leads/expired_watchlist.csv")


def _scc_url(name: str) -> str:
    return ("https://cis.scc.virginia.gov/EntitySearch/AdvancedSearch?searchType=BUSINESS"
            f"&name={_up.quote((name or '').strip())}")


def _whitepages_url(owner: str, locality: str) -> str:
    return (f"https://www.whitepages.com/name/"
            f"{_up.quote((owner or '').replace(' ', '-'))}/"
            f"{_up.quote((locality or '').upper())}-VA")


def _truepeople_url(owner: str, locality: str) -> str:
    return (f"https://www.truepeoplesearch.com/results?"
            f"name={_up.quote(owner or '')}&citystatezip={_up.quote((locality or '') + ' VA')}")


def _next_step(score: int, n_prior: int, days_off: int) -> str:
    if days_off <= 7 and score >= 30:
        return "call_within_72hr"
    if n_prior >= 2:
        return "send_relist_pitch_letter"
    if days_off <= 30:
        return "send_followup_postcard"
    return "add_to_quarterly_drip"


def build_expired_watchlist(*, lookback_days: int = 30, min_score: int = 10) -> int:
    """Build the expired-listing watchlist CSV. Returns number of rows written."""
    con = connect()

    # Per-parcel summary across ALL its listings (so we can count prior expirations)
    sql = f"""
    WITH ranked AS (
      SELECT
        parcel_id,
        listing_id,
        UPPER(TRIM(city)) AS city,
        UPPER(TRIM(county)) AS county,
        address,
        subdivision,
        property_subtype,
        _class,
        TRY_CAST(list_date AS DATE) AS list_date,
        COALESCE(
          TRY_CAST(off_market_date AS DATE),
          TRY_CAST(status_changed_at AS DATE),
          TRY_CAST(list_date AS DATE)
        ) AS event_date,
        TRY_CAST(list_price AS DOUBLE) AS list_price,
        TRY_CAST(original_list_price AS DOUBLE) AS original_list_price,
        TRY_CAST(bedrooms AS INT) AS bedrooms,
        TRY_CAST(full_baths AS INT) AS full_baths,
        TRY_CAST(sqft AS DOUBLE) AS sqft,
        TRY_CAST(year_built AS INT) AS year_built,
        status_category,
        parcel_owner1,
        TRY_CAST(parcel_assessed_total AS DOUBLE) AS assessed,
        TRY_CAST(parcel_owner_occupied AS BOOLEAN) AS owner_occupied,
        list_office_name
      FROM listings
      WHERE parcel_id IS NOT NULL AND parcel_id != ''
        AND status_category IN ('Expired/Cancelled','Withdrawn')
    ),
    summarized AS (
      SELECT
        parcel_id,
        ANY_VALUE(city) AS city,
        ANY_VALUE(county) AS county,
        ANY_VALUE(address) AS address,
        ANY_VALUE(subdivision) AS subdivision,
        ANY_VALUE(property_subtype) AS property_subtype,
        ANY_VALUE(_class) AS _class,
        ANY_VALUE(parcel_owner1) AS owner1,
        ANY_VALUE(assessed) AS assessed,
        ANY_VALUE(owner_occupied) AS owner_occupied,
        ANY_VALUE(bedrooms) AS bedrooms,
        ANY_VALUE(full_baths) AS full_baths,
        ANY_VALUE(sqft) AS sqft,
        ANY_VALUE(year_built) AS year_built,
        COUNT(*) AS n_expirations,
        MAX(event_date) AS last_off_date,
        ARG_MAX(list_price, event_date) AS final_list_price,
        ARG_MAX(original_list_price, event_date) AS final_original_price,
        ARG_MAX(list_date, event_date) AS final_list_date,
        ARG_MAX(list_office_name, event_date) AS final_office,
        ARG_MAX(listing_id, event_date) AS final_listing_id
      FROM ranked
      GROUP BY parcel_id
    )
    SELECT *,
        DATEDIFF('day', last_off_date, CURRENT_DATE) AS days_off,
        DATEDIFF('day', final_list_date, last_off_date) AS days_on_market,
        ROUND(
          (final_original_price - final_list_price) /
          NULLIF(final_original_price, 0) * 100, 1
        ) AS pct_cut_off_orig
    FROM summarized
    WHERE last_off_date >= CURRENT_DATE - INTERVAL '{lookback_days} days'
    """

    rows = con.execute(sql).fetchdf().to_dict(orient="records")

    # Exclude any parcel that's currently active again
    active_ids = {r[0] for r in con.execute(
        "SELECT DISTINCT parcel_id FROM listings WHERE status_category IN ('Active','Pending')"
    ).fetchall() if r[0]}
    rows = [r for r in rows if r.get("parcel_id") not in active_ids]

    out_rows = []
    for r in rows:
        def _f(v) -> float:
            try:
                f = float(v)
                import math
                return 0.0 if math.isnan(f) else f
            except (TypeError, ValueError):
                return 0.0

        score = 0
        days_off = int(_f(r.get("days_off")))
        n_exp = int(_f(r.get("n_expirations")) or 1)
        pct_cut = _f(r.get("pct_cut_off_orig"))
        assessed = _f(r.get("assessed"))
        final_price = _f(r.get("final_list_price"))
        original_price = _f(r.get("final_original_price"))

        if 0 <= days_off <= 7:
            score += 20
        elif 0 <= days_off <= 30:
            score += 10
        if n_exp >= 2:
            score += 15
        if pct_cut >= 10:
            score += 10
        if assessed and final_price and (final_price - assessed) >= 100_000:
            score += 10
        # Mild boost when off-market window is "ripe" (~14 days, sellers regrouping)
        if 10 <= days_off <= 21:
            score += 5

        if score < min_score:
            continue

        def _s(v) -> str:
            if v is None:
                return ""
            try:
                import math
                if isinstance(v, float) and math.isnan(v):
                    return ""
            except Exception:
                pass
            return str(v).strip()

        owner = _s(r.get("owner1")) or "(owner unknown)"
        city = _s(r.get("city"))
        county = _s(r.get("county"))

        out_rows.append({
            "score": score,
            "next_step": _next_step(score, n_exp, days_off),
            "parcel_id": r.get("parcel_id") or "",
            "county": county,
            "city": city,
            "owner": owner,
            "address": _s(r.get("address")),
            "subdivision": _s(r.get("subdivision")),
            "property_subtype": _s(r.get("property_subtype")),
            "bedrooms": int(_f(r.get("bedrooms"))) or "",
            "full_baths": int(_f(r.get("full_baths"))) or "",
            "sqft": int(_f(r.get("sqft"))) or "",
            "year_built": int(_f(r.get("year_built"))) or "",
            "n_expirations": n_exp,
            "last_off_date": str(r.get("last_off_date") or "")[:10],
            "days_off_market": days_off,
            "days_on_market": int(_f(r.get("days_on_market"))),
            "original_list_price": int(original_price) if original_price else "",
            "final_list_price": int(final_price) if final_price else "",
            "pct_cut_off_orig": pct_cut,
            "assessed_total": int(assessed) if assessed else "",
            "owner_occupied": r.get("owner_occupied") if r.get("owner_occupied") in (True, False) else "",
            "prior_office": _s(r.get("final_office")),
            "scc_lookup_url": _scc_url(owner),
            "whitepages_url": _whitepages_url(owner, city or county),
            "true_people_url": _truepeople_url(owner, city or county),
        })

    out_rows.sort(key=lambda x: -x["score"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not out_rows:
        OUT_PATH.write_text("score,parcel_id,owner,address\n", encoding="utf-8-sig")
        return 0
    with OUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    return len(out_rows)
