"""Price-cut waterfall — how often listings cut price, by how much, when.

Uses two sources:
  1. Direct: original_list_price vs final list_price/sold_price on each listing
     (always available; works even on first run).
  2. History log (data/mls/listings_history.jsonl) for time-series: time-to-
     first-cut, intermediate cut amounts. Sparse until log accumulates.

Outputs:
  outputs/mls_analytics/price_cut_waterfall.csv  — cohort summary
  outputs/mls_analytics/listings_with_cuts.csv   — per-listing detail (closed)
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


def write_listings_with_cuts_csv(out_path: Path, *, year_min: int = 2023) -> int:
    """Closed listings whose original_list_price > final list_price (=did cut)."""
    con = connect()
    sql = f"""
    SELECT
        listing_id, _class,
        UPPER(TRIM(city)) AS city,
        address, subdivision,
        TRY_CAST(original_list_price AS DOUBLE) AS original_price,
        TRY_CAST(list_price AS DOUBLE) AS final_list_price,
        TRY_CAST(sold_price AS DOUBLE) AS sold_price,
        ROUND(TRY_CAST(list_price AS DOUBLE) - TRY_CAST(original_list_price AS DOUBLE), 0) AS list_cut_dollars,
        ROUND((TRY_CAST(list_price AS DOUBLE) - TRY_CAST(original_list_price AS DOUBLE))
              / NULLIF(TRY_CAST(original_list_price AS DOUBLE), 0) * 100, 2) AS list_cut_pct,
        ROUND(TRY_CAST(sold_price AS DOUBLE) - TRY_CAST(original_list_price AS DOUBLE), 0) AS net_total_cut,
        ROUND((TRY_CAST(sold_price AS DOUBLE) - TRY_CAST(original_list_price AS DOUBLE))
              / NULLIF(TRY_CAST(original_list_price AS DOUBLE), 0) * 100, 2) AS net_total_cut_pct,
        TRY_CAST(list_date AS DATE) AS list_date,
        TRY_CAST(close_date AS DATE) AS close_date,
        COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
        list_office_name
    FROM listings
    WHERE status_category = 'Closed'
      AND TRY_CAST(close_date AS DATE) >= '{year_min}-01-01'
      AND TRY_CAST(original_list_price AS DOUBLE) > 0
      AND TRY_CAST(list_price AS DOUBLE) < TRY_CAST(original_list_price AS DOUBLE)
    ORDER BY list_cut_pct ASC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def write_price_cut_waterfall_csv(out_path: Path, *, year_min: int = 2023, min_cohort: int = 10) -> int:
    """Cohort summary: % that cut price, median cut size, median DOM cut vs no-cut."""
    con = connect()
    _build_band_map(con)
    sql = f"""
    WITH closed AS (
        SELECT
            _class, UPPER(TRIM(city)) AS city,
            TRY_CAST(original_list_price AS DOUBLE) AS orig,
            TRY_CAST(list_price AS DOUBLE) AS final_list,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
            TRY_CAST(close_date AS DATE) AS close_date
        FROM listings
        WHERE status_category='Closed'
          AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) >= '{year_min}-01-01'
          AND TRY_CAST(original_list_price AS DOUBLE) > 0
    ),
    banded AS (
        SELECT c.*, b.band AS price_band,
               (final_list < orig) AS did_cut_list,
               (sold_price < orig) AS did_undersell
        FROM closed c
        LEFT JOIN price_bands b
          ON b.class_id = c._class AND c.orig >= b.lo AND c.orig < b.hi
    )
    SELECT
        _class, city, price_band,
        COUNT(*) AS n,
        SUM(CASE WHEN did_cut_list THEN 1 ELSE 0 END) AS n_with_list_cut,
        ROUND(SUM(CASE WHEN did_cut_list THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS pct_with_list_cut,
        ROUND(MEDIAN(CASE WHEN did_cut_list THEN (final_list - orig) END), 0) AS median_list_cut_dollars,
        ROUND(MEDIAN(CASE WHEN did_cut_list THEN (final_list - orig) / orig * 100 END), 2) AS median_list_cut_pct,
        ROUND(MEDIAN(CASE WHEN did_cut_list THEN dom END), 1) AS median_dom_with_cut,
        ROUND(MEDIAN(CASE WHEN NOT did_cut_list THEN dom END), 1) AS median_dom_no_cut,
        ROUND(MEDIAN((sold_price - orig) / NULLIF(orig, 0) * 100), 2) AS median_net_off_orig_pct
    FROM banded
    GROUP BY 1, 2, 3
    HAVING n >= {min_cohort}
    ORDER BY n DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]
