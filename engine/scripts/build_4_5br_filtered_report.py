"""Generate filtered (≤$600k, Detached) 4-5BR Floyd+Montgomery inventory — one page."""
import json, base64
from pathlib import Path

ROOT = Path(r"c:\Users\zach\Desktop\MLS Bot")
DATA = json.loads((ROOT / "outputs" / "_4_5br_listings_filtered.json").read_text())
LOGO = base64.b64encode((ROOT / "Gravity-FullLockup-360-White.png").read_bytes()).decode()
LOGO_URI = f"data:image/png;base64,{LOGO}"

# Tier 1/2 value reads from prior workflow (only Tier 1's Harvest Rd carries an existing read)
SPOTLIGHT_READS = {
    "5384 Harvest Road":  ("fair", "$226/sf — under $241 Montgomery comp median; best land value"),
    "607 GILES Road":     ("note", "1840 historic · land value drives price · 3.25 ac"),
}

def tier(d):
    ac = d['ac'] or 0
    if ac >= 10: return 1
    if ac >= 3:  return 2
    if ac >= 0.5: return 3
    return 4

T1 = [d for d in DATA if tier(d)==1]
T2 = [d for d in DATA if tier(d)==2]
T3 = sorted([d for d in DATA if tier(d)==3], key=lambda d: (-(d['ac'] or 0), d['dom'] or 0))
T4 = sorted([d for d in DATA if tier(d)==4], key=lambda d: (-(d['ac'] or 0), d['dom'] or 0))
SPOT = T1 + T2

def short_addr(a, max=34):
    return a if len(a) <= max else a[:max-1] + "…"

def spot_row(d):
    key = d['address'].split(',')[0]
    tone, note = SPOTLIGHT_READS.get(key, ("note",""))
    tag_class = {"fair":"v-fair","high":"v-high","note":"v-note"}[tone]
    tag_text = {"fair":"FAIR","high":"HIGH","note":"NOTABLE"}[tone]
    cut_s = f'<span class="cut">↓{abs(d["cut"]):.0f}%</span>' if d['cut'] and d['cut']<-1 else ''
    return f"""<tr>
      <td class="l"><span class="addr2">{d['address']}</span><div class="sub">{d['city']} · {d['subd'] or '—'} · {d['hs'] or '—'} HS</div></td>
      <td class="price">${d['lp']:,}{cut_s}</td>
      <td>{d['sf'] or '—'}</td>
      <td><b>{d['ac']:.2f}</b></td>
      <td>{d['bd']}/{d['fb']}.{d['hb']}</td>
      <td>{d['yb'] or '?'}</td>
      <td>{d['dom']}</td>
      <td class="l"><span class="vtag {tag_class}">{tag_text}</span><div class="vrnote">{note}</div></td>
    </tr>"""

def t34_row(d):
    cut_s = '<span class="cut2">↓</span>' if d['cut'] and d['cut']<-1 else ''
    stale = ' stale' if (d['dom'] or 0) >= 120 else ''
    return f"""<tr>
      <td class="l"><span class="caddr">{short_addr(d['address'], 32)}</span><div class="ssub">{d['city']}</div></td>
      <td>${d['lp']:,}{cut_s}</td>
      <td>{d['sf'] or '—'}</td>
      <td>{d['ac']:.2f}</td>
      <td>{d['bd']}/{d['fb']}</td>
      <td>{d['yb'] or '?'}</td>
      <td class="dom{stale}">{d['dom']}</td>
    </tr>"""

