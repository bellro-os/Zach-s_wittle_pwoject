"""Per-property history page — every listing + deed sale for one parcel.

Given a parcel_id (or address), produce a single-page HTML showing:
  - Subject property identifiers
  - All MLS listings ever observed (status, prices, DOM, agents)
  - All deed sales (date, price, deed type when available)
  - Owner-occupancy + manufactured/distressed flags
  - Flood + commute + condition signals (when enriched)
  - Quick CMA link generator footer

Useful when researching a specific property — combines everything we know
about it into one scrollable page.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .db import connect


HISTORY_DIR = Path("outputs/mls_analytics/property_history")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "x"


def _fmt_money(v) -> str:
    if v in (None, "", "None"): return ""
    try: return f"${float(v):,.0f}"
    except (TypeError, ValueError): return str(v)


def render_property_history(
    *, parcel_id: str | None = None, address: str | None = None,
    out_dir: Path = HISTORY_DIR,
) -> Path | None:
    if not (parcel_id or address):
        return None
    con = connect()

    if parcel_id:
        where = f"parcel_id = '{parcel_id.replace(chr(39), chr(39)*2)}'"
    else:
        where = f"UPPER(address) LIKE '%{address.upper().replace(chr(39), chr(39)*2)}%'"

    listings = con.execute(f"""
        SELECT listing_id, status_category, address, city, _class, parcel_id,
               bedrooms, full_baths, half_baths, sqft, year_built, acres,
               original_list_price, list_price, sold_price,
               COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
               list_date, status_changed_at, close_date, off_market_date,
               subdivision, zoning, list_office_name, list_agent,
               public_remarks,
               in_floodplain, flood_zone, condition_score, condition_flags,
               is_manufactured, is_distressed,
               drive_min_vt, drive_min_carilion, drive_min_christiansburg,
               parcel_owner1, parcel_owner_occupied, parcel_assessed_total,
               deed_last_sale_date, deed_last_sale_price, deed_county
        FROM listings
        WHERE {where}
        ORDER BY list_date DESC NULLS LAST
    """).fetchall()
    if not listings:
        print(f"  no listings for {parcel_id or address}")
        return None

    # Subject info from the most recent listing
    subj = listings[0]
    (lid, status, addr, city, cls, pid, br, fb, hb, sf, yb, ac,
     op, lp, sp, dom, ld, sct, cd, omd, sd, zo, off, agent,
     remarks, in_fp, fz, cs, cflags, ism, isd, dvt, dcar, dcb,
     po, ooc, pat, ddate, dprice, dcounty) = subj

    # Build listing history rows
    listing_rows = []
    for row in listings:
        lid_ = row[0]; st = row[1]
        op_ = row[12]; lp_ = row[13]; sp_ = row[14]; dom_ = row[15]
        ld_ = row[16]; cd_ = row[18]; omd_ = row[19]
        off_ = row[22]
        listing_rows.append(
            f"<tr><td>{lid_}</td><td>{st}</td>"
            f"<td>{str(ld_)[:10] if ld_ else ''}</td>"
            f"<td>{str(omd_ or cd_)[:10] if (omd_ or cd_) else ''}</td>"
            f"<td>{_fmt_money(op_)}</td>"
            f"<td>{_fmt_money(lp_)}</td>"
            f"<td>{_fmt_money(sp_)}</td>"
            f"<td>{dom_ or '-'}d</td>"
            f"<td>{(off_ or '-')[:30]}</td></tr>"
        )

    # Deed sale chain — pull standalone deed_sales for this parcel too
    deed_chain = []
    if pid:
        try:
            ds = con.execute(f"""
                SELECT deed_last_sale_date, deed_last_sale_price, deed_county,
                       deed_arms_length, owner1
                FROM deed_sales
                WHERE parcel_id = '{pid.replace(chr(39), chr(39)*2)}'
                ORDER BY deed_last_sale_date DESC
            """).fetchall()
            deed_chain = ds
        except Exception:
            deed_chain = []

    deed_rows = []
    if ddate or dprice:
        deed_rows.append(
            f"<tr><td>{str(ddate)[:10] if ddate else ''}</td>"
            f"<td>{_fmt_money(dprice)}</td><td>{po or ''}</td>"
            f"<td>{dcounty or ''}</td><td>(from MLS join)</td></tr>"
        )
    for d in deed_chain:
        d_date, d_price, d_county, d_al, d_owner = d
        if ddate and str(d_date)[:10] == str(ddate)[:10]:
            continue  # already captured above
        deed_rows.append(
            f"<tr><td>{str(d_date)[:10] if d_date else ''}</td>"
            f"<td>{_fmt_money(d_price)}</td><td>{d_owner or ''}</td>"
            f"<td>{d_county or ''}</td>"
            f"<td>{'arms-length' if d_al else 'gift / non-arms'}</td></tr>"
        )

    deed_html = "".join(deed_rows) or "<tr><td colspan=5>(no deed records on file)</td></tr>"
    listing_html = "".join(listing_rows) or "<tr><td colspan=9>(no listings)</td></tr>"

    # Flag list
    flags = []
    if ism: flags.append('<span class="flag manuf">Manufactured</span>')
    if isd: flags.append('<span class="flag distress">Distressed listing</span>')
    if in_fp: flags.append(f'<span class="flag flood">Flood zone {fz or ""}</span>')
    if ooc is False: flags.append('<span class="flag invest">Absentee/investor-owned</span>')
    if ooc is True: flags.append('<span class="flag oo">Owner-occupied</span>')
    if cs and cs >= 4: flags.append(f'<span class="flag good">Renovated (cond {cs})</span>')
    if cs is not None and cs <= 1.5: flags.append(f'<span class="flag bad">Needs work (cond {cs})</span>')
    flags_html = " ".join(flags) or "<span class='meta'>(none)</span>"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(city)}__{_slug(addr or pid or 'subject')}__{_slug(pid or 'x')}.html"

    today = datetime.now().strftime("%Y-%m-%d")
    html = f"""<!doctype html>
