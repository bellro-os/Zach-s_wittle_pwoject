"""Generate Gravity-branded 2-page inventory brief for 4-5BR Floyd+Montgomery homes."""
import json, base64
from pathlib import Path

ROOT = Path(r"c:\Users\zach\Desktop\MLS Bot")
DATA = json.loads((ROOT / "outputs" / "_4_5br_listings.json").read_text())
LOGO = base64.b64encode((ROOT / "Gravity-FullLockup-360-White.png").read_bytes()).decode()
LOGO_URI = f"data:image/png;base64,{LOGO}"

# Tier 1 value reads from workflow
TIER1_READS = {
    "3384 Fairview Church Road":  ("high",  "$746/sf vs $356 comp median"),
    "2822 Huffville Road":        ("high",  "$612/sf vs $305 comp median; 2025 build premium"),
    "231 Floyd Highway N":        ("fair",  "$351/sf — below $393 Floyd comp median"),
    "4589 Franklin Pike":         ("high",  "$503/sf vs $267 comp median"),
    "4255 Fortress Drive":        ("high",  "$444/sf vs $204 comp median (Brush Mtn estate)"),
    "5384 Harvest Road":          ("fair",  "$226/sf — under $241 comp median; best land value"),
    "335 Deercroft Drive":        ("high",  "$494/sf vs $229 comp median"),
}

def tier(d):
    ac = d['ac'] or 0
    if ac >= 10: return 1
    if ac >= 3:  return 2
    if ac >= 0.5: return 3
    return 4

T1 = [d for d in DATA if tier(d)==1]
T2 = [d for d in DATA if tier(d)==2]
T3 = [d for d in DATA if tier(d)==3]
T4 = [d for d in DATA if tier(d)==4]

def fmt_k(v): return f"${int(v/1000)}k" if v < 1_000_000 else f"${v/1_000_000:.2f}M"
def short_addr(a, max=32):
    return a if len(a) <= max else a[:max-1] + "…"

# Build Tier 1 rows with value reads
def t1_row(d):
    key = d['address'].split(',')[0]
    vr = TIER1_READS.get(key, ("?", ""))
    tone, note = vr
    tag = '<span class="vtag v-fair">FAIR</span>' if tone=="fair" else \
          '<span class="vtag v-high">HIGH</span>' if tone=="high" else \
          '<span class="vtag v-low">LOW</span>'
    cut_s = f'<span class="cut">↓{abs(d["cut"]):.0f}%</span>' if d['cut'] and d['cut']<-1 else ''
    dom_class = ' stale' if (d['dom'] or 0) >= 120 else ''
    return f"""<tr>
      <td class="l"><span class="addr2">{d['address']}</span><div class="sub">{d['city']} · {d['subd'] or '—'} · {d['pt']}</div></td>
      <td class="price">${d['lp']:,}{cut_s}</td>
      <td>{d['sf'] or '—'}</td>
      <td><b>{d['ac']:.2f}</b></td>
      <td>{d['bd']}/{d['fb']}.{d['hb']}</td>
      <td>{d['yb'] or '?'}</td>
      <td class="dom{dom_class}">{d['dom']}</td>
      <td class="l">{tag}<div class="note">{note}</div></td>
    </tr>"""

def t2_row(d):
    cut_s = f'<span class="cut">↓{abs(d["cut"]):.0f}%</span>' if d['cut'] and d['cut']<-1 else ''
    dom_class = ' stale' if (d['dom'] or 0) >= 120 else ''
    return f"""<tr>
      <td class="l"><span class="addr2">{d['address']}</span><div class="sub">{d['city']} · {d['subd'] or '—'}</div></td>
      <td>${d['lp']:,}{cut_s}</td>
      <td>{d['sf'] or '—'}</td>
      <td><b>{d['ac']:.2f}</b></td>
      <td>{d['bd']}/{d['fb']}.{d['hb']}</td>
      <td>{d['yb'] or '?'}</td>
      <td class="dom{dom_class}">{d['dom']}</td>
    </tr>"""

def t34_row(d):
    cut_s = '↓' if d['cut'] and d['cut']<-1 else ''
    return f"""<tr>
      <td class="l"><span class="caddr">{short_addr(d['address'], 36)}</span></td>
      <td class="l ssub">{d['city']}</td>
      <td>${d['lp']:,}{cut_s}</td>
      <td>{d['sf'] or '—'}</td>
      <td>{d['ac']:.2f}</td>
      <td>{d['bd']}/{d['fb']}</td>
      <td>{d['yb'] or '?'}</td>
      <td>{d['dom']}</td>
    </tr>"""

