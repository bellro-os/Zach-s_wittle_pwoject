"""Subdivision deep-dive HTML reports.

For a given (city, subdivision), produces a single-page report with:
  - Headline stats: 5-year sale count, median sold $, median DOM, sold/list ratio
  - Inventory: every active + pending listing in the subdivision (price, DOM)
  - Recent sales: last 24 months with price + DOM
  - Sparkline: median sold price by year
  - Owner mix: who owns the most parcels (investor / OO / family trust)

Outputs: outputs/mls_analytics/subdivisions/<city>_<subdivision>.html
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .db import connect


SUBDIV_DIR = Path("outputs/mls_analytics/subdivisions")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "x"


def _fmt_money(v) -> str:
    if v in (None, "", "None"):
        return ""
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _svg_yearly_median_price(con, city: str, subdivision: str,
                              *, years_back: int = 8,
                              width: int = 720, height: int = 160) -> str:
    rows = con.execute(f"""
        SELECT EXTRACT(YEAR FROM TRY_CAST(close_date AS DATE))::INT AS y,
               MEDIAN(TRY_CAST(sold_price AS DOUBLE)) AS med_p,
               COUNT(*) AS n
        FROM listings
        WHERE UPPER(city)='{city.replace("'","''").upper()}'
          AND UPPER(subdivision)='{subdivision.replace("'","''").upper()}'
          AND status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '{years_back} years'
        GROUP BY 1 HAVING COUNT(*) >= 1 ORDER BY 1
    """).fetchall()
    if len(rows) < 2:
        return ""
    years = [r[0] for r in rows]
    prices = [float(r[1]) for r in rows]
    lo, hi = min(prices), max(prices)
    if lo == hi: hi = lo + 1
    pad_l, pad_r, pad_t, pad_b = 70, 16, 14, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(prices)
    pts = []
    for i, p in enumerate(prices):
        x = pad_l + (i / max(n - 1, 1)) * plot_w
        y = pad_t + (1 - (p - lo) / (hi - lo)) * plot_h
        pts.append((x, y, p))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#0a7e2c"/>'
                    f'<text x="{x:.1f}" y="{y-7:.1f}" font-size="10" text-anchor="middle" fill="#0a7e2c">${p/1000:.0f}k</text>'
                   for x, y, p in pts)
    y_labels = (
        f'<text x="{pad_l-6}" y="{pad_t+10}" font-size="11" fill="#555" text-anchor="end">${hi/1000:.0f}k</text>'
        f'<text x="{pad_l-6}" y="{pad_t+plot_h}" font-size="11" fill="#555" text-anchor="end">${lo/1000:.0f}k</text>'
    )
    x_labels = (
        f'<text x="{pad_l}" y="{height-10}" font-size="11" fill="#555">{years[0]}</text>'
        f'<text x="{pad_l + plot_w}" y="{height-10}" font-size="11" text-anchor="end" fill="#555">{years[-1]}</text>'
    )
    return (f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
            f'<polyline points="{polyline}" stroke="#0a7e2c" stroke-width="2.5" fill="none"/>'
            f'{dots}{y_labels}{x_labels}</svg>')


def render_subdivision_html(city: str, subdivision: str,
                              out_dir: Path = SUBDIV_DIR) -> Path | None:
    """Build a single-page HTML report for one (city, subdivision). Skips if
    there are <3 historical sales (not enough data)."""
    con = connect()
    city_u = city.upper().strip()
    subd_u = subdivision.upper().strip()

    headline = con.execute(f"""
        SELECT
            COUNT(*) AS n,
            ROUND(MEDIAN(TRY_CAST(sold_price AS DOUBLE)), 0) AS med_sold,
            ROUND(MEDIAN(COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT))), 1) AS med_dom,
            ROUND(MEDIAN(TRY_CAST(sold_price AS DOUBLE)
                  / NULLIF(TRY_CAST(original_list_price AS DOUBLE),0)) * 100, 2) AS sold_to_orig_pct,
            ROUND(MEDIAN(TRY_CAST(sqft AS DOUBLE)), 0) AS med_sqft,
            ROUND(MEDIAN(TRY_CAST(sold_price AS DOUBLE) / NULLIF(TRY_CAST(sqft AS DOUBLE),0)), 1) AS med_psf
        FROM listings
        WHERE UPPER(city)='{city_u.replace("'","''")}'
          AND UPPER(subdivision)='{subd_u.replace("'","''")}'
          AND status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '5 years'
    """).fetchone()
    if not headline or (headline[0] or 0) < 3:
        return None

    active = con.execute(f"""
        SELECT listing_id, address, list_price, original_list_price,
               bedrooms, full_baths, sqft, year_built,
               status_category, list_date, list_office_name
        FROM listings
        WHERE UPPER(city)='{city_u.replace("'","''")}'
          AND UPPER(subdivision)='{subd_u.replace("'","''")}'
          AND status_category IN ('Active','Pending')
        ORDER BY list_date DESC NULLS LAST
    """).fetchall()

    recent = con.execute(f"""
        SELECT listing_id, address, original_list_price, sold_price,
               bedrooms, full_baths, sqft, year_built, list_date, close_date,
               COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom
        FROM listings
        WHERE UPPER(city)='{city_u.replace("'","''")}'
          AND UPPER(subdivision)='{subd_u.replace("'","''")}'
          AND status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '24 months'
        ORDER BY close_date DESC LIMIT 50
    """).fetchall()

    chart = _svg_yearly_median_price(con, city_u, subd_u)

    n, med_sold, med_dom, st_orig, med_sqft, med_psf = headline

    def row(cells: list) -> str:
        return "<tr>" + "".join(f"<td>{c if c is not None else ''}</td>" for c in cells) + "</tr>"

    active_rows = "".join(row([
        r[0], r[1], r[8], _fmt_money(r[2]), _fmt_money(r[3]),
        f"{r[4] or '-'}/{r[5] or '-'}", r[6], r[7], r[9], r[10] or "-"
    ]) for r in active)

    def _ratio(num, den) -> str:
        try:
            f_num, f_den = float(num), float(den)
            return f"{f_num / f_den * 100:.1f}%" if f_den else "-"
        except (TypeError, ValueError):
            return "-"

    recent_rows = "".join(row([
        r[0], r[1], _fmt_money(r[2]), _fmt_money(r[3]),
        _ratio(r[3], r[2]),
        f"{r[4] or '-'}/{r[5] or '-'}", r[6], r[7], r[8], r[9], r[10]
    ]) for r in recent)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(city)}__{_slug(subdivision)}.html"
    today = datetime.now().strftime("%Y-%m-%d")

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{subdivision} ({city}) — subdivision report</title>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#222}}
h1{{margin-bottom:6px}} h2{{border-bottom:1px solid #ccc;padding-bottom:6px;margin-top:30px;font-size:16px}}
.kpi{{display:flex;gap:14px;margin:14px 0;flex-wrap:wrap}}
.kpi div{{background:#eef;padding:10px 14px;border-radius:6px;min-width:130px}}
.kpi .lbl{{font-size:11px;color:#555}} .kpi .val{{font-size:20px;font-weight:600}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}}
th,td{{border:1px solid #ddd;padding:4px 7px;text-align:left}} th{{background:#f0f0f0}}
.foot{{font-size:11px;color:#777;margin-top:30px}}
</style></head><body>
<h1>{subdivision}</h1>
<p style="color:#666">{city}, VA — subdivision report — {today}</p>
<div class="kpi">
  <div><div class="lbl">5-yr sales</div><div class="val">{n}</div></div>
  <div><div class="lbl">Median sold</div><div class="val">{_fmt_money(med_sold)}</div></div>
  <div><div class="lbl">Median DOM</div><div class="val">{med_dom or '-'}d</div></div>
  <div><div class="lbl">Sold/orig list</div><div class="val">{st_orig or '-'}%</div></div>
  <div><div class="lbl">Median sqft</div><div class="val">{int(med_sqft) if med_sqft else '-'}</div></div>
  <div><div class="lbl">Median $/sqft</div><div class="val">${med_psf or '-'}</div></div>
</div>
{('<h2>Median sold price by year</h2>' + chart) if chart else ''}
<h2>Active &amp; Pending ({len(active)})</h2>
<table>
<tr><th>MLS#</th><th>Address</th><th>Status</th><th>List $</th><th>Orig $</th>
    <th>BR/BA</th><th>Sqft</th><th>Year</th><th>Listed</th><th>Office</th></tr>
{active_rows or row(['(none)','','','','','','','','',''])}
</table>
<h2>Recent sales (last 24 months, n={len(recent)})</h2>
<table>
<tr><th>MLS#</th><th>Address</th><th>Orig $</th><th>Sold $</th><th>%</th>
    <th>BR/BA</th><th>Sqft</th><th>Year</th><th>Listed</th><th>Closed</th><th>DOM</th></tr>
{recent_rows or row(['(none)','','','','','','','','','',''])}
</table>
<p class="foot">Generated {today} from MLS + parcel data.</p>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_top_subdivisions(min_sales: int = 10, max_n: int = 100) -> int:
    """Render reports for every (city, subdivision) with >= min_sales closed
    listings in the last 5 years. Returns count of reports written."""
    con = connect()
    rows = con.execute(f"""
        SELECT UPPER(TRIM(city)) AS city,
               UPPER(TRIM(subdivision)) AS subdivision,
               COUNT(*) AS n
        FROM listings
        WHERE status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '5 years'
          AND subdivision IS NOT NULL AND TRIM(subdivision) NOT IN ('','-','UNKNOWN','OTHER','None')
        GROUP BY 1, 2
        HAVING COUNT(*) >= {min_sales}
        ORDER BY n DESC LIMIT {max_n}
    """).fetchall()
    written = 0
    for city, subd, _n in rows:
        if not city or not subd:
            continue
        path = render_subdivision_html(city, subd)
        if path:
            written += 1
    return written
