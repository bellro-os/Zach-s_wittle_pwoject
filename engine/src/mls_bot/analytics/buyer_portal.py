"""Single-page buyer-search HTML portal.

Embeds the full Active+Pending listings dataset (~1,200 rows) into a static
HTML file with interactive client-side filtering. No web server required —
double-click to open in any browser, share via email or Dropbox.

Filters:
  - city (multi-select)
  - price min/max
  - bedrooms min
  - sqft min/max
  - acres min
  - status
  - flood-zone exclusion
  - manufactured-home exclusion
  - condition score min
  - drive-time max to selected hub
  - text search across address / subdivision / public_remarks

Output: outputs/mls_analytics/buyer_portal.html
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .db import connect


PORTAL_PATH = Path("outputs/mls_analytics/buyer_portal.html")


def build_portal(out_path: Path = PORTAL_PATH) -> Path:
    con = connect()
    rows = con.execute("""
        SELECT
            listing_id, mls_number, _class,
            UPPER(TRIM(city)) AS city,
            address, subdivision, zoning,
            TRY_CAST(list_price AS DOUBLE) AS list_price,
            TRY_CAST(original_list_price AS DOUBLE) AS original_price,
            TRY_CAST(bedrooms AS INT) AS bedrooms,
            TRY_CAST(full_baths AS INT) AS full_baths,
            TRY_CAST(half_baths AS INT) AS half_baths,
            TRY_CAST(sqft AS DOUBLE) AS sqft,
            TRY_CAST(acres AS DOUBLE) AS acres,
            TRY_CAST(year_built AS INT) AS year_built,
            property_subtype,
            list_office_name,
            TRY_CAST(list_date AS DATE) AS list_date,
            status_category,
            TRY_CAST(latitude AS DOUBLE) AS lat,
            TRY_CAST(longitude AS DOUBLE) AS lng,
            in_floodplain, flood_zone,
            condition_score, is_manufactured, is_distressed,
            drive_min_vt, drive_min_carilion, drive_min_christiansburg,
            drive_min_radford,
            parcel_owner_occupied,
            public_remarks
        FROM listings
        WHERE _class IN ('RE_1','LD_3','MF_2','RN_6')
          AND status_category IN ('Active','Pending')
          AND TRY_CAST(list_price AS DOUBLE) > 0
        ORDER BY list_date DESC NULLS LAST
    """).fetchall()

    # Convert to JSON-friendly list of dicts
    cols = [
        "lid","mls","cls","city","addr","subd","zone","price","orig","br","fb","hb",
        "sqft","acres","yb","subtype","office","ld","status","lat","lng",
        "flood","fz","cond","manuf","distress","vt","car","cb","rad","oo","rem",
    ]
    data = []
    for row in rows:
        d = {}
        for i, k in enumerate(cols):
            v = row[i]
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            d[k] = v
        # Trim public_remarks for embed size
        if d.get("rem"):
            d["rem"] = (d["rem"] or "")[:200]
        data.append(d)

    cities = sorted({d["city"] for d in data if d.get("city")})

    today = datetime.now().strftime("%Y-%m-%d %H:%M")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html>
<html><head><meta charset=utf-8><title>NRV buyer search</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;margin:0;padding:0;background:#fafafa;color:#222}}
header{{background:#1a5fb4;color:#fff;padding:20px 30px}}
header h1{{margin:0;font-size:20px}} header .meta{{font-size:12px;opacity:.85}}
.layout{{display:grid;grid-template-columns:280px 1fr;gap:20px;padding:20px 30px}}
aside{{background:#fff;padding:18px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.06);height:fit-content;position:sticky;top:20px}}
aside h3{{font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#888;margin:18px 0 6px;border-top:1px solid #eee;padding-top:14px}}
aside h3:first-child{{border-top:none;padding-top:0;margin-top:0}}
aside label{{font-size:12px;color:#555;display:block;margin-top:8px}}
aside input,aside select{{width:100%;padding:6px 8px;font-size:13px;border:1px solid #ccc;border-radius:4px;margin-top:2px}}
aside .row{{display:flex;gap:6px}}
aside .row input{{width:100%}}
aside .check{{display:flex;align-items:center;gap:6px;font-size:12px;color:#333;margin:6px 0}}
aside button{{width:100%;background:#1a5fb4;color:#fff;border:none;padding:8px;border-radius:4px;font-size:13px;cursor:pointer;margin-top:14px}}
main{{min-height:80vh}}
.summary{{font-size:13px;color:#666;margin-bottom:10px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);font-size:12px}}
th,td{{padding:8px 10px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}}
th{{background:#f0f4f8;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#555;cursor:pointer;user-select:none}}
th:hover{{background:#e6edf2}}
tr:hover{{background:#fafbfc}}
.flag{{display:inline-block;font-size:10px;padding:1px 5px;border-radius:3px;margin-left:3px}}
.flag.flood{{background:#cef;color:#06a}}.flag.man{{background:#eef;color:#229}}.flag.dist{{background:#fdd;color:#900}}
</style></head><body>
<header>
  <h1>NRV Buyer Search</h1>
  <div class="meta">{len(data):,} active+pending listings · {len(cities)} cities · refreshed {today}</div>
</header>
<div class="layout">
<aside>
  <h3>Where</h3>
  <label>City</label>
  <select id="city" multiple size="6">
    {"".join(f"<option>{c}</option>" for c in cities)}
  </select>

  <h3>Type & price</h3>
  <label>Class</label>
  <select id="cls">
    <option value="">Any</option>
    <option value="RE_1">Residential</option>
    <option value="LD_3">Land</option>
    <option value="MF_2">Multifamily</option>
    <option value="RN_6">Rental</option>
  </select>
  <label>Status</label>
  <select id="status">
    <option value="">Active+Pending</option>
    <option>Active</option>
    <option>Pending</option>
  </select>
  <label>Price ($)</label>
  <div class="row"><input id="pmin" type="number" placeholder="min"><input id="pmax" type="number" placeholder="max"></div>

  <h3>Beds / size / lot</h3>
  <div class="row"><input id="brmin" type="number" placeholder="min BR"><input id="brmax" type="number" placeholder="max BR"></div>
  <label>Sqft</label>
  <div class="row"><input id="sfmin" type="number" placeholder="min"><input id="sfmax" type="number" placeholder="max"></div>
  <label>Acres min</label>
  <input id="acmin" type="number" step="0.1" placeholder="min">

  <h3>Filters</h3>
  <label class="check"><input id="nofld" type="checkbox"> Exclude flood zone</label>
  <label class="check"><input id="nomanuf" type="checkbox"> Exclude manufactured</label>
  <label class="check"><input id="nodist" type="checkbox"> Exclude distressed</label>
  <label>Min condition score</label>
  <input id="cond" type="number" step="0.1" placeholder="0-5">

  <h3>Commute (max minutes)</h3>
  <label>To VT</label>
  <input id="vtmax" type="number" placeholder="∞">
  <label>To Carilion (Roanoke)</label>
  <input id="carmax" type="number" placeholder="∞">
  <label>To Christiansburg</label>
  <input id="cbmax" type="number" placeholder="∞">

  <h3>Search</h3>
  <input id="q" type="text" placeholder="address, subdivision, remark...">

  <button onclick="apply()">Apply filters</button>
  <button onclick="clearAll()" style="background:#aaa;margin-top:6px">Clear all</button>
</aside>
<main>
  <div class="summary" id="summary"></div>
  <table>
    <thead><tr>
      <th data-sort="addr">Address</th>
      <th data-sort="city">City</th>
      <th data-sort="status">Status</th>
      <th data-sort="price">Price</th>
      <th data-sort="br">BR/BA</th>
      <th data-sort="sqft">Sqft</th>
      <th data-sort="acres">Acres</th>
      <th data-sort="yb">Yr</th>
      <th data-sort="vt">VT min</th>
      <th data-sort="ld">Listed</th>
      <th>Office</th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table>
</main>
</div>
<script>
const DATA = {json.dumps(data, default=str)};
let filtered = DATA.slice();
let sortKey = "ld", sortDir = -1;

function fmt(v) {{ return (v===null||v===undefined||v==="")?"":v; }}
function fmtMoney(v) {{ if (!v) return ""; return "$" + Math.round(v).toLocaleString(); }}

function apply() {{
  const cities = Array.from(document.getElementById("city").selectedOptions).map(o=>o.value);
  const cls = document.getElementById("cls").value;
  const status = document.getElementById("status").value;
  const pmin = +document.getElementById("pmin").value || 0;
  const pmax = +document.getElementById("pmax").value || 1e12;
  const brmin = +document.getElementById("brmin").value || 0;
  const brmax = +document.getElementById("brmax").value || 99;
  const sfmin = +document.getElementById("sfmin").value || 0;
  const sfmax = +document.getElementById("sfmax").value || 1e9;
  const acmin = +document.getElementById("acmin").value || 0;
  const nofld = document.getElementById("nofld").checked;
  const nomanuf = document.getElementById("nomanuf").checked;
  const nodist = document.getElementById("nodist").checked;
  const cond = +document.getElementById("cond").value || 0;
  const vtmax = +document.getElementById("vtmax").value || 1e9;
  const carmax = +document.getElementById("carmax").value || 1e9;
  const cbmax = +document.getElementById("cbmax").value || 1e9;
  const q = (document.getElementById("q").value || "").toLowerCase();

  filtered = DATA.filter(d => {{
    if (cities.length && !cities.includes(d.city)) return false;
    if (cls && d.cls !== cls) return false;
    if (status && d.status !== status) return false;
    if (d.price < pmin || d.price > pmax) return false;
    if ((d.br||0) < brmin || (d.br||99) > brmax) return false;
    if ((d.sqft||0) < sfmin || (d.sqft||1e9) > sfmax) return false;
    if ((d.acres||0) < acmin) return false;
    if (nofld && d.flood) return false;
    if (nomanuf && d.manuf) return false;
    if (nodist && d.distress) return false;
    if (cond && (d.cond||0) < cond) return false;
    if (vtmax && d.vt && d.vt > vtmax) return false;
    if (carmax && d.car && d.car > carmax) return false;
    if (cbmax && d.cb && d.cb > cbmax) return false;
    if (q) {{
      const blob = ((d.addr||"") + " " + (d.subd||"") + " " + (d.rem||"")).toLowerCase();
      if (!blob.includes(q)) return false;
    }}
    return true;
  }});
  render();
}}

function clearAll() {{
  document.querySelectorAll("aside input").forEach(el => {{
    if (el.type === "checkbox") el.checked = false;
    else el.value = "";
  }});
  document.querySelectorAll("aside select").forEach(s => s.selectedIndex = 0);
  apply();
}}

function render() {{
  const sorted = filtered.slice().sort((a, b) => {{
    const av = a[sortKey], bv = b[sortKey];
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
  }});
  const tbody = document.getElementById("rows");
  tbody.innerHTML = sorted.slice(0, 500).map(d => {{
    const flags = [];
    if (d.flood) flags.push('<span class="flag flood">flood</span>');
    if (d.manuf) flags.push('<span class="flag man">manuf</span>');
    if (d.distress) flags.push('<span class="flag dist">distress</span>');
    return `<tr>
      <td><strong>${{fmt(d.addr)}}</strong> ${{flags.join("")}}<br><small style="color:#888">${{fmt(d.subd)||""}}</small></td>
      <td>${{fmt(d.city)}}</td>
      <td>${{fmt(d.status)}}</td>
      <td>${{fmtMoney(d.price)}}</td>
      <td>${{fmt(d.br)}}/${{fmt(d.fb)}}</td>
      <td>${{fmt(d.sqft)}}</td>
      <td>${{fmt(d.acres)}}</td>
      <td>${{fmt(d.yb)}}</td>
      <td>${{d.vt?Math.round(d.vt)+"m":""}}</td>
      <td>${{fmt(d.ld)}}</td>
      <td>${{fmt(d.office)}}</td>
    </tr>`;
  }}).join("");
  document.getElementById("summary").textContent =
    `Showing ${{Math.min(sorted.length, 500)}} of ${{sorted.length}} matches (sorted by ${{sortKey}}, ${{sortDir>0?"asc":"desc"}})`;
}}

document.querySelectorAll("th[data-sort]").forEach(th => {{
  th.addEventListener("click", () => {{
    const k = th.dataset.sort;
    if (sortKey === k) sortDir = -sortDir;
    else {{ sortKey = k; sortDir = 1; }}
    render();
  }});
}});

apply();
</script>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path
