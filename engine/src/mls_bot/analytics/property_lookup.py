"""Unified property lookup across MLS listings and county assessor parcels.

The existing :func:`mls_bot.analytics.cma.find_subject` only queries the MLS
``listings`` view, which fails for the common off-market case (most homes most
of the time). This module adds a parcel-data fallback that covers ~580 MB of
NRV + extended-NRV assessor data, exposing:

* :func:`search_properties` — used by the dashboard typeahead. Returns top
  matches from both MLS and parcels, ranked by string match + recency.
* :func:`resolve_subject` — used by the CMA orchestrator. Tries MLS first,
  then parcel by id, then parcel by address. Always returns a dict shaped
  like a ``find_subject`` result so downstream renderers don't care which
  source produced it.

Parcel JSONL files come from :data:`mls_bot.analytics.owner_dedup.PARCEL_FILES_NRV`
and ``PARCEL_FILES_EXTENDED`` so this module never re-enumerates them.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import duckdb

from .db import connect
from .owner_dedup import PARCEL_FILES_EXTENDED, PARCEL_FILES_NRV


# Slim combined Parquet files produced by scripts/build_parcel_lookup.py.
# When present, used in preference to the raw JSONL files (sub-second
# cold-start vs ~20 s on parcel JSONL and ~9 s on listings JSONL).
# Rebuild after any quarterly assessor refresh or major MLS pull.
_PARCEL_LOOKUP_PARQUET = Path("data/parcel_lookup.parquet")
_MLS_LOOKUP_PARQUET = Path("data/mls_lookup.parquet")


_GEOCODE_CACHE: dict[tuple[str, str], Optional[tuple[float, float]]] = {}


def _street_token(address: str) -> Optional[str]:
    """Extract the street-name token from a freeform address.

    Drops the leading number (and any directional like "S" / "NW"), keeps
    only the street name and suffix. Returns ``None`` if the address isn't
    parseable. Used by the same-street geocode fallback so a subject like
    ``"509 JEFFERSON ST"`` matches MLS rows like ``"504 Jefferson Street"``
    or ``"602 JEFFERSON Street"``.
    """
    raw = (address or "").strip().upper()
    if not raw:
        return None
    # Drop the leading number group.
    m = re.match(r"^(\d+[A-Z]?)\s+(.*)$", raw)
    if not m:
        return None
    rest = m.group(2).strip()
    # Drop a leading single-letter directional ("S", "N", "E", "W") or
    # two-letter compound ("NW","NE","SW","SE") so "S JEFFERSON FOREST"
    # collapses to "JEFFERSON FOREST".
    rest = re.sub(r"^(N|S|E|W|NE|NW|SE|SW)\s+", "", rest)
    # Take only up to the first comma — strips off ", BLACKSBURG VA 24060"
    # if the user typed a full mailing address.
    rest = rest.split(",")[0].strip()
    if not rest:
        return None
    return rest


def _enrich_subject_with_geocode(subject: dict[str, Any]) -> dict[str, Any]:
    """Populate ``latitude`` / ``longitude`` on an off-market subject by
    taking the median of same-street MLS records.

    Skips the work if the subject already has lat/lng. Returns the subject
    dict unchanged (mutated in place) when geocoding succeeds OR when no
    same-street record exists — never raises."""
    if not isinstance(subject, dict):
        return subject
    try:
        lat = subject.get("latitude")
        lng = subject.get("longitude")
        if lat is not None and lng is not None and lat != "" and lng != "":
            return subject
    except Exception:
        pass

    address = str(subject.get("address") or "").strip()
    city = str(subject.get("city") or "").strip()
    street = _street_token(address)
    if not street or not city:
        return subject

    key = (street.upper(), city.upper())
    cached = _GEOCODE_CACHE.get(key)
    if cached is not None:
        subject["latitude"], subject["longitude"] = cached
        return subject
    if key in _GEOCODE_CACHE:
        # Cached miss — don't re-query.
        return subject

    if not _MLS_LOOKUP_PARQUET.exists():
        _GEOCODE_CACHE[key] = None
        return subject

    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW listings AS "
        f"SELECT * FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}')"
    )
    safe_street = _sql_quote(street)
    safe_city = _sql_quote(city)
    sql = f"""
        SELECT latitude, longitude
        FROM listings
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
          AND UPPER(address) LIKE '%{safe_street}%'
          AND UPPER(COALESCE(city,'')) = '{safe_city.upper()}'
        LIMIT 20
    """
    try:
        rows = con.execute(sql).fetchall()
    except Exception:
        rows = []
    if not rows:
        _GEOCODE_CACHE[key] = None
        return subject
    lats = sorted(r[0] for r in rows if r[0] is not None)
    lngs = sorted(r[1] for r in rows if r[1] is not None)
    if not lats or not lngs:
        _GEOCODE_CACHE[key] = None
        return subject
    med_lat = lats[len(lats) // 2]
    med_lng = lngs[len(lngs) // 2]
    _GEOCODE_CACHE[key] = (med_lat, med_lng)
    subject["latitude"] = med_lat
    subject["longitude"] = med_lng
    return subject


def _mls_find_fast(*, address: Optional[str] = None,
                   parcel_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Lookup the subject record from the slim MLS parquet.

    Mirrors ``cma.find_subject`` but reads the slim ``mls_lookup.parquet``
    instead of the full ``listings`` JSONL — sub-second cold start vs ~30s.
    Returns ``None`` if no match or the parquet is missing (the caller will
    then fall back to the heavy path)."""
    if not _MLS_LOOKUP_PARQUET.exists():
        return None
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW listings AS "
        f"SELECT * FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}')"
    )
    if parcel_id:
        sql = f"""SELECT * FROM listings
                  WHERE CAST(parcel_id AS VARCHAR) = '{_sql_quote(parcel_id.strip())}'
                  ORDER BY (status_category = 'Active') DESC,
                           list_date DESC NULLS LAST
                  LIMIT 1"""
    elif address:
        addr = _sql_quote(address.upper().strip())
        sql = f"""SELECT * FROM listings
                  WHERE UPPER(address) LIKE '%{addr}%'
                  ORDER BY (status_category = 'Active') DESC,
                           list_date DESC NULLS LAST
                  LIMIT 1"""
    else:
        return None
    rows = con.execute(sql).fetchdf().to_dict(orient="records")
    return rows[0] if rows else None


