"""Daily-driver alerts — recent price drops, status changes, watch matches.

These read listings_history.jsonl (populated by rets_incremental) plus the
current listings.jsonl snapshot. Outputs are CSVs intended for a daily digest.

Functions:
    write_recent_price_changes_csv  — listings whose list price dropped
    write_recent_status_changes_csv — recent status transitions
    watch_listings                  — find active listings matching saved criteria
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .db import connect


HISTORY_PATH = Path("data/mls/listings_history.jsonl")


def _has_history() -> bool:
    return HISTORY_PATH.exists() and HISTORY_PATH.stat().st_size > 0


def write_recent_price_changes_csv(out_path: Path, *, days: int = 7,
                                   only_drops: bool = True,
                                   min_pct_change: float = 1.0) -> int:
    """Recent price changes from listings_history.jsonl.

    By default returns drops >= 1% in the last 7 days.
    """
    if not _has_history():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("listing_id,observed_at,kind,from_price,to_price,delta,delta_pct,city,address\n",
                            encoding="utf-8-sig")
        return 0
    con = connect()
    where_dir = "AND delta < 0" if only_drops else ""
    sql = f"""
    WITH h AS (
        SELECT * FROM read_json_auto('{HISTORY_PATH.as_posix()}',
                                      format='newline_delimited',
                                      union_by_name=true, sample_size=-1)
    )
    SELECT
        listing_id, observed_at, kind, from_price, to_price,
        ROUND(delta, 0) AS delta,
        ROUND(delta_pct, 2) AS delta_pct,
        city, address, _class
    FROM h
    WHERE kind='price_change'
      AND TRY_CAST(observed_at AS TIMESTAMP) >= NOW() - INTERVAL '{days} days'
      AND ABS(delta_pct) >= {min_pct_change}
      {where_dir}
    ORDER BY observed_at DESC, ABS(delta_pct) DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def write_recent_status_changes_csv(out_path: Path, *, days: int = 7) -> int:
    """Recent status changes — new listings, pending, sold, withdrawn."""
    if not _has_history():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("listing_id,observed_at,kind,from_status,to_status,city,address\n",
                            encoding="utf-8-sig")
        return 0
    con = connect()
    sql = f"""
    WITH h AS (
        SELECT * FROM read_json_auto('{HISTORY_PATH.as_posix()}',
                                      format='newline_delimited',
                                      union_by_name=true, sample_size=-1)
    )
    SELECT
        listing_id, observed_at, kind, from_status, to_status,
        city, address, _class, list_price
    FROM h
    WHERE kind IN ('status_change', 'new', 'sold_price_set')
      AND TRY_CAST(observed_at AS TIMESTAMP) >= NOW() - INTERVAL '{days} days'
    ORDER BY observed_at DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def watch_listings(
    *,
    cities: Iterable[str] | None = None,
    classes: Iterable[str] = ("RE_1",),
    statuses: Iterable[str] = ("Active", "Pending"),
    min_price: float | None = None,
    max_price: float | None = None,
    min_beds: int | None = None,
    max_beds: int | None = None,
    min_full_baths: int | None = None,
    min_sqft: int | None = None,
    max_sqft: int | None = None,
    min_acres: float | None = None,
    max_acres: float | None = None,
    zoning_like: str | None = None,
    subdivision_like: str | None = None,
    school_districts: Iterable[str] | None = None,
    center_lat: float | None = None,
    center_lng: float | None = None,
    radius_mi: float | None = None,
    listed_within_days: int | None = None,
    out_csv: Path | None = None,
) -> int:
    """Find active+pending listings matching saved criteria.

    Returns the count of matching listings; writes CSV if out_csv given.

    Radius is straight-line miles via Pythagoras (lat-scaled at 37°N). For
    NRV / SW VA this approximates a 15-min drive at ~10mi; in mountain
    terrain the actual drive may be longer.
    """
    con = connect()
    where: list[str] = []
    if classes:
        cl = ",".join(f"'{c}'" for c in classes)
        where.append(f"_class IN ({cl})")
    if statuses:
        st = ",".join(f"'{s}'" for s in statuses)
        where.append(f"status_category IN ({st})")
    if cities:
        ct = ",".join(f"'{c.upper().strip()}'" for c in cities)
        where.append(f"UPPER(TRIM(city)) IN ({ct})")
    if school_districts:
        sd = ",".join(f"'{s.strip()}'" for s in school_districts)
        where.append(f"high_school IN ({sd})")
    if min_price is not None:
        where.append(f"TRY_CAST(list_price AS DOUBLE) >= {min_price}")
    if max_price is not None:
        where.append(f"TRY_CAST(list_price AS DOUBLE) <= {max_price}")
    if min_beds is not None:
        where.append(f"TRY_CAST(bedrooms AS INT) >= {min_beds}")
    if max_beds is not None:
        where.append(f"TRY_CAST(bedrooms AS INT) <= {max_beds}")
    if min_full_baths is not None:
        where.append(f"TRY_CAST(full_baths AS INT) >= {min_full_baths}")
    if min_sqft is not None:
        where.append(f"TRY_CAST(sqft AS DOUBLE) >= {min_sqft}")
    if max_sqft is not None:
        where.append(f"TRY_CAST(sqft AS DOUBLE) <= {max_sqft}")
    if min_acres is not None:
        where.append(f"TRY_CAST(acres AS DOUBLE) >= {min_acres}")
    if max_acres is not None:
        where.append(f"TRY_CAST(acres AS DOUBLE) <= {max_acres}")
    if zoning_like:
        where.append(f"UPPER(zoning) LIKE '%{zoning_like.upper()}%'")
    if subdivision_like:
        where.append(f"UPPER(subdivision) LIKE '%{subdivision_like.upper()}%'")
    if listed_within_days is not None:
        where.append(f"TRY_CAST(list_date AS DATE) >= CURRENT_DATE - INTERVAL '{listed_within_days} days'")

    has_radius = (
        center_lat is not None
        and center_lng is not None
        and radius_mi is not None
        and radius_mi > 0
    )
    if has_radius:
        # Tight pre-filter with a bbox (cheap), then exact Pythagorean cutoff.
        dlat = radius_mi / 69.0
        dlng = radius_mi / 55.2  # 55.2 mi/deg lng at ~37°N
        where.append(
            f"TRY_CAST(latitude AS DOUBLE) BETWEEN {center_lat - dlat} AND {center_lat + dlat}"
        )
        where.append(
            f"TRY_CAST(longitude AS DOUBLE) BETWEEN {center_lng - dlng} AND {center_lng + dlng}"
        )
        miles_expr = (
            f"ROUND(SQRT("
            f"POW((TRY_CAST(latitude AS DOUBLE) - {center_lat}) * 69.0, 2) + "
            f"POW((TRY_CAST(longitude AS DOUBLE) - ({center_lng})) * 55.2, 2)"
            f"), 2)"
        )
        where.append(f"{miles_expr} <= {radius_mi}")
    else:
        miles_expr = "NULL::DOUBLE"

    where_sql = " AND ".join(where) if where else "1=1"
    sql = f"""
    SELECT
        listing_id, mls_number, _class, status_category,
        city, address, subdivision, high_school,
        list_price, original_list_price, bedrooms, full_baths, half_baths,
        sqft, acres, year_built, zoning,
        latitude, longitude,
        {miles_expr} AS miles_to_center,
        list_date, feed_dom, list_office_name,
        parcel_owner1, parcel_owner_occupied, parcel_assessed_total,
        deed_last_sale_date, deed_last_sale_price
    FROM listings
    WHERE {where_sql}
    ORDER BY list_date DESC NULLS LAST
    """
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        con.sql(f"COPY ({sql}) TO '{out_csv.as_posix()}' WITH (FORMAT CSV, HEADER)")
        return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_csv.as_posix()}')").fetchone()[0]
    return con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
