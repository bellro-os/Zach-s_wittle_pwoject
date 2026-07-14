"""Expired-and-not-relisted watchlist — listings that went Expired/Cancelled
in the last N days and have NOT been re-listed since (matched by normalized
site address, not by MLS#).

This is distinct from `expired_watchlist.py` (which groups by parcel_id and
only filters out parcels with a *currently* active listing). The MLS routinely
issues a relist under a new listing_id at the same address, sometimes with a
different parcel_id reference. The de-dup here is by normalized address, so
those relists drop out cleanly.

Output: outputs/mls_analytics/leads/expired_unrelisted.csv

Auto-runs in mls-daily.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..profile import _norm_mail
from .db import connect
from .expired_watchlist import _scc_url, _whitepages_url, _truepeople_url


OUT_PATH = Path("outputs/mls_analytics/leads/expired_unrelisted.csv")


def build_expired_unrelisted(*, lookback_days: int = 28) -> int:
    """Build the expired-and-not-relisted CSV. Returns row count written."""
    con = connect()

    # Pull recent expireds + the most-recent list_date across ALL listings for
    # each address (computed in SQL, then we apply the suffix-mapped normalization
    # in Python because DuckDB doesn't have the _SUFFIX_MAP).
    #
    # Note: in this MLS feed, status_category="Expired/Cancelled" collapses
    # Expired + Withdrawn + Cancelled into a single bucket — confirmed via
    # SELECT DISTINCT status_category. status_detail is a coded 0/1/2 which
    # isn't useful for distinguishing those three.
    candidate_sql = f"""
    SELECT
        listing_id,
        address,
        address_number,
        address_direction,
        address_street,
        city,
        state,
        zip,
        county,
        subdivision,
        parcel_id,
        TRY_CAST(status_changed_at AS DATE) AS expired_at,
        TRY_CAST(list_date AS DATE)         AS list_date,
        TRY_CAST(list_price AS DOUBLE)      AS last_list_price,
        TRY_CAST(original_list_price AS DOUBLE) AS original_list_price,
        TRY_CAST(bedrooms AS INT)           AS bedrooms,
        TRY_CAST(full_baths AS INT)         AS full_baths,
        TRY_CAST(half_baths AS INT)         AS half_baths,
        TRY_CAST(sqft AS INT)               AS sqft,
        TRY_CAST(year_built AS INT)         AS year_built,
        TRY_CAST(feed_dom AS INT)           AS dom,
        list_office_name,
        property_subtype,
        parcel_owner1                       AS owner,
        TRY_CAST(parcel_assessed_total AS DOUBLE) AS assessed_total,
        parcel_owner_occupied               AS owner_occupied
    FROM listings
    WHERE status_category = 'Expired/Cancelled'
      AND TRY_CAST(status_changed_at AS DATE) >= CURRENT_DATE - INTERVAL {lookback_days} DAY
      AND TRY_CAST(status_changed_at AS DATE) IS NOT NULL
    """

    # All listings — used to detect relists. We need TWO independent checks:
    #
    #   1. Any listing on the same address that is *currently* Active or Pending,
    #      regardless of its list_date. (Catches the common MLS pattern where
    #      an old MLS# is revived back to Active — its list_date may predate
    #      the recent expiration, but it's still actively being marketed today.)
    #
    #   2. Any listing on the same address whose list_date is AFTER our
    #      candidate's expiration date, regardless of its current status.
    #      (Catches the case where a relist came up and has since gone off
    #      market again — still indicates the address has been worked.)
    all_listings_sql = """
    SELECT
        listing_id,
        address,
        city,
        zip,
        status_category,
        TRY_CAST(list_date AS DATE) AS list_date
    FROM listings
    """

    candidates = con.execute(candidate_sql).fetchall()
    candidate_cols = [d[0] for d in con.description]
    all_rows = con.execute(all_listings_sql).fetchall()

    addr_to_latest_listdate: dict[str, object] = {}
    addr_active_or_pending: set[str] = set()
    for lid, addr, city, zipc, status, ld in all_rows:
        norm = _norm_mail(addr, f"{city or ''} {zipc or ''}".strip())
        if not norm:
            continue
        if status in ("Active", "Pending"):
            addr_active_or_pending.add(norm)
        if ld is not None:
            prev = addr_to_latest_listdate.get(norm)
            if prev is None or ld > prev:
                addr_to_latest_listdate[norm] = ld

    # Filter candidates: drop any address that is currently Active/Pending OR
    # has a post-expiration list_date on file. Also collapse multiple
    # expirations on the same address to the most recent (the actionable one).
    keep_by_addr: dict[str, dict] = {}
    for row in candidates:
        rec = dict(zip(candidate_cols, row))
        addr_norm = _norm_mail(
            rec["address"],
            f"{rec['city'] or ''} {rec['zip'] or ''}".strip(),
        )
        if not addr_norm:
            continue
        if addr_norm in addr_active_or_pending:
            continue  # currently being marketed
        latest_ld = addr_to_latest_listdate.get(addr_norm)
        if (
            latest_ld is not None
            and rec["expired_at"] is not None
            and latest_ld > rec["expired_at"]
        ):
            continue  # relisted after this expiration (since gone too)
        rec["normalized_address"] = addr_norm
        prior = keep_by_addr.get(addr_norm)
        if prior is None or (
            rec["expired_at"] is not None
            and (prior["expired_at"] is None or rec["expired_at"] > prior["expired_at"])
        ):
            keep_by_addr[addr_norm] = rec
    keep = list(keep_by_addr.values())

    # Sort freshest-expired first
    keep.sort(key=lambda r: (r["expired_at"] or _Min()), reverse=True)

    # Enrich each row with derived fields + outreach URLs
    today_iso = con.execute("SELECT CURRENT_DATE").fetchone()[0]
    out_rows: list[dict] = []
    for r in keep:
        last = r["last_list_price"] or 0
        orig = r["original_list_price"] or 0
        cut_pct = round(((orig - last) / orig) * 100, 1) if orig and last and last < orig else 0.0
        days_off = (today_iso - r["expired_at"]).days if r["expired_at"] else None
        locality = (r["city"] or "").strip()
        out_rows.append({
            "normalized_address":   r["normalized_address"],
            "address":              r["address"] or "",
            "city":                 r["city"] or "",
            "state":                r["state"] or "",
            "zip":                  r["zip"] or "",
            "county":               (r["county"] or "").upper(),
            "subdivision":          r["subdivision"] or "",
            "parcel_id":            r["parcel_id"] or "",
            "expired_at":           r["expired_at"].isoformat() if r["expired_at"] else "",
            "days_off_market":      days_off if days_off is not None else "",
            "list_date":            r["list_date"].isoformat() if r["list_date"] else "",
            "dom":                  r["dom"] if r["dom"] is not None else "",
            "last_list_price":      int(last) if last else "",
            "original_list_price":  int(orig) if orig else "",
            "price_cut_pct":        cut_pct,
            "bedrooms":             r["bedrooms"] if r["bedrooms"] is not None else "",
            "full_baths":           r["full_baths"] if r["full_baths"] is not None else "",
            "half_baths":           r["half_baths"] if r["half_baths"] is not None else "",
            "sqft":                 r["sqft"] if r["sqft"] is not None else "",
            "year_built":           r["year_built"] if r["year_built"] is not None else "",
            "property_subtype":     r["property_subtype"] or "",
            "owner":                r["owner"] or "",
            "owner_occupied":       "yes" if r["owner_occupied"] else ("no" if r["owner_occupied"] is not None else ""),
            "assessed_total":       int(r["assessed_total"]) if r["assessed_total"] else "",
            "prior_list_office":    r["list_office_name"] or "",
            "mls_id":               r["listing_id"] or "",
            "scc_url":              _scc_url(r["owner"] or "") if r["owner"] else "",
            "whitepages_url":       _whitepages_url(r["owner"] or "", locality) if r["owner"] else "",
            "truepeople_url":       _truepeople_url(r["owner"] or "", locality) if r["owner"] else "",
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        if not out_rows:
            f.write("")
            return 0
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)
    return len(out_rows)


class _Min:
    """Sort sentinel — sorts before all real dates."""
    def __lt__(self, other): return True
    def __gt__(self, other): return False
    def __eq__(self, other): return isinstance(other, _Min)