def _fast_lookup_connection() -> duckdb.DuckDBPyConnection:
    """Open a dedicated in-memory DuckDB connection with the slim lookup
    Parquet views registered.

    Avoids the heavy ``db.connect()`` path that re-parses 200 MB+ of JSONL
    on every call. Used by :func:`search_properties` so the typeahead
    stays sub-second per keystroke.
    """
    con = duckdb.connect(":memory:")
    if _PARCEL_LOOKUP_PARQUET.exists():
        con.execute(
            f"CREATE VIEW parcels_all AS "
            f"SELECT * FROM read_parquet('{_PARCEL_LOOKUP_PARQUET.as_posix()}')"
        )
    if _MLS_LOOKUP_PARQUET.exists():
        con.execute(
            f"CREATE VIEW mls_all AS "
            f"SELECT * FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}')"
        )
    return con


# Backwards-compatible alias for any callers that still use the older name.
_fast_parcel_connection = _fast_lookup_connection


# Street-suffix abbreviation table — used for both the address normalizer
# (Rd → ROAD) and a pass over assessor data (assessor often stores ROAD vs RD
# inconsistently). Same set as in scripts/build_cma.py.
_STREET_ABBREV: dict[str, str] = {
    " RD": " ROAD",
    " ST": " STREET",
    " AVE": " AVENUE",
    " DR": " DRIVE",
    " HWY": " HIGHWAY",
    " LN": " LANE",
    " CT": " COURT",
    " BLVD": " BOULEVARD",
    " PKWY": " PARKWAY",
    " PL": " PLACE",
    " TER": " TERRACE",
    " CIR": " CIRCLE",
    " TRL": " TRAIL",
    " PT": " POINT",
    " SQ": " SQUARE",
}