total = len(DATA)
mont = sum(1 for d in DATA if d['county']=='Montgomery')
floyd = sum(1 for d in DATA if d['county']=='Floyd')
stale = sum(1 for d in DATA if (d['dom'] or 0) >= 120)
cuts = sum(1 for d in DATA if d['cut'] and d['cut'] < -2)
med_price = sorted(d['lp'] for d in DATA)[len(DATA)//2]

# Price band counts
b_400 = sum(1 for d in DATA if d['lp'] < 400000)
b_5 = sum(1 for d in DATA if 400000 <= d['lp'] < 500000)
b_6 = sum(1 for d in DATA if 500000 <= d['lp'] <= 600000)

html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Gravity Real Estate Group — 4-5BR Inventory · Under $600k · Floyd + Montgomery</title>
<style>
  :root{{--ink:#141414;--slate:#4a4a52;--muted:#8d8d97;--line:#e6e3ec;--paper:#ffffff;--band:#f7f5fb;
    --violet:#7c22ce;--violet-d:#5d1a9c;--violet-t:#f0e6fb;--violet-tt:#faf4ff;--good:#2f7d5b;--flag:#9a3b34;
    --fair:#2f7d5b;--high:#9a3b34;}}
  *{{box-sizing:border-box;}}
  html,body{{margin:0;padding:0;}}
  body{{font-family:"Helvetica Neue",Arial,system-ui,sans-serif;color:var(--ink);
       background:#ecebf0;-webkit-font-smoothing:antialiased;font-size:10px;line-height:1.4;}}
  .page{{width:8.5in;min-height:11in;margin:18px auto;background:var(--paper);
        box-shadow:0 2px 22px rgba(40,20,70,.16);display:flex;flex-direction:column;}}
  .mastbar{{background:var(--ink);padding:13px 30px;display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid var(--violet);}}
  .lockup-img{{height:28px;width:auto;display:block;}}
  .docmeta{{text-align:right;font-size:8.5px;color:#a7a7b2;line-height:1.7;}}
  .docmeta strong{{color:#fff;font-weight:600;}}
  .titleblock{{padding:11px 30px 0;}}
  .kicker{{font-size:9px;letter-spacing:.32em;text-transform:uppercase;color:var(--violet);font-weight:700;}}
  .title{{font-family:Georgia,serif;font-size:21px;font-weight:700;margin:3px 0 2px;color:var(--ink);}}
  .subtitle{{font-size:10.5px;color:var(--slate);}}
  .rule{{height:2px;background:var(--violet);opacity:.25;margin:10px 30px 0;border:0;}}
  .body{{padding:13px 30px 14px;flex:1;display:flex;flex-direction:column;}}
  .exec{{font-family:Georgia,serif;font-size:11px;line-height:1.5;color:var(--ink);
        border-left:3px solid var(--violet);padding:1px 0 1px 12px;margin:0 0 11px;}}
  .kpis{{display:flex;border:1px solid var(--line);border-radius:4px;overflow:hidden;margin:0 0 11px;}}
  .kpi{{flex:1;padding:7px 10px;border-right:1px solid var(--line);}}
  .kpi:last-child{{border-right:0;}}
  .kpi .n{{font-family:Georgia,serif;font-size:15px;font-weight:700;color:var(--violet);line-height:1;}}
  .kpi .l{{font-size:7px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-top:3px;}}
  .kpi .s{{font-size:8px;color:var(--slate);margin-top:1px;}}

  .chart{{border:1px solid var(--line);border-radius:4px;padding:8px 12px;margin:0 0 11px;}}
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
  .cut2{{color:var(--flag);font-weight:700;margin-left:2px;}}
  .dom.stale{{color:var(--flag);font-weight:700;}}
  .vtag{{display:inline-block;font-size:6.5px;letter-spacing:.06em;text-transform:uppercase;
        padding:1px 5px;border-radius:2px;font-weight:700;}}
  .v-fair{{background:var(--fair);color:#fff;}}
  .v-high{{background:var(--high);color:#fff;}}
  .v-note{{background:var(--violet);color:#fff;}}
  .vrnote{{font-size:7.5px;color:var(--slate);margin-top:2px;line-height:1.3;}}

  table.compact tbody td{{padding:3px 4px;font-size:8.5px;}}
  table.compact thead th{{padding:0 4px 2px;font-size:6.5px;}}
  .caddr{{color:var(--ink);font-weight:600;line-height:1.2;}}
  .ssub{{color:var(--slate);font-size:7.5px;line-height:1.2;}}

  .twocol{{display:flex;gap:14px;}}
  .twocol > div{{flex:1;min-width:0;}}

  .foot{{background:var(--ink);padding:11px 30px 12px;margin-top:auto;border-top:3px solid var(--violet);}}
  .foot .sig{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}}
  .foot .who{{font-size:9px;color:#c4c4cf;}}
  .foot .who strong{{color:#fff;font-size:10.5px;display:block;font-family:Georgia,serif;}}
  .foot-lockup{{height:20px;width:auto;display:block;}}
  .foot .disc{{font-size:7px;color:#86868f;line-height:1.5;}}

  @media print{{
    html,body{{margin:0;padding:0;background:#fff;overflow:hidden;line-height:0;}}
    .page{{margin:0;box-shadow:none;width:8.5in;height:11in;min-height:0;max-height:11in;overflow:hidden;line-height:1.4;}}
    @page{{size:8.5in 11in;margin:0;}}
    *{{-webkit-print-color-adjust:exact;print-color-adjust:exact;}}}}
</style>
</head>
<body>
<div class="page">
  <div class="mastbar">
    <img class="lockup-img" src="{LOGO_URI}" alt="Gravity Real Estate Group" />
    <div class="docmeta">
      <div><strong>Issued</strong> June 1, 2026</div>
      <div><strong>Counties</strong> Floyd · Montgomery</div>
      <div><strong>Filter</strong> Active · 4–5 BR · Detached · ≤ $600k</div>
      <div><strong>Sorted</strong> Acreage desc, then DOM asc</div>
    </div>
  </div>
  <div class="titleblock">
    <div class="kicker">Buyer Inventory Brief</div>
    <div class="title">4–5 Bedroom Detached · Under $600,000</div>
    <div class="subtitle">All currently-listed single-family homes · Floyd + Montgomery County</div>
  </div>
  <hr class="rule"/>

  <div class="body">
    <p class="exec">
      <b>{total} Active detached single-family homes</b> meet the 4–5 BR criterion at $600k or under across
      Floyd ({floyd}) and Montgomery ({mont}) counties. Median list price <b>${med_price:,}</b>. Only
      <b>two properties carry 3+ acres</b> at this price point — the spotlight set below. The bulk of the
      inventory is suburban (Tier 3, {len(T3)}) or in-town (Tier 4, {len(T4)}), concentrated in the $400–500k band.
    </p>

    <div class="kpis">
      <div class="kpi"><div class="n">{total}</div><div class="l">Total Matches</div><div class="s">Active 4–5 BR Detached</div></div>
      <div class="kpi"><div class="n">{mont} / {floyd}</div><div class="l">Montgomery / Floyd</div><div class="s">93% / 7% mix</div></div>
      <div class="kpi"><div class="n">${med_price/1000:.0f}k</div><div class="l">Median List Price</div><div class="s">Range $295k–$600k</div></div>
      <div class="kpi"><div class="n">{stale}</div><div class="l">Stale (DOM ≥ 120)</div><div class="s">Negotiation leverage</div></div>
      <div class="kpi"><div class="n">{cuts}</div><div class="l">With Cuts ≥ 2%</div><div class="s">{cuts*100//total}% of set</div></div>
    </div>

    <div class="chart">
      <h3>Price Band Distribution</h3>
      <div class="sub">{total} properties · concentration in the $400–500k band</div>
      <svg viewBox="0 0 600 80" preserveAspectRatio="none">
        <line x1="100" y1="10" x2="100" y2="70" stroke="#141414" stroke-width="1"/>
        <line x1="100" y1="70" x2="595" y2="70" stroke="#141414" stroke-width="1"/>
        <text x="95" y="24" font-size="10" fill="#141414" text-anchor="end" font-weight="600">&lt; $400k</text>
        <rect x="103" y="14" width="{b_400*18:.0f}" height="14" fill="#7c22ce" opacity=".55"/>
        <text x="{103+b_400*18+6:.0f}" y="25" font-size="10" fill="#141414" font-weight="700">{b_400}</text>
        <text x="95" y="44" font-size="10" fill="#141414" text-anchor="end" font-weight="600">$400–500k</text>
        <rect x="103" y="34" width="{b_5*18:.0f}" height="14" fill="#7c22ce"/>
        <text x="{103+b_5*18+6:.0f}" y="45" font-size="10" fill="#141414" font-weight="700">{b_5} · largest band</text>
        <text x="95" y="64" font-size="10" fill="#141414" text-anchor="end" font-weight="600">$500–600k</text>
        <rect x="103" y="54" width="{b_6*18:.0f}" height="14" fill="#7c22ce" opacity=".8"/>
        <text x="{103+b_6*18+6:.0f}" y="65" font-size="10" fill="#141414" font-weight="700">{b_6}</text>
      </svg>
    </div>

    <h2 class="sec">Spotlight · 3+ Acres <span>only {len(SPOT)} qualify at this price point</span></h2>
    <table>
      <thead><tr>
        <th class="l" style="width:30%">Property</th>
        <th>List Price</th><th>Sq Ft</th><th>Acres</th><th>Bd/Ba</th><th>Built</th><th>DOM</th>
        <th class="l">Read</th>
      </tr></thead>
      <tbody>
        {''.join(spot_row(d) for d in SPOT)}
      </tbody>
    </table>

    <div class="twocol">
      <div>
        <h2 class="sec">Tier 3 · 0.5–3 Acres <span>{len(T3)} properties</span></h2>
        <table class="compact">
          <thead><tr><th class="l">Address / City</th><th>Price</th><th>SF</th><th>Ac</th><th>Bd/Ba</th><th>YB</th><th>DOM</th></tr></thead>
          <tbody>
            {''.join(t34_row(d) for d in T3)}
          </tbody>
        </table>
      </div>
      <div>
        <h2 class="sec">Tier 4 · &lt; 0.5 Acres <span>{len(T4)} in-town properties</span></h2>
        <table class="compact">
          <thead><tr><th class="l">Address / City</th><th>Price</th><th>SF</th><th>Ac</th><th>Bd/Ba</th><th>YB</th><th>DOM</th></tr></thead>
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
      Inventory snapshot · NRV MLS · June 1 2026. Filters: status=Active, 4–5 bedrooms, property_subtype=Detached,
      list_price ≤ $600,000, county IN (Floyd, Montgomery). Townhouse, multifamily, condominium, farm, and land
      subtypes excluded per request. Value read on spotlight properties is comp-derived; not an offer or appraisal.
      © 2026 Gravity Real Estate Group.
    </div>
  </div>

</div>
</body>
</html>
"""

out = ROOT / "outputs" / "buyer_inventory_4_5br_under_600k.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out}")
print(f"  total={total} t1={len(T1)} t2={len(T2)} t3={len(T3)} t4={len(T4)}")
