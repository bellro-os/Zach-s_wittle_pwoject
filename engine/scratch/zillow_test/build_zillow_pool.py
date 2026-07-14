"""Build an ISOLATED Zillow comp pool mapped into the engine's `listings` schema.

Reads the VA Zillow sold parquet and writes a NEW parquet whose columns match
the DuckDB `listings` view that `cma_compset._fast_listings_connection` exposes
(data/mls_lookup.parquet schema), so `pick_comps` can read it UNCHANGED.

Nothing here touches production data — output goes only to scratch/zillow_test/.
"""
from pathlib import Path
import duckdb

SRC = "C:/Users/zach/Desktop/va-parcels-pipeline/zillow_store/zillow_sales.parquet"
OUT = Path(__file__).resolve().parent / "zillow_listings.parquet"

# home_type -> engine _class
#   SINGLE_FAMILY/TOWNHOUSE/MANUFACTURED/CONDO -> RE_1 (residential improved)
#   LOT  -> LD_3 (land)   [we also FILTER lots out per spec]
#   MULTI_FAMILY/APARTMENT -> MF_2
CLASS_CASE = """
CASE
  WHEN home_type IN ('SINGLE_FAMILY','TOWNHOUSE','MANUFACTURED','CONDO') THEN 'RE_1'
  WHEN home_type = 'LOT' THEN 'LD_3'
  WHEN home_type IN ('MULTI_FAMILY','APARTMENT') THEN 'MF_2'
  ELSE 'RE_1'
END
"""

con = duckdb.connect()

# Map Zillow -> exact MLS `listings` column set (data/mls_lookup.parquet).
# sold_price is COALESCED into list_price + original_list_price so the engine's
# _EFFECTIVE_PRICE = COALESCE(sold_price, list_price) always resolves, and so the
# sqft/price soft-bounds in _pull_candidates have a price to bound on.
sql = f"""
SELECT
  'Z' || CAST(zpid AS VARCHAR)                              AS listing_id,
  COALESCE(address, site_addr1)                            AS address,
  city                                                      AS city,
  COALESCE(county, jurisdiction)                            AS county,
  CAST(NULL AS VARCHAR)                                     AS subdivision,
  CAST(NULL AS VARCHAR)                                     AS high_school,
  'Z' || CAST(zpid AS VARCHAR)                              AS parcel_id,
  'Closed'                                                  AS status_category,
  TRY_CAST(sold_date AS DATE)                               AS status_changed_at,
  CAST(NULL AS VARCHAR)                                     AS property_subtype,
  TRY_CAST(sold_price AS DOUBLE)                            AS list_price,
  TRY_CAST(sold_price AS DOUBLE)                            AS original_list_price,
  TRY_CAST(sold_price AS DOUBLE)                            AS sold_price,
  CAST(NULL AS INTEGER)                                     AS feed_dom,
  TRY_CAST(sfla AS INTEGER)                                 AS sqft,
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
  {CLASS_CASE}                                              AS _class,
  CAST(NULL AS VARCHAR)                                     AS deed_last_sale_date,
  CAST(NULL AS DOUBLE)                                      AS deed_last_sale_price,
  CAST(NULL AS VARCHAR)                                     AS public_remarks,
  CAST(NULL AS VARCHAR)                                     AS agent_remarks,
  CAST(NULL AS VARCHAR)                                     AS appearance,
  'zillow'                                                  AS source
FROM read_parquet('{SRC}')
WHERE TRY_CAST(sold_price AS DOUBLE) >= 10000      -- drop sold_price < 10000
  AND home_type <> 'LOT'                            -- drop LOT
  AND lat IS NOT NULL AND lng IS NOT NULL
"""

con.execute(f"COPY ({sql}) TO '{OUT.as_posix()}' (FORMAT PARQUET)")

n = con.execute(f"SELECT count(*) FROM read_parquet('{OUT.as_posix()}')").fetchone()[0]
print("WROTE", OUT, "rows=", n)
print(con.execute(
    f"SELECT _class, count(*) c FROM read_parquet('{OUT.as_posix()}') GROUP BY 1 ORDER BY 2 DESC"
).fetchdf().to_string())
print("--- sample ---")
print(con.execute(
    f"SELECT listing_id,address,city,county,sold_price,close_date,bedrooms,full_baths,sqft,acres,latitude,longitude,_class "
    f"FROM read_parquet('{OUT.as_posix()}') LIMIT 5"
).fetchdf().to_string())
