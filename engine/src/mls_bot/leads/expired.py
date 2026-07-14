"""Expired / withdrawn / cancelled MLS listings.

Fires when a listing's most recent status flips to one of the "failed to sell"
states. Uses listing_history so we catch the transition even if an MLS update
arrives days after status change.

IMPORTANT: your NRV MLS participation agreement almost certainly restricts
contacting sellers while their listing is active. Expired/withdrawn/cancelled
typically sit outside that restriction — but confirm against your specific
agreement before you make calls.
"""

from __future__ import annotations

from ..db import connect

EXPIRED_STATUSES = ("Expired", "Withdrawn", "Cancelled", "Canceled")

# Find listings whose latest status is "failed to sell" AND for which we
# haven't yet created an EXPIRED lead.
DETECT_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (listing_id)
        listing_id, status, observed_at
    FROM listing_history
    ORDER BY listing_id, observed_at DESC
)
SELECT l.listing_id,
       l.mls_number,
       l.site_addr,
       l.city,
       l.zip,
       l.list_price,
       l.original_list_price,
       l.list_date,
       l.expiration_date,
       l.dom,
       l.bedrooms,
       l.full_baths,
       l.half_baths,
       l.sqft,
       l.status,
       latest.observed_at AS status_changed_at
FROM listings l
JOIN latest USING (listing_id)
WHERE latest.status = ANY(%s)
  AND l.city = 'Blacksburg'
  AND NOT EXISTS (
      SELECT 1 FROM leads
      WHERE leads.category = 'EXPIRED'
        AND leads.listing_id = l.listing_id
  );
"""

INSERT_SQL = """
INSERT INTO leads (category, listing_id, parcel_id, score, detail)
VALUES ('EXPIRED', %(listing_id)s, %(parcel_id)s, %(score)s, %(detail)s::jsonb)
ON CONFLICT (category, coalesce(parcel_id,''), coalesce(listing_id,'')) DO NOTHING;
"""


def _score(row: dict) -> int:
    # crude: longer DOM and recent expiry = higher intent to sell now
    dom = row.get("dom") or 0
    base = 50
    if dom >= 180: base += 20
    elif dom >= 90: base += 10
    if row.get("list_price") and row.get("original_list_price"):
        if row["list_price"] < row["original_list_price"]:
            base += 10  # already reduced price = signal of motivation
    return min(base, 100)


def detect() -> int:
    import json as _json
    n = 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute(DETECT_SQL, (list(EXPIRED_STATUSES),))
        rows = cur.fetchall()
        for r in rows:
            cur.execute(INSERT_SQL, {
                "listing_id": r["listing_id"],
                "parcel_id": None,
                "score": _score(r),
                "detail": _json.dumps({
                    "mls_number": r["mls_number"],
                    "site_addr": r["site_addr"],
                    "city": r["city"],
                    "zip": r["zip"],
                    "list_price": float(r["list_price"]) if r["list_price"] else None,
                    "original_list_price": float(r["original_list_price"]) if r["original_list_price"] else None,
                    "dom": r["dom"],
                    "bedrooms": r["bedrooms"],
                    "sqft": r["sqft"],
                    "status": r["status"],
                    "status_changed_at": r["status_changed_at"].isoformat() if r["status_changed_at"] else None,
                }),
            })
            n += cur.rowcount
        conn.commit()
    return n
