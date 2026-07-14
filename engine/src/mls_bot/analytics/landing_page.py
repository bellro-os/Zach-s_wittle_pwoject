"""Personalized landing pages for mail-merge prospects.

One HTML page per prospect at outputs/mls_analytics/landing/<tracking_id>.html.
The QR code on each printed letter links here. Each page shows:
  - The owner's address, AVM estimate (big), tenure, last sale, equity gain
  - A mini comp grid (3–8 nearest similar sales)
  - Cohort market context (median DOM, sold/list ratio, n)
  - Agent contact card + a single "Get a free CMA" CTA

The landing pages are static and self-contained (no JS, no external assets
besides the optional MLS photo URLs). They can be hosted on any static-site
host or served from local file:// during testing.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .cma import _load_agent_card, find_comparables


LANDING_DIR = Path("outputs/mls_analytics/landing")


def _fmt_money(v) -> str:
    if v in (None, "", "None"):
        return "—"
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _cohort_stats(con, city: str, cls: str) -> dict:
    """Median DOM + sold/list ratio for the prospect's city × class cohort."""
    if not city:
        return {}
    cutoff = (date.today() - timedelta(days=365 * 3)).isoformat()
    cls_safe = (cls or "RE_1").replace("'", "''")
    city_safe = city.upper().strip().replace("'", "''")
    sql = f"""
    SELECT
      COUNT(*) AS n,
      MEDIAN(COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT))) AS median_dom,
      MEDIAN(TRY_CAST(sold_price AS DOUBLE) / NULLIF(TRY_CAST(original_list_price AS DOUBLE),0)) AS median_sold_to_orig,
      MEDIAN(TRY_CAST(sold_price AS DOUBLE)) AS median_sold
    FROM listings
    WHERE _class = '{cls_safe}'
      AND UPPER(city) = '{city_safe}'
      AND status_category = 'Closed'
      AND TRY_CAST(sold_price AS DOUBLE) > 0
      AND TRY_CAST(close_date AS DATE) >= '{cutoff}'
    """
    rows = con.execute(sql).fetchdf().to_dict(orient="records")
    return rows[0] if rows else {}


