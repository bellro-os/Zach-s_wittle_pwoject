"""Pull VA parcels from a registered county's public ArcGIS endpoint.

The per-county URL, field list, and attribute-to-canonical-schema mapper
all live in `sources.py`. This module handles the HTTP plumbing and the
generic row loop; everything county-specific is driven by a `ParcelSource`.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Iterable

import httpx
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from ..config import load
from ..db import connect
from .sources import ParcelSource, SOURCES, get as get_source

PAGE_SIZE = 2000


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
def _fetch_page(
    client: httpx.Client,
    source: ParcelSource,
    where: str,
    offset: int,
    page_size: int,
) -> dict:
    """ESRI JSON format; returns {'features': [{'attributes': ...}, ...]}.
    We don't request geometry here — enrichment adds centroids separately."""
    r = client.get(
        f"{source.url}/query",
        params={
            "where": where,
            "outFields": source.out_fields,
            "f": "json",
            "returnGeometry": "false",
            "orderByFields": f"{source.object_id_field} ASC",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _layer_page_size(client: httpx.Client, source: ParcelSource) -> int:
    """Ask the server how many rows it will return per page. Falls back to
    PAGE_SIZE. Many VA layers cap at 1000."""
    try:
        r = client.get(source.url, params={"f": "json"}, timeout=30)
        meta = r.json()
        mx = int(meta.get("maxRecordCount") or PAGE_SIZE)
        return min(PAGE_SIZE, max(1, mx))
    except Exception:
        return PAGE_SIZE


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
def _fetch_wfs_page(
    client: httpx.Client,
    source: ParcelSource,
    start_index: int,
    page_size: int,
) -> dict:
    # Some VA county GeoServers can't reproject on demand (HTTP 400 with
    # srsName=EPSG:4326). Geometry isn't written to JSONL anyway, so we
    # leave the projection at the layer's native SRS.
    r = client.get(
        source.url,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": source.wfs_typename or "",
            "outputFormat": "application/json",
            "count": page_size,
            "startIndex": start_index,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def fetch_parcels(
    jurisdiction: str | None = None,
    *,
    source: ParcelSource | None = None,
) -> Iterable[dict]:
    """Iterate parcel feature dicts for a source. Dispatches by source.kind."""
    if source is None:
        s = load()
        if jurisdiction is None:
            jurisdiction = s.assessor_jurisdiction
        source = SOURCES["MONTGOMERY"]

    if source.kind == "geoserver_wfs":
        with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}, timeout=300) as client:
            page_size = 1000
            # First page — also tells us whether the server accepts startIndex.
            try:
                data = _fetch_wfs_page(client, source, 0, page_size)
            except (httpx.HTTPStatusError, RetryError):
                data = None

            if data is None:
                # Pagination unsupported (old GeoServer); fetch everything in
                # one request. Memory cost: ~30-100 MB JSON for VA counties.
                r = client.get(source.url, params={
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": source.wfs_typename or "",
                    "outputFormat": "application/json",
                })
                r.raise_for_status()
                for f in r.json().get("features", []) or []:
                    yield f
                return

            feats = data.get("features", []) or []
            for f in feats:
                yield f
            if len(feats) < page_size:
                return

            start = len(feats)
            while True:
                data = _fetch_wfs_page(client, source, start, page_size)
                feats = data.get("features", []) or []
                if not feats:
                    return
                for f in feats:
                    yield f
                start += len(feats)
                if len(feats) < page_size:
                    return
        return

    # ArcGIS REST path
    where = "1=1"
    jfield = source.jurisdiction_filter_field
    if jfield and jurisdiction and jurisdiction.upper() != "ALL":
        where = f"{jfield}='{jurisdiction}'"

    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}) as client:
        page_size = _layer_page_size(client, source)
        offset = 0
        while True:
            data = _fetch_page(client, source, where, offset, page_size)
            feats = data.get("features", [])
            if not feats:
                return
            for f in feats:
                yield f
            offset += len(feats)
            if len(feats) < page_size:
                return


