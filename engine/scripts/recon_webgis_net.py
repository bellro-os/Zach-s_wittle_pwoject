"""Recon webgis.net (Hurt & Proffitt) — load Craig's viewer in headless
Chromium and dump every XHR/fetch URL. Their viewer uses ESRI ArcGIS JS,
so the underlying service URLs MUST be requested at runtime, just not
hardcoded into the page HTML.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def recon(county: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"https://webgis.net/va/{county}/"
    network: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = ctx.new_page()

        skip_re = ("/assets/", "googletagmanager", ".css", ".png", ".jpg",
                   ".svg", ".woff", ".ico", ".gif", "fonts.googleapis",
                   "code.jquery.com")

        def on_request(req):
            if any(x in req.url for x in skip_re):
                return
            network.append({
                "ts": "req", "method": req.method, "url": req.url,
                "post_data": req.post_data,
            })

        def on_response(resp):
            if any(x in resp.url for x in skip_re):
                return
            ct = (resp.headers.get("content-type") or "").lower()
            sample = None
            try:
                if "json" in ct or ("javascript" in ct and "config" in resp.url.lower()):
                    sample = resp.text()[:1500]
            except Exception:
                pass
            network.append({
                "ts": "resp", "status": resp.status, "url": resp.url,
                "content_type": ct, "body_sample": sample,
            })

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"[{county}] loading {base}")
        page.goto(base, wait_until="networkidle", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        # Many WebGIS viewers have a "Continue" / agreement modal — try common selectors.
        for sel in ["text=Continue", "text=I Agree", "text=Accept",
                    "button.btn-primary", "#agree", "#continue"]:
            try:
                page.click(sel, timeout=2000)
                print(f"[{county}] clicked {sel}")
                page.wait_for_load_state("networkidle", timeout=10_000)
                break
            except Exception:
                continue

        print(f"[{county}] final url: {page.url}")
        (out_dir / f"{county}_dom.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / f"{county}_screen.png"), full_page=True)
        browser.close()

    (out_dir / f"{county}_network.json").write_text(
        json.dumps(network, indent=2, default=str), encoding="utf-8"
    )
    urls = sorted({f'{e.get("method","??"):>4}  {e["url"]}' for e in network if e["ts"] == "req"})
    (out_dir / f"{county}_urls.txt").write_text("\n".join(urls), encoding="utf-8")
    print(f"[{county}] {len(network)} events, {len(urls)} unique requests")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", default="craig")
    ap.add_argument("--out", default="data/recon/webgis_net")
    args = ap.parse_args()
    recon(args.county, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