# Tokens we strip from the tail of a user query to make matching tolerant of
# "Blacksburg VA 24060"-style suffixes that aren't in the parcel ``site_addr1``.
_STATE_AND_ZIP = re.compile(r"\b(VA|VIRGINIA|\d{5}(?:-\d{4})?)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# DuckDB view registration
# ---------------------------------------------------------------------------

_VIEWS_INSTALLED_FOR: set[int] = set()


def _install_parcel_views(con) -> None:
    """Register a ``parcels_all`` DuckDB view across every parcel file.

    Idempotent per-connection. Prefers the slim combined Parquet at
    ``data/parcel_lookup.parquet`` when present (sub-second cold-start);
    falls back to per-county JSONL views otherwise (~20 s but works on a
    cold checkout without the pre-built artifact).
    """
    key = id(con)
    if key in _VIEWS_INSTALLED_FOR:
        return

    if _PARCEL_LOOKUP_PARQUET.exists():
        con.execute(
            f"""CREATE OR REPLACE VIEW parcels_all AS
                SELECT * FROM read_parquet('{_PARCEL_LOOKUP_PARQUET.as_posix()}')"""
        )
        _VIEWS_INSTALLED_FOR.add(key)
        return

    # Fallback: union the raw JSONL files. Each county file becomes its own
    # ``parcels_<key>`` view; ``parcels_all`` is the union with a
    # ``parcel_source`` label column so search results can attribute the
    # right county.
    parts: list[str] = []
    for label, path in PARCEL_FILES_NRV + PARCEL_FILES_EXTENDED:
        p = Path(path)
        if not p.exists():
            continue
        view = f"parcels_{label.lower()}"
        con.execute(
            f"""CREATE OR REPLACE VIEW {view} AS
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
                    TRY_CAST(last_sale_price AS DOUBLE) AS last_sale_price
                FROM read_json_auto(
                    '{p.as_posix()}',
                    format='newline_delimited',
                    ignore_errors=true
                )"""
        )
        parts.append(f"SELECT * FROM {view}")
    if parts:
        con.execute(f"CREATE OR REPLACE VIEW parcels_all AS {' UNION ALL '.join(parts)}")
    _VIEWS_INSTALLED_FOR.add(key)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class PropertyMatch:
    """A single search hit, normalized across MLS and parcel sources."""

    source: str                       # "mls" | "parcel"
    address: str
    city: str
    county: str
    parcel_id: str
    acres: Optional[float] = None
    sqft: Optional[int] = None
    year_built: Optional[int] = None
    bedrooms: Optional[float] = None
    full_baths: Optional[float] = None
    half_baths: Optional[float] = None
    owner: Optional[str] = None
    subdivision: Optional[str] = None
    last_sale_price: Optional[float] = None
    last_sale_date: Optional[str] = None
    status: str = "Off-Market"        # "Active" | "Closed" | "Off-Market"
    list_price: Optional[float] = None
    list_date: Optional[str] = None
    listing_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Dates may come back as datetime.date — stringify for JSON safety.
        if d.get("last_sale_date") and not isinstance(d["last_sale_date"], str):
            d["last_sale_date"] = str(d["last_sale_date"])
        if d.get("list_date") and not isinstance(d["list_date"], str):
            d["list_date"] = str(d["list_date"])
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_query(q: str) -> str:
    """Uppercase, strip state/zip tail, collapse whitespace.

    We deliberately DO NOT expand abbreviations here — county parcel feeds
    overwhelmingly store the short form (``509 JEFFERSON ST``, not
    ``... STREET``). Expansion would zero-out matches. If the first
    query attempt comes back empty, :func:`_expand_abbrev` is tried as a
    fallback for the rarer feeds that did expand.
    """
    s = (q or "").upper().strip()
    s = _STATE_AND_ZIP.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _expand_abbrev(s: str) -> str:
    """Apply the short→long street suffix expansion (``ST → STREET`` etc.)."""
    for k, v in _STREET_ABBREV.items():
        s = s.replace(k, v)
    return s


def _contract_abbrev(s: str) -> str:
    """Apply the long→short street suffix contraction (``STREET → ST`` etc.)."""
    for short, long in _STREET_ABBREV.items():
        s = s.replace(long, short)
    return s


def _sql_quote(s: str) -> str:
    return s.replace("'", "''")


# ---------------------------------------------------------------------------
# Search — used by the typeahead
# ---------------------------------------------------------------------------

def search_properties(query: str, limit: int = 8) -> list[PropertyMatch]:
    """Top-``limit`` properties matching the query string.

    Searches MLS listings first (where we have rich market data) and falls
    back to parcel files for off-market homes. Ranks by (a) whether the query
    matches the address prefix, (b) recency of activity, (c) MLS > parcel
    when a record is in both.
    """
    raw = (query or "").strip()
    if len(raw) < 2:
        return []
    norm = _norm_query(raw)
    if not norm:
        return []

    # Use a dedicated fast connection — db.connect() rebuilds the listings
    # view from a 200 MB JSONL every call, which makes the typeahead
    # unusable. The slim Parquet views load in milliseconds.
    con = _fast_lookup_connection()

    matches: list[PropertyMatch] = []
    seen_keys: set[tuple[str, str]] = set()  # (county, parcel_id) dedup

    # --- MLS first ----------------------------------------------------------
    # Active and closed listings live in their own slim parquet so the typeahead
    # can show "7423 Floyd Highway N · Active" instantly even when that county's
    # assessor feed (Floyd in particular) is missing structured addresses.
    mls_haystack = "UPPER(COALESCE(address,'') || ' ' || COALESCE(city,'') || ' ' || COALESCE(subdivision,''))"

    def _run_mls(query_form: str) -> list[dict[str, Any]]:
        toks = [t for t in query_form.split() if t]
        if not toks:
            return []
        safe = [_sql_quote(t) for t in toks]
        where = " AND ".join(f"{mls_haystack} LIKE '%{t}%'" for t in safe)
        first = safe[0]
        sql = f"""
            SELECT listing_id, address, city, county, subdivision, parcel_id,
                   status_category, list_date, close_date, list_price,
                   sqft, acres, year_built, bedrooms, full_baths, half_baths,
                   (CASE WHEN UPPER(COALESCE(address,'')) LIKE '{first}%' THEN 3
                         WHEN UPPER(COALESCE(address,'')) LIKE '%{first}%' THEN 2
                         ELSE 0 END) AS addr_score
            FROM mls_all
            WHERE {where}
            ORDER BY addr_score DESC,
                     (status_category = 'Active') DESC,
                     COALESCE(list_date, close_date) DESC NULLS LAST
            LIMIT {limit * 2}
        """
        try:
            return con.execute(sql).fetchdf().to_dict(orient="records")
        except duckdb.CatalogException:
            return []

    mls_rows = _run_mls(norm)
    if not mls_rows:
        c = _contract_abbrev(norm)
        if c != norm:
            mls_rows = _run_mls(c)
    if not mls_rows:
        e = _expand_abbrev(norm)
        if e != norm:
            mls_rows = _run_mls(e)

    for row in mls_rows:
        pid = str(row.get("parcel_id") or "")
        county = str(row.get("county") or "")
        key = (county.upper(), pid) if pid else ("MLS", str(row.get("listing_id") or ""))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        status_raw = str(row.get("status_category") or "").strip()
        if status_raw.lower() == "active":
            status = "Active"
        elif status_raw.lower() == "closed":
            status = "Closed"
        elif status_raw.lower().startswith("pend"):
            status = "Pending"
        else:
            status = status_raw or "Off-Market"
        matches.append(PropertyMatch(
            source="mls",
            address=str(row.get("address") or ""),
            city=str(row.get("city") or ""),
            county=county,
            parcel_id=pid,
            acres=row.get("acres"),
            sqft=row.get("sqft"),
            year_built=row.get("year_built"),
            bedrooms=row.get("bedrooms"),
            full_baths=row.get("full_baths"),
            half_baths=row.get("half_baths"),
            subdivision=str(row.get("subdivision") or "") or None,
            list_price=row.get("list_price"),
            list_date=row.get("list_date"),
            listing_id=str(row.get("listing_id") or "") or None,
            status=status,
        ))
        if len(matches) >= limit:
            return matches

    # --- Parcel fallback ----------------------------------------------------
    parcel_haystack = "UPPER(COALESCE(site_addr1,'') || ' ' || COALESCE(site_addr2,'') || ' ' || COALESCE(jurisdiction,'') || ' ' || COALESCE(subd_name,''))"

    def _run(query_form: str) -> list[dict[str, Any]]:
        toks = [t for t in query_form.split() if t]
        if not toks:
            return []
        safe = [_sql_quote(t) for t in toks]
        where = " AND ".join(f"{parcel_haystack} LIKE '%{t}%'" for t in safe)
        first = safe[0]
        sql = f"""
            SELECT parcel_source, parcel_id, site_addr1, site_addr2, jurisdiction,
                   owner1, subd_name, acres, year_built, bedrooms, full_baths,
                   half_baths, sfla, assessed_total, last_sale_date, last_sale_price,
                   latitude, longitude,
                   (CASE WHEN UPPER(COALESCE(site_addr1,'')) LIKE '{first}%' THEN 3
                         WHEN UPPER(COALESCE(site_addr1,'')) LIKE '%{first}%' THEN 2
                         ELSE 0 END) AS addr_score
            FROM parcels_all
            WHERE {where}
            ORDER BY addr_score DESC,
                     last_sale_date DESC NULLS LAST
            LIMIT {limit * 2}
        """
        try:
            return con.execute(sql).fetchdf().to_dict(orient="records")
        except duckdb.CatalogException:
            return []

    # Pass 1: query exactly as the user typed (just whitespace/zip normalized).
    rows = _run(norm)
    if not rows:
        contracted = _contract_abbrev(norm)
        if contracted != norm:
            rows = _run(contracted)
    if not rows:
        expanded = _expand_abbrev(norm)
        if expanded != norm:
            rows = _run(expanded)

    for row in rows:
        pid = str(row.get("parcel_id") or "")
        county = str(row.get("parcel_source") or "").title()
        key = (county.upper(), pid)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        addr1 = str(row.get("site_addr1") or "").strip()
        addr2 = str(row.get("site_addr2") or "").strip()
        # site_addr2 carries the city in MOST records, but occasionally comes
        # back as NaN / "nan" from the source feed — fall back to jurisdiction.
        if not addr2 or addr2.lower() == "nan":
            addr2 = ""
        city = addr2 or str(row.get("jurisdiction") or "").title()
        matches.append(PropertyMatch(
            source="parcel",
            address=addr1,
            city=city,
            county=county,
            parcel_id=pid,
            acres=row.get("acres"),
            sqft=row.get("sfla"),
            year_built=row.get("year_built"),
            bedrooms=row.get("bedrooms"),
            full_baths=row.get("full_baths"),
            half_baths=row.get("half_baths"),
            owner=str(row.get("owner1") or "").strip() or None,
            subdivision=str(row.get("subd_name") or "").strip() or None,
            last_sale_price=row.get("last_sale_price"),
            last_sale_date=row.get("last_sale_date"),
            status="Off-Market",
        ))
        if len(matches) >= limit:
            break
    return matches


# ---------------------------------------------------------------------------
# Resolve — used by the CMA builder
# ---------------------------------------------------------------------------

def _parcel_row_to_subject(row: dict[str, Any]) -> dict[str, Any]:
    """Adapt a parcels_all row into a ``find_subject``-shaped dict."""
    sfla = row.get("sfla")
    beds = row.get("bedrooms")
    acres = row.get("acres") or 0
    # Synthetic _class: if it looks improved, residential; otherwise treat as land.
    is_improved = bool(sfla and sfla > 200 and beds and beds > 0)
    cls = "RE_1" if is_improved else "LD_3"

    addr1 = str(row.get("site_addr1") or "").strip()
    addr2 = str(row.get("site_addr2") or "").strip()
    juris = str(row.get("jurisdiction") or "").strip()
    city = addr2 or juris.title()
    county = str(row.get("parcel_source") or "").title()

    last_sale_price = row.get("last_sale_price")
    last_sale_date = row.get("last_sale_date")
    if last_sale_date and not isinstance(last_sale_date, str):
        last_sale_date = str(last_sale_date)

    return {
        "address": addr1,
        "city": city,
        "county": county,
        "subdivision": str(row.get("subd_name") or "").strip() or None,
        "parcel_id": str(row.get("parcel_id") or ""),
        "_class": cls,
        "status_category": "Off-Market",
        "sqft": sfla,
        "acres": acres if acres else None,
        "year_built": row.get("year_built"),
        "bedrooms": beds,
        "full_baths": row.get("full_baths"),
        "half_baths": row.get("half_baths"),
        # Parcel centroid (WGS84) when parcel_lookup carries one (parcels
        # re-pulled with geometry via va-parcels-pipeline) — this is what lets
        # radius comp selection work for subjects OUTSIDE the NRV/MLS core.
        # Still null for not-yet-re-pulled parcels; the comp scorer's haversine
        # returns inf -> neutral 0.5, so it degrades gracefully as before.
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        # No active list price for an off-market subject. Surface the
        # assessor's value so the renderer has something to put in the
        # docmeta and the verdict can fall back to comp midpoint.
        "list_price": None,
        "original_list_price": None,
        "assessed_total": row.get("assessed_total"),
        "deed_last_sale_date": last_sale_date,
        "deed_last_sale_price": last_sale_price,
        "feed_dom": None,
        "list_date": None,
    }


def _fast_parcels_only_connection() -> Optional["duckdb.DuckDBPyConnection"]:
    """Open a DuckDB connection with ONLY the parcels_all view registered
    against the slim parquet — no listings, no other views.

    Used by ``resolve_subject``'s parcel fallback so an off-market subject
    lookup doesn't pay the heavy ``connect()`` listings-JSONL load cost."""
    if not _PARCEL_LOOKUP_PARQUET.exists():
        return None
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW parcels_all AS "
        f"SELECT * FROM read_parquet('{_PARCEL_LOOKUP_PARQUET.as_posix()}')"
    )
    return con


