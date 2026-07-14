"""Build a single combined Parquet file for fast property lookup.

Reads every county parcel JSONL listed in
:data:`mls_bot.analytics.owner_dedup.PARCEL_FILES_NRV` and
``PARCEL_FILES_EXTENDED``, projects to the columns the typeahead +
``resolve_subject`` need, and writes one Parquet file at
``data/parcel_lookup.parquet``.

The point is to make DuckDB's cold-start fast in the dashboard API path
(every typeahead keystroke spawns a new Python process). On JSONL via
``read_json_auto`` the cold-start is ~20 s; reading a single Parquet
file is well under a second.

Run via::

    python scripts/build_parcel_lookup.py

Re-run any time the underlying parcel JSONLs are refreshed (after a
quarterly assessor pull). Roughly one minute end-to-end.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Make `mls_bot.*` importable when invoked from the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import duckdb  # noqa: E402

from mls_bot.analytics.owner_dedup import (  # noqa: E402
    PARCEL_FILES_EXTENDED,
    PARCEL_FILES_NRV,
)


OUT_PATH = _PROJECT_ROOT / "data" / "parcel_lookup.parquet"
MLS_OUT_PATH = _PROJECT_ROOT / "data" / "mls_lookup.parquet"


def _pick_listings_jsonl() -> Path:
    """Mirror db.connect()'s preference for the richest listings source."""
    candidates = [
        _PROJECT_ROOT / "data" / "mls" / "listings_plus_deeds.jsonl",
        _PROJECT_ROOT / "data" / "mls" / "listings_with_parcels.jsonl",
        _PROJECT_ROOT / "data" / "mls" / "listings.jsonl",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]  # let the caller fail loudly downstream


