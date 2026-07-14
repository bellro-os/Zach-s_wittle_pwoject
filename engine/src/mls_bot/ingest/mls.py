"""NRV MLS ingest — two code paths.

Pick one by setting MLS_MODE=reso (preferred) or MLS_MODE=rets in .env.

RESO Web API (OData/JSON): modern, the go-forward standard. If NRV MLS offers
it, use it. The RESO standard resource for listings is "Property". We pull
all changes since the last successful run using $filter=ModificationTimestamp gt ...

RETS 1.x (legacy XML): fallback. Requires rets-python. The NRV MLS
field names for STATUS / LIST_DATE / etc. will almost certainly differ
from the standard RESO names — fill in the mapping in RETS_FIELD_MAP
once you have the metadata export from the MLS.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import load
from ..db import connect


# RESO standard field name -> our column name.
RESO_MAP = {
    "ListingKey": "listing_id",
    "ListingId": "mls_number",
    "StandardStatus": "status",
    "StatusChangeTimestamp": "status_changed_at",
    "ListPrice": "list_price",
    "OriginalListPrice": "original_list_price",
    "ClosePrice": "sold_price",
    "ListingContractDate": "list_date",
    "ExpirationDate": "expiration_date",
    "CloseDate": "close_date",
    "DaysOnMarket": "dom",
    "PropertyType": "property_type",
    "BedroomsTotal": "bedrooms",
    "BathroomsFull": "full_baths",
    "BathroomsHalf": "half_baths",
    "LivingArea": "sqft",
    "YearBuilt": "year_built",
    "UnparsedAddress": "site_addr",
    "City": "city",
    "StateOrProvince": "state",
    "PostalCode": "zip",
    "ListAgentKey": "list_agent_key",
    "ListOfficeKey": "list_office_key",
    "PublicRemarks": "public_remarks",
}


def _reso_token(s) -> str:
    r = httpx.post(
        s.reso_token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": s.reso_client_id,
            "client_secret": s.reso_client_secret,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _iso(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _date(v: Any) -> date | None:
    d = _iso(v)
    return d.date() if d else None


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
def _reso_page(client: httpx.Client, url: str) -> dict:
    r = client.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def _last_mod() -> datetime:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT max(updated_at) AS t FROM listings")
        t = cur.fetchone()["t"]
        return t or datetime(2000, 1, 1, tzinfo=timezone.utc)


def fetch_reso_listings() -> Iterable[dict]:
    s = load()
    token = _reso_token(s)
    since = _last_mod().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # Scope to Blacksburg to stay within IDX display rules at phase 1.
    url = (
        f"{s.reso_base_url.rstrip('/')}/Property"
        f"?$filter=City eq 'Blacksburg' and ModificationTimestamp gt {since}"
        f"&$orderby=ModificationTimestamp asc&$top=200"
    )
    with httpx.Client(headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "mls-bot/0.1",
    }) as client:
        while url:
            data = _reso_page(client, url)
            for item in data.get("value", []):
                yield item
            url = data.get("@odata.nextLink") or ""


def _map_reso(item: dict) -> dict:
    out: dict[str, Any] = {"raw": json.dumps(item)}
    for src, dst in RESO_MAP.items():
        out[dst] = item.get(src)
    out["status_changed_at"] = _iso(out.get("status_changed_at"))
    out["list_date"] = _date(out.get("list_date"))
    out["expiration_date"] = _date(out.get("expiration_date"))
    out["close_date"] = _date(out.get("close_date"))
    for k in ("bedrooms", "full_baths", "half_baths", "sqft", "year_built", "dom"):
        v = out.get(k)
        if v is not None:
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                out[k] = None
    for k in ("list_price", "original_list_price", "sold_price"):
        v = out.get(k)
        if v is not None:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = None
    return out


UPSERT = """
INSERT INTO listings (
    listing_id, mls_number, status, status_changed_at,
    list_price, original_list_price, sold_price,
    list_date, expiration_date, close_date, dom,
    property_type, bedrooms, full_baths, half_baths, sqft, year_built,
    site_addr, city, state, zip,
    list_agent_key, list_office_key, public_remarks,
    raw, updated_at
) VALUES (
    %(listing_id)s, %(mls_number)s, %(status)s, %(status_changed_at)s,
    %(list_price)s, %(original_list_price)s, %(sold_price)s,
    %(list_date)s, %(expiration_date)s, %(close_date)s, %(dom)s,
    %(property_type)s, %(bedrooms)s, %(full_baths)s, %(half_baths)s, %(sqft)s, %(year_built)s,
    %(site_addr)s, %(city)s, %(state)s, %(zip)s,
    %(list_agent_key)s, %(list_office_key)s, %(public_remarks)s,
    %(raw)s, now()
)
ON CONFLICT (listing_id) DO UPDATE SET
    status = EXCLUDED.status,
    status_changed_at = EXCLUDED.status_changed_at,
    list_price = EXCLUDED.list_price,
    original_list_price = COALESCE(listings.original_list_price, EXCLUDED.original_list_price),
    sold_price = EXCLUDED.sold_price,
    expiration_date = EXCLUDED.expiration_date,
    close_date = EXCLUDED.close_date,
    dom = EXCLUDED.dom,
    public_remarks = EXCLUDED.public_remarks,
    raw = EXCLUDED.raw,
    updated_at = now()
RETURNING (xmax = 0) AS inserted,
          (SELECT status FROM listings WHERE listing_id = EXCLUDED.listing_id) AS prev_status;
"""

HISTORY_INSERT = """
INSERT INTO listing_history (listing_id, status, list_price)
VALUES (%s, %s, %s);
"""


def _write(rows: Iterable[dict]) -> tuple[int, int]:
    n_ins = n_upd = 0
    with connect() as conn, conn.cursor() as cur:
        for row in rows:
            if not row.get("listing_id") or not row.get("status"):
                continue
            cur.execute(
                "SELECT status FROM listings WHERE listing_id = %s",
                (row["listing_id"],),
            )
            prev = cur.fetchone()
            cur.execute(UPSERT, row)
            if prev is None:
                n_ins += 1
                cur.execute(HISTORY_INSERT, (row["listing_id"], row["status"], row.get("list_price")))
            else:
                n_upd += 1
                if prev["status"] != row["status"]:
                    cur.execute(HISTORY_INSERT, (row["listing_id"], row["status"], row.get("list_price")))
        conn.commit()
    return n_ins, n_upd


def refresh() -> tuple[int, int]:
    s = load()
    if s.mls_mode == "reso":
        return _write(_map_reso(x) for x in fetch_reso_listings())
    if s.mls_mode == "rets":
        raise NotImplementedError(
            "RETS path not yet wired up. Paste your NRV MLS RETS metadata export "
            "(GetMetadata for the Property resource) and we'll fill in RETS_FIELD_MAP "
            "and the librets/rets-python client."
        )
    raise RuntimeError(f"unknown MLS_MODE={s.mls_mode!r}")
