"""Cohort newsletter generator — quarterly market update for a (city, subdivision).

Produces a one-page HTML brief copy-pasteable into Mailchimp / Constant Contact /
Gmail. Designed to be sent to past clients in the subdivision as ongoing nurture.

Sections:
  - Headline KPIs (median sold, median DOM, sold/list ratio) for the period
  - Period-over-period delta vs the prior quarter
  - Recent sold table (last N closed)
  - Active inventory table
  - Days-on-market trend bullet
  - Agent contact footer (from agent_card.yaml)

Output: outputs/mls_analytics/newsletters/<city>__<subdivision>__<period>.html
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .db import connect


NEWSLETTER_DIR = Path("outputs/mls_analytics/newsletters")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "x"


def _quarter_dates(period: str) -> tuple[date, date, date, date]:
    """Parse 'Q1-2026' style into (start, end, prev_start, prev_end)."""
    m = re.match(r"Q(\d)-?(\d{4})", period.upper())
    if not m:
        raise ValueError(f"period must look like Q1-2026, got {period}")
    q, y = int(m.group(1)), int(m.group(2))
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    s = date(y, *starts[q])
    e = date(y, *ends[q])
    if q == 1:
        ps, pe = date(y - 1, 10, 1), date(y - 1, 12, 31)
    else:
        ps = date(y, *starts[q - 1])
        pe = date(y, *ends[q - 1])
    return s, e, ps, pe


def _fmt_money(v) -> str:
    if v in (None, "", "None"): return ""
    try: return f"${float(v):,.0f}"
    except (TypeError, ValueError): return str(v)


def _delta_str(curr, prev) -> str:
    if curr is None or prev is None: return ""
    try:
        c, p = float(curr), float(prev)
        if p == 0: return ""
        d = (c - p) / p * 100
        sign = "+" if d >= 0 else ""
        return f"{sign}{d:.1f}% vs prior Q"
    except (TypeError, ValueError):
        return ""


def render_newsletter(city: str, subdivision: str, period: str,
                      out_dir: Path = NEWSLETTER_DIR) -> Path:
    s, e, ps, pe = _quarter_dates(period)
    con = connect()
    city_u = city.upper().strip()
    subd_clause = ""
    if subdivision and subdivision.upper().strip() not in ("ALL", "ANY", ""):
        subd_clause = f"AND UPPER(subdivision) = '{subdivision.upper().strip().replace(chr(39), chr(39)*2)}'"

    def _kpis(d_start: date, d_end: date) -> dict:
        r = con.execute(f"""
        SELECT COUNT(*) AS n,
               ROUND(MEDIAN(TRY_CAST(sold_price AS DOUBLE))) AS med_sold,
               ROUND(MEDIAN(COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT))), 1) AS med_dom,
               ROUND(MEDIAN(TRY_CAST(sold_price AS DOUBLE) / NULLIF(TRY_CAST(original_list_price AS DOUBLE),0))*100, 2) AS sold_pct,
               ROUND(MEDIAN(TRY_CAST(sold_price AS DOUBLE)/NULLIF(TRY_CAST(sqft AS DOUBLE),0)), 0) AS psf
        FROM listings
        WHERE _class='RE_1' AND UPPER(city)='{city_u.replace(chr(39), chr(39)*2)}'
          AND status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) BETWEEN '{d_start}' AND '{d_end}'
          {subd_clause}
        """).fetchone()
        n, ms, dom, sp, psf = r or (0, None, None, None, None)
        return {"n": n or 0, "med_sold": ms, "med_dom": dom, "sold_pct": sp, "psf": psf}

    curr = _kpis(s, e)
    prev = _kpis(ps, pe)

    sold_rows = con.execute(f"""
    SELECT address, bedrooms, full_baths, sqft, original_list_price, sold_price,
           COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
           close_date, list_office_name
    FROM listings
    WHERE _class='RE_1' AND UPPER(city)='{city_u.replace(chr(39), chr(39)*2)}'
      AND status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE) > 0
      AND TRY_CAST(close_date AS DATE) BETWEEN '{s}' AND '{e}'
      {subd_clause}
    ORDER BY close_date DESC LIMIT 8
    """).fetchall()

    active_rows = con.execute(f"""
    SELECT address, bedrooms, full_baths, sqft, list_price, list_date
    FROM listings
    WHERE _class='RE_1' AND UPPER(city)='{city_u.replace(chr(39), chr(39)*2)}'
      AND status_category IN ('Active','Pending')
      {subd_clause}
    ORDER BY list_date DESC LIMIT 6
    """).fetchall()

    # Agent card
    agent_card_path = Path("config/agent_card.yaml")
    agent: dict = {}
    if agent_card_path.exists():
        try:
            import yaml
            agent = (yaml.safe_load(agent_card_path.read_text(encoding="utf-8")) or {}).get("agent") or {}
        except Exception:
            agent = {}

    title_subd = (subdivision or "All Subdivisions").title()
    title = f"{title_subd}, {city.title()} — {period} Market Update"

    sold_html = "".join(
        f"<tr><td>{a}</td><td>{b or '-'}/{fb or '-'}</td><td>{int(sf or 0) if sf else '-'}</td>"
        f"<td>{_fmt_money(op)}</td><td><strong>{_fmt_money(sp)}</strong></td>"
        f"<td>{d or '-'}d</td><td>{str(cd)[:10]}</td></tr>"
        for a, b, fb, sf, op, sp, d, cd, _ in sold_rows
    ) or "<tr><td colspan=7 style='color:#888'>(no sales this period)</td></tr>"

    active_html = "".join(
        f"<tr><td>{a}</td><td>{b or '-'}/{fb or '-'}</td><td>{int(sf or 0) if sf else '-'}</td>"
        f"<td>{_fmt_money(lp)}</td><td>{str(ld)[:10]}</td></tr>"
        for a, b, fb, sf, lp, ld in active_rows
    ) or "<tr><td colspan=5 style='color:#888'>(no active inventory)</td></tr>"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(city)}__{_slug(subdivision)}__{_slug(period)}.html"

    today = datetime.now().strftime("%B %d, %Y")
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:Georgia,'Times New Roman',serif;max-width:680px;margin:0 auto;padding:30px 20px;color:#222;line-height:1.5}}
h1{{font-size:24px;border-bottom:3px solid #1a5fb4;padding-bottom:8px}}
h2{{font-size:16px;color:#1a5fb4;margin-top:24px;margin-bottom:8px}}
.kpis{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:16px 0}}
.kpi{{background:#f6f6f6;padding:12px;border-radius:6px}}
.kpi .lbl{{font-size:12px;color:#666;text-transform:uppercase;letter-spacing:1px}}
.kpi .val{{font-size:22px;font-weight:bold;margin-top:4px}}
.kpi .delta{{font-size:11px;color:#0a7e2c}}
.kpi .delta.neg{{color:#a41010}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}}
th,td{{padding:6px 8px;border-bottom:1px solid #eee;text-align:left}}
th{{background:#fafafa;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
.foot{{margin-top:30px;padding-top:14px;border-top:1px solid #ccc;font-size:13px;color:#444}}
.foot strong{{color:#1a5fb4}}
.intro{{font-style:italic;color:#555}}
</style></head><body>
<h1>{title}</h1>
<p class="intro">A quarterly snapshot of how {title_subd} is moving — sale prices, days on market, and what's currently for sale. Sent {today}.</p>

<h2>The numbers ({s.strftime('%b %d')}–{e.strftime('%b %d, %Y')})</h2>
<div class="kpis">
  <div class="kpi">
    <div class="lbl">Closed sales</div>
    <div class="val">{curr['n']}</div>
    <div class="delta {'neg' if (curr['n'] or 0) < (prev['n'] or 0) else ''}">{_delta_str(curr['n'], prev['n'])}</div>
  </div>
  <div class="kpi">
    <div class="lbl">Median sold price</div>
    <div class="val">{_fmt_money(curr['med_sold'])}</div>
    <div class="delta {'neg' if (curr['med_sold'] or 0) < (prev['med_sold'] or 0) else ''}">{_delta_str(curr['med_sold'], prev['med_sold'])}</div>
  </div>
  <div class="kpi">
    <div class="lbl">Median days on market</div>
    <div class="val">{curr['med_dom'] or '-'}d</div>
    <div class="delta {'neg' if (curr['med_dom'] or 0) > (prev['med_dom'] or 0) else ''}">{_delta_str(curr['med_dom'], prev['med_dom'])}</div>
  </div>
  <div class="kpi">
    <div class="lbl">Sold-to-original list</div>
    <div class="val">{curr['sold_pct'] or '-'}%</div>
    <div class="delta">{_delta_str(curr['sold_pct'], prev['sold_pct'])}</div>
  </div>
</div>

<h2>Recent sales</h2>
<table>
<tr><th>Address</th><th>BR/BA</th><th>Sqft</th><th>List</th><th>Sold</th><th>DOM</th><th>Closed</th></tr>
{sold_html}
</table>

<h2>Currently for sale</h2>
<table>
<tr><th>Address</th><th>BR/BA</th><th>Sqft</th><th>Price</th><th>Listed</th></tr>
{active_html}
</table>

<div class="foot">
  <p><strong>Curious what your home is worth in today's market?</strong> I run free no-obligation CMAs (comparative market analyses) for owners in {title_subd}. Reply to this email or call me directly.</p>
  <p>
    <strong>{agent.get('name','')}</strong><br>
    {agent.get('brokerage','')}<br>
    {agent.get('phone','')} · <a href="mailto:{agent.get('email','')}">{agent.get('email','')}</a><br>
    <em>{agent.get('tagline','')}</em>
  </p>
  <p style="font-size:11px;color:#888;margin-top:18px">Sourced from NRV MLS data + Montgomery County deed records. Not all properties may appear; off-market and FSBO sales not included.</p>
</div>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")
    return out_path
