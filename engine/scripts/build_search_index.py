"""
Build the address typeahead search index: a prebuilt SQLite + FTS5 file the
Next app queries IN-NODE (better-sqlite3) in <2 ms, with zero Python spawn.

Replaces the old per-keystroke `python -c` cold-spawn search path. Run on deploy
and after every data refresh (wire into refresh.py / the hourly task).

    python scripts/build_search_index.py

Output: data/search_index.sqlite  (built atomically via a .tmp + replace)

Schema:
  properties(id, source, rank0, address, city, county, parcel_id, acres, sqft,
             year_built, bedrooms, full_baths, half_baths, owner, subdivision,
             last_sale_price, last_sale_date, status, list_price, list_date,
             listing_id, latitude, longitude, search_text)
  properties_fts = FTS5(search_text) external-content over properties, with
                   prefix indexes (2,3,4) so "123 ma" matches instantly.

Row policy:
  - MLS listings (mls_lookup.parquet) — always included; ranked above parcels.
    rank0: 0 active, 1 pending/contingent, 2 closed/sold, 3 other.
  - Parcels (parcel_lookup.parquet) — included only when site_addr1 is non-empty
    AND the parcel_id is NOT already an MLS listing (dedupe → the MLS row wins,
    since it carries lat/lng + richer fields). rank0 = 4.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MLS = DATA / "mls_lookup.parquet"
PARCELS = DATA / "parcel_lookup.parquet"
OUT = DATA / "search_index.sqlite"
TMP = DATA / "search_index.sqlite.tmp"

# One UNION query produces the normalized, deduped row set. concat_ws skips NULLs
# so the FTS search_text is clean. CAST dates to text for portable JSON later.
UNION_SQL = f"""
WITH mls AS (
  SELECT
    'mls' AS source,
    CASE lower(coalesce(status_category,''))
      WHEN 'active' THEN 0
      WHEN 'coming soon' THEN 0
      WHEN 'pending' THEN 1
      WHEN 'contingent' THEN 1
      WHEN 'under contract' THEN 1
      WHEN 'closed' THEN 2
      WHEN 'sold' THEN 2
      ELSE 3
    END AS rank0,
    trim(address) AS address,
    city, county, parcel_id,
    acres, sqft, year_built, bedrooms, full_baths, half_baths,
    CAST(NULL AS VARCHAR) AS owner,
    subdivision,
    coalesce(sold_price, deed_last_sale_price) AS last_sale_price,
    CAST(coalesce(close_date, status_changed_at) AS VARCHAR) AS last_sale_date,
    lower(coalesce(nullif(trim(status_category), ''), 'off-market')) AS status,
    list_price,
    CAST(list_date AS VARCHAR) AS list_date,
    listing_id,
    latitude, longitude
  FROM read_parquet('{MLS.as_posix()}')
  WHERE address IS NOT NULL AND length(trim(address)) > 0
),
parcels AS (
  SELECT
    'parcel' AS source,
    4 AS rank0,
    trim(coalesce(site_addr1, '')
         || CASE WHEN site_addr2 IS NOT NULL AND length(trim(site_addr2)) > 0
                 THEN ' ' || trim(site_addr2) ELSE '' END) AS address,
    CAST(NULL AS VARCHAR) AS city,
    jurisdiction AS county,
    parcel_id,
    acres, sfla AS sqft, year_built, bedrooms, full_baths, half_baths,
    owner1 AS owner,
    subd_name AS subdivision,
    last_sale_price,
    CAST(last_sale_date AS VARCHAR) AS last_sale_date,
    'off-market' AS status,
    CAST(NULL AS DOUBLE) AS list_price,
    CAST(NULL AS VARCHAR) AS list_date,
    CAST(NULL AS VARCHAR) AS listing_id,
    CAST(NULL AS DOUBLE) AS latitude,
    CAST(NULL AS DOUBLE) AS longitude
  FROM read_parquet('{PARCELS.as_posix()}')
  WHERE site_addr1 IS NOT NULL AND length(trim(site_addr1)) > 0
    AND parcel_id NOT IN (
      SELECT parcel_id FROM read_parquet('{MLS.as_posix()}')
      WHERE parcel_id IS NOT NULL AND length(trim(parcel_id)) > 0
    )
)
SELECT *, lower(concat_ws(' ', address, city, county, subdivision, owner, parcel_id)) AS search_text
FROM (SELECT * FROM mls UNION ALL SELECT * FROM parcels)
"""

COLUMNS = [
    "source", "rank0", "address", "city", "county", "parcel_id",
    "acres", "sqft", "year_built", "bedrooms", "full_baths", "half_baths",
    "owner", "subdivision", "last_sale_price", "last_sale_date", "status",
    "list_price", "list_date", "listing_id", "latitude", "longitude", "search_text",
]


def main() -> int:
    t0 = time.time()
    if not MLS.exists() or not PARCELS.exists():
        print(f"[build_search_index] missing parquet(s): {MLS.exists()=} {PARCELS.exists()=}", file=sys.stderr)
        return 1

    if TMP.exists():
        TMP.unlink()

    con = sqlite3.connect(TMP)
    con.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;
        CREATE TABLE properties (
          id INTEGER PRIMARY KEY,
          source TEXT, rank0 INTEGER,
          address TEXT, city TEXT, county TEXT, parcel_id TEXT,
          acres REAL, sqft INTEGER, year_built INTEGER,
          bedrooms REAL, full_baths REAL, half_baths REAL,
          owner TEXT, subdivision TEXT,
          last_sale_price REAL, last_sale_date TEXT,
          status TEXT, list_price REAL, list_date TEXT, listing_id TEXT,
          latitude REAL, longitude REAL,
          search_text TEXT
        );
        """
    )

    placeholders = ",".join("?" for _ in COLUMNS)
    insert_sql = f"INSERT INTO properties ({','.join(COLUMNS)}) VALUES ({placeholders})"

    duck = duckdb.connect(":memory:")
    cur = duck.execute(UNION_SQL)
    total = 0
    con.execute("BEGIN")
    while True:
        batch = cur.fetchmany(50_000)
        if not batch:
            break
        con.executemany(insert_sql, batch)
        total += len(batch)
    con.execute("COMMIT")
    duck.close()

    # FTS5 external-content index. prefix='2 3 4' so 2-4 char prefixes are indexed
    # (instant "12", "123", "123 m" matching). porter+unicode61 would over-stem
    # street names, so use the default unicode61 tokenizer (case/diacritic fold).
    con.executescript(
        """
        -- Full index over ALL rows (MLS + parcels) — the fallback for areas with
        -- no MLS coverage and for parcel-id lookups.
        CREATE VIRTUAL TABLE properties_fts USING fts5(
          search_text,
          content='properties',
          content_rowid='id',
          prefix='2 3 4'
        );
        INSERT INTO properties_fts(rowid, search_text) SELECT id, search_text FROM properties;

        -- MLS-ONLY index (~44k rows). Queried FIRST so a common bare token like a
        -- city/street name returns in single-digit ms instead of bm25-ranking
        -- across millions of parcel matches. Parcels only supplement when MLS
        -- yields fewer than the requested limit. Also encodes the MLS-first
        -- accuracy preference: real listings (with lat/lng) surface above raw parcels.
        CREATE VIRTUAL TABLE mls_fts USING fts5(
          search_text,
          content='properties',
          content_rowid='id',
          prefix='2 3 4'
        );
        INSERT INTO mls_fts(rowid, search_text) SELECT id, search_text FROM properties WHERE source = 'mls';

        CREATE INDEX idx_props_rank ON properties(rank0);
        PRAGMA optimize;
        """
    )
    con.execute("INSERT INTO properties_fts(properties_fts) VALUES('optimize')")
    con.execute("INSERT INTO mls_fts(mls_fts) VALUES('optimize')")
    con.commit()

    by_source = dict(con.execute("SELECT source, count(*) FROM properties GROUP BY source").fetchall())
    con.close()

    os.replace(TMP, OUT)
    size_mb = OUT.stat().st_size / 1e6
    print(
        f"[build_search_index] {total:,} rows "
        f"(mls={by_source.get('mls', 0):,}, parcel={by_source.get('parcel', 0):,}) "
        f"-> {OUT.name} {size_mb:.1f} MB in {time.time() - t0:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
