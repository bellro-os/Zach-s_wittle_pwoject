"""NRV-wide market heatmap — color-coded grid of metrics by zip × class.

Inline SVG/CSS heatmap with no external libraries. Shows trailing 12-month:
  - Median sold price
  - Median DOM
  - Sold/list ratio
  - Closed sales count
  - Months of inventory
  - % of cohort that cut price ≥3%

For each (zip, class) bucket, color cells by relative value within the metric
(percentile-based). Lets the user spot which zip codes are hottest/coldest at
a glance.

Output: outputs/mls_analytics/market_heatmap.html
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .db import connect


HEATMAP_PATH = Path("outputs/mls_analytics/market_heatmap.html")


def _color_scale(values: list[float], reverse: bool = False) -> dict:
    """Return {value: hex_color} mapping where higher values get warmer color
    (or cooler if reverse=True). Uses percentile bucketing."""
    if not values:
        return {}
    nonzero = sorted(v for v in values if v is not None)
    if not nonzero:
        return {}
    n = len(nonzero)
    # 5 quantile buckets
    palette_warm = ["#e7f3e7", "#aaeaaa", "#5fc060", "#1e8a3a", "#0a5a18"]  # cool→warm green
    palette_cold = palette_warm[::-1]
    palette = palette_cold if reverse else palette_warm
    quantile_bounds = [nonzero[int(n * q)] for q in (0.2, 0.4, 0.6, 0.8)]
    out = {}
    for v in values:
        if v is None:
            out[v] = "#f4f4f4"
            continue
        i = 0
        for j, b in enumerate(quantile_bounds):
            if v >= b:
                i = j + 1
        out[v] = palette[i]
    return out


def _build_buckets() -> tuple[list[dict], list[str], list[str]]:
    """Return (buckets, cities_ordered, classes_ordered) where buckets is a list
    of dicts: city, class, n, median_sold, median_dom, sold_pct, inventory_mo, cut_pct."""
    con = connect()
    rows = con.execute("""
        WITH closed AS (
            SELECT UPPER(TRIM(city)) AS city,
                   _class,
                   TRY_CAST(sold_price AS DOUBLE) AS sold_price,
                   TRY_CAST(original_list_price AS DOUBLE) AS orig_price,
                   TRY_CAST(list_price AS DOUBLE) AS final_list,
                   COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
                   close_date
            FROM listings
            WHERE status_category='Closed'
              AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '12 months'
              AND TRY_CAST(sold_price AS DOUBLE) > 0
        ),
        active AS (
            SELECT UPPER(TRIM(city)) AS city, _class, COUNT(*) AS n_active
            FROM listings WHERE status_category='Active' GROUP BY 1, 2
        )
        SELECT
            c.city, c._class,
            COUNT(*) AS n_closed,
            ROUND(MEDIAN(c.sold_price), 0) AS med_sold,
            ROUND(MEDIAN(c.dom), 1) AS med_dom,
            ROUND(MEDIAN(c.sold_price / NULLIF(c.orig_price, 0)) * 100, 1) AS sold_pct,
            ROUND(SUM(CASE WHEN c.final_list < c.orig_price * 0.97 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS cut_pct,
            COALESCE(a.n_active, 0) AS n_active,
            ROUND(COALESCE(a.n_active, 0) * 1.0 / NULLIF(COUNT(*) / 12.0, 0), 2) AS months_inv
        FROM closed c
        LEFT JOIN active a USING (city, _class)
        GROUP BY c.city, c._class, a.n_active
        HAVING COUNT(*) >= 5
        ORDER BY n_closed DESC
    """).fetchall()

    buckets = []
    for city, cls, n, ms, dm, sp, cp, na, mi in rows:
        buckets.append({
            "city": city, "class": cls, "n_closed": n, "n_active": na or 0,
            "med_sold": ms, "med_dom": dm, "sold_pct": sp, "cut_pct": cp, "months_inv": mi,
        })
    cities = sorted({b["city"] for b in buckets},
                    key=lambda c: -sum(b["n_closed"] for b in buckets if b["city"] == c))
    classes = ["RE_1", "MF_2", "LD_3", "CM_4", "RN_6"]
    return buckets, cities, classes


def render_heatmap(out_path: Path = HEATMAP_PATH) -> Path:
    buckets, cities, classes = _build_buckets()
    if not buckets:
        return out_path

    # Per-metric color scales (calibrated against all values for that metric)
    by_key = {b["city"] + "|" + b["class"]: b for b in buckets}
    metrics = [
        ("med_sold", "Median sold $", lambda v: f"${int(v/1000)}k" if v else "", False),
        ("med_dom", "Median DOM", lambda v: f"{int(v)}d" if v else "", True),  # lower=hotter
        ("sold_pct", "Sold/list %", lambda v: f"{v:.0f}%" if v else "", False),
        ("cut_pct", "Cut rate %", lambda v: f"{v:.0f}%" if v is not None else "", True),
        ("months_inv", "Mo inventory", lambda v: f"{v:.1f}" if v else "", True),
        ("n_closed", "Closed (12mo)", lambda v: f"{int(v)}" if v else "", False),
    ]
    color_scales = {
        m[0]: _color_scale([b.get(m[0]) for b in buckets], reverse=m[3])
        for m in metrics
    }

    # Limit to top 18 cities by volume to keep it readable
    cities = cities[:18]

    today = datetime.now().strftime("%Y-%m-%d")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sections = []
    for key, label, fmt, _ in metrics:
        # Build city × class grid
        cells = []
        for city in cities:
            cells.append(f'<tr><th>{city}</th>')
            for cls in classes:
                b = by_key.get(f"{city}|{cls}")
                if not b:
                    cells.append('<td class="empty">—</td>')
                    continue
                v = b.get(key)
                col = color_scales[key].get(v, "#f4f4f4")
                txt = fmt(v) if v is not None else ""
                tip = f"{city} {cls}: n_closed={b['n_closed']}, n_active={b['n_active']}, sold ${int(b['med_sold'] or 0):,}, dom={b['med_dom']}"
                cells.append(f'<td style="background:{col}" title="{tip}">{txt}</td>')
            cells.append("</tr>")
        sections.append(f"""
<h2>{label}</h2>
<table class="hm">
<thead><tr><th></th>{''.join(f'<th>{c}</th>' for c in classes)}</tr></thead>
<tbody>{''.join(cells)}</tbody>
</table>""")

    html = f"""<!doctype html>
<html><head><meta charset=utf-8><title>NRV market heatmap</title>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#222}}
h1{{margin-bottom:6px}}
h2{{font-size:15px;margin:30px 0 8px;color:#1a5fb4;border-bottom:1px solid #ccc;padding-bottom:4px}}
.meta{{color:#777;font-size:13px}}
table.hm{{border-collapse:collapse;width:100%;font-size:12px}}
table.hm th, table.hm td{{padding:8px 10px;text-align:center;border:1px solid #fff}}
table.hm th{{background:#1a5fb4;color:#fff;font-size:11px;text-transform:uppercase;letter-spacing:1px}}
table.hm tbody th{{background:#f0f4f8;color:#222;text-align:left;font-weight:600}}
table.hm td.empty{{background:#f4f4f4;color:#aaa}}
.legend{{font-size:11px;color:#666;margin-top:6px}}
</style></head><body>
<h1>NRV Market Heatmap</h1>
<p class="meta">Trailing 12 months · {len(buckets)} (city × class) buckets · top {len(cities)} cities by volume · refreshed {today}</p>
<p class="legend">Color: warmer green = higher value (cooler = lower). For DOM, cuts, and months-of-inventory, the scale is inverted — lower numbers = hotter market = warmer green. Hover any cell for context.</p>
{''.join(sections)}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path
