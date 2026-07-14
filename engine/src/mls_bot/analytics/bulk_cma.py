"""Bulk CMA generator — runs the CMA tool over every active listing.

Use cases:
  - Pre-compute CMAs for every listing in your farm area, refresh nightly,
    so any seller you cold-call already has a CMA waiting
  - Generate a "CMA folder" for client outreach

Produces one HTML per listing under outputs/mls_analytics/bulk_cma/,
named `<city>__<address>__<listing_id>.html` (slugified).

Default scope: all RES Active+Pending listings. Filter via CLI flags.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .cma import cma_for, render_html
from .db import connect


BULK_DIR = Path("outputs/mls_analytics/bulk_cma")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "x"


def generate_bulk_cmas(
    *,
    cities: list[str] | None = None,
    classes: list[str] | None = None,
    statuses: list[str] | None = None,
    max_n: int | None = None,
    out_dir: Path = BULK_DIR,
) -> dict:
    """Stream every listing matching the filter criteria, run cma_for() on each
    using the listing's own list_price as the proposed price, write HTML.
    Returns summary dict."""
    out_dir.mkdir(parents=True, exist_ok=True)

    classes = classes or ["RE_1"]
    statuses = statuses or ["Active", "Pending"]
    cities_uc = [c.upper().strip() for c in (cities or [])]

    con = connect()
    where = [
        f"_class IN ({','.join(repr(c) for c in classes)})",
        f"status_category IN ({','.join(repr(s) for s in statuses)})",
        "listing_id IS NOT NULL",
        "TRY_CAST(list_price AS DOUBLE) > 0",
    ]
    if cities_uc:
        where.append(f"UPPER(TRIM(city)) IN ({','.join(repr(c) for c in cities_uc)})")

    rows = con.execute(f"""
        SELECT listing_id, address, city, _class, parcel_id,
               TRY_CAST(list_price AS DOUBLE) AS lp,
               bedrooms, full_baths, sqft, acres, year_built, subdivision,
               property_subtype, parcel_owner_occupied, list_agent, list_office
        FROM listings
        WHERE {' AND '.join(where)}
        ORDER BY list_date DESC NULLS LAST
    """).fetchall()
    if max_n:
        rows = rows[:max_n]

    n_total = len(rows)
    n_ok = n_skip = 0
    started = time.time()
    print(f"generating CMAs for {n_total} listings...")

    for i, row in enumerate(rows, 1):
        lid, addr, city, cls, pid, lp, br, fb, sf, ac, yb, sd, pst, oo, la, lo = row
        if not (addr and city and lp):
            n_skip += 1
            continue
        try:
            subject = {
                "listing_id": lid, "address": addr, "city": city, "_class": cls,
                "parcel_id": pid,
                "bedrooms": br, "full_baths": fb, "sqft": sf, "acres": ac,
                "year_built": yb, "subdivision": sd, "property_subtype": pst,
                "parcel_owner_occupied": oo,
                "list_agent": la, "list_office": lo,
                "list_price": lp,
            }
            report = cma_for(proposed_price=float(lp), subject_override=subject)
            if "error" in report:
                n_skip += 1
                continue
            fname = f"{_slug(city)}__{_slug(addr)}__{lid}.html"
            render_html(report, out_dir / fname)
            n_ok += 1
        except Exception as e:
            n_skip += 1
            if n_skip < 5:
                print(f"  [skip {lid} @ {addr[:30]}]: {e}")

        if i % 50 == 0:
            rate = i / (time.time() - started + 1)
            eta = (n_total - i) / rate if rate > 0 else 0
            print(f"  {i}/{n_total}  ({rate:.1f}/s, eta {eta/60:.1f}m)")

    elapsed = time.time() - started
    return {
        "total": n_total, "ok": n_ok, "skipped": n_skip,
        "elapsed_s": round(elapsed, 1), "out_dir": str(out_dir),
    }


def write_bulk_index(out_dir: Path = BULK_DIR) -> Path:
    """Build a simple index.html linking every CMA in the bulk folder."""
    idx = out_dir / "index.html"
    files = sorted(out_dir.glob("*.html"))
    files = [f for f in files if f.name != "index.html"]
    rows = []
    for f in files:
        # Slug filename layout: city__address__listing_id.html
        parts = f.stem.split("__")
        city = (parts[0] if parts else "?").replace("_", " ").title()
        addr = (parts[1] if len(parts) > 1 else "?").replace("_", " ").title()
        lid = parts[2] if len(parts) > 2 else "?"
        rows.append(f'<tr><td><a href="{f.name}">{addr}</a></td><td>{city}</td><td>{lid}</td></tr>')
    body = "".join(rows) or '<tr><td colspan=3>(no CMAs generated yet)</td></tr>'
    html = f"""<!doctype html>
<html><head><meta charset=utf-8><title>Bulk CMA index</title>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:1000px;margin:30px auto;padding:0 20px}}
h1{{margin-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border-bottom:1px solid #eee;padding:6px 10px;text-align:left}}
th{{background:#f0f0f0}}
.meta{{color:#777;font-size:12px;margin-bottom:14px}}
input{{width:100%;padding:8px;font-size:14px;margin:10px 0;border:1px solid #ccc;border-radius:4px}}
</style></head><body>
<h1>Bulk CMA library</h1>
<p class="meta">{len(files)} CMA reports · all RES Active+Pending listings</p>
<input id="filter" placeholder="filter by address or city..." oninput="
  const q=this.value.toLowerCase();
  document.querySelectorAll('tbody tr').forEach(r=>{{ r.style.display = r.innerText.toLowerCase().includes(q)?'':'none'; }});
">
<table>
<thead><tr><th>Address</th><th>City</th><th>MLS#</th></tr></thead>
<tbody>{body}</tbody>
</table>
</body></html>"""
    idx.write_text(html, encoding="utf-8")
    return idx
