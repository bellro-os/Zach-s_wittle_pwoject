"""Laggards detection — listings that didn't sell, or sold well below ask.

A listing is a "laggard" if any of:
  - status_category in ('Expired/Cancelled', 'Withdrawn')  AND  list_date >= year_min
  - status_category='Closed' AND sold_price/original_list_price < 0.95
  - status_category='Closed' AND DOM > cohort p75 (cohort = city/class/band/year)

Output bundles:
  outputs/mls_analytics/laggards.csv — every laggard with reason flag
"""

from __future__ import annotations

from pathlib import Path

from .db import connect


def _build_band_map(con) -> None:
    from .bands import BANDS_BY_CLASS, label
    rows = []
    for cls, bands in BANDS_BY_CLASS.items():
        for lo, hi in bands:
            rows.append((cls, float(lo), float(hi) if hi != float("inf") else 1e15, label(lo, hi)))
    con.execute("CREATE OR REPLACE TABLE price_bands (class_id VARCHAR, lo DOUBLE, hi DOUBLE, band VARCHAR)")
    con.executemany("INSERT INTO price_bands VALUES (?, ?, ?, ?)", rows)


def write_laggards_csv(out_path: Path, *, year_min: int = 2020, min_cohort: int = 5) -> int:
    con = connect()
    _build_band_map(con)
    sql = f"""
    WITH base AS (
        SELECT
            listing_id, _class,
            status_category,
            UPPER(TRIM(city)) AS city,
            address, subdivision,
            TRY_CAST(list_price AS DOUBLE) AS list_price,
            TRY_CAST(original_list_price AS DOUBLE) AS original_price,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
            TRY_CAST(close_date AS DATE) AS close_date,
            TRY_CAST(list_date AS DATE) AS list_date,
            TRY_CAST(off_market_date AS DATE) AS off_market_date,
            property_subtype, bedrooms, full_baths,
            TRY_CAST(sqft AS DOUBLE) AS sqft,
            list_office_name
        FROM listings
        WHERE TRY_CAST(list_date AS DATE) >= '{year_min}-01-01'
    ),
    banded AS (
        SELECT
            base.*,
            b.band AS price_band,
            EXTRACT(YEAR FROM COALESCE(close_date, off_market_date, list_date)) AS year_event
        FROM base
        LEFT JOIN price_bands b
          ON b.class_id = base._class
         AND base.original_price >= b.lo
         AND base.original_price < b.hi
    ),
    sold_cohorts AS (
        SELECT year_event, _class, city, price_band,
               COUNT(*) AS cohort_n,
               QUANTILE_CONT(dom, 0.75) AS p75_dom,
               MEDIAN(dom) AS median_dom
        FROM banded
        WHERE status_category='Closed' AND sold_price > 0
        GROUP BY 1,2,3,4
        HAVING COUNT(*) >= {min_cohort}
    )
    SELECT
        b.listing_id, b._class, b.status_category,
        b.city, b.price_band, b.address, b.subdivision,
        b.list_date, b.close_date, b.off_market_date,
        b.list_price, b.original_price, b.sold_price, b.dom,
        ROUND(b.sold_price / NULLIF(b.original_price, 0), 4) AS sold_to_original,
        b.bedrooms, b.full_baths, b.sqft, b.property_subtype, b.list_office_name,
        ROUND(c.p75_dom, 1) AS cohort_p75_dom,
        ROUND(c.median_dom, 1) AS cohort_median_dom,
        c.cohort_n,
        CASE
          WHEN b.status_category IN ('Expired/Cancelled','Withdrawn') THEN 'didnt_sell'
          WHEN b.status_category='Closed' AND b.sold_price < 0.95 * b.original_price THEN 'price_cut_5pct'
          WHEN b.status_category='Closed' AND b.dom > c.p75_dom THEN 'over_p75_dom'
          ELSE NULL
        END AS reason
    FROM banded b
    LEFT JOIN sold_cohorts c
      USING (year_event, _class, city, price_band)
    WHERE
      b.status_category IN ('Expired/Cancelled','Withdrawn')
      OR (b.status_category='Closed' AND b.sold_price < 0.95 * b.original_price)
      OR (b.status_category='Closed' AND c.p75_dom IS NOT NULL AND b.dom > c.p75_dom)
    ORDER BY b.list_date DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]
