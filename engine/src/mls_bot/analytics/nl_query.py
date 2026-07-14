"""Layer 2 — natural-language property search.

The typeahead is address-first and stays that way (fast substring match, no
LLM per keystroke). This module handles the *other* kind of search — prose
like "renovated 4-bed near VT under $800k" — by parsing it into structured
filters with one LLM call, then running a deterministic DuckDB query.

Degrades cleanly: :func:`parse_nl_query` returns ``None`` when no API key is
configured or the text isn't parseable, and :func:`search_by_nl` falls back
to the plain token search in that case.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import duckdb

from .llm import call_json, llm_available

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MLS_LOOKUP_PARQUET = _PROJECT_ROOT / "data" / "mls_lookup.parquet"


_SYSTEM = (
    "You translate a real-estate agent's free-text property search into a "
    "strict JSON filter object. You only emit keys you are confident about; "
    "omit anything not stated. You never invent values."
)


def looks_like_prose(query: str) -> bool:
    """Heuristic: is this a natural-language query rather than an address?

    Addresses start with a number; prose usually doesn't and has several
    words. Keeps the LLM off the hot path for ordinary address typeahead."""
    q = (query or "").strip()
    if not q:
        return False
    if q[0].isdigit():
        return False  # "509 Jefferson" — address
    return len(q.split()) >= 3


def parse_nl_query(query: str) -> Optional[dict[str, Any]]:
    """Parse prose into a structured filter dict, or ``None`` if unavailable.

    Returned keys (all optional): ``city``, ``subdivision``, ``min_beds``,
    ``min_baths``, ``min_price``, ``max_price``, ``min_sqft``, ``max_sqft``,
    ``min_acres``, ``max_acres``, ``status`` ("Active"|"Closed"),
    ``keywords`` (list of remark keywords like "renovated", "pool")."""
    if not llm_available():
        return None
    user = (
        f'Search text: "{query}"\n\n'
        "Return a JSON object with any of these keys you can infer: "
        "city (string), subdivision (string), min_beds (int), min_baths (number), "
        "min_price (int), max_price (int), min_sqft (int), max_sqft (int), "
        "min_acres (number), max_acres (number), status (\"Active\" or \"Closed\"), "
        "keywords (array of lowercase strings to match in the listing remarks, "
        'e.g. ["renovated","pool","mountain view"]). '
        "Omit keys you cannot infer. Return ONLY the JSON object."
    )
    result = call_json(system=_SYSTEM, user=user, max_tokens=400)
    if not isinstance(result, dict):
        return None
    return result


def _filters_to_sql(filters: dict[str, Any]) -> tuple[str, list[str]]:
    """Build a WHERE clause + a human-readable summary of applied filters."""
    clauses: list[str] = ["COALESCE(address,'') <> ''"]
    summary: list[str] = []

    def q(s: str) -> str:
        return str(s).replace("'", "''")

    if filters.get("city"):
        clauses.append(f"UPPER(COALESCE(city,'')) = UPPER('{q(filters['city'])}')")
        summary.append(f"city={filters['city']}")
    if filters.get("subdivision"):
        clauses.append(f"UPPER(COALESCE(subdivision,'')) LIKE UPPER('%{q(filters['subdivision'])}%')")
        summary.append(f"subdivision~{filters['subdivision']}")
    for key, col, op in [
        ("min_beds", "bedrooms", ">="), ("min_baths", "full_baths", ">="),
        ("min_price", "sold_price", ">="), ("max_price", "sold_price", "<="),
        ("min_sqft", "sqft", ">="), ("max_sqft", "sqft", "<="),
        ("min_acres", "acres", ">="), ("max_acres", "acres", "<="),
    ]:
        v = filters.get(key)
        if v is not None:
            # Price filters apply to whichever price exists (sold or list).
            if col == "sold_price":
                clauses.append(
                    f"COALESCE(TRY_CAST(sold_price AS DOUBLE), TRY_CAST(list_price AS DOUBLE)) {op} {float(v)}"
                )
            else:
                clauses.append(f"TRY_CAST({col} AS DOUBLE) {op} {float(v)}")
            summary.append(f"{key}={v}")
    status = filters.get("status")
    if status in ("Active", "Closed"):
        clauses.append(f"status_category = '{status}'")
        summary.append(f"status={status}")
    kws = filters.get("keywords") or []
    if isinstance(kws, list):
        for kw in kws[:4]:
            kw = q(str(kw))
            clauses.append(
                f"(UPPER(COALESCE(public_remarks,'')) LIKE UPPER('%{kw}%') "
                f"OR UPPER(COALESCE(agent_remarks,'')) LIKE UPPER('%{kw}%'))"
            )
            summary.append(f"kw~{kw}")
    return " AND ".join(clauses), summary


def search_by_nl(query: str, limit: int = 12) -> Optional[dict[str, Any]]:
    """Run a natural-language search. Returns ``{filters, summary, matches}``
    or ``None`` when the LLM is unavailable / the text didn't parse."""
    filters = parse_nl_query(query)
    if not filters:
        return None
    if not _MLS_LOOKUP_PARQUET.exists():
        return None
    where, summary = _filters_to_sql(filters)
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW l AS SELECT * FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}')"
    )
    sql = f"""
        SELECT listing_id, address, city, county, subdivision, parcel_id,
               status_category, list_price, sold_price, sqft, acres, year_built,
               bedrooms, full_baths, half_baths, close_date
        FROM l
        WHERE {where}
        ORDER BY (status_category='Active') DESC, close_date DESC NULLS LAST
        LIMIT {int(limit)}
    """
    try:
        rows = con.execute(sql).fetchdf().to_dict(orient="records")
    except Exception:
        return None
    matches = []
    for r in rows:
        matches.append({
            "source": "mls",
            "address": r.get("address"),
            "city": r.get("city"),
            "county": r.get("county"),
            "parcel_id": str(r.get("parcel_id") or ""),
            "listing_id": str(r.get("listing_id") or ""),
            "subdivision": r.get("subdivision"),
            "status": r.get("status_category"),
            "list_price": r.get("list_price"),
            "sold_price": r.get("sold_price"),
            "sqft": r.get("sqft"),
            "acres": r.get("acres"),
            "year_built": r.get("year_built"),
            "bedrooms": r.get("bedrooms"),
            "full_baths": r.get("full_baths"),
        })
    return {"filters": filters, "summary": summary, "matches": matches}


__all__ = ["looks_like_prose", "parse_nl_query", "search_by_nl"]
