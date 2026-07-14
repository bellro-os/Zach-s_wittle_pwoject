"""Recon SouthsideGIS (Timmons) viewer for Mecklenburg.

Loads https://meck.southsidegis.org/ in headless Chromium, captures all
XHR/fetch URLs, dumps HTML+screenshot. Goal: find the underlying parcel
data backend (likely ArcGIS REST or GeoServer behind the viewer)."""

from __future__ import annotations

import argparse, json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SKIP = ("/assets/", "googletagmanager", ".css", ".png", ".jpg", ".svg",
        ".woff", ".ico", ".gif", "fonts.googleapis", "code.jquery.com")


def recon(sub: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"https://{sub}.southsidegis.org/"
    network = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1600, "height": 1200})
        page = ctx.new_page()

        def on_req(req):
            if any(x in req.url for x in SKIP): return
            network.append({"ts": "req", "url": req.url, "method": req.method})

        def on_resp(resp):
            if any(x in resp.url for x in SKIP): return
            ct = (resp.headers.get("content-type") or "").lower()
            sample = None
            try:
                if "json" in ct: sample = resp.text()[:1500]
            except: pass
            network.append({"ts": "resp", "url": resp.url, "status": resp.status, "content_type": ct, "sample": sample})

        page.on("request", on_req)
        page.on("response", on_resp)

        print(f"[{sub}] loading {base}")
        page.goto(base, wait_until="networkidle", timeout=60_000)
        # Click any agreement / continue buttons
        for sel in ["text=I Agree", "text=Continue", "text=Accept", "text=Public",
                    ".btn-primary", "#submit_guest", "#agree"]:
            try:
                page.click(sel, timeout=2500)
                print(f"[{sub}] clicked {sel}")
                page.wait_for_load_state("networkidle", timeout=15_000)
                break
            except: continue

        print(f"[{sub}] final url: {page.url}, title: {page.title()}")
        (out_dir / f"{sub}_dom.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / f"{sub}_screen.png"), full_page=True)
        b.close()

    (out_dir / f"{sub}_network.json").write_text(json.dumps(network, indent=2, default=str), encoding="utf-8")
    urls = sorted({f'{e.get("method","??"):>4}  {e["url"]}' for e in network if e["ts"] == "req"})
    (out_dir / f"{sub}_urls.txt").write_text("\n".join(urls), encoding="utf-8")
    print(f"[{sub}] {len(network)} events, {len(urls)} unique URLs")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", default="meck")
    ap.add_argument("--out", default="data/recon/southside")
    args = ap.parse_args()
    recon(args.sub, Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
