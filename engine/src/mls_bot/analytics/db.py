"""DuckDB connection helper. Loads listings JSONL once into a view.

Usage:
    from mls_bot.analytics.db import connect
    con = connect()
    con.execute("SELECT count(*) FROM listings WHERE _class='RE_1'").fetchone()
"""

from __future__ import annotations

from pathlib import Path

import duckdb


DEFAULT_LISTINGS = Path("data/mls/listings.jsonl")
DEFAULT_LISTINGS_WITH_PARCELS = Path("data/mls/listings_with_parcels.jsonl")
DEFAULT_LISTINGS_PLUS_DEEDS = Path("data/mls/listings_plus_deeds.jsonl")
DEFAULT_DEED_SALES = Path("data/mls/deed_sales_nrv.jsonl")


def _pick_listings() -> Path:
    """Resolve the richest listings source on disk."""
    for p in (DEFAULT_LISTINGS_PLUS_DEEDS, DEFAULT_LISTINGS_WITH_PARCELS, DEFAULT_LISTINGS):
        if p.exists():
            return p
    raise FileNotFoundError("No listings JSONL found — run RETS pull first")


def connect(listings_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB con with `listings` view registered.

    When `data/mls/deed_sales_nrv.jsonl` exists, also registers a `deed_sales`
    view containing the standalone deed-only sale records. This lets
    deed-aware analytics combine MLS + deed data via UNION.
    """
    listings_path = Path(listings_path) if listings_path else _pick_listings()
    if not listings_path.exists():
        raise FileNotFoundError(f"{listings_path} — run RETS pull + join first")

    con = duckdb.connect(":memory:")
    con.execute(f"""
        CREATE VIEW listings AS
        SELECT * FROM read_json_auto('{listings_path.as_posix()}', format='newline_delimited',
                                      union_by_name=true, sample_size=-1)
    """)
    if DEFAULT_DEED_SALES.exists():
        con.execute(f"""
            CREATE VIEW deed_sales AS
            SELECT * FROM read_json_auto('{DEFAULT_DEED_SALES.as_posix()}',
                                          format='newline_delimited',
                                          union_by_name=true, sample_size=-1)
        """)
    return con
