"""Dashboard-managed saved searches.

Reads SavedSearch rows from the dashboard SQLite (web/prisma/dev.db) and
upserts SavedSearchResult rows back into the same DB. Runs on the same
hourly cadence as the MLS pull via `tasks.py mls-hourly`.

Companion to saved_search.py (YAML-driven) — both can coexist; this one
is what the dashboard UI manages.

Result lifecycle:
  - new match in this run     → INSERT (firstSeenAt = lastSeenAt = now)
  - still matching            → UPDATE lastSeenAt = now
  - no longer matching        → DELETE (rendered via 'dropped' panel if we
                                surface that later)
A result is "NEW" if firstSeenAt >= search.lastRunAt at render time.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .alerts import watch_listings


DB_PATH = Path("web/prisma/dev.db")
# Use a temp CSV for the DuckDB → Python handoff. Cheaper than a giant
# in-memory result roundtrip and reuses the existing watch_listings code.
TMP_CSV = Path("data/.tmp_saved_search_results.csv")


def _now_iso() -> str:
    # Prisma stores DateTime as ISO-8601 with millisecond precision (Z).
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _open_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Dashboard SQLite not found at {DB_PATH}. "
            "Run `cd web && npx prisma db push` to create it."
        )
    con = sqlite3.connect(DB_PATH.as_posix())
    con.row_factory = sqlite3.Row
    return con


def _load_searches(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT id, displayId, name, criteria FROM SavedSearch WHERE isPaused = 0"
    ).fetchall()


def _run_one(search_id: str, name: str, criteria_json: str) -> tuple[list[dict], str | None]:
    """Execute one search; return (matches, error). On error, matches=[]."""
    try:
        criteria = json.loads(criteria_json or "{}")
    except json.JSONDecodeError as e:
        return [], f"criteria JSON parse error: {e}"
    try:
        n = watch_listings(
            cities=criteria.get("cities"),
            classes=criteria.get("classes") or ["RE_1"],
            statuses=criteria.get("statuses") or ["Active"],
            min_price=criteria.get("price_min"),
            max_price=criteria.get("price_max"),
            min_beds=criteria.get("beds_min"),
            max_beds=criteria.get("beds_max"),
            min_full_baths=criteria.get("baths_min"),
            min_sqft=criteria.get("sqft_min"),
            max_sqft=criteria.get("sqft_max"),
            min_acres=criteria.get("acres_min"),
            max_acres=criteria.get("acres_max"),
            zoning_like=criteria.get("zoning_like"),
            subdivision_like=criteria.get("subdivision_like"),
            school_districts=criteria.get("school_districts"),
            center_lat=criteria.get("center_lat"),
            center_lng=criteria.get("center_lng"),
            radius_mi=criteria.get("radius_mi"),
            listed_within_days=criteria.get("listed_within_days"),
            out_csv=TMP_CSV,
        )
    except Exception as e:
        return [], f"query error: {e}"

    if n == 0 or not TMP_CSV.exists():
        return [], None

    # Read the CSV back into dicts. Use csv.DictReader to avoid pulling in
    # pandas just for this.
    import csv
    rows: list[dict] = []
    with TMP_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows, None


def _to_float(v: Any) -> float | None:
    try:
        if v in (None, "", "None"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


def _upsert_results(
    con: sqlite3.Connection, search_id: str, matches: list[dict], now: str
) -> int:
    """Upsert matches and delete rows that no longer match. Returns count."""
    seen_ids: set[str] = set()
    cur = con.cursor()
    for row in matches:
        lid = (row.get("listing_id") or "").strip()
        if not lid:
            continue
        seen_ids.add(lid)
        snapshot = {
            "address": row.get("address") or None,
            "city": row.get("city") or None,
            "highSchool": row.get("high_school") or None,
            "price": _to_float(row.get("list_price")),
            "sqft": _to_int(row.get("sqft")),
            "beds": _to_int(row.get("bedrooms")),
            "fullBaths": _to_int(row.get("full_baths")),
            "acres": _to_float(row.get("acres")),
            "yearBuilt": _to_int(row.get("year_built")),
            "feedDom": _to_int(row.get("feed_dom")),
            "listOffice": row.get("list_office_name") or None,
            "latitude": _to_float(row.get("latitude")),
            "longitude": _to_float(row.get("longitude")),
            "milesToCenter": _to_float(row.get("miles_to_center")),
        }
        existing = cur.execute(
            "SELECT id FROM SavedSearchResult WHERE searchId = ? AND listingId = ?",
            (search_id, lid),
        ).fetchone()
        if existing:
            cur.execute(
                """UPDATE SavedSearchResult SET
                    lastSeenAt = ?,
                    address = ?, city = ?, highSchool = ?,
                    price = ?, sqft = ?, beds = ?, fullBaths = ?,
                    acres = ?, yearBuilt = ?, feedDom = ?, listOffice = ?,
                    latitude = ?, longitude = ?, milesToCenter = ?
                  WHERE id = ?""",
                (
                    now,
                    snapshot["address"], snapshot["city"], snapshot["highSchool"],
                    snapshot["price"], snapshot["sqft"], snapshot["beds"], snapshot["fullBaths"],
                    snapshot["acres"], snapshot["yearBuilt"], snapshot["feedDom"], snapshot["listOffice"],
                    snapshot["latitude"], snapshot["longitude"], snapshot["milesToCenter"],
                    existing["id"],
                ),
            )
        else:
            # cuid-equivalent: just use listingId+timestamp as a unique-enough
            # local id. Prisma reads back by composite (searchId, listingId).
            new_id = f"r_{lid}_{int(datetime.now().timestamp() * 1000)}"
            cur.execute(
                """INSERT INTO SavedSearchResult
                    (id, searchId, listingId, firstSeenAt, lastSeenAt,
                     address, city, highSchool, price, sqft, beds, fullBaths,
                     acres, yearBuilt, feedDom, listOffice,
                     latitude, longitude, milesToCenter)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id, search_id, lid, now, now,
                    snapshot["address"], snapshot["city"], snapshot["highSchool"],
                    snapshot["price"], snapshot["sqft"], snapshot["beds"], snapshot["fullBaths"],
                    snapshot["acres"], snapshot["yearBuilt"], snapshot["feedDom"], snapshot["listOffice"],
                    snapshot["latitude"], snapshot["longitude"], snapshot["milesToCenter"],
                ),
            )

    # Drop rows that didn't match this time.
    if seen_ids:
        placeholders = ",".join("?" for _ in seen_ids)
        cur.execute(
            f"DELETE FROM SavedSearchResult WHERE searchId = ? "
            f"AND listingId NOT IN ({placeholders})",
            (search_id, *seen_ids),
        )
    else:
        cur.execute("DELETE FROM SavedSearchResult WHERE searchId = ?", (search_id,))

    return len(seen_ids)


def run_all_db_searches() -> dict[str, dict]:
    """Run every non-paused saved search stored in the dashboard DB."""
    summary: dict[str, dict] = {}
    con = _open_db()
    try:
        searches = _load_searches(con)
        if not searches:
            return {"_meta": {"count": 0, "note": "no saved searches in dashboard DB"}}
        now = _now_iso()
        for s in searches:
            matches, err = _run_one(s["id"], s["name"], s["criteria"])
            if err:
                con.execute(
                    "UPDATE SavedSearch SET lastRunAt = ?, lastError = ?, lastMatchCount = 0 WHERE id = ?",
                    (now, err, s["id"]),
                )
                summary[s["displayId"]] = {"name": s["name"], "error": err}
                continue
            n = _upsert_results(con, s["id"], matches, now)
            con.execute(
                "UPDATE SavedSearch SET lastRunAt = ?, lastError = NULL, lastMatchCount = ? WHERE id = ?",
                (now, n, s["id"]),
            )
            summary[s["displayId"]] = {"name": s["name"], "matches": n}
        con.commit()
    finally:
        con.close()
    # Clean up the temp CSV.
    if TMP_CSV.exists():
        try:
            TMP_CSV.unlink()
        except OSError:
            pass
    return summary