def _parcel_lookup_by_parcel_id(con, parcel_id: str) -> Optional[dict[str, Any]]:
    sql = (
        f"SELECT * FROM parcels_all "
        f"WHERE UPPER(CAST(parcel_id AS VARCHAR)) = UPPER('{_sql_quote(parcel_id.strip())}') "
        f"LIMIT 1"
    )
    rows = con.execute(sql).fetchdf().to_dict(orient="records")
    return _parcel_row_to_subject(rows[0]) if rows else None


def _parcel_lookup_by_address(con, address: str) -> Optional[dict[str, Any]]:
    """Try several progressively-broader address forms against parcels_all."""
    raw = (address or "").strip()
    if not raw:
        return None
    norm = _norm_query(raw)
    tokens = norm.split()
    queries: list[str] = []
    queries.append(norm)                                # as-typed
    if _contract_abbrev(norm) != norm:
        queries.append(_contract_abbrev(norm))          # STREET → ST
    if _expand_abbrev(norm) != norm:
        queries.append(_expand_abbrev(norm))            # ST → STREET
    if len(tokens) >= 2:
        queries.append(" ".join(tokens[:2]))            # number + street name only
    if len(tokens) > 3:
        queries.append(" ".join(tokens[:-1]))           # minus likely city tail

    seen: set[str] = set()
    for q in queries:
        if not q or q in seen:
            continue
        seen.add(q)
        qtokens = q.split()
        if not qtokens:
            continue
        haystack = "UPPER(COALESCE(site_addr1,'') || ' ' || COALESCE(site_addr2,'') || ' ' || COALESCE(jurisdiction,''))"
        # House-number anchor: a leading numeric token MUST appear at the START
        # of site_addr1 (the number followed by a non-digit or end-of-string).
        # Without this, a bare street token LIKE-matched any parcel containing
        # that word and LIMIT 1 could bind a DIFFERENT-numbered house in another
        # jurisdiction — the statewide-merge wrong-bind regression. If no parcel
        # shares the house number we return nothing for this form (miss > mis-bind).
        house = qtokens[0] if qtokens[0].isdigit() else None
        street_tokens = qtokens[1:] if house else qtokens
        clauses: list[str] = []
        if house:
            clauses.append(
                f"regexp_matches(UPPER(COALESCE(site_addr1,'')), '^{house}([^0-9]|$)')"
            )
        clauses += [f"{haystack} LIKE '%{_sql_quote(t)}%'" for t in street_tokens]
        if not clauses:
            continue
        where = " AND ".join(clauses)
        sql = f"""
            SELECT * FROM parcels_all
            WHERE {where}
              AND COALESCE(site_addr1,'') <> ''
            ORDER BY (UPPER(COALESCE(site_addr1,'')) LIKE '{_sql_quote(qtokens[0])}%') DESC,
                     last_sale_date DESC NULLS LAST
            LIMIT 1
        """
        rows = con.execute(sql).fetchdf().to_dict(orient="records")
        if rows:
            return _parcel_row_to_subject(rows[0])
    return None


