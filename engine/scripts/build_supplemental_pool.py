"""Build compbird's SUPPLEMENTAL comp pool, mapped into the engine's `listings`
schema (data/mls_lookup.parquet columns), so `pick_comps` reads it UNCHANGED.

This is the maintained, production form of the proven scratch harness. It emits
`data/supplemental_listings.parquet`, which compbird's engine reads via the
`CMA_LISTINGS_PARQUET` override (see cma_compset._fast_listings_connection). It
does NOT touch `data/mls_lookup.parquet` (Ratifyly's pool), which is unaffected.

Source is the periodic public-records sales scrape (a parquet of VA sold rows with
lat/lng). Referenced via env so the vendor path isn't hard-baked here.

  python scripts/build_supplemental_pool.py

sqft-basis correction: comp `sqft` is scaled by SUPPLEMENTAL_SQFT_FACTOR to remove
the supplemental pool's systematic low bias (larger living-area basis + lower sold
prices vs MLS). CALIBRATED value = 0.76, chosen by the isolated backtest sweep
(scratchpad/calibrate_sqft.py) over 80 Montgomery dense-both sold subjects: it
drives median SIGNED error to ~0 (bias-free) at median |APE| ~12% (competitive with
the MLS pool's ~11.4%), where both bias and error are near their optimum. A uniform
scale leaves RELATIVE sqft-similarity (comp selection) intact and mainly corrects
the $/sqft value level. Re-calibrate if the source or its basis changes.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

_ROOT = Path(__file__).resolve().parent.parent
SRC = os.environ.get(
    "SUPPLEMENTAL_SOURCE_PARQUET",
    "C:/Users/zach/Desktop/va-parcels-pipeline/zillow_store/zillow_sales.parquet",
)
# Output is env-overridable so calibration sweeps can build throwaway pools
# without touching the published one (default unchanged).
OUT = Path(os.environ.get("SUPPLEMENTAL_OUT_PARQUET", str(_ROOT / "data" / "supplemental_listings.parquet")))
SQFT_FACTOR = float(os.environ.get("SUPPLEMENTAL_SQFT_FACTOR", "0.76"))  # backtest-calibrated (bias→0)

# home_type -> engine _class (LOT rows are filtered out below).
_CLASS_CASE = """
CASE
  WHEN home_type IN ('SINGLE_FAMILY','TOWNHOUSE','MANUFACTURED','CONDO') THEN 'RE_1'
  WHEN home_type = 'LOT' THEN 'LD_3'
  WHEN home_type IN ('MULTI_FAMILY','APARTMENT') THEN 'MF_2'
  ELSE 'RE_1'
END
"""


def main() -> None:
    if not Path(SRC).exists():
        raise SystemExit(f"Supplemental source parquet not found: {SRC}")

    con = duckdb.connect()
    # Map the supplemental sales rows onto the EXACT mls_lookup `listings` columns.
    # list_price / original_list_price / feed_dom are LITERAL NULL — the supplemental
    # source has NO real list price or DOM. (Do NOT copy sold_price into list_price:
    # that would make any sold-to-list market stat compute a fabricated 100% SP/LP.)
    # The comp valuation resolves off `sold_price` (_EFFECTIVE_PRICE = COALESCE(sold_price,
    # list_price)); the `source='supplemental'` flag lets market SELECTs filter these
    # rows OUT of list-price / DOM / absorption / sold-to-list metrics.
    sql = f"""
    SELECT
      'S' || CAST(zpid AS VARCHAR)                              AS listing_id,
      COALESCE(address, site_addr1)                            AS address,
      city                                                      AS city,
      COALESCE(county, jurisdiction)                            AS county,
      CAST(NULL AS VARCHAR)                                     AS subdivision,
      CAST(NULL AS VARCHAR)                                     AS high_school,
      'S' || CAST(zpid AS VARCHAR)                              AS parcel_id,
      'Closed'                                                  AS status_category,
      TRY_CAST(sold_date AS DATE)                               AS status_changed_at,
      CAST(NULL AS VARCHAR)                                     AS property_subtype,
      CAST(NULL AS DOUBLE)                                     AS list_price,
      CAST(NULL AS DOUBLE)                                     AS original_list_price,
      TRY_CAST(sold_price AS DOUBLE)                            AS sold_price,
      CAST(NULL AS INTEGER)                                     AS feed_dom,
      -- sqft-basis correction (see module docstring); backtest-calibrate P1.
      CAST(TRY_CAST(sfla AS DOUBLE) * {SQFT_FACTOR} AS INTEGER) AS sqft,
      CASE WHEN lot_size_sqft IS NOT NULL AND lot_size_sqft > 0
           THEN TRY_CAST(lot_size_sqft AS DOUBLE) / 43560.0
           ELSE NULL END                                        AS acres,
      CAST(NULL AS INTEGER)                                     AS year_built,
      TRY_CAST(beds AS DOUBLE)                                  AS bedrooms,
      TRY_CAST(baths AS DOUBLE)                                 AS full_baths,
      CAST(NULL AS DOUBLE)                                      AS half_baths,
      TRY_CAST(sold_date AS DATE)                               AS list_date,
      TRY_CAST(sold_date AS DATE)                               AS close_date,
      TRY_CAST(lat AS DOUBLE)                                   AS latitude,
      TRY_CAST(lng AS DOUBLE)                                   AS longitude,
      {_CLASS_CASE}                                             AS _class,
      CAST(NULL AS VARCHAR)                                     AS deed_last_sale_date,
      CAST(NULL AS DOUBLE)                                      AS deed_last_sale_price,
      CAST(NULL AS VARCHAR)                                     AS public_remarks,
      CAST(NULL AS VARCHAR)                                     AS agent_remarks,
      CAST(NULL AS VARCHAR)                                     AS appearance,
      'supplemental'                                           AS source,
      -- Raw (unfactored) living area + geography passthrough: lets calibration
      -- sweeps re-derive sqft at any factor in-memory (sqft_raw * f) and lets
      -- the per-region loader key on state/county without re-reading the source.
      TRY_CAST(sfla AS INTEGER)                                 AS sqft_raw,
      upper(state)                                              AS state,
      fips3                                                     AS fips3
    FROM read_parquet('{Path(SRC).as_posix()}')
    WHERE TRY_CAST(sold_price AS DOUBLE) >= 10000
      AND home_type <> 'LOT'
      AND lat IS NOT NULL AND lng IS NOT NULL
    """

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_name(OUT.name + ".tmp")
    con.execute(f"COPY ({sql}) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(tmp, OUT)  # atomic publish — a reader never sees a half-written pool

    n = con.execute(f"SELECT count(*) FROM read_parquet('{OUT.as_posix()}')").fetchone()[0]
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"WROTE {OUT}  rows={n:,}  size={size_mb:.1f}MB  sqft_factor={SQFT_FACTOR}")


if __name__ == "__main__":
    main()
