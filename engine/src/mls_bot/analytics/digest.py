"""MLS analytics daily digest — HTML email summary.

Builds a single HTML email summarizing:
  - New listings, status changes, and price drops in the last 24 hours
  - Hot watch matches (default: Blacksburg RES <= $500k, 3+ bed)
  - Headline market-velocity numbers per major NRV city
  - Top expired-then-sold leads from this week
  - Top investor-portfolio movements

Render-only (no SMTP send) — outputs to outputs/mls_analytics/digest.html.
A separate `send_digest()` function uses the existing SMTP config in mls_bot.config
to mail it if SMTP_USER + DIGEST_TO are configured.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .db import connect


DIGEST_HTML = Path("outputs/mls_analytics/digest.html")


def _qs(con, sql: str) -> list[tuple]:
    try:
        return con.execute(sql).fetchall()
    except Exception:
        return []


def build_digest_html(out_path: Path = DIGEST_HTML, *, days: int = 7) -> Path:
    con = connect()

    # Section: recent status changes (last `days`)
    status_changes = _qs(con, f"""
        WITH h AS (
            SELECT * FROM read_json_auto('data/mls/listings_history.jsonl',
                format='newline_delimited', union_by_name=true, sample_size=-1)
        )
        SELECT listing_id, observed_at, kind, from_status, to_status, city, address, list_price
        FROM h
        WHERE kind IN ('status_change', 'new')
          AND TRY_CAST(observed_at AS TIMESTAMP) >= NOW() - INTERVAL '{days} days'
          AND _synthetic IS NOT TRUE
        ORDER BY observed_at DESC LIMIT 30
    """)

    # Section: recent price drops
    price_drops = _qs(con, f"""
        WITH h AS (
            SELECT * FROM read_json_auto('data/mls/listings_history.jsonl',
                format='newline_delimited', union_by_name=true, sample_size=-1)
        )
        SELECT listing_id, observed_at, from_price, to_price, delta_pct, city, address
        FROM h
        WHERE kind='price_change' AND delta < 0
          AND TRY_CAST(observed_at AS TIMESTAMP) >= NOW() - INTERVAL '{days} days'
          AND _synthetic IS NOT TRUE
        ORDER BY ABS(delta_pct) DESC LIMIT 20
    """)

    # Section: hot watch matches (defaults — user can customize)
    hot_matches = _qs(con, """
        SELECT listing_id, city, address, list_price, bedrooms, full_baths, sqft, list_date
        FROM listings
        WHERE _class='RE_1' AND status_category='Active'
          AND UPPER(city) IN ('BLACKSBURG','CHRISTIANSBURG')
          AND TRY_CAST(list_price AS DOUBLE) <= 500000
          AND TRY_CAST(bedrooms AS INT) >= 3
          AND TRY_CAST(list_date AS DATE) >= CURRENT_DATE - INTERVAL '14 days'
        ORDER BY list_date DESC LIMIT 15
    """)

    # Section: market velocity headlines
    velocity = _qs(con, """
        SELECT city, _class, months_of_inventory, market_label, active_n, dom_median_90d
        FROM read_csv_auto('outputs/mls_analytics/market_velocity.csv')
        ORDER BY active_n DESC LIMIT 8
    """) if Path("outputs/mls_analytics/market_velocity.csv").exists() else []

    # Section: top expired-then-sold leads
    et_leads = _qs(con, """
        SELECT city, address, original_price, deed_sale_price, deed_sale_date, days_listed_to_deed
        FROM read_csv_auto('outputs/mls_analytics/leads/expired_then_sold_leads.csv')
        WHERE deed_sale_date >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY deed_sale_date DESC LIMIT 12
    """) if Path("outputs/mls_analytics/leads/expired_then_sold_leads.csv").exists() else []

    # Section: top investor portfolios with active inventory
    investors = _qs(con, """
        SELECT owner, owner_type, n_active, n_pending, n_closed_24mo, sold_volume_24mo, cities
        FROM read_csv_auto('outputs/mls_analytics/leads/investor_portfolios.csv')
        WHERE n_active >= 3
        ORDER BY n_active DESC LIMIT 10
    """) if Path("outputs/mls_analytics/leads/investor_portfolios.csv").exists() else []

    today = datetime.now().strftime("%Y-%m-%d")

    def fmt_money(v) -> str:
        if v in (None, "", "None"): return ""
        try:
            return f"${float(v):,.0f}"
        except: return str(v)

    def section(title: str, rows: list, headers: list[str]) -> str:
        if not rows:
            return f'<h2>{title}</h2><p style="color:#888">(none)</p>'
        thead = "".join(f"<th>{h}</th>" for h in headers)
        body = ""
        for row in rows:
            tds = "".join(f"<td>{(c if c is not None else '')}</td>" for c in row)
            body += f"<tr>{tds}</tr>"
        return f'<h2>{title}</h2><table>{thead}{body}</table>'

    sections = []
    sections.append(section(
        f"Status changes (last {days} days)",
        [(r[0], str(r[1])[:16], r[2], r[3] or '-', r[4] or '-', r[5], r[6], fmt_money(r[7])) for r in status_changes],
        ["#","when","kind","from","to","city","address","price"]))
    sections.append(section(
        f"Price drops (last {days} days)",
        [(r[0], str(r[1])[:16], fmt_money(r[2]), fmt_money(r[3]), f"{r[4]:.1f}%", r[5], r[6]) for r in price_drops],
        ["#","when","from","to","Δ%","city","address"]))
    sections.append(section(
        "Hot new listings (Bburg/Cburg, RES, ≤$500k, 3+ BR, last 14 days)",
        [(r[0], r[1], r[2], fmt_money(r[3]), r[4], r[5], r[6], str(r[7])[:10]) for r in hot_matches],
        ["#","city","address","price","BR","FB","sqft","listed"]))
    sections.append(section(
        "Market velocity (top markets by active volume)",
        [(r[0], r[1], f"{r[2]:.2f} mo" if r[2] else "-", r[3] or "-", r[4], f"{r[5]:.0f}d" if r[5] else "-") for r in velocity],
        ["city","class","mo inventory","label","active","DOM med 90d"]))
    sections.append(section(
        "Expired-then-sold leads (last 90 days)",
        [(r[0], r[1], fmt_money(r[2]), fmt_money(r[3]), str(r[4])[:10], r[5]) for r in et_leads],
        ["city","address","orig list","deed sold","deed date","days list→deed"]))
    sections.append(section(
        "Investor portfolios with 3+ active listings",
        [(r[0], r[1], r[2], r[3], r[4], fmt_money(r[5]), r[6]) for r in investors],
        ["owner","type","active","pending","closed 24mo","sold $","cities"]))

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>MLS Daily — {today}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#222}}
h1{{margin-bottom:6px}} h2{{border-bottom:1px solid #ccc;padding-bottom:6px;margin-top:30px;font-size:16px}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}}
th,td{{border:1px solid #ddd;padding:4px 7px;text-align:left}} th{{background:#f0f0f0}}
.head{{font-size:12px;color:#666}}
</style></head><body>
<h1>MLS Bot — Daily Digest</h1>
<p class="head">{today}  ·  NRV MLS analytics  ·  data through last sync</p>
{"".join(sections)}
<p class="head" style="margin-top:30px">Generated by mls-daily; configure SMTP in .env to receive via email.</p>
</body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def send_digest_email(subject_prefix: str = "MLS Daily Digest") -> bool:
    """Send the digest HTML via SMTP if configured. Returns True on success."""
    from email.mime.text import MIMEText
    import smtplib
    from ..config import load
    s = load()
    if not s.smtp_user or not s.digest_to:
        print("  [digest] SMTP_USER or DIGEST_TO not set; skipping send")
        return False
    if not DIGEST_HTML.exists():
        print(f"  [digest] {DIGEST_HTML} not found")
        return False
    html = DIGEST_HTML.read_text(encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = f"{subject_prefix} — {today}"
    msg["From"] = s.digest_from or s.smtp_user
    msg["To"] = s.digest_to
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port) as srv:
            srv.starttls()
            srv.login(s.smtp_user, s.smtp_pass)
            srv.send_message(msg)
        print(f"  [digest] sent to {s.digest_to}")
        return True
    except Exception as e:
        print(f"  [digest] send failed: {e}")
        return False