def _mls_lookup_by_address(address: str) -> Optional[dict[str, Any]]:
    """Try ``find_subject`` against MLS with the same multi-step address
    normalization used for parcel lookup.

    This is critical for the common case where the user types a freeform
    "{number} {street} {abbrev} {city}" but MLS stores only "{number}
    {street} {full-suffix}" (city lives in a separate column). Without this,
    ``find_subject('4861 Morris Rd Hiwassee')`` misses the actual MLS record
    for 4861 MORRIS Road and we fall through to parcel data with the wrong
    (assessor-derived) sqft.
    """
    from .cma import find_subject as _mls_find  # local to avoid cycle
    raw = (address or "").strip()
    if not raw:
        return None
    norm = _norm_query(raw)
    tokens = norm.split()
    queries: list[str] = [raw, norm]
    if _contract_abbrev(norm) != norm:
        queries.append(_contract_abbrev(norm))
    if _expand_abbrev(norm) != norm:
        queries.append(_expand_abbrev(norm))
    if len(tokens) >= 2:
        queries.append(" ".join(tokens[:2]))
    if len(tokens) > 3:
        queries.append(" ".join(tokens[:-1]))
    seen: set[str] = set()
    for q in queries:
        if not q or q in seen:
            continue
        seen.add(q)
        hit = _mls_find(address=q)
        if hit:
            return hit
    return None


