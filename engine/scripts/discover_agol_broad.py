"""Broader AGOL search for VA counties that didn't match a predictable subdomain.

For each remaining county, run unauthenticated AGOL searches against the
global endpoint (not scoped to an org) with queries tuned to match on
county name + state + parcel-ish tokens. For each hit that points at a
FeatureServer or MapServer with `parcel` in the URL/title, walk the
service and score fields.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx


REMAINING = [
    "FLOYD", "GILES", "CRAIG", "CARROLL", "WYTHE", "SMYTH", "WASHINGTON",
    "BLAND", "RUSSELL", "DICKENSON", "WISE", "LEE",
    "HALIFAX", "PATRICK", "LUNENBURG", "BRUNSWICK", "MECKLENBURG",
    "BEDFORD", "PULASKI", "GRAYSON",
    # Also re-check BUCHANAN, GILES (found orgs but no parcels via in-org search)
    "BUCHANAN",
]


SIG = {
    "owner": re.compile(r"owner|ownname|ownr|own_name|ownername", re.I),
    "sale_price": re.compile(r"sale.?price|saleprice|consideration|price1", re.I),
    "sale_date": re.compile(r"sale.?date|saledate", re.I),
    "acres": re.compile(r"^acres$|acres[_ ]|acreage|calc_acreage|gisacres", re.I),
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


def probe_layer(client: httpx.Client, url: str) -> dict | None:
    try:
        r = client.get(url, params={"f": "json"}, timeout=15)
        if r.status_code != 200:
            return None
        j = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if "fields" in j:
        return {"fields": j["fields"], "name": j.get("name")}
    return None


def probe_service(client: httpx.Client, url: str) -> list[dict]:
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
        probe = probe_layer(client, sub)
        if not probe:
            continue
        out.append({
            "url": sub,
            "layer_name": probe["name"] or lyr.get("name"),
            "signals": score_fields(probe["fields"]),
            "field_count": len(probe["fields"]),
        })
    return out


def global_search(client: httpx.Client, county: str) -> list[str]:
    pretty = county.replace("_", " ").title()
    queries = [
        f'"{pretty} County" Virginia parcels type:"Feature Service"',
        f'"{pretty} County" Virginia parcels type:"Map Service"',
        f'"{pretty}" Virginia parcel',
        f'{pretty} VA tax parcel',
    ]
    urls: list[str] = []
    seen: set[str] = set()
    for q in queries:
        try:
            r = client.get(
                "https://www.arcgis.com/sharing/rest/search",
                params={"q": q, "f": "json", "num": 25,
                        "sortField": "numViews", "sortOrder": "desc"},
                timeout=20,
            )
            if r.status_code != 200:
                continue
            data = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        for item in data.get("results", []):
            u = item.get("url") or ""
            title = (item.get("title") or "")
            if not u or u in seen:
                continue
            # County name has to appear in title OR url to avoid cross-county contamination.
            if (county.lower() not in title.lower()) and (county.lower() not in u.lower()):
                continue
            if not re.search(r"parcel|tax|cama|assess|property|land", title, re.I) \
               and not re.search(r"parcel|tax|cama|assess|property|land", u, re.I):
                continue
            seen.add(u)
            urls.append(u)
    return urls


def probe_county(client: httpx.Client, county: str) -> dict:
    urls = global_search(client, county)
    if not urls:
        return {"county": county, "status": "no_candidates"}
    best: dict | None = None
    tried: list[str] = []
    for svc in urls:
        tried.append(svc)
        stripped = svc.rstrip("/")
        # Case 1: direct layer URL (ends with /<digit>)
        if re.search(r"/\d+$", stripped):
            direct = probe_layer(client, stripped)
            if direct:
                cand = {
                    "url": stripped,
                    "layer_name": direct["name"],
                    "signals": score_fields(direct["fields"]),
                    "field_count": len(direct["fields"]),
                }
                if best is None or len(cand["signals"]) > len(best["signals"]):
                    best = cand
        # Case 2: service root — walk layers
        probes = probe_service(client, stripped)
        for p in probes:
            if best is None or len(p["signals"]) > len(best["signals"]):
                best = p
        if best and len(best["signals"]) >= 4:
            break
    if not best:
        return {"county": county, "status": "no_layer_fields", "tried": tried[:10]}
    signals = best["signals"]
    has_owner = "owner" in signals
    has_sale = "sale_price" in signals
    status = "ok" if (has_owner and has_sale) else (
        "partial" if (has_owner or has_sale) else "geometry_only")
    return {"county": county, "status": status, "url": best["url"],
            "layer_name": best["layer_name"], "signals": signals,
            "field_count": best["field_count"]}


def main() -> int:
    out_path = Path("data/va_parcel_sources_broad.json")
    results = []
    with httpx.Client(headers={"User-Agent": "mls-bot/0.1"}, follow_redirects=True) as c:
        for county in REMAINING:
            r = probe_county(c, county)
            results.append(r)
            mark = {"ok": "OK", "partial": "~~", "geometry_only": "..",
                    "no_candidates": "--", "no_layer_fields": "!!"}.get(r["status"], "??")
            extra = ""
            if r["status"] in ("ok", "partial", "geometry_only"):
                extra = f"  {r['layer_name']}  [{','.join(r['signals'])}]"
            print(f"  {mark}  {county:20s}  {r['status']}{extra}")
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
