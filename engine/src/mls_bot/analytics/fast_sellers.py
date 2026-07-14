"""Fast-sellers detection — listings that closed at or below cohort p25 DOM.

A listing is a "fast seller" if its DOM is at or below the 25th-percentile DOM
for its cohort (city × _class × price_band × close_year). The output is a CSV
flagging these listings with their cohort context, so the user can study what
made them move — pricing, condition, marketing, agent.

Cohort requires at least 5 sales to compute a p25 reliably.
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


def write_fast_sellers_csv(out_path: Path, *, year_min: int = 2018, min_cohort: int = 5) -> int:
    con = connect()
    _build_band_map(con)
    sql = f"""
    WITH sold AS (
        SELECT
            listing_id, _class,
            UPPER(TRIM(city)) AS city,
            UPPER(TRIM(county)) AS county,
            address, subdivision,
            TRY_CAST(list_price AS DOUBLE) AS list_price,
            TRY_CAST(original_list_price AS DOUBLE) AS original_price,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
            TRY_CAST(close_date AS DATE) AS close_date,
            TRY_CAST(list_date AS DATE) AS list_date,
            property_subtype, bedrooms, full_baths, half_baths,
            TRY_CAST(sqft AS DOUBLE) AS sqft, list_office_name
        FROM listings
        WHERE status_category='Closed'
          AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) IS NOT NULL
    ),
    banded AS (
        SELECT s.*, b.band AS price_band, EXTRACT(YEAR FROM close_date) AS close_year
        FROM sold s
        LEFT JOIN price_bands b
          ON b.class_id = s._class AND s.list_price >= b.lo AND s.list_price < b.hi
    ),
    cohorts AS (
        SELECT close_year, _class, city, price_band,
               COUNT(*) AS cohort_n,
               QUANTILE_CONT(dom, 0.25) AS p25_dom,
               MEDIAN(dom) AS median_dom,
               QUANTILE_CONT(dom, 0.75) AS p75_dom,
               MEDIAN(sold_price / NULLIF(original_price, 0)) AS median_sold_to_orig
        FROM banded
        WHERE close_year >= {year_min}
        GROUP BY 1,2,3,4
        HAVING COUNT(*) >= {min_cohort}
    )
    SELECT
        b.close_year, b._class, b.city, b.price_band,
        b.listing_id, b.address, b.subdivision,
        b.list_date, b.close_date, b.dom,
        b.list_price, b.original_price, b.sold_price,
        ROUND(b.sold_price / NULLIF(b.original_price, 0), 4) AS sold_to_original,
        b.bedrooms, b.full_baths, b.sqft, b.property_subtype, b.list_office_name,
        ROUND(c.p25_dom, 1) AS cohort_p25_dom,
        ROUND(c.median_dom, 1) AS cohort_median_dom,
        c.cohort_n,
        ROUND(c.median_sold_to_orig, 4) AS cohort_median_sold_to_orig
    FROM banded b
    JOIN cohorts c
      USING (close_year, _class, city, price_band)
    WHERE b.dom IS NOT NULL AND b.dom <= c.p25_dom
    ORDER BY b.close_date DESC, b.dom ASC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]