def _enrich_with_parcel(mls_record: dict[str, Any]) -> dict[str, Any]:
    """A2 — Merge parcel-derived extras into an MLS hit without overriding it.

    MLS wins on every field that exists in both (sqft / bedrooms / baths /
    acres / year_built / status / etc.). The parcel record contributes only
    fields MLS doesn't carry: ``assessed_total``, ``deed_last_sale_date``,
    ``deed_last_sale_price``, ``owner``. Returns the input record unchanged
    when no parcel match is found.

    Uses a dedicated raw DuckDB connection over the slim parcel parquet so
    we don't pay the heavy ``connect()`` + listings-view setup just for
    one enrichment lookup."""
    if not mls_record:
        return mls_record
    pid = str(mls_record.get("parcel_id") or "").strip()
    if not pid:
        return mls_record
    if not _PARCEL_LOOKUP_PARQUET.exists():
        return mls_record
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW parcels_all AS "
        f"SELECT * FROM read_parquet('{_PARCEL_LOOKUP_PARQUET.as_posix()}')"
    )
    sql = (
        f"SELECT assessed_total, last_sale_date, last_sale_price, owner1 "
        f"FROM parcels_all "
        f"WHERE UPPER(CAST(parcel_id AS VARCHAR)) = UPPER('{_sql_quote(pid)}') "
        f"LIMIT 1"
    )
    try:
        rows = con.execute(sql).fetchdf().to_dict(orient="records")
    except Exception:
        return mls_record
    if not rows:
        return mls_record
    p = rows[0]
    # Use setdefault so MLS values are never overridden — only fill blanks.
    enriched = dict(mls_record)
    if enriched.get("assessed_total") in (None, ""):
        enriched["assessed_total"] = p.get("assessed_total")
    # MLS already carries deed_last_sale_* in the listings_plus_deeds view; keep
    # MLS's version when present, else use parcel.
    if not enriched.get("deed_last_sale_date") and p.get("last_sale_date"):
        d = p["last_sale_date"]
        enriched["deed_last_sale_date"] = str(d) if d is not None else None
    if not enriched.get("deed_last_sale_price") and p.get("last_sale_price"):
        enriched["deed_last_sale_price"] = p["last_sale_price"]
    if not enriched.get("owner") and p.get("owner1"):
        enriched["owner"] = str(p["owner1"]).strip() or None
    return enriched


