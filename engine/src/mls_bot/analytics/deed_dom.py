"""Deed-aware analytics — extends DOM/price analysis with county deed records.

Two new analytics:

1. expired_then_sold_offmls
   Listings that *expired or were withdrawn from the MLS* but later showed up
   in deed records as sold. Reveals "this didn't sell at $X on MLS, but did
   sell off-market for $Y after Z months". Strong signal for forced/private
   sales and pricing patterns where the original list was too aggressive.

2. price_trends_with_deeds
   Median sold price by city × class × close_year, UNION-ing the MLS Closed
   listings with the standalone deed sale corpus. Extends price-trend coverage
   back to the 1940s for Montgomery / Blacksburg, ~1990 for Floyd / Giles /
   Pulaski. Note: deeds carry no DOM, so this output is price-only; see
   dom.py for DOM analytics (still MLS-only).
"""

from __future__ import annotations

from pathlib import Path

from .db import connect


def write_expired_then_sold_csv(out_path: Path, *, year_min: int = 2010) -> int:
    """Listings whose MLS history is Expired/Withdrawn but later sold per deed."""
    con = connect()
    sql = f"""
    WITH expired AS (
        SELECT
            listing_id, _class,
            UPPER(TRIM(city)) AS city,
            address, subdivision,
            TRY_CAST(list_price AS DOUBLE) AS list_price,
            TRY_CAST(original_list_price AS DOUBLE) AS original_price,
            COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom_at_expire,
            TRY_CAST(list_date AS DATE) AS list_date,
            TRY_CAST(off_market_date AS DATE) AS off_market_date,
            TRY_CAST(close_date AS DATE) AS close_date,
            TRY_CAST(deed_last_sale_date AS DATE) AS deed_sale_date,
            TRY_CAST(deed_last_sale_price AS DOUBLE) AS deed_sale_price,
            bedrooms, full_baths, TRY_CAST(sqft AS DOUBLE) AS sqft,
            property_subtype, list_office_name,
            status_category
        FROM listings
        WHERE status_category IN ('Expired/Cancelled', 'Withdrawn')
          AND deed_last_sale_date IS NOT NULL
          AND TRY_CAST(deed_last_sale_price AS DOUBLE) > 5000
          AND TRY_CAST(list_date AS DATE) >= '{year_min}-01-01'
    )
    SELECT
        listing_id, _class, status_category,
        city, address, subdivision,
        list_date, off_market_date,
        deed_sale_date, deed_sale_price,
        list_price, original_price,
        ROUND(deed_sale_price / NULLIF(original_price, 0), 4) AS deed_to_original_ratio,
        DATEDIFF('day', off_market_date, deed_sale_date) AS days_offmls_to_deed,
        DATEDIFF('day', list_date, deed_sale_date) AS days_listed_to_deed,
        dom_at_expire,
        bedrooms, full_baths, sqft, property_subtype, list_office_name
    FROM expired
    WHERE deed_sale_date >= COALESCE(off_market_date, list_date)
      -- Only keep cases where the deed sale is plausibly the same listing —
      -- not a stale prior sale on the same parcel.
    ORDER BY deed_sale_date DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def write_price_trends_csv(out_path: Path, *, year_min: int = 1990) -> int:
    """Median sold price by city × class × year, MLS Closed UNION deed sales.

    Deduplicates: when a deed-only row matches an MLS listing_id by parcel +
    close_date proximity, we keep only the MLS row. (Prevents double-counting
    in 2023+ where both sources have the same sale.)
    """
    con = connect()
    has_deeds = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'deed_sales' LIMIT 1"
    ).fetchone() is not None

    if not has_deeds:
        # MLS only
        sql = f"""
        SELECT
            EXTRACT(YEAR FROM TRY_CAST(close_date AS DATE)) AS year,
            UPPER(TRIM(city)) AS city,
            _class,
            'mls' AS source,
            COUNT(*) AS n,
            ROUND(MEDIAN(TRY_CAST(sold_price AS DOUBLE)), 0) AS median_sold,
            ROUND(QUANTILE_CONT(TRY_CAST(sold_price AS DOUBLE), 0.25), 0) AS p25_sold,
            ROUND(QUANTILE_CONT(TRY_CAST(sold_price AS DOUBLE), 0.75), 0) AS p75_sold
        FROM listings
        WHERE status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) IS NOT NULL
        GROUP BY 1, 2, 3
        HAVING COUNT(*) >= 3 AND year >= {year_min}
        ORDER BY year DESC, city, _class
        """
    else:
        # MLS UNION deed (deed bag includes parcels that may also be in MLS;
        # we de-dup by tagging deed rows with parcel+year and excluding any
        # parcel+year already covered by MLS).
        sql = f"""
        WITH mls_sold AS (
            SELECT
                EXTRACT(YEAR FROM TRY_CAST(close_date AS DATE)) AS year,
                parcel_id,
                UPPER(TRIM(city)) AS city,
                _class,
                TRY_CAST(sold_price AS DOUBLE) AS price
            FROM listings
            WHERE status_category='Closed'
              AND TRY_CAST(sold_price AS DOUBLE) > 0
              AND TRY_CAST(close_date AS DATE) IS NOT NULL
        ),
        deed_only AS (
            SELECT
                EXTRACT(YEAR FROM TRY_CAST(deed_last_sale_date AS DATE)) AS year,
                parcel_id,
                UPPER(TRIM(deed_county)) AS city,  -- best proxy when we don't have deed-side city
                'DEED' AS _class,
                TRY_CAST(deed_last_sale_price AS DOUBLE) AS price
            FROM deed_sales
            WHERE deed_arms_length = TRUE
              AND TRY_CAST(deed_last_sale_price AS DOUBLE) > 5000
              AND TRY_CAST(deed_last_sale_date AS DATE) IS NOT NULL
        ),
        deed_dedup AS (
            -- drop deed rows whose (parcel_id, year) is already in MLS
            SELECT d.* FROM deed_only d
            LEFT JOIN mls_sold m
              ON d.parcel_id = m.parcel_id AND d.year = m.year
            WHERE m.parcel_id IS NULL
        ),
        combined AS (
            SELECT year, city, _class, 'mls' AS source, price FROM mls_sold
            UNION ALL
            SELECT year, city, _class, 'deed' AS source, price FROM deed_dedup
        )
        SELECT
            year, city, _class, source,
            COUNT(*) AS n,
            ROUND(MEDIAN(price), 0) AS median_sold,
            ROUND(QUANTILE_CONT(price, 0.25), 0) AS p25_sold,
            ROUND(QUANTILE_CONT(price, 0.75), 0) AS p75_sold
        FROM combined
        WHERE year >= {year_min}
        GROUP BY 1, 2, 3, 4
        HAVING n >= 3
        ORDER BY year DESC, city, _class, source
        """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]