def render_landing_page(
    *,
    tracking_id: str,
    parcel_id: str,
    site_addr: str,
    owner_first: str,
    avm_value: float | None,
    last_sale_date: str,
    last_sale_price: float | None,
    tenure_years: float,
    equity_gain: float | None,
    out_dir: Path = LANDING_DIR,
) -> Path:
    """Render the prospect's landing page. Returns the path written.

    Looks up the parcel's most recent MLS record for the comp set + photos;
    if the parcel has never been MLS-listed, the comp grid falls back to
    county-level cohort stats.
    """
    from .db import connect

    con = connect()

    subject: dict[str, Any] = {}
    photos: list[str] = []
    if parcel_id:
        try:
            r = con.execute(f"""
                SELECT listing_id, address, city, _class, subdivision, property_subtype,
                       TRY_CAST(bedrooms AS INT) AS bedrooms,
                       TRY_CAST(full_baths AS INT) AS full_baths,
                       TRY_CAST(sqft AS DOUBLE) AS sqft,
                       TRY_CAST(acres AS DOUBLE) AS acres,
                       TRY_CAST(year_built AS INT) AS year_built
                FROM listings
                WHERE parcel_id = '{parcel_id.replace(chr(39), chr(39)*2)}'
                ORDER BY list_date DESC NULLS LAST LIMIT 1
            """).fetchdf().to_dict(orient="records")
            if r:
                subject = r[0]
        except Exception:
            subject = {}

    if subject:
        try:
            import json as _json
            media_path = Path("data/mls/listings_media.jsonl")
            lid = subject.get("listing_id")
            if lid and media_path.exists():
                with media_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        rec = _json.loads(line)
                        if rec.get("listing_id") == lid:
                            photos = [p.get("url") for p in (rec.get("photos") or []) if p.get("url")]
                            break
        except Exception:
            photos = []

    comps: list[dict] = []
    if subject:
        try:
            comps = find_comparables(con, subject, max_n=8)
        except Exception:
            comps = []

    # Cohort stats — for the comp grid header
    city = (subject.get("city") or "").strip() if subject else ""
    cls = subject.get("_class") if subject else "RE_1"
    cohort = _cohort_stats(con, city, cls or "RE_1")

    agent = (_load_agent_card() or {}).get("agent") or {}

    # ---- HTML --------------------------------------------------------------
    photo_html = ""
    if photos:
        cells = "".join(
            f'<a href="{u}" target="_blank"><img src="{u}" alt=""></a>'
            for u in photos[:6]
        )
        photo_html = f'<div class="photos">{cells}</div>'

    comp_rows_html = ""
    if comps:
        for c in comps[:8]:
            comp_rows_html += (
                f"<tr><td>{c.get('address','') or ''}</td>"
                f"<td>{c.get('subdivision','') or ''}</td>"
                f"<td>{c.get('bedrooms','') or '—'}/{c.get('full_baths','') or '—'}</td>"
                f"<td>{int(c.get('sqft') or 0) if c.get('sqft') else '—'}</td>"
                f"<td>{_fmt_money(c.get('sold_price'))}</td>"
                f"<td>{c.get('feed_cdom') or c.get('feed_dom') or '—'}d</td>"
                f"<td>{str(c.get('close_date',''))[:10]}</td></tr>"
            )
    comp_table = f"""
    <table class="comps">
      <thead><tr><th>Address</th><th>Subdivision</th><th>BR/BA</th><th>Sqft</th>
        <th>Sold</th><th>DOM</th><th>Closed</th></tr></thead>
      <tbody>{comp_rows_html}</tbody>
    </table>""" if comp_rows_html else "<p><em>Custom comparable set will be assembled when you request a full CMA.</em></p>"

    cohort_html = ""
    if cohort and cohort.get("n"):
        sold_to_orig_pct = (cohort.get("median_sold_to_orig") or 0) * 100
        cohort_html = f"""
        <div class="kpis">
          <div><div class="lbl">Comparable sales (3y)</div><div class="num">{int(cohort['n'])}</div></div>
          <div><div class="lbl">Median DOM</div><div class="num">{round(cohort.get('median_dom') or 0)}d</div></div>
          <div><div class="lbl">Sold / list ratio</div><div class="num">{sold_to_orig_pct:.1f}%</div></div>
          <div><div class="lbl">Median sold</div><div class="num">{_fmt_money(cohort.get('median_sold'))}</div></div>
        </div>"""

    if equity_gain and equity_gain > 0:
        equity_str = f'<span class="gain">+{_fmt_money(equity_gain)} since {last_sale_date[:4] if last_sale_date else ""}</span>'
    elif last_sale_date:
        equity_str = f'<span class="muted">last deeded transfer {last_sale_date}</span>'
    else:
        equity_str = ""

    agent_email = agent.get("email", "")
    agent_phone = agent.get("phone", "")
    cta_email = (
        f'<a class="cta" href="mailto:{agent_email}?subject=Free%20CMA%20for%20{site_addr.replace(" ", "%20")}'
        f'&body=Hi%20{agent.get("name","").split(" ")[0]}%2C%0A%0AI%27d%20like%20a%20full%20CMA%20for%20{site_addr.replace(" ", "%20")}.%0A%0AThanks%2C%0A">'
        f'Email me a free CMA</a>'
    ) if agent_email else ""
    cta_phone = f'<a class="cta secondary" href="tel:{agent_phone.replace(" ", "")}">Call {agent_phone}</a>' if agent_phone else ""

    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{site_addr} — your home's market report</title>