def resolve_subject(*, address: Optional[str] = None,
                    parcel_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Resolve a subject record from MLS first, then parcel data.

    Returns a dict shaped like a ``find_subject`` result with extra
    parcel-derived fields (``assessed_total``, ``deed_last_sale_*``) when
    the match comes from assessor data — or, when the match comes from
    MLS, the same parcel extras are merged in via :func:`_enrich_with_parcel`
    so the renderer can use them either way. Returns ``None`` if every
    path misses.
    """
    # MLS first — we want active-listing fields when available. Prefer the
    # slim parquet (sub-second) before falling back to the heavy
    # find_subject path that loads 200 MB of JSONL.
    if parcel_id:
        fast = _mls_find_fast(parcel_id=parcel_id)
        if fast:
            return _enrich_subject_with_geocode(_enrich_with_parcel(fast))
    if address:
        for q in [address, _norm_query(address)] + (
            [_contract_abbrev(_norm_query(address))]
            if _contract_abbrev(_norm_query(address)) != _norm_query(address)
            else []
        ) + (
            [_expand_abbrev(_norm_query(address))]
            if _expand_abbrev(_norm_query(address)) != _norm_query(address)
            else []
        ) + (
            [" ".join(_norm_query(address).split()[:2])]
            if len(_norm_query(address).split()) >= 2
            else []
        ):
            if not q:
                continue
            fast = _mls_find_fast(address=q)
            if fast:
                return _enrich_subject_with_geocode(_enrich_with_parcel(fast))

    # MLS fast-path FIRST. Parcels are the fallback for off-market subjects
    # only — running them first wins parcel rows for any property that
    # exists in both MLS and parcels, which strips the MLS-only fields
    # (lat/lng, original_list_price, etc.) and breaks the radius cohorts.
    # The fast path above already covered parcel_id and the typeahead-friendly
    # address forms; nothing more to do for the MLS side.

    # Parcel fallback uses a dedicated parcels-only connection so off-market
    # subjects don't pay the heavy ``connect()`` listings-JSONL load cost.
    fast_parcel_con = _fast_parcels_only_connection()
    if fast_parcel_con is not None:
        if parcel_id:
            hit = _parcel_lookup_by_parcel_id(fast_parcel_con, parcel_id)
            if hit:
                return _enrich_subject_with_geocode(hit)
        if address:
            hit = _parcel_lookup_by_address(fast_parcel_con, address)
            if hit:
                return _enrich_subject_with_geocode(hit)
        # Parcel parquet exists but no hit. Don't bother with the heavy path —
        # if it isn't in the slim parquet it isn't in the JSONL either.
        return None

    # Heavy fallback for fresh checkouts where the parquet hasn't been built yet.
    from .cma import find_subject as _mls_find  # local import to avoid cycle
    if parcel_id:
        mls = _mls_find(parcel_id=parcel_id)
        if mls:
            return _enrich_with_parcel(mls)
    if address:
        mls = _mls_lookup_by_address(address)
        if mls:
            return _enrich_with_parcel(mls)

    con = connect()
    _install_parcel_views(con)

    if parcel_id:
        hit = _parcel_lookup_by_parcel_id(con, parcel_id)
        if hit:
            return hit
    if address:
        hit = _parcel_lookup_by_address(con, address)
        if hit:
            return hit
    return None


__all__ = ["PropertyMatch", "resolve_subject", "search_properties"]
