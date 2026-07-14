"""Recon the iGIS (InteractiveGIS) platform.

Drives Chromium headless against floyd.interactivegis.com:
  1. Load the landing/login page
  2. Submit the "Public Access" guest form (the checkbox + submit button)
  3. Record every XHR/fetch URL the app makes once authenticated
  4. Dump those URLs + sample response bodies for a human to read

Once we know the parcel data endpoints, we can build an async scraper
that calls them directly without a browser.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def recon(subdomain: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"https://{subdomain}.interactivegis.com/"

    network: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = ctx.new_page()

        def on_request(req):
            url = req.url
            # Only interesting paths — skip assets, analytics
            if any(x in url for x in ["/assets/", "googletagmanager", ".css", ".png",
                                       ".jpg", ".svg", ".woff", ".ico", "/js/"]):
                return
            network.append({
                "ts": "req",
                "method": req.method,
                "url": url,
                "post_data": req.post_data,
                "headers": dict(req.headers),
            })

        def on_response(resp):
            url = resp.url
            if any(x in url for x in ["/assets/", "googletagmanager", ".css", ".png",
                                       ".jpg", ".svg", ".woff", ".ico", "/js/"]):
                return
            ct = (resp.headers.get("content-type") or "").lower()
            body_sample = None
            try:
                if "json" in ct or "javascript" in ct:
                    body_sample = resp.text()[:2000]
            except Exception:
                pass
            network.append({
                "ts": "resp",
                "status": resp.status,
                "url": url,
                "content_type": ct,
                "body_sample": body_sample,
            })

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"[{subdomain}] loading landing...")
        page.goto(base, wait_until="networkidle", timeout=60_000)
        print(f"[{subdomain}] title: {page.title()}")

        # Click agreement checkbox + submit guest
        try:
            # The checkbox is visually styled (Bootstrap custom-control) and its
            # real input is offscreen — use JS to check + fire change.
            page.evaluate(
                """() => {
                    const cb = document.querySelector('#agreement');
                    if (cb) { cb.checked = true; cb.dispatchEvent(new Event('change', {bubbles: true})); }
                }"""
            )
            print(f"[{subdomain}] checked agreement via JS")
            page.click("#submit_guest", timeout=5000, force=True)
            print(f"[{subdomain}] clicked submit_guest")
        except Exception as e:
            print(f"[{subdomain}] guest-form click failed: {e}")

        # Wait a bit for post-login XHRs
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        print(f"[{subdomain}] post-guest URL: {page.url}")
        print(f"[{subdomain}] post-guest title: {page.title()}")

        # Capture final DOM + a screenshot
        (out_dir / f"{subdomain}_dom.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / f"{subdomain}_screen.png"), full_page=True)

        browser.close()

    # Dump network log
    (out_dir / f"{subdomain}_network.json").write_text(
        json.dumps(network, indent=2, default=str), encoding="utf-8"
    )
    # Also a compact URL-only summary
    urls = sorted({
        f'{e.get("method", "??"):>4}  {e["url"]}'
        for e in network if e["ts"] == "req"
    })
    (out_dir / f"{subdomain}_urls.txt").write_text("\n".join(urls), encoding="utf-8")
    print(f"[{subdomain}] wrote {len(network)} events, {len(urls)} unique requests")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subdomain", default="floyd",
                    help="iGIS subdomain to probe (floyd, giles, carroll, washington, ...)")
    ap.add_argument("--out", default="data/recon/igis", help="Output dir")
    args = ap.parse_args()
    recon(args.subdomain, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
