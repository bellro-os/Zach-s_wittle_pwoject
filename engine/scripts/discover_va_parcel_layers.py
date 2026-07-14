"""Probe VA county GIS endpoints for public ArcGIS parcel layers.

For each county in the "south of Roanoke" target list, we try a small set
of common URL patterns. If we reach a Services root, we list its services
and look for anything with "parcel" in the name. If we reach a FeatureServer
or MapServer, we list layers. If we reach a specific layer, we inspect its
fields and score it on whether it exposes owner/sale/assessment attributes.

Output: data/va_parcel_sources.json — one entry per county with the best
layer found (if any), the fields it has, and a status/notes field.

Usage:
    python scripts/discover_va_parcel_layers.py --out data/va_parcel_sources.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx


TARGET_COUNTIES: list[str] = [
    # NRV / SW
    "FLOYD", "FRANKLIN", "PULASKI", "GILES", "CRAIG",
    "CARROLL", "GRAYSON", "WYTHE", "SMYTH", "WASHINGTON",
    "BLAND", "TAZEWELL", "RUSSELL", "SCOTT", "LEE",
    "DICKENSON", "BUCHANAN", "WISE",
    # Roanoke-adjacent
    "ROANOKE_COUNTY", "BEDFORD",
    # Southside
    "HENRY", "PATRICK", "PITTSYLVANIA", "HALIFAX",
    "MECKLENBURG", "CHARLOTTE", "LUNENBURG", "BRUNSWICK",
]

# Known / likely ArcGIS services roots or layer URLs per county.
# Entries can be service roots (ending /rest/services) OR direct layer URLs.
CANDIDATES: dict[str, list[str]] = {
    "FLOYD":        ["https://gis.floydcova.org/arcgis/rest/services"],
    "FRANKLIN":     ["https://gis.franklincountyva.gov/arcgis/rest/services",
                     "https://gis.franklincountyva.org/arcgis/rest/services"],
    "PULASKI":      ["https://gis.pulaskicounty.org/arcgis/rest/services"],
    "GILES":        ["https://gis.gilescountyva.gov/arcgis/rest/services"],
    "CRAIG":        ["https://gis.craigcountyva.us/arcgis/rest/services"],
    "CARROLL":      ["https://gis.carrollcountyva.org/arcgis/rest/services"],
    "GRAYSON":      ["https://gis.graysoncountyva.com/arcgis/rest/services"],
    "WYTHE":        ["https://gis.wytheco.org/arcgis/rest/services"],
    "SMYTH":        ["https://gis.smythcounty.org/arcgis/rest/services"],
    "WASHINGTON":   ["https://gis.washcova.com/arcgis/rest/services",
                     "https://gis.washcova.com/server/rest/services"],
    "BLAND":        ["https://gis.blandcountyva.gov/arcgis/rest/services"],
    "TAZEWELL":     ["https://gis.tazewellcounty.org/arcgis/rest/services"],
    "RUSSELL":      ["https://gis.russellcountyva.us/arcgis/rest/services"],
    "SCOTT":        ["https://gis.scottcountyva.com/arcgis/rest/services"],
    "LEE":          ["https://gis.leecova.org/arcgis/rest/services"],
    "DICKENSON":    ["https://gis.dickensonva.org/arcgis/rest/services"],
    "BUCHANAN":     ["https://gis.buchanancountyonline.com/arcgis/rest/services"],
    "WISE":         ["https://gis.wisecounty.org/arcgis/rest/services"],
    "ROANOKE_COUNTY": [
        "https://gis.roanokecountyva.gov/arcgis/rest/services",
        "https://gispub.roanokecountyva.gov/arcgis/rest/services",
    ],
    "BEDFORD":      ["https://gis.bedfordcountyva.gov/arcgis/rest/services",
                     "https://gis.bedfordva.gov/arcgis/rest/services"],
    "HENRY":        ["https://gis.henrycountyva.gov/arcgis/rest/services",
                     "https://gis.henrycountyva.org/arcgis/rest/services"],
    "PATRICK":      ["https://gis.co.patrick.va.us/arcgis/rest/services",
                     "https://gis.patrickcountyva.gov/arcgis/rest/services"],
    "PITTSYLVANIA": ["https://gis.pittsylvaniacountyva.gov/arcgis/rest/services",
                     "https://gis.pittgov.org/arcgis/rest/services"],
    "HALIFAX":      ["https://gis.halifaxcountyva.gov/arcgis/rest/services"],
    "MECKLENBURG":  ["https://gis.mecklenburgva.com/arcgis/rest/services"],
    "CHARLOTTE":    ["https://gis.co.charlotte.va.us/arcgis/rest/services"],
    "LUNENBURG":    ["https://gis.lunenburgcova.gov/arcgis/rest/services"],
    "BRUNSWICK":    ["https://gis.brunswickcountyva.gov/arcgis/rest/services"],
}

# Field-name regexes used to score how useful a layer is.
SIGNAL_PATTERNS: dict[str, re.Pattern] = {
    "parcel_id":      re.compile(r"^(parcel|pin|gpin|pid)[_ ]?(id|num|number)?$", re.I),
    "owner":          re.compile(r"^(owner|own|ownname|ownr|owner1|owner_name)$", re.I),
    "site_addr":      re.compile(r"^(site|phys|prop|prem|situs).*(add|str|add1)?|site_?add1?$", re.I),
    "mail_addr":      re.compile(r"^mail.*(add|addr|add1)?", re.I),
    "sale_price":     re.compile(r"^(sale|sales|last_?sale|consid).*(pric|amt|amount|consideration)?$", re.I),
    "sale_date":      re.compile(r"^(sale|sales|last_?sale).*(date|dt)?$", re.I),
    "acres":          re.compile(r"^(acres|nacres|land.*acre)$", re.I),
    "assessed_total": re.compile(r"^(total.*val|ttl.*val|assessed.*total|fmv|fair.*mkt)$", re.I),
    "year_built":     re.compile(r"^(year.*b(ui)?lt|yr.*b(ui)?lt|yearbuilt|yrblt|yearblt)$", re.I),
}


def _get(client: httpx.Client, url: str, params: dict | None = None) -> dict | None:
    try:
        r = client.get(url, params={**(params or {}), "f": "json"}, timeout=15)
        if r.status_code != 200:
            return None
        if "application/json" not in (r.headers.get("content-type") or "").lower():
            # Some servers return HTML 200 for missing endpoints.
            try:
                return r.json()
            except ValueError:
                return None
        return r.json()
    except httpx.HTTPError:
        return None


def _score_fields(fields: list[dict]) -> dict:
    """Given an ArcGIS layer's fields list, tag which signals are present."""
    names = [f.get("name", "") for f in fields]
    hits: dict[str, str] = {}
    for signal, pat in SIGNAL_PATTERNS.items():
        for name in names:
            if pat.match(name):
                hits[signal] = name
                break
    return {"field_count": len(names), "field_names": names, "signals": hits}