# Sort Tier 3, Tier 4 — by acres desc then DOM asc
T3.sort(key=lambda d: (-(d['ac'] or 0), d['dom'] or 0))
T4.sort(key=lambda d: (-(d['ac'] or 0), d['dom'] or 0))

# Build HTML
total = len(DATA)
mont = sum(1 for d in DATA if d['county']=='Montgomery')
floyd = sum(1 for d in DATA if d['county']=='Floyd')
stale = sum(1 for d in DATA if (d['dom'] or 0) >= 120)
cuts = sum(1 for d in DATA if d['cut'] and d['cut'] < -2)

html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Gravity Real Estate Group — Buyer Inventory · 4-5BR Floyd + Montgomery</title>
<style>
  :root{{--ink:#141414;--slate:#4a4a52;--muted:#8d8d97;--line:#e6e3ec;--paper:#ffffff;--band:#f7f5fb;
    --violet:#7c22ce;--violet-d:#5d1a9c;--violet-t:#f0e6fb;--violet-tt:#faf4ff;--good:#2f7d5b;--flag:#9a3b34;
    --fair:#2f7d5b;--high:#9a3b34;--low:#7c22ce;}}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;}}
  body{{font-family:"Helvetica Neue",Arial,system-ui,sans-serif;color:var(--ink);
       background:#ecebf0;-webkit-font-smoothing:antialiased;font-size:10px;line-height:1.4;}}
  .page{{width:8.5in;height:11in;margin:18px auto;background:var(--paper);
        box-shadow:0 2px 22px rgba(40,20,70,.16);display:flex;flex-direction:column;
        page-break-after:always;overflow:hidden;}}
  .page:last-child{{page-break-after:auto;}}
  .mastbar{{background:var(--ink);padding:14px 30px;display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid var(--violet);}}
  .lockup-img{{height:30px;width:auto;display:block;}}
  .docmeta{{text-align:right;font-size:8.5px;color:#a7a7b2;line-height:1.7;}}
  .docmeta strong{{color:#fff;font-weight:600;}}
  .titleblock{{padding:13px 30px 0;}}
  .kicker{{font-size:9px;letter-spacing:.32em;text-transform:uppercase;color:var(--violet);font-weight:700;}}
  .title{{font-family:Georgia,serif;font-size:22px;font-weight:700;margin:3px 0 2px;color:var(--ink);}}
  .subtitle{{font-size:10.5px;color:var(--slate);}}
  .rule{{height:2px;background:var(--violet);opacity:.25;margin:12px 30px 0;border:0;}}
  .body{{padding:14px 30px 16px;flex:1;display:flex;flex-direction:column;}}
  .exec{{font-family:Georgia,serif;font-size:11px;line-height:1.5;color:var(--ink);
        border-left:3px solid var(--violet);padding:1px 0 1px 12px;margin:0 0 12px;}}
  .kpis{{display:flex;border:1px solid var(--line);border-radius:4px;overflow:hidden;margin:0 0 12px;}}
  .kpi{{flex:1;padding:7px 10px;border-right:1px solid var(--line);}}
  .kpi:last-child{{border-right:0;}}
  .kpi .n{{font-family:Georgia,serif;font-size:15px;font-weight:700;color:var(--violet);line-height:1;}}
  .kpi .l{{font-size:7px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-top:3px;}}
  .kpi .s{{font-size:8px;color:var(--slate);margin-top:1px;}}

  .charts{{display:flex;gap:14px;margin:0 0 12px;}}
  .chart{{flex:1;border:1px solid var(--line);border-radius:4px;padding:9px 12px;}}
  .chart h3{{font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--violet);font-weight:700;margin:0 0 4px;}}
  .chart .sub{{font-size:8px;color:var(--muted);margin-bottom:4px;}}
  .chart svg{{display:block;width:100%;height:auto;}}

  h2.sec{{font-size:9px;letter-spacing:.2em;text-transform:uppercase;color:var(--ink);margin:0 0 5px;
         padding-bottom:3px;border-bottom:2px solid var(--violet);font-weight:700;
         display:flex;justify-content:space-between;align-items:baseline;}}
  h2.sec span{{font-size:8px;letter-spacing:.05em;color:var(--muted);text-transform:none;font-weight:400;}}

  table{{width:100%;border-collapse:collapse;margin:0 0 10px;}}
  thead th{{font-size:7px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
           text-align:right;padding:0 5px 3px;border-bottom:1px solid var(--line);font-weight:600;}}
  thead th.l{{text-align:left;}}
  tbody td{{padding:4px 5px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums;vertical-align:top;}}
  tbody td.l{{text-align:left;}}
  tbody tr:nth-child(even){{background:var(--band);}}
  .addr2{{font-weight:700;color:var(--ink);font-size:9.5px;}}
  .sub{{color:var(--muted);font-size:7.5px;line-height:1.3;}}
  .price{{font-weight:600;color:var(--ink);}}
  .cut{{display:inline-block;margin-left:4px;color:var(--flag);font-size:7.5px;font-weight:600;}}
  .dom.stale{{color:var(--flag);font-weight:700;}}

  .vtag{{display:inline-block;font-size:6.5px;letter-spacing:.06em;text-transform:uppercase;
        padding:1px 5px;border-radius:2px;font-weight:700;}}
  .vtag.v-fair{{background:var(--fair);color:#fff;}}
  .vtag.v-high{{background:var(--high);color:#fff;}}
  .vtag.v-low{{background:var(--low);color:#fff;}}
  .note{{font-size:7.5px;color:var(--slate);margin-top:2px;line-height:1.3;}}

  table.compact tbody td{{padding:2.5px 4px;font-size:8.5px;}}
  table.compact thead th{{padding:0 4px 2px;font-size:6.5px;}}
  .caddr{{color:var(--ink);font-weight:600;}}
  .ssub{{color:var(--slate);font-size:8px;}}

  .foot{{background:var(--ink);padding:11px 30px 12px;border-top:3px solid var(--violet);}}
  .foot .sig{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}}
  .foot .who{{font-size:9px;color:#c4c4cf;}}
  .foot .who strong{{color:#fff;font-size:10.5px;display:block;font-family:Georgia,serif;}}
  .foot-lockup{{height:20px;width:auto;display:block;}}
  .foot .disc{{font-size:7px;color:#86868f;line-height:1.5;}}
  .twocol{{display:flex;gap:14px;}}
  .twocol > div{{flex:1;}}

  @media print{{
    html,body{{margin:0;padding:0;background:#fff;overflow:hidden;line-height:0;}}
    .page{{margin:0;box-shadow:none;width:8.5in;height:11in;line-height:1.4;}}
    @page{{size:8.5in 11in;margin:0;}}
    *{{-webkit-print-color-adjust:exact;print-color-adjust:exact;}}}}
</style>
</head>
<body>

<!-- ============ PAGE 1: DASHBOARD + TIER 1 + TIER 2 ============ -->
<div class="page">
  <div class="mastbar">
    <img class="lockup-img" src="{LOGO_URI}" alt="Gravity Real Estate Group" />
    <div class="docmeta">
      <div><strong>Issued</strong> June 1, 2026</div>
      <div><strong>Counties</strong> Floyd · Montgomery</div>
      <div><strong>Filter</strong> Active · 4–5 BR · Detached/Farm</div>
      <div><strong>Sorted</strong> Acreage descending</div>
    </div>
  </div>
  <div class="titleblock">
    <div class="kicker">Buyer Inventory Brief · Page 1 of 2</div>
    <div class="title">4–5 Bedroom Homes · Floyd + Montgomery County</div>
    <div class="subtitle">All currently-listed Detached &amp; Farm properties, organized by acreage tier</div>
  </div>
  <hr class="rule"/>

  <div class="body">
    <p class="exec">
      <b>{total} Active listings</b> meet the 4–5 bedroom criterion across Floyd ({floyd}) and Montgomery ({mont}) counties.
      <b>{len(T1)+len(T2)} properties carry 3+ acres</b> — the acreage-rich set on Page 1. Adversarial verification
      against townhouse, multifamily, farm, geographic, and bedroom-NULL edge cases confirms the list is exhaustive
      for &quot;family home with land&quot; intent. <b>Two standout values</b> in the high-acreage tier (≥10 ac):
      <b>5384 Harvest Road, Riner</b> ($549k / 17.5 ac) and <b>231 Floyd Highway N, Floyd</b> ($1.89M / 22 ac) — both
      priced at or under their county comp $/sf medians.
    </p>

    <div class="kpis">
      <div class="kpi"><div class="n">{total}</div><div class="l">Active 4–5 BR Listings</div><div class="s">Detached + Farm</div></div>
      <div class="kpi"><div class="n">{mont} / {floyd}</div><div class="l">Montgomery / Floyd</div><div class="s">92% / 8% mix</div></div>
      <div class="kpi"><div class="n">{len(T1)+len(T2)}</div><div class="l">3+ Acre Properties</div><div class="s">{len(T1)} are 10+ ac</div></div>
      <div class="kpi"><div class="n">{stale}</div><div class="l">Stale (DOM ≥ 120)</div><div class="s">Negotiation leverage</div></div>
      <div class="kpi"><div class="n">{cuts}</div><div class="l">With Price Cuts</div><div class="s">≥2% off original</div></div>
    </div>

    <div class="charts">
      <div class="chart">
        <h3>Acreage Distribution</h3>
        <div class="sub">Property count by acreage tier (n=87)</div>
        <svg viewBox="0 0 300 130" preserveAspectRatio="none">
          <line x1="80" y1="15" x2="80" y2="115" stroke="#141414" stroke-width="1"/>
          <line x1="80" y1="115" x2="295" y2="115" stroke="#141414" stroke-width="1"/>
          <!-- 5px per unit, max 50 → 250px. So 87 max would be wider; use 45 cap → ~5.5px per. Use 4.5px per unit -->
          <text x="78" y="29" font-size="8" fill="#141414" text-anchor="end" font-weight="600">10+ ac</text>
          <rect x="83" y="20" width="{7*5.5:.0f}" height="14" fill="#7c22ce"/>
          <text x="{83 + 7*5.5 + 5:.0f}" y="29" font-size="8" fill="#141414" font-weight="700">{len(T1)}</text>
          <text x="78" y="54" font-size="8" fill="#141414" text-anchor="end" font-weight="600">3–10 ac</text>
          <rect x="83" y="45" width="{11*5.5:.0f}" height="14" fill="#7c22ce" opacity=".8"/>
          <text x="{83 + 11*5.5 + 5:.0f}" y="54" font-size="8" fill="#141414" font-weight="700">{len(T2)}</text>
          <text x="78" y="79" font-size="8" fill="#141414" text-anchor="end" font-weight="600">0.5–3 ac</text>
          <rect x="83" y="70" width="{28*5.5:.0f}" height="14" fill="#7c22ce" opacity=".6"/>
          <text x="{83 + 28*5.5 + 5:.0f}" y="79" font-size="8" fill="#141414" font-weight="700">{len(T3)}</text>
          <text x="78" y="104" font-size="8" fill="#141414" text-anchor="end" font-weight="600">&lt; 0.5 ac</text>
          <rect x="83" y="95" width="{41*5.5:.0f}" height="14" fill="#7c22ce" opacity=".4"/>
          <text x="{83 + 41*5.5 + 5:.0f}" y="104" font-size="8" fill="#141414" font-weight="700">{len(T4)} (in-town)</text>
        </svg>
      </div>
      <div class="chart">
        <h3>Price Band Distribution</h3>
        <div class="sub">Property count by list price band</div>
        <svg viewBox="0 0 300 130" preserveAspectRatio="none">
          <line x1="80" y1="15" x2="80" y2="115" stroke="#141414" stroke-width="1"/>
          <line x1="80" y1="115" x2="295" y2="115" stroke="#141414" stroke-width="1"/>
          <text x="78" y="26" font-size="8" fill="#141414" text-anchor="end" font-weight="600">&lt; $400k</text>
          <rect x="83" y="18" width="{9*5.5:.0f}" height="11" fill="#7c22ce" opacity=".45"/>
          <text x="{83 + 9*5.5 + 5:.0f}" y="26" font-size="8" fill="#141414" font-weight="700">9</text>
          <text x="78" y="46" font-size="8" fill="#141414" text-anchor="end" font-weight="600">$400–600k</text>
          <rect x="83" y="38" width="{31*5.5:.0f}" height="11" fill="#7c22ce"/>
          <text x="{83 + 31*5.5 + 5:.0f}" y="46" font-size="8" fill="#141414" font-weight="700">31 (largest)</text>
          <text x="78" y="66" font-size="8" fill="#141414" text-anchor="end" font-weight="600">$600–850k</text>
          <rect x="83" y="58" width="{28*5.5:.0f}" height="11" fill="#7c22ce" opacity=".85"/>
          <text x="{83 + 28*5.5 + 5:.0f}" y="66" font-size="8" fill="#141414" font-weight="700">28</text>
          <text x="78" y="86" font-size="8" fill="#141414" text-anchor="end" font-weight="600">$850k–1.25M</text>
          <rect x="83" y="78" width="{8*5.5:.0f}" height="11" fill="#7c22ce" opacity=".55"/>
          <text x="{83 + 8*5.5 + 5:.0f}" y="86" font-size="8" fill="#141414" font-weight="700">8</text>
          <text x="78" y="106" font-size="8" fill="#141414" text-anchor="end" font-weight="600">$1.25M+</text>
          <rect x="83" y="98" width="{11*5.5:.0f}" height="11" fill="#7c22ce" opacity=".7"/>
          <text x="{83 + 11*5.5 + 5:.0f}" y="106" font-size="8" fill="#141414" font-weight="700">11</text>
        </svg>
      </div>
    </div>

    <h2 class="sec">Tier 1 · 10+ Acres <span>{len(T1)} properties · value reads vs same-county comp $/sf band</span></h2>
    <table>
      <thead><tr>
        <th class="l" style="width:30%">Property</th>
        <th>List Price</th><th>Sq Ft</th><th>Acres</th><th>Bd/Ba</th><th>Built</th><th>DOM</th>
        <th class="l">Value Read</th>
      </tr></thead>
      <tbody>
        {''.join(t1_row(d) for d in T1)}
      </tbody>
    </table>

    <h2 class="sec">Tier 2 · 3–10 Acres <span>{len(T2)} properties · sorted by acreage</span></h2>
    <table>
      <thead><tr>
        <th class="l" style="width:35%">Property</th>
        <th>List Price</th><th>Sq Ft</th><th>Acres</th><th>Bd/Ba</th><th>Built</th><th>DOM</th>
      </tr></thead>
      <tbody>
        {''.join(t2_row(d) for d in T2)}
      </tbody>
    </table>

  </div>

  <div class="foot">
    <div class="sig">
      <div class="who"><strong>Zachary Stotz</strong>Licensed Real Estate Agent · Commonwealth of Virginia</div>
      <img class="foot-lockup" src="{LOGO_URI}" alt="Gravity Real Estate Group" />
    </div>
    <div class="disc">
      Page 1 of 2. Inventory sourced from NRV MLS Active listings, June 1 2026. Value reads against trailing-36mo
      closed comps in same county. Continue to Page 2 for Tier 3 (0.5–3 ac) and Tier 4 (&lt;0.5 ac) detail.
      © 2026 Gravity Real Estate Group.
    </div>
  </div>

</div>

<!-- ============ PAGE 2: TIER 3 + TIER 4 ============ -->
<div class="page">
  <div class="mastbar">
    <img class="lockup-img" src="{LOGO_URI}" alt="Gravity Real Estate Group" />
    <div class="docmeta">
      <div><strong>Issued</strong> June 1, 2026</div>
      <div><strong>Continued</strong> Page 2 of 2</div>
      <div><strong>Lower Acreage</strong> Tiers 3 + 4</div>
      <div><strong>{len(T3)+len(T4)} properties</strong></div>
    </div>
  </div>
  <div class="titleblock">
    <div class="kicker">Buyer Inventory Brief · Continued</div>
    <div class="title">Tiers 3 &amp; 4 · Sub-3-Acre Detail</div>
    <div class="subtitle">In-town and small-lot homes · all 4–5 BR · {len(T3)} suburban + {len(T4)} in-town</div>
  </div>
  <hr class="rule"/>

  <div class="body">
    <div class="twocol">
      <div>
        <h2 class="sec">Tier 3 · 0.5–3 Acres <span>{len(T3)} properties</span></h2>
        <table class="compact">
          <thead><tr><th class="l">Address</th><th class="l">City</th><th>Price</th><th>SF</th><th>Ac</th><th>Bd/Ba</th><th>YB</th><th>DOM</th></tr></thead>
          <tbody>
            {''.join(t34_row(d) for d in T3)}
          </tbody>
        </table>
      </div>
      <div>
        <h2 class="sec">Tier 4 · &lt; 0.5 Acres <span>{len(T4)} properties (in-town)</span></h2>
        <table class="compact">
          <thead><tr><th class="l">Address</th><th class="l">City</th><th>Price</th><th>SF</th><th>Ac</th><th>Bd/Ba</th><th>YB</th><th>DOM</th></tr></thead>
          <tbody>
            {''.join(t34_row(d) for d in T4)}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="foot">
    <div class="sig">
      <div class="who"><strong>Zachary Stotz</strong>Licensed Real Estate Agent · Commonwealth of Virginia</div>
      <img class="foot-lockup" src="{LOGO_URI}" alt="Gravity Real Estate Group" />
    </div>
    <div class="disc">
      Inventory snapshot · NRV MLS · June 1 2026. Adversarial verification confirms exhaustiveness for the 4–5BR
      Active Detached/Farm universe in Floyd + Montgomery. Townhouse subtype excluded — zero materially-acreage units
      were missed. Not an offer or solicitation. © 2026 Gravity Real Estate Group.
    </div>
  </div>
</div>

</body>
</html>
"""

out = ROOT / "outputs" / "buyer_inventory_4_5br_floyd_montgomery.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out}")
print(f"  total={total} t1={len(T1)} t2={len(T2)} t3={len(T3)} t4={len(T4)}")