<html><head><meta charset=utf-8><title>Property history — {addr}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#222}}
h1{{margin-bottom:6px}} h2{{border-bottom:1px solid #ccc;padding-bottom:6px;margin-top:30px;font-size:16px}}
.subj{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 20px;background:#f6f6f6;padding:14px;border-radius:8px}}
.subj div{{font-size:14px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:6px}}
th,td{{border-bottom:1px solid #eee;padding:5px 7px;text-align:left}}
th{{background:#fafafa;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
.flag{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;margin-right:5px}}
.flag.manuf{{background:#eef;color:#229}}
.flag.distress{{background:#fdd;color:#900}}
.flag.flood{{background:#cef;color:#06a}}
.flag.invest{{background:#fed;color:#a40}}
.flag.oo{{background:#dfd;color:#070}}
.flag.good{{background:#cfc;color:#070}}
.flag.bad{{background:#fcc;color:#900}}
.meta{{color:#888;font-size:12px}}
.cma-link{{background:#1a5fb4;color:#fff;padding:8px 14px;border-radius:5px;display:inline-block;margin-top:14px;font-size:13px}}
.cma-link a{{color:#fff;text-decoration:none}}
</style></head><body>
<h1>{addr}</h1>
<p class="meta">{city}, VA · parcel {pid or '?'} · property history report · {today}</p>
<div>{flags_html}</div>

<div class="subj" style="margin-top:14px">
  <div><strong>Beds/Baths:</strong> {br or '-'} / {fb or '-'}{f' + {hb}h' if hb else ''}</div>
  <div><strong>Sqft:</strong> {int(sf or 0) if sf else '-'}</div>
  <div><strong>Year built:</strong> {yb or '-'}</div>
  <div><strong>Acres:</strong> {ac or '-'}</div>
  <div><strong>Class:</strong> {cls or '-'}</div>
  <div><strong>Subdivision:</strong> {sd or '-'}</div>
  <div><strong>Zoning:</strong> {zo or '-'}</div>
  <div><strong>Current parcel owner:</strong> {po or '-'}</div>
  <div><strong>Assessed:</strong> {_fmt_money(pat)}</div>
  <div><strong>Condition score:</strong> {cs if cs is not None else '-'} / 5</div>
  <div><strong>Drive to VT:</strong> {dvt or '-'}m</div>
  <div><strong>Drive to Carilion:</strong> {dcar or '-'}m</div>
  <div><strong>Drive to Christiansburg:</strong> {dcb or '-'}m</div>
  <div><strong>Flood zone:</strong> {fz or '(none)'}</div>
</div>

<h2>Listing history ({len(listings)} record{'s' if len(listings) != 1 else ''})</h2>
<table>
<tr><th>MLS#</th><th>Status</th><th>Listed</th><th>Off-mkt/closed</th>
    <th>Original $</th><th>Final list $</th><th>Sold $</th><th>DOM</th><th>Office</th></tr>
{listing_html}
</table>

<h2>Deed history ({len(deed_rows) if deed_rows and not (len(deed_rows)==1 and 'no deed' in deed_rows[0]) else 0} sale{'s' if (len(deed_rows) > 1) else ''})</h2>
<table>
<tr><th>Date</th><th>Price</th><th>Owner / Grantee</th><th>County</th><th>Notes</th></tr>
{deed_html}
</table>

{f'<h2>Public remarks (most recent listing)</h2><p style="background:#f9f9f4;padding:12px;border-radius:5px;font-size:13px">{remarks[:1500]}{"..." if len(remarks or "") > 1500 else ""}</p>' if remarks else ''}

<div class="cma-link">
  <a href="../cma_5491_mccoy_v8.html">Generate fresh CMA →</a> (run: python tasks.py cma --address "{addr}" --price &lt;your_price&gt;)
</div>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_top_properties(min_listings: int = 2, max_n: int = 200) -> int:
    """Render history pages for parcels with >= min_listings (interesting cases:
    flips, expired-then-relisted, multi-listing investors)."""
    con = connect()
    rows = con.execute(f"""
        SELECT parcel_id, MAX(address) AS addr, MAX(city) AS city, COUNT(*) AS n
        FROM listings
        WHERE parcel_id IS NOT NULL AND parcel_id != ''
        GROUP BY parcel_id
        HAVING COUNT(*) >= {min_listings}
        ORDER BY n DESC LIMIT {max_n}
    """).fetchall()
    written = 0
    for pid, addr, city, n in rows:
        path = render_property_history(parcel_id=pid)
        if path:
            written += 1
    return written
