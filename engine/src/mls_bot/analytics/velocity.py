"""Market velocity — months-of-inventory by city × class, plus expiry rates.

Months of inventory = (active listings now) / (avg monthly closings, last 12 mo).
Standard heuristic: <3 mo = strong seller's market, 3-6 mo = balanced, 6+ mo
= buyer's market.

Output: outputs/mls_analytics/market_velocity.csv — sorted by months-of-
inventory ascending (hottest first).
"""

from __future__ import annotations

from pathlib import Path

from .db import connect


def write_velocity_csv(out_path: Path, *, min_n_active: int = 1, min_n_closed: int = 5) -> int:
    con = connect()
    sql = f"""
    WITH active AS (
        SELECT _class, UPPER(TRIM(city)) AS city, COUNT(*) AS active_n
        FROM listings
        WHERE status_category = 'Active'
        GROUP BY 1, 2
    ),
    closed_12mo AS (
        SELECT _class, UPPER(TRIM(city)) AS city,
               COUNT(*) AS closed_12mo,
               MEDIAN(COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT))) AS dom_med_12mo
        FROM listings
        WHERE status_category = 'Closed'
          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '365 days'
        GROUP BY 1, 2
    ),
    closed_90 AS (
        SELECT _class, UPPER(TRIM(city)) AS city,
               COUNT(*) AS closed_90d,
               MEDIAN(COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT))) AS dom_med_90d,
               MEDIAN(TRY_CAST(sold_price AS DOUBLE) / NULLIF(TRY_CAST(original_list_price AS DOUBLE), 0)) AS sold_to_orig_90d
        FROM listings
        WHERE status_category = 'Closed'
          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY 1, 2
    ),
    expired_12mo AS (
        SELECT _class, UPPER(TRIM(city)) AS city, COUNT(*) AS expired_12mo
        FROM listings
        WHERE status_category IN ('Expired/Cancelled', 'Withdrawn')
          AND TRY_CAST(off_market_date AS DATE) >= CURRENT_DATE - INTERVAL '365 days'
        GROUP BY 1, 2
    )
    SELECT
        a.city, a._class,
        a.active_n,
        c.closed_12mo,
        ROUND(a.active_n * 1.0 / NULLIF(c.closed_12mo / 12.0, 0), 2) AS months_of_inventory,
        c90.closed_90d,
        ROUND(c90.dom_med_90d, 1) AS dom_median_90d,
        ROUND(c.dom_med_12mo, 1) AS dom_median_12mo,
        ROUND(c90.sold_to_orig_90d * 100, 2) AS pct_of_orig_list_90d,
        e.expired_12mo,
        ROUND(e.expired_12mo * 1.0 / NULLIF(e.expired_12mo + c.closed_12mo, 0), 4) AS expiry_rate_12mo,
        CASE
          WHEN a.active_n * 1.0 / NULLIF(c.closed_12mo / 12.0, 0) < 1.5 THEN 'extreme seller'
          WHEN a.active_n * 1.0 / NULLIF(c.closed_12mo / 12.0, 0) < 3 THEN 'strong seller'
          WHEN a.active_n * 1.0 / NULLIF(c.closed_12mo / 12.0, 0) < 6 THEN 'balanced'
          WHEN a.active_n * 1.0 / NULLIF(c.closed_12mo / 12.0, 0) < 9 THEN 'soft buyer'
          ELSE 'strong buyer'
        END AS market_label
    FROM active a
    LEFT JOIN closed_12mo c USING (_class, city)
    LEFT JOIN closed_90    c90 USING (_class, city)
    LEFT JOIN expired_12mo e USING (_class, city)
    WHERE a.active_n >= {min_n_active}
      AND COALESCE(c.closed_12mo, 0) >= {min_n_closed}
    ORDER BY months_of_inventory ASC NULLS LAST
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def headline_summary() -> list[tuple[str, str, float, str]]:
    """Return (city, class, months_of_inventory, market_label) for the top
    rows by listing volume — for daily-driver console output."""
    con = connect()
    out_path = Path("outputs/mls_analytics/market_velocity.csv")
    if not out_path.exists():
        return []
    rows = con.execute(f"""
        SELECT city, _class, months_of_inventory, market_label, active_n
        FROM read_csv_auto('{out_path.as_posix()}')
        ORDER BY active_n DESC
        LIMIT 6
    """).fetchall()
    return [(r[0], r[1], r[2], r[3]) for r in rows]
