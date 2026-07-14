"""DOM cohort tables — median/p25/p75 days on market by cohort.

Cohort = (city, _class, price_band, year). The metric is `feed_cdom` (cumulative
DOM across re-listings, the "true" days on market) when present, falling back
to `feed_dom` when CDOM is missing.

Output: outputs/mls_analytics/dom_by_cohort.csv plus an optional `subdivision`
roll-up.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .db import connect


def _build_band_map(con: duckdb.DuckDBPyConnection) -> None:
    """Register a SQL function `price_band(price, class)` returning the band label."""
    from .bands import BANDS_BY_CLASS, label

    # Build a per-class CASE statement once. For DuckDB, easier to materialize
    # a small bands table and join.
    rows = []
    for cls, bands in BANDS_BY_CLASS.items():
        for lo, hi in bands:
            rows.append((cls, float(lo), float(hi) if hi != float("inf") else 1e15, label(lo, hi)))
    con.execute("""
        CREATE OR REPLACE TABLE price_bands (
            class_id VARCHAR, lo DOUBLE, hi DOUBLE, band VARCHAR
        )
    """)
    con.executemany(
        "INSERT INTO price_bands VALUES (?, ?, ?, ?)",
        rows,
    )


SOLD_BASE_SQL = """
WITH sold AS (
    SELECT
        listing_id,
        _class,
        UPPER(TRIM(city)) AS city,
        UPPER(TRIM(county)) AS county,
        TRY_CAST(list_price AS DOUBLE) AS list_price,
        TRY_CAST(original_list_price AS DOUBLE) AS original_price,
        TRY_CAST(sold_price AS DOUBLE) AS sold_price,
        TRY_CAST(feed_dom AS INT) AS dom,
        TRY_CAST(feed_cdom AS INT) AS cdom,
        TRY_CAST(close_date AS DATE) AS close_date,
        TRY_CAST(list_date AS DATE) AS list_date,
        property_subtype,
        bedrooms, full_baths, half_baths,
        TRY_CAST(sqft AS DOUBLE) AS sqft,
        zip,
    FROM listings
    WHERE status_category = 'Closed'
      AND TRY_CAST(sold_price AS DOUBLE) > 0
      AND TRY_CAST(list_price AS DOUBLE) > 0
      AND TRY_CAST(close_date AS DATE) IS NOT NULL
)
"""


def dom_by_cohort(con: duckdb.DuckDBPyConnection, *, year_min: int = 2010) -> "duckdb.DuckDBPyRelation":
    """Median/p25/p75 DOM per (year, class, city, band). Returns a DuckDB relation."""
    sql = SOLD_BASE_SQL + f"""
    SELECT
        EXTRACT(YEAR FROM close_date) AS close_year,
        _class,
        city,
        b.band AS price_band,
        COUNT(*) AS n,
        ROUND(MEDIAN(COALESCE(cdom, dom)), 1) AS dom_median,
        ROUND(QUANTILE_CONT(COALESCE(cdom, dom), 0.25), 1) AS dom_p25,
        ROUND(QUANTILE_CONT(COALESCE(cdom, dom), 0.75), 1) AS dom_p75,
        ROUND(MEDIAN(sold_price), 0) AS median_sold_price,
        ROUND(MEDIAN(sold_price / NULLIF(original_price, 0)), 4) AS median_sold_to_original,
        ROUND(MEDIAN(sold_price / NULLIF(list_price, 0)), 4) AS median_sold_to_list
    FROM sold s
    LEFT JOIN price_bands b
      ON b.class_id = s._class AND s.list_price >= b.lo AND s.list_price < b.hi
    WHERE EXTRACT(YEAR FROM close_date) >= {year_min}
    GROUP BY 1, 2, 3, 4
    HAVING n >= 3
    ORDER BY close_year DESC, _class, city, price_band
    """
    return con.sql(sql)


def write_dom_csv(out_path: Path, *, year_min: int = 2010) -> int:
    con = connect()
    _build_band_map(con)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({dom_by_cohort(con, year_min=year_min).sql_query()}) "
            f"TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    n = con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]
    return n


def write_dom_by_subdivision_csv(out_path: Path, *, year_min: int = 2018, min_sales: int = 3) -> int:
    con = connect()
    _build_band_map(con)
    sql = SOLD_BASE_SQL + f"""
    SELECT
        UPPER(TRIM(city)) AS city,
        UPPER(TRIM(subdivision)) AS subdivision,
        _class,
        COUNT(*) AS n_sales_5y,
        ROUND(MEDIAN(COALESCE(cdom, dom)), 1) AS dom_median,
        ROUND(QUANTILE_CONT(COALESCE(cdom, dom), 0.25), 1) AS dom_p25,
        ROUND(QUANTILE_CONT(COALESCE(cdom, dom), 0.75), 1) AS dom_p75,
        ROUND(MEDIAN(sold_price), 0) AS median_sold_price,
        ROUND(MEDIAN(sold_price / NULLIF(original_price, 0)), 4) AS median_sold_to_original
    FROM sold
    JOIN listings USING (listing_id)
    WHERE EXTRACT(YEAR FROM close_date) >= {year_min}
      AND subdivision IS NOT NULL AND subdivision != ''
    GROUP BY 1, 2, 3
    HAVING n_sales_5y >= {min_sales}
    ORDER BY n_sales_5y DESC
    """
    # The above join is awkward; rewrite without it
    sql = f"""
    WITH sold AS (
        SELECT
            UPPER(TRIM(city)) AS city,
            UPPER(TRIM(subdivision)) AS subdivision,
            _class,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            TRY_CAST(original_list_price AS DOUBLE) AS original_price,
            COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
            TRY_CAST(close_date AS DATE) AS close_date
        FROM listings
        WHERE status_category = 'Closed'
          AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND subdivision IS NOT NULL AND subdivision != ''
    )
    SELECT
        city, subdivision, _class,
        COUNT(*) AS n_sales,
        ROUND(MEDIAN(dom), 1) AS dom_median,
        ROUND(QUANTILE_CONT(dom, 0.25), 1) AS dom_p25,
        ROUND(QUANTILE_CONT(dom, 0.75), 1) AS dom_p75,
        ROUND(MEDIAN(sold_price), 0) AS median_sold_price,
        ROUND(MEDIAN(sold_price / NULLIF(original_price, 0)), 4) AS median_sold_to_original
    FROM sold
    WHERE EXTRACT(YEAR FROM close_date) >= {year_min}
    GROUP BY 1, 2, 3
    HAVING n_sales >= {min_sales}
    ORDER BY n_sales DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]
