"""List-to-sold spread — how much sellers left on the table (or didn't).

Computes (sold_price - original_list_price) / original_list_price by cohort.
Negative = sold below ask; positive = bidding war.

Output: outputs/mls_analytics/list_to_sold_spread.csv
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


def write_spread_csv(out_path: Path, *, year_min: int = 2018, min_cohort: int = 5) -> int:
    con = connect()
    _build_band_map(con)
    sql = f"""
    WITH sold AS (
        SELECT
            UPPER(TRIM(city)) AS city,
            _class,
            TRY_CAST(original_list_price AS DOUBLE) AS original_price,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            EXTRACT(YEAR FROM TRY_CAST(close_date AS DATE)) AS close_year
        FROM listings
        WHERE status_category='Closed'
          AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(original_list_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) IS NOT NULL
    ),
    banded AS (
        SELECT s.*, b.band AS price_band, (s.sold_price - s.original_price) / s.original_price AS spread_pct
        FROM sold s
        LEFT JOIN price_bands b
          ON b.class_id = s._class AND s.original_price >= b.lo AND s.original_price < b.hi
    )
    SELECT
        close_year, _class, city, price_band,
        COUNT(*) AS n,
        ROUND(MEDIAN(spread_pct) * 100, 2) AS median_spread_pct,
        ROUND(QUANTILE_CONT(spread_pct, 0.25) * 100, 2) AS p25_spread_pct,
        ROUND(QUANTILE_CONT(spread_pct, 0.75) * 100, 2) AS p75_spread_pct,
        ROUND(MEDIAN(original_price), 0) AS median_original_price,
        ROUND(MEDIAN(sold_price), 0) AS median_sold_price,
        ROUND(SUM(CASE WHEN sold_price >= original_price THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS pct_at_or_over_ask
    FROM banded
    WHERE close_year >= {year_min}
    GROUP BY 1, 2, 3, 4
    HAVING n >= {min_cohort}
    ORDER BY close_year DESC, _class, city, price_band
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]
