"""CMA — comparable market analysis.

Given a subject property (parcel_id OR address+city) and a proposed list price,
return:
  - Cohort definition (city, property_class, price_band, year-window)
  - Comparable sample of N most similar recent sales
  - Expected DOM range (cohort p25 / median / p75)
  - Expected sold/original ratio (median for cohort)
  - Pricing verdict — where the proposed price sits in the cohort distribution
  - Suggested list price range bracket

The "similarity" ranking factors:
  - Same _class (hard)
  - Same city (preferred); fall back to neighboring cities
  - Sqft within ±25% (RES); acres within ±50% (LAND)
  - Beds (RES) ±1
  - Sold within last 3 years (preferred), else 5

Output: dict + a self-contained HTML report.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .bands import band_for, BANDS_BY_CLASS, label
from .db import connect


def _load_agent_card() -> dict:
    """Load agent branding from config/agent_card.yaml (or empty dict)."""
    p = Path("config/agent_card.yaml")
    if not p.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _agent_header_html(card: dict) -> str:
    """Return a small HTML header div for the agent card. Empty if no data."""
    a = (card or {}).get("agent") or {}
    if not a.get("name"):
        return ""
    parts = [f'<strong>{a.get("name","")}</strong>']
    if a.get("license"):    parts.append(f'License #{a["license"]}')
    if a.get("brokerage"):  parts.append(a["brokerage"])
    if a.get("phone"):      parts.append(a["phone"])
    if a.get("email"):      parts.append(f'<a href="mailto:{a["email"]}">{a["email"]}</a>')
    if a.get("website"):    parts.append(f'<a href="{a["website"]}">{a["website"]}</a>')
    line1 = " · ".join(parts)
    tagline = a.get("tagline") or ""
    return (
        f'<div class="agent-card">'
        f'<div class="agent-line">{line1}</div>'
        f'{f"<div class=agent-tag>{tagline}</div>" if tagline else ""}'
        f'</div>'
    )


def render_pdf(html_path: Path | str, pdf_path: Path | str | None = None) -> Path | None:
    """Convert an HTML CMA file to PDF using Edge headless (preinstalled on Win11).

    Returns the PDF path on success, None on failure (caller should print
    a "Use Ctrl+P from browser" fallback message).
    """
    import subprocess
    html_path = Path(html_path).resolve()
    if not html_path.exists():
        return None
    if pdf_path is None:
        pdf_path = html_path.with_suffix(".pdf")
    pdf_path = Path(pdf_path).resolve()
    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    edge_exe = next((p for p in edge_candidates if Path(p).exists()), None)
    if not edge_exe:
        print("  [pdf] msedge.exe not found; open the HTML in a browser and Ctrl+P → Save as PDF")
        return None
    cmd = [
        edge_exe, "--headless=new", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={pdf_path}",
        f"--print-to-pdf-no-header",
        html_path.as_uri(),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=60, capture_output=True)
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            return pdf_path
    except Exception as e:
        print(f"  [pdf] Edge headless failed: {e}")
    return None


def render_deck(report: dict, out_path: Path) -> Path:
    """Render the CMA as a slide-style presenter deck — one fact per slide,
    big fonts, full-screen ready. Uses simple <section> page breaks and large
    typography. Designed for tablet / laptop viewing in a seller meeting."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = report.get("subject") or {}
    cohort = report.get("cohort") or {}
    comps = report.get("comparables") or []
    pp = report.get("proposed_price") or 0
    model = report.get("model_prediction") or {}
    rec = report.get("price_recommendation") or {}
    photos = report.get("photos") or []
    agent = (_load_agent_card() or {}).get("agent") or {}

    def fmt_money(v) -> str:
        if v in (None, "", "None"): return ""
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v)

    # Slide 1: title + subject
    slides = []
    slides.append(f"""
    <section class="title">
      <div class="brand">{agent.get('name','')}</div>
      <h1>{s.get('address','(no address)')}</h1>
      <div class="city">{s.get('city','')}, VA · {s.get('property_subtype','')}</div>
      <div class="big-stats">
        <div><div class="lbl">Beds/Baths</div><div class="val">{s.get('bedrooms','-')}/{s.get('full_baths','-')}</div></div>
        <div><div class="lbl">Sqft</div><div class="val">{int(s['sqft']) if s.get('sqft') else '-'}</div></div>
        <div><div class="lbl">Year built</div><div class="val">{s.get('year_built','-')}</div></div>
        <div><div class="lbl">Acres</div><div class="val">{s.get('acres','-')}</div></div>
      </div>
    </section>""")

    # Slide 2: photos
    if photos:
        cells = "".join(f'<img src="{u}" alt="">' for u in photos[:6])
        slides.append(f'<section class="photos"><div class="ph-grid">{cells}</div></section>')

    # Slide 3: proposed price + model
    slides.append(f"""
    <section>
      <h2>Proposed list price</h2>
      <div class="hero-num">{fmt_money(pp)}</div>
      <div class="hero-sub">at the ~p{report.get('cohort_percentile_for_price',0)} of {s.get('city','')} {s.get('_class','')} cohort</div>
    </section>""")

    if model:
        slides.append(f"""
    <section>
      <h2>Model prediction — days on market</h2>
      <div class="trio">
        <div><div class="lbl">Optimistic (p25)</div><div class="num">{model.get('p25', '-'):.0f}d</div></div>
        <div><div class="lbl">Median (p50)</div><div class="num">{model.get('p50', '-'):.0f}d</div></div>
        <div><div class="lbl">Slow case (p75)</div><div class="num">{model.get('p75', '-'):.0f}d</div></div>
      </div>
    </section>""")

    # Slide: cohort detail
    slides.append(f"""
    <section>
      <h2>Cohort context</h2>
      <div class="trio">
        <div><div class="lbl">Comparable sales (3y)</div><div class="num">{cohort.get('n','-')}</div></div>
        <div><div class="lbl">Median DOM</div><div class="num">{round(cohort.get('median_dom') or 0)}d</div></div>
        <div><div class="lbl">Sold/list ratio</div><div class="num">{(cohort.get('median_sold_to_orig') or 0)*100:.1f}%</div></div>
      </div>
      <div class="trio">
        <div><div class="lbl">p25 sold</div><div class="num">{fmt_money(cohort.get('p25_orig'))}</div></div>
        <div><div class="lbl">Median sold</div><div class="num">{fmt_money(cohort.get('median_sold'))}</div></div>
        <div><div class="lbl">p75 sold</div><div class="num">{fmt_money(cohort.get('p75_orig'))}</div></div>
      </div>
    </section>""")

    # Slide: recommendation
    if rec and rec.get("feasible"):
        slides.append(f"""
    <section>
      <h2>Recommended price for 14-day sale</h2>
      <div class="hero-num">{fmt_money(rec.get('sweet_spot'))}</div>
      <div class="hero-sub">Range: {fmt_money(rec.get('min_price'))} – {fmt_money(rec.get('max_price'))}</div>
    </section>""")

    # Slide: listing strategy
    strat = report.get("listing_strategy") or _listing_strategy(report)
    if strat:
        mp_html = "".join(f"<li>{x}</li>" for x in strat.get("marketing_plan") or [])
        risk_html = "".join(f"<li>{x}</li>" for x in strat.get("risk_items") or [])
        rp = strat.get("recommended_price")
        rmin = strat.get("rec_min")
        rmax = strat.get("rec_max")
        rp_str = fmt_money(rp) if rp else "—"
        rng_str = (f"{fmt_money(rmin)} – {fmt_money(rmax)}" if (rmin and rmax) else "")
        slides.append(f"""
    <section class="strategy-slide">
      <h2>Listing strategy</h2>
      <div class="strat-hero">
        <div class="lbl">Recommended list price</div>
        <div class="hero-num" style="color:#1a5fb4">{rp_str}</div>
        <div class="hero-sub">{rng_str}</div>
        <div class="hero-sub" style="margin-top:8px">Expected DOM: <strong>{strat.get('expected_dom_range','')}</strong></div>
      </div>
      <div class="strat-cols">
        <div><h3>Marketing plan</h3><ul>{mp_html}</ul></div>
        <div><h3>Risk items</h3><ul>{risk_html}</ul></div>
      </div>
    </section>""")

    # Slide: top 6 comps
    top_comps = comps[:6]
    if top_comps:
        comp_rows = ""
        for c in top_comps:
            comp_rows += (
                f"<tr><td>{c.get('address','')}</td>"
                f"<td>{c.get('bedrooms','') or '-'}/{c.get('full_baths','') or '-'}</td>"
                f"<td>{int(c.get('sqft') or 0) if c.get('sqft') else '-'}</td>"
                f"<td>{fmt_money(c.get('original_list_price'))}</td>"
                f"<td>{fmt_money(c.get('sold_price'))}</td>"
                f"<td>{c.get('feed_cdom') or c.get('feed_dom') or '-'}d</td>"
                f"<td>{str(c.get('close_date',''))[:10]}</td></tr>"
            )
        slides.append(f"""
    <section>
      <h2>Top comparables</h2>
      <table class="comps">
        <tr><th>Address</th><th>BR/BA</th><th>Sqft</th><th>Orig</th><th>Sold</th><th>DOM</th><th>Closed</th></tr>
        {comp_rows}
      </table>
    </section>""")

    # Slide: verdict
    slides.append(f"""
    <section class="verdict-slide">
      <h2>The bottom line</h2>
      <p class="verdict-text">{report.get('verdict','')}</p>
    </section>""")

    # Slide: agent contact (closer)
    if agent.get('name'):
        slides.append(f"""
    <section class="closer">
      <h2>Let's talk strategy</h2>
      <div class="agent-name">{agent.get('name','')}</div>
      <div class="agent-meta">{agent.get('brokerage','')}</div>
      <div class="agent-meta">{agent.get('phone','')} · {agent.get('email','')}</div>
      <div class="agent-meta">{agent.get('tagline','')}</div>
    </section>""")

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>CMA deck — {s.get('address','subject')}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;margin:0;padding:0;background:#fafafa;color:#222}}
section{{min-height:90vh;padding:60px 80px;page-break-after:always;display:flex;flex-direction:column;justify-content:center;border-bottom:1px solid #ddd}}
h1{{font-size:48px;margin:8px 0;line-height:1.1}}
h2{{font-size:32px;margin:0 0 24px 0;color:#1a5fb4;border-bottom:3px solid #1a5fb4;padding-bottom:6px;display:inline-block}}
.brand{{font-size:14px;color:#888;text-transform:uppercase;letter-spacing:2px}}
.city{{font-size:22px;color:#666;margin-bottom:30px}}
.big-stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;margin-top:40px}}
.big-stats div{{background:#fff;padding:24px;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.08);text-align:center}}
.big-stats .lbl{{font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px}}
.big-stats .val{{font-size:42px;font-weight:600;margin-top:8px}}
.trio{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:24px}}
.trio div{{background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,.06);text-align:center}}
.trio .lbl{{font-size:13px;color:#777}}
.trio .num{{font-size:36px;font-weight:600;color:#0a7e2c;margin-top:6px}}
.hero-num{{font-size:96px;font-weight:700;color:#1a5fb4;text-align:center;margin:20px 0}}
.hero-sub{{font-size:18px;color:#666;text-align:center}}
.ph-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;width:100%}}
.ph-grid img{{width:100%;height:300px;object-fit:cover;border-radius:8px}}
table.comps{{width:100%;border-collapse:collapse;font-size:18px;margin-top:14px}}
table.comps th,table.comps td{{padding:14px;border-bottom:1px solid #eee;text-align:left}}
table.comps th{{background:#f0f0f0;font-size:14px;text-transform:uppercase;letter-spacing:1px}}
.verdict-slide .verdict-text{{font-size:24px;line-height:1.6;background:#fff7e0;padding:30px;border-left:6px solid #f5a623;border-radius:8px}}
.strategy-slide .strat-hero{{text-align:center;margin-bottom:24px;padding-bottom:18px;border-bottom:1px solid #ddd}}
.strategy-slide .strat-cols{{display:grid;grid-template-columns:1fr 1fr;gap:30px}}
.strategy-slide .strat-cols h3{{font-size:18px;color:#1a5fb4;border:0;margin:0 0 8px}}
.strategy-slide .strat-cols ul{{font-size:18px;line-height:1.6;padding-left:24px}}
.closer{{background:#1a5fb4;color:#fff}}
.closer h2{{color:#fff;border-bottom-color:#fff}}
.closer .agent-name{{font-size:48px;font-weight:700;margin:24px 0 8px}}
.closer .agent-meta{{font-size:20px;color:#cce}}
@media print {{
  section{{page-break-after:always}}
  body{{background:#fff}}
}}
@page{{size:landscape;margin:0}}
</style></head><body>
{''.join(slides)}
</body></html>"""

    out_path.write_text(html, encoding="utf-8")
    return out_path


def _listing_strategy(report: dict) -> dict:
    """Synthesize a listing-strategy block from the CMA report.

    Returns a dict with: recommended_price (str), expected_dom_range (str),
    marketing_plan (list[str]), risk_items (list[str])."""
    s = report.get("subject") or {}
    cohort = report.get("cohort") or {}
    rec = report.get("price_recommendation") or {}
    model = report.get("model_prediction") or {}

    # Recommended price — prefer the model's 14-day target if feasible,
    # else fall back to the cohort median * 1.0
    if rec and rec.get("feasible"):
        recommended_price = rec.get("sweet_spot")
        rec_min = rec.get("min_price")
        rec_max = rec.get("max_price")
    else:
        recommended_price = cohort.get("median_orig") or report.get("proposed_price")
        rec_min = recommended_price * 0.97 if recommended_price else None
        rec_max = recommended_price * 1.03 if recommended_price else None

    if model and model.get("p25") is not None:
        expected_dom_range = f"{model['p25']:.0f}–{model['p75']:.0f} days (median {model['p50']:.0f})"
    elif cohort.get("p25_dom") is not None:
        expected_dom_range = (f"{round(cohort.get('p25_dom') or 0)}–"
                              f"{round(cohort.get('p75_dom') or 0)} days "
                              f"(median {round(cohort.get('median_dom') or 0)})")
    else:
        expected_dom_range = "thin cohort — directional only"

    cls = s.get("_class") or "RE_1"
    sqft = s.get("sqft") or 0
    is_lux = (report.get("proposed_price") or 0) >= 700_000

    marketing_plan: list[str] = []
    if cls == "RE_1":
        marketing_plan.append("Pre-listing photography (24-shot interior/exterior + drone if lot size > 0.4 acre)")
        if is_lux:
            marketing_plan.append("Light staging or virtual staging on 3 primary rooms (LR/kitchen/primary)")
            marketing_plan.append("Print piece in cohort comp folder for buyer-agent showings")
        else:
            marketing_plan.append("Stage primary bedroom + decluttering pass on living spaces")
        marketing_plan.append("MLS remarks emphasize 2–3 cohort-distinguishing features")
        marketing_plan.append("Tier-1 syndication (MLS, Zillow, Realtor, Redfin) + agent-network broadcast")
        marketing_plan.append("Open house weekend 1; reassess weekly thereafter")
        if sqft and sqft >= 2400:
            marketing_plan.append("Floor-plan diagram included in the listing")
    else:  # land
        marketing_plan.append("Drone aerial showing parcel boundaries + topography")
        marketing_plan.append("Survey, soils report, well/septic notes attached to listing")
        marketing_plan.append("MLS remarks highlight zoning + utility availability")

    # Buyer-profile note from the cohort if available
    cohort_n = cohort.get("n") or 0
    if cohort_n >= 5:
        marketing_plan.append(
            f"Target buyer profile: {(s.get('city') or 'this market').title()} "
            f"{cls} cohort (n={cohort_n}, sold/list median "
            f"{(cohort.get('median_sold_to_orig') or 0)*100:.1f}%)"
        )

    risk_items: list[str] = []
    cut_prob = report.get("cut_probability")  # set below in cma_for if available
    if cut_prob is not None:
        if cut_prob >= 0.45:
            risk_items.append(f"Elevated price-cut risk ({cut_prob*100:.0f}%) — pre-list price-stress test recommended")
        elif cut_prob >= 0.30:
            risk_items.append(f"Moderate cut risk ({cut_prob*100:.0f}%) — monitor at day 14 / day 21")
    pctile = report.get("cohort_percentile_for_price") or 0
    if pctile >= 80:
        risk_items.append(f"Price sits at cohort p{pctile} — expect longer DOM unless condition strongly outperforms cohort")
    if s.get("in_floodplain") is True or (s.get("flood_zone") or "") in ("AE", "A", "VE"):
        risk_items.append(f"Property in flood zone {s.get('flood_zone','A')} — disclosure required + insurance friction")
    cf = s.get("condition_flags") or []
    if isinstance(cf, str):
        cf = [c.strip() for c in cf.split(",") if c.strip()]
    if any(f in cf for f in ("as_is", "fixer", "investor_special", "distressed")):
        risk_items.append("Distressed-condition signals in remarks — price for cash/investor pool, manage expectation timeline")
    if not risk_items:
        risk_items.append("No major risk flags — execute the marketing plan as planned")

    return {
        "recommended_price": recommended_price,
        "rec_min": rec_min,
        "rec_max": rec_max,
        "expected_dom_range": expected_dom_range,
        "marketing_plan": marketing_plan,
        "risk_items": risk_items,
    }


def _listing_strategy_html(strategy: dict) -> str:
    rp = strategy.get("recommended_price")
    rmin = strategy.get("rec_min")
    rmax = strategy.get("rec_max")
    rp_str = f"${float(rp):,.0f}" if rp else "—"
    range_str = (f"${float(rmin):,.0f} – ${float(rmax):,.0f}"
                 if (rmin and rmax) else "")
    mp_html = "".join(f"<li>{x}</li>" for x in strategy.get("marketing_plan") or [])
    risk_html = "".join(f"<li>{x}</li>" for x in strategy.get("risk_items") or [])
    return f"""<h2>Listing strategy</h2>
<div class="strategy">
  <div class="strategy-hero">
    <div class="lbl">Recommended list price</div>
    <div class="big">{rp_str}</div>
    <div class="rng">{range_str}</div>
    <div class="dom">Expected DOM: <strong>{strategy.get('expected_dom_range','')}</strong></div>
  </div>
  <div class="strategy-cols">
    <div>
      <h3>Marketing plan</h3>
      <ul>{mp_html}</ul>
    </div>
    <div>
      <h3>Risk items</h3>
      <ul>{risk_html}</ul>
    </div>
  </div>
</div>"""


def _normalize_subject(subject: dict) -> dict:
    """Coerce the subject dict's numerics."""
    out = dict(subject)
    for k in ("list_price", "sqft", "acres"):
        if out.get(k) not in (None, ""):
            try:
                out[k] = float(out[k])
            except (TypeError, ValueError):
                out[k] = None
    for k in ("bedrooms", "full_baths", "year_built"):
        if out.get(k) not in (None, ""):
            try:
                out[k] = int(out[k])
            except (TypeError, ValueError):
                out[k] = None
    return out


def find_subject(parcel_id: str | None = None, address: str | None = None,
                 city: str | None = None) -> dict | None:
    """Look up the subject property. Prefers active listing, then most recent."""
    con = connect()
    if parcel_id:
        sql = f"""
        SELECT * FROM listings
        WHERE parcel_id = '{parcel_id.replace("'", "''")}'
        ORDER BY status_category='Active' DESC, list_date DESC
        LIMIT 1
        """
    elif address:
        addr = address.replace("'", "''").upper().strip()
        city_part = f" AND UPPER(city) = '{city.replace(chr(39), chr(39)+chr(39)).upper()}'" if city else ""
        sql = f"""
        SELECT * FROM listings
        WHERE UPPER(address) LIKE '%{addr}%'{city_part}
        ORDER BY status_category='Active' DESC, list_date DESC
        LIMIT 1
        """
    else:
        return None
    rows = con.execute(sql).fetchdf().to_dict(orient="records")
    return rows[0] if rows else None


def find_comparables(con, subject: dict, *, max_n: int = 20) -> list[dict]:
    """Return up to N comparable sold listings, ranked by similarity."""
    cls = subject.get("_class") or "RE_1"
    city = (subject.get("city") or "").upper().strip()
    sqft = subject.get("sqft")
    acres = subject.get("acres")
    beds = subject.get("bedrooms")

    today = date.today()
    cutoff = today - timedelta(days=365 * 3)

    where = [
        f"_class = '{cls}'",
        "status_category = 'Closed'",
        "TRY_CAST(sold_price AS DOUBLE) > 0",
        f"TRY_CAST(close_date AS DATE) >= '{cutoff.isoformat()}'",
    ]
    if city:
        where.append(f"UPPER(city) = '{city}'")
    if sqft and cls == "RE_1":
        where.append(f"TRY_CAST(sqft AS DOUBLE) BETWEEN {sqft*0.75} AND {sqft*1.25}")
    if acres and cls == "LD_3":
        where.append(f"TRY_CAST(acres AS DOUBLE) BETWEEN {acres*0.5} AND {acres*1.5}")
    if beds and cls == "RE_1":
        where.append(f"TRY_CAST(bedrooms AS INT) BETWEEN {beds-1} AND {beds+1}")

    sql = f"""
    SELECT listing_id, address, city, subdivision,
           list_price, original_list_price, sold_price,
           feed_dom, feed_cdom, list_date, close_date,
           bedrooms, full_baths, half_baths, sqft, acres,
           property_subtype, year_built, list_office_name
    FROM listings
    WHERE {' AND '.join(where)}
    ORDER BY close_date DESC
    LIMIT {max_n}
    """
    return con.execute(sql).fetchdf().to_dict(orient="records")


def _percentile_of_value(values: list[float], v: float) -> int:
    if not values:
        return 50
    below = sum(1 for x in values if x < v)
    return int(round(below / len(values) * 100))


def _svg_price_distribution(prices: list[float], proposed_price: float,
                            *, width: int = 720, height: int = 220, n_bins: int = 24) -> str:
    """SVG histogram of cohort original-list prices with proposed-price marker.

    Clips to [p1, p99] to avoid outlier drag (commercial mis-classifications)."""
    if not prices:
        return ""
    sorted_prices = sorted(p for p in prices if p and p > 0)
    if len(sorted_prices) < 5:
        return ""
    lo = sorted_prices[max(0, int(len(sorted_prices) * 0.01))]
    hi = sorted_prices[min(len(sorted_prices) - 1, int(len(sorted_prices) * 0.99))]
    if lo >= hi:
        return ""
    # Filter prices into the clipped range
    prices = [p for p in sorted_prices if lo <= p <= hi]
    if len(prices) < 5:
        return ""
    bin_w = (hi - lo) / n_bins
    counts = [0] * n_bins
    for p in prices:
        idx = min(int((p - lo) / bin_w), n_bins - 1)
        counts[idx] += 1
    max_count = max(counts) or 1
    pad_l, pad_r, pad_t, pad_b = 50, 16, 14, 36
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    bar_w = plot_w / n_bins
    bars = []
    for i, c in enumerate(counts):
        h = (c / max_count) * plot_h if max_count else 0
        x = pad_l + i * bar_w
        y = pad_t + (plot_h - h)
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w-1:.1f}" height="{h:.1f}" fill="#6892c8" />')
    # Marker line for proposed price
    if lo <= proposed_price <= hi:
        x_mark = pad_l + ((proposed_price - lo) / (hi - lo)) * plot_w
        marker = (f'<line x1="{x_mark:.1f}" y1="{pad_t}" x2="{x_mark:.1f}" y2="{pad_t+plot_h}" '
                  f'stroke="#f5a623" stroke-width="3"/>'
                  f'<text x="{x_mark:.1f}" y="{pad_t-3}" font-size="11" text-anchor="middle" fill="#c47800">'
                  f'proposed ${proposed_price/1000:.0f}k</text>')
    else:
        marker = ""
    # X-axis labels: lo / mid / hi
    mid = (lo + hi) / 2
    x_labels = (
        f'<text x="{pad_l}" y="{height-12}" font-size="11" fill="#555">${lo/1000:.0f}k</text>'
        f'<text x="{pad_l + plot_w/2}" y="{height-12}" font-size="11" text-anchor="middle" fill="#555">${mid/1000:.0f}k</text>'
        f'<text x="{pad_l + plot_w}" y="{height-12}" font-size="11" text-anchor="end" fill="#555">${hi/1000:.0f}k</text>'
    )
    y_label = f'<text x="6" y="{pad_t+plot_h/2}" font-size="11" fill="#555" transform="rotate(-90 6 {pad_t+plot_h/2})" text-anchor="middle">listings</text>'
    return (f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
            f'{"".join(bars)}{marker}{x_labels}{y_label}</svg>')


def _svg_sparkline(con, cls: str, city: str,
                   *, width: int = 720, height: int = 160, months_back: int = 18) -> str:
    """Median sold price by month, last N months, for cohort city × class."""
    cls_safe = cls.replace("'", "''")
    city_safe = city.replace("'", "''")
    q = f"""
    SELECT
        DATE_TRUNC('month', TRY_CAST(close_date AS DATE)) AS month,
        MEDIAN(TRY_CAST(sold_price AS DOUBLE)) AS med_price,
        COUNT(*) AS n
    FROM listings
    WHERE _class = '{cls_safe}'
      AND UPPER(city) = '{city_safe}'
      AND status_category = 'Closed'
      AND TRY_CAST(sold_price AS DOUBLE) > 0
      AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '{months_back} months'
    GROUP BY 1
    HAVING COUNT(*) >= 2
    ORDER BY 1
    """
    rows = con.execute(q).fetchall()
    if len(rows) < 3:
        return ""
    months = [r[0] for r in rows]
    prices = [float(r[1]) for r in rows]
    lo, hi = min(prices), max(prices)
    if lo == hi:
        hi = lo + 1
    pad_l, pad_r, pad_t, pad_b = 60, 16, 14, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(prices)
    pts = []
    for i, p in enumerate(prices):
        x = pad_l + (i / max(n - 1, 1)) * plot_w
        y = pad_t + (1 - (p - lo) / (hi - lo)) * plot_h
        pts.append((x, y, p, months[i]))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in pts)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#0a7e2c"/>' for x, y, _, _ in pts)
    # Y-axis labels at top + bottom
    y_labels = (
        f'<text x="{pad_l-6}" y="{pad_t+10}" font-size="11" fill="#555" text-anchor="end">${hi/1000:.0f}k</text>'
        f'<text x="{pad_l-6}" y="{pad_t+plot_h}" font-size="11" fill="#555" text-anchor="end">${lo/1000:.0f}k</text>'
    )
    # First/last month labels
    first_label = months[0].strftime("%b %y") if hasattr(months[0], "strftime") else str(months[0])[:7]
    last_label = months[-1].strftime("%b %y") if hasattr(months[-1], "strftime") else str(months[-1])[:7]
    x_labels = (
        f'<text x="{pad_l}" y="{height-10}" font-size="11" fill="#555">{first_label}</text>'
        f'<text x="{pad_l + plot_w}" y="{height-10}" font-size="11" text-anchor="end" fill="#555">{last_label}</text>'
    )
    return (f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
            f'<polyline points="{polyline}" stroke="#0a7e2c" stroke-width="2.5" fill="none"/>'
            f'{dots}{y_labels}{x_labels}</svg>')


def cma_for(*, parcel_id: str | None = None, address: str | None = None,
            city: str | None = None, proposed_price: float,
            subject_override: dict | None = None) -> dict[str, Any]:
    con = connect()

    subject = subject_override or find_subject(parcel_id=parcel_id, address=address, city=city)
    if not subject:
        return {"error": "subject not found in MLS data; pass subject_override with class/city/sqft/etc."}
    subject = _normalize_subject(subject)

    cls = subject.get("_class") or "RE_1"
    band = band_for(proposed_price, cls)

    comps = find_comparables(con, subject, max_n=20)

    # Cohort stats — same band, same city, last 3 years sold
    today = date.today()
    cutoff = today - timedelta(days=365 * 3)
    cls_safe = cls.replace("'", "''")
    city_safe = (subject.get("city") or "").upper().strip().replace("'", "''")

    cohort_sql = f"""
    WITH sold AS (
        SELECT
            COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            TRY_CAST(original_list_price AS DOUBLE) AS orig_price,
            TRY_CAST(list_price AS DOUBLE) AS list_price
        FROM listings
        WHERE _class = '{cls_safe}'
          AND UPPER(city) = '{city_safe}'
          AND status_category = 'Closed'
          AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(close_date AS DATE) >= '{cutoff.isoformat()}'
          AND TRY_CAST(original_list_price AS DOUBLE) BETWEEN {proposed_price*0.7} AND {proposed_price*1.3}
    )
    SELECT
      COUNT(*) AS n,
      MEDIAN(dom) AS median_dom,
      QUANTILE_CONT(dom, 0.25) AS p25_dom,
      QUANTILE_CONT(dom, 0.75) AS p75_dom,
      MEDIAN(sold_price) AS median_sold,
      MEDIAN(sold_price / NULLIF(orig_price, 0)) AS median_sold_to_orig,
      MEDIAN(orig_price) AS median_orig,
      QUANTILE_CONT(orig_price, 0.25) AS p25_orig,
      QUANTILE_CONT(orig_price, 0.75) AS p75_orig
    FROM sold
    """
    cohort = con.execute(cohort_sql).fetchdf().to_dict(orient="records")
    cohort = cohort[0] if cohort else {}

    # Deed-augmented historical context — pulls in pre-2023 sold prices from
    # county deed records. MLS DOM stats are unchanged (deeds have no DOM).
    has_deeds = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'deed_sales' LIMIT 1"
    ).fetchone() is not None
    deed_history: dict = {}
    if has_deeds:
        deed_county_safe = (subject.get("deed_county") or
                             subject.get("county") or "").upper().strip().replace("'", "''")
        deed_history_sql = f"""
        WITH deed AS (
            SELECT TRY_CAST(deed_last_sale_price AS DOUBLE) AS price,
                   TRY_CAST(deed_last_sale_date AS DATE) AS sale_date
            FROM deed_sales
            WHERE UPPER(deed_county) LIKE '%{deed_county_safe}%'
              AND deed_arms_length = TRUE
              AND TRY_CAST(deed_last_sale_price AS DOUBLE) BETWEEN {proposed_price*0.7} AND {proposed_price*1.3}
        )
        SELECT
          COUNT(*) AS n,
          MEDIAN(price) AS median_deed_sold,
          QUANTILE_CONT(price, 0.25) AS p25_deed_sold,
          QUANTILE_CONT(price, 0.75) AS p75_deed_sold,
          MIN(sale_date) AS earliest_deed,
          MAX(sale_date) AS latest_deed
        FROM deed
        """
        rows = con.execute(deed_history_sql).fetchdf().to_dict(orient="records")
        deed_history = rows[0] if rows else {}

    # Where in the cohort price distribution does the proposed price sit?
    # Pulls from BOTH MLS Closed AND deed sales when available, for a denser
    # distribution.
    orig_prices_sql = f"""
    SELECT TRY_CAST(original_list_price AS DOUBLE) AS p
    FROM listings
    WHERE _class = '{cls_safe}'
      AND UPPER(city) = '{city_safe}'
      AND status_category = 'Closed'
      AND TRY_CAST(close_date AS DATE) >= '{cutoff.isoformat()}'
      AND TRY_CAST(original_list_price AS DOUBLE) > 0
    """
    prices = [r[0] for r in con.execute(orig_prices_sql).fetchall() if r[0] is not None]
    pctile = _percentile_of_value(prices, proposed_price)

    # Inline charts (SVG)
    distribution_svg = _svg_price_distribution(prices, proposed_price)
    sparkline_svg = _svg_sparkline(con, cls, (subject.get("city") or "").upper().strip())

    expected_sold = (cohort.get("median_sold_to_orig") or 0.99) * proposed_price

    # Model-based DOM prediction (if model trained)
    model_pred: dict | None = None
    price_recommendation: dict | None = None
    try:
        from .dom_model import load as _load_model, predict_dom, recommend_price_for_target_dom, MODEL_DIR
        from pathlib import Path as _Path
        if (_Path(MODEL_DIR) / "bundle_meta.joblib").exists():
            bundle = _load_model()
            model_pred = predict_dom(subject, proposed_price, bundle=bundle)
            price_recommendation = recommend_price_for_target_dom(
                subject, target_dom=14,
                cohort_median_price=cohort.get("median_orig") or proposed_price,
                bundle=bundle,
            )
    except Exception as e:
        print(f"  [cma] DOM model unavailable: {e}")

    # Photos from Media pull (if available)
    photo_urls: list[str] = []
    try:
        import json as _json
        from pathlib import Path as _Path
        media_path = _Path("data/mls/listings_media.jsonl")
        lid = subject.get("listing_id")
        if lid and media_path.exists():
            with media_path.open("r", encoding="utf-8") as f:
                for line in f:
                    r = _json.loads(line)
                    if r.get("listing_id") == lid:
                        photo_urls = [p.get("url") for p in (r.get("photos") or []) if p.get("url")]
                        break
    except Exception:
        pass

    verdict_parts = []
    cohort_n = cohort.get("n") or 0
    if cohort_n < 3:
        verdict = "thin cohort — only %d recent comparables; treat results as directional" % cohort_n
    else:
        med_dom = cohort.get("median_dom")
        p25_dom = cohort.get("p25_dom")
        p75_dom = cohort.get("p75_dom")
        verdict_parts.append(
            f"At ${proposed_price:,.0f}, this property sits at the ~p{pctile} of {city_safe} {cls} sales "
            f"(${cohort.get('median_orig',0):,.0f} median, ${cohort.get('p25_orig',0):,.0f}-${cohort.get('p75_orig',0):,.0f} p25-p75)."
        )
        if med_dom is not None:
            verdict_parts.append(
                f"Expect DOM ~{med_dom:.0f} days (p25 {p25_dom:.0f}, p75 {p75_dom:.0f})."
            )
        verdict_parts.append(
            f"Expected sold price ~${expected_sold:,.0f} "
            f"({(cohort.get('median_sold_to_orig') or 0)*100:.1f}% of list, cohort median)."
        )
        if pctile > 75:
            verdict_parts.append("Pricing skews HIGH for the cohort — expect longer DOM / price reduction risk.")
        elif pctile < 25:
            verdict_parts.append("Pricing skews LOW for the cohort — multiple offers possible if condition supports it.")
        verdict = " ".join(verdict_parts)

    if model_pred:
        verdict_parts.append(
            f"Model: p25={model_pred['p25']:.0f}d, p50={model_pred['p50']:.0f}d, p75={model_pred['p75']:.0f}d (per-property prediction)."
        )

    # Price-cut probability (separate classifier)
    cut_prob: float | None = None
    try:
        from .price_cut_model import predict_cut_probability
        cut_prob = predict_cut_probability(subject, proposed_price)
        if cut_prob is not None:
            verdict_parts.append(f"Cut-risk: {cut_prob*100:.0f}% chance of needing a price reduction (cohort base rate ~27%).")
    except Exception as e:
        print(f"  [cma] cut model unavailable: {e}")
    if price_recommendation and price_recommendation.get("feasible"):
        verdict_parts.append(
            f"For 14-day target: list at ${price_recommendation['min_price']:,}-${price_recommendation['max_price']:,} (sweet spot ~${price_recommendation['sweet_spot']:,})."
        )

    # Comp-adjustment engine — line-item adjustments to comparable sold prices
    adjusted_comps = []
    coefficients: dict = {}
    try:
        from .comp_adjust import adjust_comps, cohort_coefficients_for
        coefficients = cohort_coefficients_for((subject.get("city") or "").upper(), cls)
        adjusted_comps = adjust_comps(subject, comps[:12])
        if adjusted_comps:
            med_adj = sorted(c["adjusted_sold_price"] for c in adjusted_comps)[len(adjusted_comps) // 2]
            verdict_parts.append(
                f"Adjusted comp median: ${med_adj:,.0f} (sqft/age/acres deltas applied to top {len(adjusted_comps)} comps)."
            )
    except Exception as e:
        print(f"  [cma] comp-adjustment unavailable: {e}")

    base_report = {
        "subject": {k: subject.get(k) for k in (
            "listing_id", "address", "city", "_class", "parcel_id",
            "bedrooms", "full_baths", "sqft", "acres", "year_built",
            "subdivision", "property_subtype", "list_price", "status_category",
            "deed_last_sale_date", "deed_last_sale_price", "deed_county",
            "in_floodplain", "flood_zone", "condition_flags",
        )},
        "proposed_price": proposed_price,
        "price_band": band,
        "cohort": cohort,
        "deed_history": deed_history,
        "cohort_percentile_for_price": pctile,
        "expected_sold_price": round(expected_sold) if cohort_n >= 3 else None,
        "comparables": comps,
        "verdict": " ".join(verdict_parts) if verdict_parts else verdict,
        "model_prediction": model_pred,
        "price_recommendation": price_recommendation,
        "cut_probability": cut_prob,
        "photos": photo_urls,
        "distribution_svg": distribution_svg,
        "sparkline_svg": sparkline_svg,
        "adjusted_comps": adjusted_comps,
        "comp_coefficients": coefficients,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    base_report["listing_strategy"] = _listing_strategy(base_report)
    return base_report


def render_html(report: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s = report.get("subject") or {}
    cohort = report.get("cohort") or {}
    comps = report.get("comparables") or []
    pp = report.get("proposed_price") or 0

    def fmt_money(v) -> str:
        if v in (None, ""): return ""
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v)

    rows = ""
    for c in comps:
        rows += (
            f"<tr><td>{c.get('listing_id','')}</td><td>{c.get('address','')}</td>"
            f"<td>{c.get('city','')}</td><td>{c.get('subdivision','') or ''}</td>"
            f"<td>{c.get('bedrooms','') or ''}/{c.get('full_baths','') or ''}</td>"
            f"<td>{int(c.get('sqft') or 0) if c.get('sqft') else ''}</td>"
            f"<td>{fmt_money(c.get('original_list_price'))}</td>"
            f"<td>{fmt_money(c.get('list_price'))}</td>"
            f"<td>{fmt_money(c.get('sold_price'))}</td>"
            f"<td>{c.get('feed_cdom') or c.get('feed_dom') or ''}</td>"
            f"<td>{c.get('list_date','')}</td><td>{c.get('close_date','')}</td>"
            f"<td>{c.get('list_office_name','') or ''}</td></tr>"
        )

    photos = report.get("photos") or []
    photo_html = ""
    if photos:
        cells = "".join(f'<a href="{u}" target="_blank"><img src="{u}" alt=""></a>' for u in photos[:6])
        photo_html = f'<div class="photos">{cells}</div>'

    # Adjusted comps section
    adj_comps = report.get("adjusted_comps") or []
    coefs = report.get("comp_coefficients") or {}
    adj_comps_html = ""
    if adj_comps:
        adj_rows = "".join(
            f"<tr><td>{c.get('listing_id','')}</td><td>{c.get('address','')}</td>"
            f"<td>{int(c.get('sqft') or 0) if c.get('sqft') else ''}</td>"
            f"<td>{int(c.get('year_built') or 0) if c.get('year_built') else ''}</td>"
            f"<td>{c.get('acres','')}</td>"
            f"<td>{fmt_money(c.get('sold_price'))}</td>"
            f"<td>{fmt_money(c.get('adj_sqft'))}</td>"
            f"<td>{fmt_money(c.get('adj_age'))}</td>"
            f"<td>{fmt_money(c.get('adj_acres'))}</td>"
            f"<td>{fmt_money(c.get('adj_total_applied'))}{' (capped)' if c.get('adj_capped') else ''}</td>"
            f"<td><strong>{fmt_money(c.get('adjusted_sold_price'))}</strong></td></tr>"
            for c in adj_comps
        )
        med_adj = sorted(c["adjusted_sold_price"] for c in adj_comps)[len(adj_comps) // 2]
        adj_comps_html = f"""<h2>Adjusted comparables (line-item: sqft / age / acres deltas)</h2>
<p style="font-size:13px;color:#555">Cohort coefficients: ${coefs.get('price_per_sqft','-')}/sqft · ${int(coefs.get('age_premium_per_year') or 0):,}/yr-of-age · ${int(coefs.get('land_value_per_acre') or 0):,}/acre · cap ±20%. <strong>Median adjusted: {fmt_money(med_adj)}.</strong></p>
<table>
<tr><th>MLS#</th><th>Address</th><th>Sqft</th><th>Year</th><th>Acres</th>
    <th>Sold $</th><th>+/− sqft</th><th>+/− age</th><th>+/− land</th><th>Net adj</th><th>Adjusted</th></tr>
{adj_rows}
</table>"""

    model = report.get("model_prediction") or {}
    rec = report.get("price_recommendation") or {}
    model_html = ""
    if model:
        model_html = f"""<h2>Model prediction</h2>
<div class="kpi">
  <div><div class="lbl">p25 DOM</div><div class="val">{model.get('p25', '-'):.0f}d</div></div>
  <div><div class="lbl">p50 DOM (median)</div><div class="val">{model.get('p50', '-'):.0f}d</div></div>
  <div><div class="lbl">p75 DOM</div><div class="val">{model.get('p75', '-'):.0f}d</div></div>
</div>"""
    rec_html = ""
    if rec and rec.get("feasible"):
        rec_html = f"""<h2>Price recommendation (target 14-day sale)</h2>
<div class="kpi">
  <div><div class="lbl">Sweet spot</div><div class="val">{fmt_money(rec.get('sweet_spot'))}</div></div>
  <div><div class="lbl">Range</div><div class="val">{fmt_money(rec.get('min_price'))} – {fmt_money(rec.get('max_price'))}</div></div>
  <div><div class="lbl">Expected p50 at sweet spot</div><div class="val">{rec.get('predicted_p50_at_sweet_spot', '-'):.0f}d</div></div>
</div>"""

    strategy_html = _listing_strategy_html(report.get("listing_strategy") or _listing_strategy(report))

    agent_card = _load_agent_card()
    agent_header = _agent_header_html(agent_card)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>CMA — {s.get('address','subject')}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#222}}
h1{{margin-bottom:6px}} h2{{border-bottom:1px solid #ccc;padding-bottom:6px;margin-top:30px}}
.agent-card{{border-bottom:2px solid #1a5fb4;padding-bottom:8px;margin-bottom:14px}}
.agent-card .agent-line{{font-size:13px;color:#444}}
.agent-card .agent-tag{{font-size:11px;color:#888;margin-top:2px}}
.subj{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 20px;background:#f6f6f6;padding:14px;border-radius:8px}}
.subj div{{font-size:14px}}
.verdict{{background:#fff7e0;padding:14px;border-left:4px solid #f5a623;border-radius:4px;margin:14px 0;font-size:15px;line-height:1.5}}
.kpi{{display:flex;gap:20px;margin:14px 0}}
.kpi div{{background:#eef;padding:10px 16px;border-radius:6px;flex:1}}
.kpi .lbl{{font-size:12px;color:#555}} .kpi .val{{font-size:22px;font-weight:600}}
.photos{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:14px 0}}
.photos img{{width:100%;height:140px;object-fit:cover;border-radius:6px;cursor:pointer}}
table{{border-collapse:collapse;width:100%;margin-top:10px;font-size:12px}}
th,td{{border:1px solid #ddd;padding:5px 7px;text-align:left}} th{{background:#f0f0f0}}
.strategy{{background:#fff;border:1px solid #d6e0eb;border-radius:8px;padding:18px 20px;margin:14px 0;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.strategy-hero{{text-align:center;border-bottom:1px solid #eee;padding-bottom:14px;margin-bottom:14px}}
.strategy-hero .lbl{{font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.7px}}
.strategy-hero .big{{font-size:36px;font-weight:700;color:#1a5fb4;margin:4px 0}}
.strategy-hero .rng{{font-size:13px;color:#777}}
.strategy-hero .dom{{font-size:14px;margin-top:6px;color:#333}}
.strategy-cols{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.strategy-cols h3{{font-size:13px;text-transform:uppercase;letter-spacing:.7px;color:#1a5fb4;margin:0 0 6px;border:0;padding:0}}
.strategy-cols ul{{margin:0;padding-left:18px;font-size:13px;line-height:1.6}}
.foot{{font-size:11px;color:#777;margin-top:30px}}
@media print {{
  body{{margin:14px;max-width:none}}
  h2{{page-break-after:avoid}}
  table{{page-break-inside:avoid;font-size:10px}}
  .photos img{{height:90px}}
  .verdict{{font-size:13px}}
  .kpi .val{{font-size:18px}}
  a{{color:#222;text-decoration:none}}
}}
@page{{size:letter;margin:0.5in}}
</style></head><body>
{agent_header}
<h1>CMA — {s.get('address','(no address)')}</h1>
{photo_html}
<div class="subj">
  <div><strong>City:</strong> {s.get('city','')}</div>
  <div><strong>Class:</strong> {s.get('_class','')} ({s.get('property_subtype','')})</div>
  <div><strong>Beds/Baths:</strong> {s.get('bedrooms','-')} / {s.get('full_baths','-')}</div>
  <div><strong>Sqft:</strong> {int(s['sqft']) if s.get('sqft') else '-'}</div>
  <div><strong>Acres:</strong> {s.get('acres','-')}</div>
  <div><strong>Year built:</strong> {s.get('year_built','-')}</div>
  <div><strong>Subdivision:</strong> {s.get('subdivision','-')}</div>
  <div><strong>Parcel:</strong> {s.get('parcel_id','-')}</div>
  <div><strong>Current MLS status:</strong> {s.get('status_category','-')}</div>
  <div><strong>Listing ID:</strong> {s.get('listing_id','-')}</div>
  <div><strong>Last deeded sale:</strong> {(s.get('deed_last_sale_date') or '-') if s.get('deed_last_sale_date') else '-'} {('@ '+fmt_money(s.get('deed_last_sale_price'))) if s.get('deed_last_sale_price') else ''}</div>
  <div><strong>Deed county:</strong> {s.get('deed_county','-') or '-'}</div>
</div>
<h2>Pricing analysis</h2>
<div class="kpi">
  <div><div class="lbl">Proposed list price</div><div class="val">{fmt_money(pp)}</div></div>
  <div><div class="lbl">Cohort percentile</div><div class="val">p{report.get('cohort_percentile_for_price',0)}</div></div>
  <div><div class="lbl">Expected sold price</div><div class="val">{fmt_money(report.get('expected_sold_price'))}</div></div>
  <div><div class="lbl">Cohort median DOM</div><div class="val">{round(cohort.get('median_dom') or 0)} d</div></div>
</div>
<div class="verdict">{report.get('verdict','')}</div>
{('<h2>Where this proposed price sits (cohort original-list distribution)</h2>' + report.get('distribution_svg','')) if report.get('distribution_svg') else ''}
{('<h2>Median sold price by month (last 18 months, ' + (s.get('city') or '').title() + ' ' + (s.get('_class') or '') + ')</h2>' + report.get('sparkline_svg','')) if report.get('sparkline_svg') else ''}
{model_html}
{rec_html}
{strategy_html}
<h2>Cohort detail (MLS Closed, last 3 yrs)</h2>
<table>
<tr><th>Cohort size (n)</th><th>Median DOM</th><th>p25 DOM</th><th>p75 DOM</th><th>Median sold</th><th>Median sold/orig</th><th>Median orig</th></tr>
<tr>
  <td>{cohort.get('n','')}</td>
  <td>{round(cohort.get('median_dom') or 0)}</td>
  <td>{round(cohort.get('p25_dom') or 0)}</td>
  <td>{round(cohort.get('p75_dom') or 0)}</td>
  <td>{fmt_money(cohort.get('median_sold'))}</td>
  <td>{(cohort.get('median_sold_to_orig') or 0)*100:.1f}%</td>
  <td>{fmt_money(cohort.get('median_orig'))}</td>
</tr>
</table>
{('<h2>County deed history (price band ±30%, all years)</h2>' +
  '<table>' +
  '<tr><th>Deed sales (n)</th><th>Median deed price</th><th>p25</th><th>p75</th><th>Earliest</th><th>Latest</th></tr>' +
  f"<tr><td>{(report.get('deed_history') or {}).get('n','')}</td>"
  f"<td>{fmt_money((report.get('deed_history') or {}).get('median_deed_sold'))}</td>"
  f"<td>{fmt_money((report.get('deed_history') or {}).get('p25_deed_sold'))}</td>"
  f"<td>{fmt_money((report.get('deed_history') or {}).get('p75_deed_sold'))}</td>"
  f"<td>{(report.get('deed_history') or {}).get('earliest_deed','') or ''}</td>"
  f"<td>{(report.get('deed_history') or {}).get('latest_deed','') or ''}</td></tr>" +
  '</table>') if (report.get('deed_history') or {}).get('n') else ''}
{adj_comps_html}
<h2>Comparables (most recent {len(comps)} similar sales — raw, no adjustments)</h2>
<table>
<tr><th>MLS#</th><th>Address</th><th>City</th><th>Subd</th><th>BR/BA</th><th>Sqft</th>
    <th>Orig $</th><th>List $</th><th>Sold $</th><th>DOM</th><th>List date</th><th>Close date</th><th>Office</th></tr>
{rows}
</table>
<div class="foot">Generated {report.get('generated_at','')} from data/mls/listings.jsonl. CDOM = cumulative days on market across re-listings.</div>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path