<style>
  *{{box-sizing:border-box}}
  body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;margin:0;background:#fafafa;color:#1d1d1d}}
  .wrap{{max-width:760px;margin:0 auto;padding:30px 22px 80px}}
  .agent{{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #1a5fb4;padding-bottom:10px;margin-bottom:18px}}
  .agent .nm{{font-weight:700;color:#1a5fb4;font-size:18px}}
  .agent .meta{{font-size:12px;color:#555}}
  h1{{font-size:24px;margin:8px 0 4px}}
  .sub{{color:#666;font-size:14px;margin-bottom:18px}}
  .photos{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:14px 0 22px}}
  .photos img{{width:100%;height:140px;object-fit:cover;border-radius:6px}}
  .hero{{background:#fff;border:1px solid #e5e5e5;border-radius:10px;padding:22px;text-align:center;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
  .hero .lbl{{font-size:13px;color:#666;text-transform:uppercase;letter-spacing:1px}}
  .hero .big{{font-size:54px;font-weight:700;color:#1a5fb4;margin:8px 0 6px;line-height:1}}
  .gain{{color:#0a7e2c;font-weight:600;font-size:15px}}
  .muted{{color:#888;font-size:13px}}
  .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0 28px}}
  .kpis div{{background:#eef2f8;padding:12px 8px;border-radius:8px;text-align:center}}
  .kpis .lbl{{font-size:11px;color:#555}}
  .kpis .num{{font-size:18px;font-weight:600;margin-top:4px}}
  h2{{font-size:18px;border-bottom:1px solid #ddd;padding-bottom:6px;margin-top:26px}}
  table.comps{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px;background:#fff;border:1px solid #eaeaea;border-radius:6px;overflow:hidden}}
  table.comps th{{background:#f0f4f8;text-align:left;padding:8px;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#555}}
  table.comps td{{padding:8px;border-top:1px solid #f0f0f0}}
  .cta-row{{display:flex;gap:12px;margin-top:24px;flex-wrap:wrap}}
  .cta{{display:inline-block;padding:14px 22px;background:#1a5fb4;color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:15px}}
  .cta.secondary{{background:#fff;color:#1a5fb4;border:2px solid #1a5fb4}}
  .footer{{margin-top:40px;font-size:11px;color:#888;text-align:center;border-top:1px solid #eee;padding-top:14px}}
  @media(max-width:600px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.photos{{grid-template-columns:repeat(2,1fr)}}.hero .big{{font-size:42px}}}}
</style></head><body>
<div class="wrap">
  <div class="agent">
    <div>
      <div class="nm">{agent.get('name','')}</div>
      <div class="meta">{agent.get('brokerage','')}{(' · ' + agent.get('tagline','')) if agent.get('tagline') else ''}</div>
    </div>
    <div class="meta" style="text-align:right">
      {f'<div>{agent_phone}</div>' if agent_phone else ''}
      {f'<div><a href="mailto:{agent_email}">{agent_email}</a></div>' if agent_email else ''}
    </div>
  </div>

  <h1>{site_addr.title()}</h1>
  <div class="sub">Hi {owner_first} — here's a quick look at your home's market position.</div>

  {photo_html}

  <div class="hero">
    <div class="lbl">Estimated current value</div>
    <div class="big">{_fmt_money(avm_value) if avm_value else 'On request'}</div>
    <div>{equity_str}</div>
    <div class="muted" style="margin-top:8px">
      {('You purchased ' + last_sale_date[:10]) if last_sale_date else ''}
      {(' for ' + _fmt_money(last_sale_price)) if last_sale_price else ''}
      {(f' · {tenure_years:.0f} years held') if tenure_years and tenure_years >= 1 else ''}
    </div>
  </div>

  <h2>Your local cohort — {city.title() if city else 'your area'}</h2>
  {cohort_html or '<p class="muted">Not enough recent comparable sales for a public cohort summary; we will assemble a custom comp set on request.</p>'}

  <h2>Recent comparable sales</h2>
  {comp_table}

  <h2>Want a full CMA?</h2>
  <p>I'll put together a written CMA with line-item adjustments (sqft, age, acres) — same kind I use with my listing clients before we set a price. No cost, no obligation.</p>

  <div class="cta-row">
    {cta_email}
    {cta_phone}
  </div>

  <div class="footer">
    Report ref: {tracking_id}<br>
    Estimates use New River Valley MLS closed sales. Final value depends on condition, updates, and market conditions at time of listing.
  </div>
</div>
</body></html>"""

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tracking_id}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
