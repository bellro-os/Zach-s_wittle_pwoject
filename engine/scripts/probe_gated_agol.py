"""Step A spike: can we bypass the gated `drkDXByy6E3bYW3a` AGOL org
using a Chrome-impersonating TLS fingerprint?

If the `services6.arcgis.com/drkDXByy6E3bYW3a/...` host is blocking plain
Python TLS handshakes (httpx got WinError 10054; requests got the same),
then `curl_cffi` with `impersonate="chrome120"` might slip through.

Runs against a few target counties and reports the status + field signals
for each. No writes.
"""

from __future__ import annotations

import argparse
import json
import sys

from curl_cffi import requests as cc


TARGETS = [
    "floyd", "giles", "pulaski", "carroll", "wythe", "smyth",
    "washington", "bland", "lee", "patrick", "halifax", "brunswick",
    "mecklenburg", "lunenburg", "bedford",
]


def probe(service_name: str) -> dict:
    url = (
        f"https://services6.arcgis.com/drkDXByy6E3bYW3a/arcgis/rest/services/"
        f"{service_name}_county_va_parcels/FeatureServer"
    )
    try:
        r = cc.get(
            url,
            params={"f": "json"},
            impersonate="chrome120",
            timeout=25,
            headers={
                "Referer": "https://www.arcgis.com/",
                "Origin": "https://www.arcgis.com",
            },
        )
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    try:
        data = r.json()
    except Exception as e:
        return {"ok": False, "status": r.status_code,
                "error": f"not-json: {e}", "body_head": r.text[:200]}

    if isinstance(data, dict) and "error" in data:
        return {"ok": False, "status": r.status_code,
                "error": data["error"].get("message"),
                "details": data["error"].get("details")}
    layers = []
    if isinstance(data, dict):
        layers = (data.get("layers") or []) + (data.get("tables") or [])
    return {"ok": True, "status": r.status_code,
            "layers": [{"id": lyr.get("id"), "name": lyr.get("name")} for lyr in layers]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", default=None,
                    help="Probe just this one (lowercase service slug). Omit to probe all.")
    args = ap.parse_args()

    targets = [args.county] if args.county else TARGETS
    any_ok = False
    for t in targets:
        res = probe(t)
        if res["ok"]:
            any_ok = True
            layers = res.get("layers", [])
            print(f"  OK  {t:14s}  layers={len(layers)}  -> {layers}")
        else:
            print(f"  !!  {t:14s}  {res.get('error')}")

    if any_ok:
        print("\n>>> TLS bypass works on at least one target. Move to harvesting.")
    else:
        print("\n>>> Bypass failed; gate is auth-based, not TLS-fingerprint-based.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