def _build_mls_lookup(con) -> None:
    """Emit a slim Parquet of the searchable MLS columns.

    This lets the dashboard typeahead surface Active / Closed listings
    sub-second, which is otherwise impossible because the full listings
    JSONL is 200 MB and takes ~9 s to load on each cold start.

    The projection covers every column ``_pull_candidates`` reads (high_school,
    original_list_price, feed_dom, property_subtype) so the comp scorer can
    also use this parquet as its candidate pool without paying the JSONL cost.
    """
    src = _pick_listings_jsonl()
    if not src.exists():
        print(f"  SKIP: {src} not found — MLS lookup parquet will not be built")
        return
    t0 = time.perf_counter()
    # Write to a temp sibling then atomically swap it into place. The live engine
    # reads this parquet per-request via DuckDB read_parquet(), so an in-place COPY
    # can expose a half-written file mid-refresh (wrong comps or a hard read error).
    # Mirrors build_search_index's os.replace(TMP, OUT); a second read-only engine
    # instance reading the same pool makes the atomic swap mandatory, not optional.
    tmp_out = MLS_OUT_PATH.with_name(MLS_OUT_PATH.name + ".tmp")
    con.execute(
        f"""COPY (
            SELECT
                CAST(listing_id AS VARCHAR) AS listing_id,
                TRY_CAST(address AS VARCHAR) AS address,
                TRY_CAST(city AS VARCHAR) AS city,
                TRY_CAST(county AS VARCHAR) AS county,
                TRY_CAST(subdivision AS VARCHAR) AS subdivision,
                TRY_CAST(high_school AS VARCHAR) AS high_school,
                CAST(parcel_id AS VARCHAR) AS parcel_id,
                TRY_CAST(status_category AS VARCHAR) AS status_category,
                TRY_CAST(status_changed_at AS DATE) AS status_changed_at,
                TRY_CAST(property_subtype AS VARCHAR) AS property_subtype,
                TRY_CAST(list_price AS DOUBLE) AS list_price,
                TRY_CAST(original_list_price AS DOUBLE) AS original_list_price,
                TRY_CAST(sold_price AS DOUBLE) AS sold_price,
                TRY_CAST(feed_dom AS INTEGER) AS feed_dom,
                TRY_CAST(sqft AS INTEGER) AS sqft,
                TRY_CAST(acres AS DOUBLE) AS acres,
                TRY_CAST(year_built AS INTEGER) AS year_built,
                TRY_CAST(bedrooms AS DOUBLE) AS bedrooms,
                TRY_CAST(full_baths AS DOUBLE) AS full_baths,
                TRY_CAST(half_baths AS DOUBLE) AS half_baths,
                TRY_CAST(list_date AS DATE) AS list_date,
                TRY_CAST(close_date AS DATE) AS close_date,
                TRY_CAST(latitude AS DOUBLE) AS latitude,
                TRY_CAST(longitude AS DOUBLE) AS longitude,
                TRY_CAST(_class AS VARCHAR) AS _class,
                TRY_CAST(deed_last_sale_date AS VARCHAR) AS deed_last_sale_date,
                TRY_CAST(deed_last_sale_price AS DOUBLE) AS deed_last_sale_price,
                TRY_CAST(public_remarks AS VARCHAR) AS public_remarks,
                TRY_CAST(agent_remarks AS VARCHAR) AS agent_remarks,
                -- LFD_Appearance: free, 91%-populated condition signal from the
                -- raw Paragon record ("Very Good", "Remodeled", "Average"...).
                TRY_CAST(_raw['LFD_Appearance_2'] AS VARCHAR) AS appearance,
                -- D1 field landing (accuracy deep-dive 2026-07): every field
                -- below is ~100%-populated on RE_1 Closed rows upstream; fills
                -- look lower parquet-wide because Expired/Cancelled and non-RE_1
                -- classes leave them blank.
                TRY_CAST(_raw['LM_Dec_59'] AS DOUBLE) AS total_fin_sqft,
                TRY_CAST(_raw['LM_Dec_61'] AS DOUBLE) AS bsmt_fin_sqft,
                TRY_CAST(_raw['L_ContractDate'] AS DATE) AS contract_date,
                TRY_CAST(how_sold AS VARCHAR) AS how_sold,
                -- Distress bits arrive as '0'/'1' strings; = 1 keeps NULL
                -- (unknown) distinct from FALSE.
                TRY_CAST(_raw['LM_bit_60'] AS INTEGER) = 1 AS is_estate,
                TRY_CAST(_raw['LM_bit_43'] AS INTEGER) = 1 AS is_manufactured,
                TRY_CAST(_raw['LM_bit_42'] AS INTEGER) = 1 AS is_modular,
                TRY_CAST(_raw['LM_bit_35'] AS INTEGER) = 1 AS is_auction,
                -- "Lender or Govt Ownd" = REO / bank-owned.
                TRY_CAST(_raw['LM_bit_47'] AS INTEGER) = 1 AS is_reo,
                TRY_CAST(_raw['LM_bit_48'] AS INTEGER) = 1 AS is_short_sale,
                TRY_CAST(_raw['LM_bit_1'] AS INTEGER) = 1 AS is_duplicate,
                TRY_CAST(garage AS VARCHAR) AS garage,
                -- Feed has no numeric bay count, only "Double Attached" style
                -- tokens; take the largest garage (non-carport) bay mentioned.
                CASE
                    WHEN garage LIKE '%4 Cars or More%' THEN 4
                    WHEN regexp_matches(garage, 'Triple (Attached|Detached|Under)') THEN 3
                    WHEN regexp_matches(garage, 'Double (Attached|Detached|Under)') THEN 2
                    WHEN regexp_matches(garage, 'Single (Attached|Detached|Under)') THEN 1
                    WHEN garage = 'None' OR garage LIKE '%Carport%' THEN 0
                END AS garage_spaces,
                TRY_CAST(basement AS VARCHAR) AS basement,
                -- TRUE on any real-basement token; crawl/slab/none-only = FALSE;
                -- blank or "Other - See Remarks"-only = NULL.
                CASE
                    WHEN regexp_matches(basement,
                        'Full|Partial|Finished|Walk Out|Outside Access|Concrete Floor'
                        || '|Dirt Floor|Garage Door|Rec Room|Sump Pump|Shower|Laundry'
                        || '|Kitchen|Plumbing|Partitioned|Tenant Use') THEN TRUE
                    WHEN regexp_matches(basement, 'None|Crawl Space|Slab') THEN FALSE
                END AS has_basement,
                TRY_CAST(levels AS VARCHAR) AS levels,
                TRY_CAST(fireplaces AS VARCHAR) AS fireplaces,
                TRY_CAST(_raw['LM_Dec_29'] AS DOUBLE) AS tax_amount,
                TRY_CAST(_raw['LM_Int2_17'] AS INTEGER) AS tax_year,
                TRY_CAST(_raw['LM_Char10_3'] AS VARCHAR) AS school_district,
                TRY_CAST(_raw['LFD_WaterFrontage_26'] AS VARCHAR) AS waterfront,
                TRY_CAST(_raw['LM_Int1_15'] AS INTEGER) AS total_rooms
            FROM read_json_auto('{src.as_posix()}', format='newline_delimited',
                                 union_by_name=true, ignore_errors=true)
            WHERE COALESCE(address,'') <> ''
        )
        TO '{tmp_out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    os.replace(tmp_out, MLS_OUT_PATH)
    elapsed = time.perf_counter() - t0
    size_mb = MLS_OUT_PATH.stat().st_size / 1024 / 1024
    n = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{MLS_OUT_PATH.as_posix()}')"
    ).fetchone()[0]
    print(f"\nWrote {MLS_OUT_PATH}")
    print(f"  rows:    {n:,}")
    print(f"  size:    {size_mb:.1f} MB")
    print(f"  elapsed: {elapsed:.1f}s")


def main() -> None:
    con = duckdb.connect()
    parts: list[str] = []
    for label, rel in PARCEL_FILES_NRV + PARCEL_FILES_EXTENDED:
        path = _PROJECT_ROOT / rel
        if not path.exists():
            print(f"  SKIP missing {rel}")
            continue
        parts.append(f"""
            SELECT
                '{label}' AS parcel_source,
                CAST(parcel_id AS VARCHAR) AS parcel_id,
                TRY_CAST(site_addr1 AS VARCHAR) AS site_addr1,
                TRY_CAST(site_addr2 AS VARCHAR) AS site_addr2,
                TRY_CAST(jurisdiction AS VARCHAR) AS jurisdiction,
                TRY_CAST(owner1 AS VARCHAR) AS owner1,
                TRY_CAST(subd_name AS VARCHAR) AS subd_name,
                TRY_CAST(acres AS DOUBLE) AS acres,
                TRY_CAST(year_built AS INTEGER) AS year_built,
                TRY_CAST(bedrooms AS DOUBLE) AS bedrooms,
                TRY_CAST(full_baths AS DOUBLE) AS full_baths,
                TRY_CAST(half_baths AS DOUBLE) AS half_baths,
                TRY_CAST(sfla AS INTEGER) AS sfla,
                TRY_CAST(assessed_total AS DOUBLE) AS assessed_total,
                TRY_CAST(last_sale_date AS DATE) AS last_sale_date,
                TRY_CAST(last_sale_price AS DOUBLE) AS last_sale_price,
                TRY_CAST(latitude AS DOUBLE) AS latitude,
                TRY_CAST(longitude AS DOUBLE) AS longitude
            FROM read_json_auto('{path.as_posix()}', format='newline_delimited', ignore_errors=true)
        """)

    # Statewide parcels from the va-parcels-pipeline (~3.1M parcels across 73 VA
    # jurisdictions) so the CMA can resolve subjects + parcel attributes across
    # the whole state, not just the NRV core. Exclude the jurisdictions already
    # covered by the curated local NRV/Roanoke jsonls above — those carry the
    # exact parcel_id format the MLS comp join expects — to avoid duplicate rows.
    statewide_csv = _PROJECT_ROOT.parent / "va-parcels-pipeline" / "outputs" / "va_parcels_statewide.csv"
    local_jurisdictions = (
        "Montgomery County", "Pulaski County", "Floyd County", "Giles County",
        "Radford City", "Roanoke County", "Botetourt County", "Franklin County",
        "Bedford County", "Carroll County", "Wythe County", "Henry County",
    )
    if statewide_csv.exists():
        excl = ", ".join(f"'{j}'" for j in local_jurisdictions)
        parts.append(f"""
            SELECT
                'VA_STATEWIDE' AS parcel_source,
                CAST(parcel_id AS VARCHAR) AS parcel_id,
                TRY_CAST(site_addr1 AS VARCHAR) AS site_addr1,
                TRY_CAST(site_addr2 AS VARCHAR) AS site_addr2,
                TRY_CAST(jurisdiction AS VARCHAR) AS jurisdiction,
                TRY_CAST(owner1 AS VARCHAR) AS owner1,
                TRY_CAST(subd_name AS VARCHAR) AS subd_name,
                TRY_CAST(acres AS DOUBLE) AS acres,
                TRY_CAST(year_built AS INTEGER) AS year_built,
                TRY_CAST(bedrooms AS DOUBLE) AS bedrooms,
                TRY_CAST(full_baths AS DOUBLE) AS full_baths,
                TRY_CAST(half_baths AS DOUBLE) AS half_baths,
                TRY_CAST(sfla AS INTEGER) AS sfla,
                TRY_CAST(assessed_total AS DOUBLE) AS assessed_total,
                TRY_CAST(last_sale_date AS DATE) AS last_sale_date,
                TRY_CAST(last_sale_price AS DOUBLE) AS last_sale_price,
                TRY_CAST(latitude AS DOUBLE) AS latitude,
                TRY_CAST(longitude AS DOUBLE) AS longitude
            FROM read_csv_auto('{statewide_csv.as_posix()}', header=true,
                                sample_size=-1, ignore_errors=true)
            WHERE jurisdiction NOT IN ({excl})
        """)
        print(f"  + VA statewide parcels (excl. {len(local_jurisdictions)} local jurisdictions): {statewide_csv}")
    else:
        print(f"  SKIP missing statewide CSV: {statewide_csv}")

    if not parts:
        print("No parcel files available. Nothing to do.")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH_STR = OUT_PATH.as_posix()

    t0 = time.perf_counter()
    union_sql = "\nUNION ALL\n".join(parts)
    con.execute(
        f"COPY ({union_sql}) TO '{OUT_PATH_STR}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    elapsed = time.perf_counter() - t0

    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    row_count = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{OUT_PATH_STR}')"
    ).fetchone()[0]

    print(f"\nWrote {OUT_PATH}")
    print(f"  rows:    {row_count:,}")
    print(f"  size:    {size_mb:.1f} MB")
    print(f"  elapsed: {elapsed:.1f}s")

    # Quick verification: a query against the parquet should now be sub-second.
    t0 = time.perf_counter()
    sample = con.execute(
        f"SELECT site_addr1, owner1 FROM read_parquet('{OUT_PATH_STR}') "
        f"WHERE UPPER(COALESCE(site_addr1,'')) LIKE '%509 JEFFERSON%' LIMIT 2"
    ).fetchall()
    t1 = time.perf_counter()
    print(f"  test query (509 Jefferson): {len(sample)} rows in {(t1-t0)*1000:.0f}ms")
    for row in sample:
        print(f"    {row}")

    # Then the same for MLS so Active / Closed listings are searchable.
    _build_mls_lookup(con)


if __name__ == "__main__":
    main()
