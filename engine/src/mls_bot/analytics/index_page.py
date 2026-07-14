"""Index landing page — single HTML linking all reports + analytics CSVs.

Output: outputs/mls_analytics/index.html
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .db import connect


OUTPUT_DIR = Path("outputs/mls_analytics")
INDEX_PATH = OUTPUT_DIR / "index.html"


def _file_link(name: str, rel_path: str, blurb: str = "") -> str:
    p = OUTPUT_DIR / rel_path
    size_kb = (p.stat().st_size // 1024) if p.exists() else 0
    age_d = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).days if p.exists() else None
    age_str = f"{age_d}d ago" if age_d is not None and age_d > 0 else ("today" if p.exists() else "missing")
    badge = '<span class="badge">missing</span>' if not p.exists() else ""
    return (f'<li><a href="{rel_path}">{name}</a> {badge} '
            f'<span class="meta">{size_kb}KB · {age_str}</span>'
            f'{f"<div class=blurb>{blurb}</div>" if blurb else ""}</li>')


def _stat_kpi(label: str, value: str, sublabel: str = "") -> str:
    return f'<div class="kpi"><div class="lbl">{label}</div><div class="val">{value}</div><div class="sub">{sublabel}</div></div>'


def build_index(out_path: Path = INDEX_PATH) -> Path:
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    con = connect()

    # Headline counts
    counts = con.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status_category='Active' THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN status_category='Closed' AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '12 months' THEN 1 ELSE 0 END) AS closed_12mo,
            SUM(CASE WHEN deed_arms_length=true THEN 1 ELSE 0 END) AS w_deed
        FROM listings
    """).fetchone() or (0, 0, 0, 0)
    deed_count = con.execute("SELECT COUNT(*) FROM deed_sales WHERE deed_arms_length=true").fetchone()[0] if con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='deed_sales'").fetchone() else 0

    # Subdivision links
    sd_dir = OUTPUT_DIR / "subdivisions"
    subdivision_links = []
    if sd_dir.exists():
        for p in sorted(sd_dir.glob("*.html")):
            label = p.stem.replace("_", " ").replace("  ", " — ").title()
            subdivision_links.append(f'<li><a href="subdivisions/{p.name}">{label}</a></li>')

    # Recent CMA links
    cma_links = []
    for p in sorted(OUTPUT_DIR.glob("cma_*.html"), key=lambda p: -p.stat().st_mtime)[:10]:
        when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        cma_links.append(f'<li><a href="{p.name}">{p.stem.replace("cma_","").replace("_"," ")}</a> <span class="meta">{when}</span></li>')

    # Build HTML
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>MLS Analytics — Index</title>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:1200px;margin:30px auto;padding:0 24px;color:#222;background:#fafafa}}
h1{{margin-bottom:4px}} h2{{border-bottom:1px solid #ccc;padding-bottom:6px;margin-top:34px;font-size:17px}}
.head{{font-size:13px;color:#666;margin-bottom:8px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0}}
.kpi{{background:#fff;padding:14px 18px;border-radius:8px;box-shadow:0 1px 2px rgba(0,0,0,.06)}}
.kpi .lbl{{font-size:11px;color:#777;text-transform:uppercase;letter-spacing:.5px}}
.kpi .val{{font-size:24px;font-weight:600;margin:4px 0 2px}}
.kpi .sub{{font-size:12px;color:#888}}
.cols{{display:grid;grid-template-columns:repeat(2,1fr);gap:30px}}
ul{{padding-left:18px;margin-top:8px}} li{{margin:4px 0}}
.meta{{color:#888;font-size:11px;margin-left:6px}}
.blurb{{color:#555;font-size:12px;margin-left:0;margin-top:2px}}
.badge{{background:#fdd;color:#900;font-size:10px;padding:1px 6px;border-radius:3px;margin-left:4px}}
a{{color:#1a5fb4;text-decoration:none}} a:hover{{text-decoration:underline}}
.cmd{{background:#f0f0f0;padding:8px 12px;border-radius:5px;font-family:monospace;font-size:12px;margin:8px 0;display:inline-block}}
</style></head><body>
<h1>MLS Analytics — Index</h1>
<p class="head">NRV MLS · {today} · run <span class="cmd">python tasks.py mls-daily</span> to refresh</p>

<div class="kpis">
{_stat_kpi("Total listings", f"{counts[0]:,}", "all classes, all statuses")}
{_stat_kpi("Active now", f"{counts[1]:,}", "currently on market")}
{_stat_kpi("Closed (12mo)", f"{counts[2]:,}", "trailing year sold")}
{_stat_kpi("Deed sales", f"{deed_count:,}", "NRV pre-2023 backfill")}
</div>

<div class="cols">
<div>
<h2>Reports</h2>
<ul>
  {_file_link("Daily digest", "digest.html", "Status changes, price drops, hot listings, leads, market velocity")}
  {_file_link("County price-coverage audit", "county_price_audit.md", "Which county feeds expose sale prices")}
</ul>

<h2>Lead lists</h2>
<ul>
  {_file_link("Off-MLS-sold leads", "leads/expired_then_sold_leads.csv", "Past sellers who fired their agent and sold via deed")}
  {_file_link("Investor portfolios", "leads/investor_portfolios.csv", "LLCs / entities owning 2+ listings")}
  {_file_link("Active builders", "leads/new_builders.csv", "Sellers with 3+ closed sales in last 24mo")}
  {_file_link("Expiring soon (defunct)", "leads/expiring_soon.csv", "Note: feed doesn't expose expiration_date")}
</ul>

<h2>Cohort analytics</h2>
<ul>
  {_file_link("DOM by cohort", "dom_by_cohort.csv", "Median/p25/p75 DOM by year × city × class × price band")}
  {_file_link("DOM by subdivision", "dom_by_subdivision.csv", "Median DOM grouped by subdivision")}
  {_file_link("Fast sellers", "fast_sellers.csv", "Listings that closed at or below cohort p25 DOM")}
  {_file_link("Laggards", "laggards.csv", "Withdrawn / cut-price / over-p75-DOM listings")}
  {_file_link("List-to-sold spread", "list_to_sold_spread.csv", "% of listings closing at or above ask")}
  {_file_link("Price-cut waterfall", "price_cut_waterfall.csv", "Cohort summary of cut rates and DOM impact")}
  {_file_link("Listings with cuts", "listings_with_cuts.csv", "Per-listing detail of every closed sale that cut price")}
</ul>
</div>

<div>
<h2>Market structure</h2>
<ul>
  {_file_link("Market velocity", "market_velocity.csv", "Months-of-inventory by city × class — hot vs soft markets")}
  {_file_link("Office rankings", "office_rankings.csv", "Trailing-24-month dollar volume by listing office")}
  {_file_link("Agent rankings", "agent_rankings.csv", "Same, by individual listing agent — names resolved")}
  {_file_link("Expired-then-sold off-MLS", "expired_then_sold_offmls.csv", "Listings that didn't sell on MLS but later deeded")}
  {_file_link("Price trends with deeds", "price_trends_with_deeds.csv", "Median sold by year, MLS UNION deed corpus")}
</ul>

<h2>DOM model</h2>
<ul>
  {_file_link("Training report", "dom_model/training_report.md", "Validation MAE + feature list")}
</ul>
<p class="head">Predict on a property: <span class="cmd">python tasks.py cma --address "123 MAIN" --price 450000</span></p>
<p class="head">Recommend a list price for a target DOM: <span class="cmd">python tasks.py mls-recommend-price --address "..." --target-dom 14</span></p>

<h2>Joined data (raw)</h2>
<ul>
  {_file_link("Listings + deeds + parcels (CSV)", "listings_with_parcels.csv", "Flat join of MLS listings to county parcels")}
  {_file_link("NRV deed sales (CSV)", "nrv_deed_sales.csv", "Standalone deed-sale corpus")}
</ul>

</div>
</div>

<h2>Subdivision deep-dives ({len(subdivision_links)})</h2>
<ul>{"".join(subdivision_links) if subdivision_links else '<li>(none — run mls-subdivisions)</li>'}</ul>

<h2>Recent CMAs ({len(cma_links)})</h2>
<ul>{"".join(cma_links) if cma_links else '<li>(none yet — run cma command)</li>'}</ul>

<p class="head" style="margin-top:40px">Daily refresh: <span class="cmd">python tasks.py mls-daily</span> · Weekly retrain: <span class="cmd">python tasks.py mls-weekly</span></p>
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
