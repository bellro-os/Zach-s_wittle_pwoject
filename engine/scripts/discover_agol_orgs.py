"""Aggressively probe ArcGIS Online organizations for each VA county.

For each county, try a set of likely AGOL subdomain patterns. If any
resolves to a valid org, list its publicly-searchable Feature/Map
Services that look parcel-related, and probe each for owner+sale fields.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx


COUNTIES_DEAD = [
    "FLOYD", "GILES", "CRAIG", "CARROLL", "WYTHE", "SMYTH", "WASHINGTON",
    "BLAND", "TAZEWELL", "RUSSELL", "DICKENSON", "BUCHANAN", "WISE", "LEE",
    "HALIFAX", "HENRY", "PATRICK", "LUNENBURG", "BRUNSWICK", "MECKLENBURG",
]

COUNTIES_CANDIDATE = [
    "FRANKLIN", "BEDFORD", "PULASKI", "GRAYSON", "CHARLOTTE", "PITTSYLVANIA",
]


def subdomain_candidates(county: str) -> list[str]:
    lo = county.lower().replace("_", "")
    if lo == "roanokecounty":
        lo_bases = ["roanokecountyva", "roanoke", "roanokeva"]
    else:
        lo_bases = [
            f"{lo}cova",
            f"{lo}countyva",
            f"{lo}va",
            f"{lo}",
            f"{lo}-va",
            f"{lo}county",
            f"co-{lo}-va",
        ]
    return [f"https://{b}.maps.arcgis.com" for b in lo_bases]


SIG = {
    "owner": re.compile(r"owner|ownname|ownr|own_name", re.I),
    "sale_price": re.compile(r"sale.?price|saleprice|consideration|price1", re.I),
    "sale_date": re.compile(r"sale.?date|saledate", re.I),
    "acres": re.compile(r"acres|acre_|calc_acreage", re.I),
    "assessed_total": re.compile(r"total.*val|fmv|fair.*mkt|assessed_?total|market_?val", re.I),
    "year_built": re.compile(r"year.?b(ui)?lt|yearblt", re.I),
    "parcel_id": re.compile(r"parcel.?id|^pin$|gpin|pid$", re.I),
}


def score_fields(fields: list[dict]) -> dict:
    names = [f.get("name", "") for f in fields]
    hits = {}
    for k, p in SIG.items():
        for n in names:
            if p.search(n):
                hits[k] = n
                break
    return hits


def probe_layer(client: httpx.Client, url: str) -> tuple[dict | None, list[str]]:
    try:
        r = client.get(url, params={"f": "json"}, timeout=15)
        if r.status_code != 200:
            return None, []
        j = r.json()
    except (httpx.HTTPError, ValueError):
        return None, []
    if "fields" in j:
        return score_fields(j["fields"]), [f.get("name", "") for f in j["fields"]]
    return None, []


def probe_service(client: httpx.Client, url: str) -> list[dict]:
    """Walk into a FeatureServer/MapServer and return per-layer probe results."""
    try:
        r = client.get(url, params={"f": "json"}, timeout=15)
        if r.status_code != 200:
            return []
        meta = r.json()
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    layers = (meta.get("layers") or []) + (meta.get("tables") or [])
    for lyr in layers:
        name = (lyr.get("name") or "").lower()
        if not re.search(r"parcel|tax|prop|cama|assess|own", name):
            continue
        sub = f"{url}/{lyr.get('id')}"
        hits, names = probe_layer(client, sub)
        if hits is not None:
            out.append({
                "url": sub,
                "layer_name": lyr.get("name"),
                "signals": hits,
                "field_count": len(names),
            })
    return out


def search_org(client: httpx.Client, org_root: str) -> list[str]:
    """Return service URLs from AGOL search within an org."""
    try:
        self_r = client.get(f"{org_root}/sharing/rest/portals/self", params={"f": "json"}, timeout=12)
        if self_r.status_code != 200:
            return []
        portal = self_r.json()
        org_id = portal.get("id")
        if not org_id:
            return []
    except (httpx.HTTPError, ValueError):
        return []

    query = f'orgid:{org_id} (type:"Feature Service" OR type:"Map Service") (parcel OR tax OR cama OR assess OR property)'
    try:
        r = client.get(
            f"{org_root}/sharing/rest/search",
            params={"q": query, "f": "json", "num": 30, "sortField": "modified", "sortOrder": "desc"},
            timeout=20,
        )
        if r.status_code != 200:
            return []
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return []

    urls = []
    for item in data.get("results", []):
        u = item.get("url")
        t = (item.get("title") or "").lower()
        if not u:
            continue
        if re.search(r"parcel|tax|cama|assess|property|land|real", t):
            urls.append(u)
    return urls


def probe_county(client: httpx.Client, county: str) -> dict:
    tried_orgs: list[str] = []
    candidate_services: list[str] = []
    org_found: str | None = None
    for sub in subdomain_candidates(county):
        tried_orgs.append(sub)
        svc_urls = search_org(client, sub)
        if svc_urls:
            org_found = sub
            candidate_services.extend(svc_urls)
            break

    if not candidate_services:
        return {"county": county, "status": "no_org", "tried_orgs": tried_orgs}

    best: dict | None = None
    for svc in candidate_services:
        probes = probe_service(client, svc.rstrip("/"))
        for p in probes:
            s = len(p["signals"])
            if best is None or s > len(best["signals"]):
                best = p
        if best and len(best["signals"]) >= 4:
            break

    if best is None:
        return {
            "county": county, "status": "org_no_parcels",
            "org": org_found, "candidates": candidate_services,
        }

    has_owner = "owner" in best["signals"]
    has_sale = "sale_price" in best["signals"]
    if has_owner and has_sale:
        status = "ok"
    elif has_owner or has_sale:
        status = "partial"
    else:
        status = "geometry_only"

    return {
        "county": county, "status": status, "org": org_found,
        "url": best["url"], "layer_name": best["layer_name"],
        "signals": best["signals"], "field_count": best["field_count"],
    }


def main() -> int:
    counties = COUNTIES_DEAD + COUNTIES_CANDIDATE
    out_path = Path("data/va_parcel_sources_agol.json")
    results = []
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}, follow_redirects=True) as c:
        for county in counties:
            r = probe_county(c, county)
            results.append(r)
            status = r["status"]
            mark = {"ok": "OK", "partial": "~~", "geometry_only": "..",
                    "no_org": "--", "org_no_parcels": "!!"}.get(status, "??")
            extra = ""
            if status in ("ok", "partial", "geometry_only"):
                extra = f"  {r['layer_name']}  [{','.join(r['signals'])}]"
            print(f"  {mark}  {county:20s}  {status}{extra}")
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    tally: dict = {}
    for r in results:
        tally[r["status"]] = tally.get(r["status"], 0) + 1
    print("\nSummary:")
    for k, v in tally.items():
        print(f"  {k:18s} {v}")
    print(f"\nReport: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