def _probe_layer(client: httpx.Client, layer_url: str) -> dict | None:
    meta = _get(client, layer_url)
    if not meta or "fields" not in meta:
        return None
    info = _score_fields(meta["fields"])
    info["name"] = meta.get("name")
    info["type"] = meta.get("type")
    info["geometryType"] = meta.get("geometryType")
    info["url"] = layer_url
    return info


def _probe_server(client: httpx.Client, server_url: str) -> list[dict]:
    """server_url is a FeatureServer or MapServer root; return per-layer probes."""
    meta = _get(client, server_url)
    if not meta:
        return []
    layers = (meta.get("layers") or []) + (meta.get("tables") or [])
    out: list[dict] = []
    for lyr in layers:
        name = (lyr.get("name") or "").lower()
        if "parcel" not in name and "tax" not in name and "prop" not in name:
            continue
        lid = lyr.get("id")
        if lid is None:
            continue
        probe = _probe_layer(client, f"{server_url}/{lid}")
        if probe:
            out.append(probe)
    return out


AGOL_SEARCH = "https://www.arcgis.com/sharing/rest/search"


def _agol_search(client: httpx.Client, county: str) -> list[str]:
    """Return candidate FeatureServer/MapServer URLs for a county via AGOL search."""
    pretty = county.replace("_", " ").title()
    queries = [
        f'"{pretty} County" Virginia parcels',
        f'"{pretty}" Virginia parcels',
        f'{pretty} County VA parcel',
    ]
    urls: list[str] = []
    seen: set[str] = set()
    for q in queries:
        try:
            r = client.get(AGOL_SEARCH, params={
                "q": q,
                "f": "json",
                "num": 20,
                "sortField": "numViews",
                "sortOrder": "desc",
            }, timeout=20)
            if r.status_code != 200:
                continue
            data = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        for item in data.get("results") or []:
            url = item.get("url") or ""
            title = (item.get("title") or "").lower()
            itype = item.get("type") or ""
            if not url:
                continue
            if "parcel" not in title and "tax" not in title and "cama" not in title:
                continue
            if itype not in ("Feature Service", "Map Service"):
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _probe_services_root(client: httpx.Client, root_url: str) -> list[dict]:
    meta = _get(client, root_url)
    if not meta:
        return []
    out: list[dict] = []
    services = meta.get("services") or []
    for svc in services:
        name = (svc.get("name") or "")
        stype = (svc.get("type") or "")
        if not re.search(r"parcel|land|cama|assess|tax", name, re.I):
            continue
        if stype not in ("FeatureServer", "MapServer"):
            continue
        svc_url = f"{root_url}/{name}/{stype}"
        out.extend(_probe_server(client, svc_url))
    return out