UPSERT = """
INSERT INTO properties (
    parcel_id, tax_map_id, jurisdiction,
    site_addr1, site_addr2, mail_addr1, mail_addr2,
    owner1, owner2,
    assessed_total, assessed_land, assessed_bldg,
    last_sale_date, last_sale_price,
    acres, year_built, bedrooms, full_baths, half_baths,
    sfla, stories, zoning, subd_name, neighborhood,
    deedbook, deedpage,
    geom, centroid, raw, updated_at
) VALUES (
    %(parcel_id)s, %(tax_map_id)s, %(jurisdiction)s,
    %(site_addr1)s, %(site_addr2)s, %(mail_addr1)s, %(mail_addr2)s,
    %(owner1)s, %(owner2)s,
    %(assessed_total)s, %(assessed_land)s, %(assessed_bldg)s,
    %(last_sale_date)s, %(last_sale_price)s,
    %(acres)s, %(year_built)s, %(bedrooms)s, %(full_baths)s, %(half_baths)s,
    %(sfla)s, %(stories)s, %(zoning)s, %(subd_name)s, %(neighborhood)s,
    %(deedbook)s, %(deedpage)s,
    ST_Multi(ST_GeomFromGeoJSON(%(geom_json)s)),
    ST_Centroid(ST_GeomFromGeoJSON(%(geom_json)s)),
    %(raw)s, now()
)
ON CONFLICT (parcel_id) DO UPDATE SET
    tax_map_id      = EXCLUDED.tax_map_id,
    jurisdiction    = EXCLUDED.jurisdiction,
    site_addr1      = EXCLUDED.site_addr1,
    site_addr2      = EXCLUDED.site_addr2,
    mail_addr1      = EXCLUDED.mail_addr1,
    mail_addr2      = EXCLUDED.mail_addr2,
    owner1          = EXCLUDED.owner1,
    owner2          = EXCLUDED.owner2,
    assessed_total  = EXCLUDED.assessed_total,
    assessed_land   = EXCLUDED.assessed_land,
    assessed_bldg   = EXCLUDED.assessed_bldg,
    last_sale_date  = EXCLUDED.last_sale_date,
    last_sale_price = EXCLUDED.last_sale_price,
    acres           = EXCLUDED.acres,
    year_built      = EXCLUDED.year_built,
    bedrooms        = EXCLUDED.bedrooms,
    full_baths      = EXCLUDED.full_baths,
    half_baths      = EXCLUDED.half_baths,
    sfla            = EXCLUDED.sfla,
    stories         = EXCLUDED.stories,
    zoning          = EXCLUDED.zoning,
    subd_name       = EXCLUDED.subd_name,
    neighborhood    = EXCLUDED.neighborhood,
    deedbook        = EXCLUDED.deedbook,
    deedpage        = EXCLUDED.deedpage,
    geom            = EXCLUDED.geom,
    centroid        = EXCLUDED.centroid,
    raw             = EXCLUDED.raw,
    updated_at      = now();
"""


def _row(feature: dict, source: ParcelSource) -> dict | None:
    # ESRI JSON uses "attributes"; fall back to "properties" if the server
    # happens to return geoJSON.
    p = feature.get("attributes") or feature.get("properties") or {}
    row = source.to_canonical(p)
    if not row.get("parcel_id"):
        return None
    geom = feature.get("geometry")
    row["geom_json"] = json.dumps(geom) if geom else None
    row["raw"] = json.dumps(p)
    return row


def refresh(jurisdiction: str | None = None, *, county: str = "MONTGOMERY") -> int:
    source = get_source(county)
    n = 0
    with connect() as conn, conn.cursor() as cur:
        for feat in fetch_parcels(jurisdiction, source=source):
            row = _row(feat, source)
            if not row or not row["geom_json"]:
                continue
            cur.execute(UPSERT, row)
            n += 1
            if n % 500 == 0:
                conn.commit()
        conn.commit()
    return n


def dump_sample(
    out_path: str,
    limit: int | None = None,
    jurisdiction: str | None = None,
    *,
    county: str = "MONTGOMERY",
) -> dict:
    """Fetch parcels from a county and write each parsed row as JSONL. No DB required."""
    import json as _json

    source = get_source(county)
    stats: dict = {
        "county": county,
        "fetched": 0, "parsed": 0, "skipped": 0,
        "has_owner": 0, "has_sale_date": 0, "has_mail_addr": 0,
        "absentee_candidates": 0,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        for feat in fetch_parcels(jurisdiction, source=source):
            stats["fetched"] += 1
            row = _row(feat, source)
            if not row:
                stats["skipped"] += 1
                continue
            stats["parsed"] += 1
            if row.get("owner1"):
                stats["has_owner"] += 1
            if row.get("last_sale_date"):
                stats["has_sale_date"] += 1
            if row.get("mail_addr1"):
                stats["has_mail_addr"] += 1
            site = (row.get("site_addr1") or "").strip().upper()
            mail = (row.get("mail_addr1") or "").strip().upper()
            if site and mail and site != mail:
                stats["absentee_candidates"] += 1

            serializable = {
                k: (v.isoformat() if isinstance(v, date) else v)
                for k, v in row.items() if k != "geom_json"
            }
            f.write(_json.dumps(serializable, ensure_ascii=False) + "\n")

            if limit and stats["parsed"] >= limit:
                break
    return stats