def probe_county(client: httpx.Client, county: str, urls: list[str]) -> dict:
    best: dict | None = None
    tried: list[str] = []
    for url in urls:
        tried.append(url)
        if re.search(r"/(MapServer|FeatureServer)/\d+/?$", url):
            p = _probe_layer(client, url.rstrip("/"))
            candidates = [p] if p else []
        elif re.search(r"/(MapServer|FeatureServer)/?$", url):
            candidates = _probe_server(client, url.rstrip("/"))
        else:
            candidates = _probe_services_root(client, url.rstrip("/"))
        for c in candidates:
            sig_count = len(c["signals"])
            if best is None or sig_count > len(best["signals"]):
                best = c
        if best and len(best["signals"]) >= 4:
            break

    if best is None:
        return {"county": county, "status": "not_found", "tried": tried}

    signals = best["signals"]
    has_owner = "owner" in signals
    has_sale = "sale_price" in signals
    if has_owner and has_sale:
        status = "ok"
    elif has_owner or has_sale:
        status = "partial"
    else:
        status = "geometry_only"

    return {
        "county": county,
        "status": status,
        "url": best["url"],
        "layer_name": best.get("name"),
        "signals": signals,
        "field_count": best.get("field_count"),
        "geometryType": best.get("geometryType"),
        "tried": tried,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/va_parcel_sources.json")
    args = ap.parse_args()

    results: list[dict] = []
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1 discovery"}) as client:
        for county in TARGET_COUNTIES:
            urls = list(CANDIDATES.get(county, []))
            agol_urls = _agol_search(client, county)
            for u in agol_urls:
                if u not in urls:
                    urls.append(u)
            if not urls:
                results.append({"county": county, "status": "no_candidates"})
                print(f"  ??  {county:20s}  no candidate URLs")
                continue
            res = probe_county(client, county, urls)
            status = res["status"]
            marker = {"ok": "OK", "partial": "~~", "geometry_only": "..",
                      "not_found": "--", "no_candidates": "??"}.get(status, "??")
            suffix = ""
            if status in ("ok", "partial", "geometry_only"):
                suffix = f"  {res.get('layer_name', '')}  [{','.join(res['signals'])}]"
            print(f"  {marker}  {county:20s}  {status}{suffix}")
            results.append(res)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    tallies: dict[str, int] = {}
    for r in results:
        tallies[r["status"]] = tallies.get(r["status"], 0) + 1
    print("\nSummary:")
    for k in ("ok", "partial", "geometry_only", "not_found", "no_candidates"):
        if k in tallies:
            print(f"  {k:15s} {tallies[k]}")
    print(f"\nReport: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
