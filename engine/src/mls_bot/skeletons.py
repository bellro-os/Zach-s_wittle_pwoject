"""Skeleton stylesheets for the supported brand layout styles.

A skeleton is a complete CSS block that uses ``var(--brand-*)`` and
``var(--type-*)`` tokens for everything that can vary by brand. The
:class:`~mls_bot.brand.Brand` object supplies a leading ``:root{}`` block
that defines those custom properties, and the skeleton fills in the rest.

Skeletons MUST NOT hardcode brand-specific values (no literal ``#7c22ce``,
no ``Cormorant Garamond``). They MUST stay in lock-step with the HTML
class structure used by the report builders (``.masthead``, ``.titleblock``,
``.body``, ``.hero``, ``.subject``, ``.verdict``, ``.exec``, ``.kpis``,
``.kpi``, ``h2.sec``, ``.tag``, ``.twocol``, ``.panel``, ``.foot``, etc.).

The two skeletons shipped here are extracted from the previously-vetted
``scripts/_gravity_template.py::PRINT_CSS`` and
``scripts/_maplehaus_template.py::PRINT_CSS`` so existing reports render
visually identical before and after the refactor.
"""
from __future__ import annotations


# =========================================================================
# dark_band — Gravity-style layout
#   * Dark mastbar with PNG logo lockup
#   * Violet accents on titleblock + kicker + section rules
#   * Helvetica body + Georgia serif display
#   * Dark footer with white text
# =========================================================================
SKELETON_DARK_BAND = """
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{font-family:var(--type-body);color:var(--brand-ink);
     background:#ecebf0;-webkit-font-smoothing:antialiased;font-size:10px;line-height:1.42;}
.page{width:8.5in;min-height:11in;margin:18px auto;background:var(--brand-paper);
      box-shadow:0 2px 22px rgba(40,20,70,.16);display:flex;flex-direction:column;}

/* ---------- masthead: dark band + lockup ---------- */
.masthead{display:block;}
.mastbar{background:var(--brand-ink);padding:14px 30px;display:flex;
         justify-content:space-between;align-items:center;border-bottom:3px solid var(--brand-primary);}
.lockup-img{height:30px;width:auto;display:block;}
.lockup-text{color:#fff;font-family:var(--type-display);font-size:20px;font-weight:700;letter-spacing:.18em;}
.docmeta{text-align:right;font-size:8.5px;color:#a7a7b2;line-height:1.7;}
.docmeta strong{color:#fff;font-weight:600;}
.titleblock{padding:13px 30px 0;}
.kicker{font-size:9px;letter-spacing:.32em;text-transform:uppercase;color:var(--brand-primary);font-weight:700;}
.title{font-family:var(--type-display);font-size:23px;font-weight:700;margin:3px 0 2px;color:var(--brand-ink);}
.subtitle{font-size:10.5px;color:var(--brand-slate);}
.rule{height:2px;background:var(--brand-primary);opacity:.25;margin:12px 30px 0;border:0;}

.body{padding:14px 30px 16px;flex:1;display:block;}

/* ---------- hero ---------- */
.hero{display:flex;gap:14px;margin:0 0 14px;}
.subject{flex:1.15;border:1px solid var(--brand-rule);border-radius:4px;padding:11px 13px;}
.subject .lbl{font-size:8px;letter-spacing:.16em;text-transform:uppercase;color:var(--brand-primary);font-weight:700;margin-bottom:5px;}
.subject .addr{font-family:var(--type-display);font-size:14px;font-weight:700;color:var(--brand-ink);}
.subject .loc{font-size:9px;color:var(--brand-slate);margin-bottom:7px;}
.specs{display:flex;flex-wrap:wrap;gap:4px 0;}
.specs div{width:50%;font-size:9.5px;color:var(--brand-slate);}
.specs b{color:var(--brand-ink);font-weight:600;}
.verdict{flex:1;background:var(--brand-ink);color:#fff;border-radius:4px;padding:11px 14px;
         display:flex;flex-direction:column;justify-content:center;position:relative;overflow:hidden;}
.verdict::after{content:"";position:absolute;right:-18px;top:-18px;width:90px;height:90px;
                background:linear-gradient(135deg,var(--brand-primary),transparent 70%);opacity:.55;transform:rotate(8deg);}
.verdict .lbl{font-size:8px;letter-spacing:.16em;text-transform:uppercase;color:#c9a6ee;font-weight:700;position:relative;}
.verdict .val{font-family:var(--type-display);font-size:27px;font-weight:700;margin:3px 0 1px;position:relative;}
.verdict .range{font-size:9.5px;color:#cfc6da;position:relative;}
.verdict .delta{margin-top:7px;padding-top:7px;border-top:1px solid rgba(255,255,255,.16);font-size:9px;color:#e3dcef;position:relative;}
.verdict .delta b{color:#fff;}

.exec{font-family:var(--type-display);font-size:11px;line-height:1.5;color:var(--brand-ink);
      border-left:3px solid var(--brand-primary);padding:1px 0 1px 12px;margin:0 0 14px;}

.kpis{display:flex;border:1px solid var(--brand-rule);border-radius:4px;overflow:hidden;margin:0 0 15px;}
.kpi{flex:1;padding:8px 11px;border-right:1px solid var(--brand-rule);}
.kpi:last-child{border-right:0;}
.kpi .n{font-family:var(--type-display);font-size:16px;font-weight:700;color:var(--brand-primary);line-height:1;}
.kpi .l{font-size:7.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--brand-muted);margin-top:4px;}
.kpi .s{font-size:8.5px;color:var(--brand-muted);margin-top:2px;font-style:italic;}

h2.sec{font-size:9.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--brand-ink);margin:0 0 7px;
       padding-bottom:4px;border-bottom:2px solid var(--brand-primary);font-weight:700;
       display:flex;justify-content:space-between;align-items:baseline;}
h2.sec span{font-size:8px;letter-spacing:.05em;color:var(--brand-muted);text-transform:none;font-weight:400;}

table{width:100%;border-collapse:collapse;margin:0 0 14px;}
thead th{font-size:7px;letter-spacing:.07em;text-transform:uppercase;color:var(--brand-muted);
         text-align:right;padding:0 6px 4px;border-bottom:1px solid var(--brand-rule);font-weight:600;}
thead th.l{text-align:left;}
tbody td{padding:5px 6px;border-bottom:1px solid var(--brand-rule);text-align:right;font-variant-numeric:tabular-nums;}
tbody td.l{text-align:left;}
tbody tr:nth-child(even){background:var(--brand-band);}
tr.subj{background:var(--brand-accent) !important;}
tr.subj td{border-bottom:1px solid var(--brand-primary);}
.addr2{font-weight:700;color:var(--brand-ink);}
.sub{color:var(--brand-muted);font-size:8px;}
.tag{display:inline-block;font-size:6.5px;letter-spacing:.05em;text-transform:uppercase;padding:1px 4px;
     border-radius:2px;font-weight:700;margin-left:4px;}
.tag.key{background:var(--brand-ink);color:#fff;}
.tag.subjt{background:var(--brand-primary);color:#fff;}
.tag.note{background:var(--brand-secondary);color:#fff;}
.tag.warn{background:var(--brand-flag);color:#fff;}
.tag.pend{background:#2563eb;color:#fff;}

.twocol{display:flex;gap:18px;}
.twocol > div{flex:1;}
.pstriped td:first-child{font-weight:600;}
.rec{background:var(--brand-band);border:1px solid var(--brand-rule);border-left:3px solid var(--brand-primary);
     border-radius:4px;padding:10px 13px;font-size:9.5px;color:var(--brand-slate);line-height:1.5;}
.rec .h{font-size:8px;letter-spacing:.16em;text-transform:uppercase;color:var(--brand-primary);font-weight:700;margin-bottom:5px;}
.rec b{color:var(--brand-ink);}
.recprice{font-family:var(--type-display);font-size:15px;font-weight:700;color:var(--brand-primary);}

/* ---------- footer: dark band ---------- */
.foot{background:var(--brand-ink);padding:13px 30px 14px;margin-top:auto;border-top:3px solid var(--brand-primary);}
.foot .sig{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.foot .who{font-size:9px;color:#c4c4cf;}
.foot .who strong{color:#fff;font-size:10.5px;display:block;font-family:var(--type-display);}
.foot-lockup{height:22px;width:auto;display:block;}
.foot-wordmark{color:#fff;font-family:var(--type-display);font-size:14px;font-weight:700;letter-spacing:.18em;}
.foot .disc{font-size:7px;color:#86868f;line-height:1.5;}

/* ---------- valuation-confidence chip (in verdict card) ---------- */
.conf{display:inline-flex;align-items:center;gap:5px;margin-top:8px;font-size:8px;letter-spacing:.14em;
      text-transform:uppercase;font-weight:700;color:#e3dcef;position:relative;}
.conf::before{content:"";width:7px;height:7px;border-radius:50%;background:#fff;}
.conf.cHigh::before{background:#34d399;}
.conf.cModerate::before{background:#fbbf24;}
.conf.cLow::before{background:var(--brand-flag);}

/* ---------- pricing & absorption band (price -> expected DOM) ---------- */
.dband{display:flex;border:1px solid var(--brand-rule);border-radius:4px;overflow:hidden;margin:0 0 15px;}
.dcell{flex:1;padding:8px 11px;border-right:1px solid var(--brand-rule);}
.dcell:last-child{border-right:0;}
.dcell.rec{background:var(--brand-accent);box-shadow:inset 3px 0 0 var(--brand-primary);}
.dcell .dl{font-size:7.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--brand-muted);font-weight:700;}
.dcell .dp{font-family:var(--type-display);font-size:14px;font-weight:700;color:var(--brand-ink);margin-top:3px;line-height:1;}
.dcell .dd{font-size:13px;font-weight:700;color:var(--brand-primary);margin-top:5px;line-height:1;}
.dcell .dd span{font-size:8px;color:var(--brand-muted);font-weight:600;}
.dcell .dr{font-size:8px;color:var(--brand-muted);margin-top:3px;font-style:italic;}

@media print{
  html,body{margin:0;padding:0;background:#fff;font-size:9.5px;}
  .page{margin:0;box-shadow:none;width:8.5in;min-height:11in;page-break-after:always;line-height:1.42;}
  @page{size:8.5in 11in;margin:0;}
  .page:last-child{page-break-after:auto;}
  table,tr,thead,tbody{page-break-inside:avoid;}
  .hero,.kpis,.kpi,.chart,.panel,.subject,.verdict,.exec,.dband,.dcell{page-break-inside:avoid;}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
}
"""


# =========================================================================
# cream_serif — Maplehaus-style layout
#   * Cream page background with text wordmark masthead (no logo PNG)
#   * Sage primary + mauve secondary accent
#   * Montserrat body + Cormorant Garamond display
#   * Warm beige footer band
# =========================================================================
SKELETON_CREAM_SERIF = """
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{font-family:var(--type-body);color:var(--brand-ink);
     background:#efe9e2;-webkit-font-smoothing:antialiased;font-size:10px;line-height:1.5;font-weight:400;}
.page{width:8.5in;min-height:11in;margin:18px auto;background:var(--brand-paper);
      box-shadow:0 2px 22px rgba(30,25,20,.12);display:flex;flex-direction:column;}

/* ---------- masthead: cream + text wordmark ---------- */
.masthead{padding:30px 36px 0;display:flex;justify-content:space-between;align-items:flex-start;}
.brand{flex:1;}
.brand .wordmark{font-family:var(--type-display);font-weight:700;font-size:28px;letter-spacing:.18em;color:var(--brand-primary);line-height:1;}
.brand .tag{font-family:var(--type-display);font-weight:300;font-size:14px;letter-spacing:.34em;color:var(--brand-primary);margin-top:3px;line-height:1;}
.docmeta{text-align:right;font-size:8.5px;color:var(--brand-muted);line-height:1.8;letter-spacing:.06em;text-transform:uppercase;font-weight:400;}
.docmeta strong{color:var(--brand-ink);font-weight:600;display:inline-block;min-width:65px;}

.titleblock{padding:24px 36px 0;}
.kicker{font-family:var(--type-body);font-size:8.5px;letter-spacing:.42em;text-transform:uppercase;color:var(--brand-secondary);font-weight:600;}
.title{font-family:var(--type-display);font-weight:600;font-size:30px;margin:6px 0 4px;color:var(--brand-ink);letter-spacing:.01em;line-height:1.1;}
.subtitle{font-family:var(--type-body);font-size:10.5px;color:var(--brand-muted);font-weight:400;letter-spacing:.04em;}
.divider{height:1px;background:var(--brand-primary);margin:14px 36px 0;border:0;opacity:.4;}

.body{padding:18px 36px 20px;flex:1;display:block;}

/* ---------- hero ---------- */
.hero{display:flex;gap:16px;margin:0 0 16px;}
.subject{flex:1.1;background:var(--brand-band);border:1px solid var(--brand-rule);border-radius:2px;padding:14px 16px;}
.subject .lbl{font-family:var(--type-body);font-size:7.5px;letter-spacing:.32em;text-transform:uppercase;color:var(--brand-secondary);font-weight:600;margin-bottom:6px;}
.subject .addr{font-family:var(--type-display);font-weight:600;font-size:18px;color:var(--brand-ink);line-height:1.2;letter-spacing:.01em;}
.subject .loc{font-size:9.5px;color:var(--brand-muted);margin:3px 0 9px;letter-spacing:.03em;}
.specs{display:flex;flex-wrap:wrap;gap:5px 0;}
.specs div{width:50%;font-size:9.5px;color:var(--brand-muted);font-weight:400;}
.specs b{color:var(--brand-ink);font-weight:600;}
.verdict{flex:1;background:var(--brand-primary);color:var(--brand-paper);border-radius:2px;padding:14px 18px;
         display:flex;flex-direction:column;justify-content:center;position:relative;overflow:hidden;}
.verdict::after{content:"";position:absolute;left:-40px;bottom:-40px;width:120px;height:120px;
                background:radial-gradient(circle,var(--brand-secondary) 0%,transparent 70%);opacity:.4;}
.verdict .lbl{font-family:var(--type-body);font-size:7.5px;letter-spacing:.32em;text-transform:uppercase;color:rgba(250,246,242,.7);font-weight:600;position:relative;}
.verdict .val{font-family:var(--type-display);font-weight:600;font-size:34px;margin:4px 0 2px;letter-spacing:.01em;line-height:1;position:relative;}
.verdict .range{font-size:9.5px;color:rgba(250,246,242,.85);position:relative;letter-spacing:.02em;}
.verdict .delta{margin-top:9px;padding-top:9px;border-top:1px solid rgba(250,246,242,.2);font-size:9px;color:rgba(250,246,242,.92);position:relative;line-height:1.5;}
.verdict .delta b{color:#fff;font-weight:600;}

.exec{font-family:var(--type-display);font-size:13px;line-height:1.55;color:var(--brand-ink);
      border-left:2px solid var(--brand-secondary);padding:2px 0 2px 14px;margin:0 0 14px;font-weight:400;font-style:italic;}

.kpis{display:flex;border-top:1px solid var(--brand-rule);border-bottom:1px solid var(--brand-rule);
      margin:0 0 16px;background:var(--brand-band);}
.kpi{flex:1;padding:10px 12px;border-right:1px solid var(--brand-rule);}
.kpi:last-child{border-right:0;}
.kpi .n{font-family:var(--type-display);font-weight:600;font-size:20px;color:var(--brand-slate);line-height:1;letter-spacing:.005em;}
.kpi .l{font-family:var(--type-body);font-size:7.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--brand-muted);margin-top:5px;font-weight:500;}
.kpi .s{font-size:8.5px;color:var(--brand-muted);margin-top:2px;font-style:italic;}

h2.sec{font-family:var(--type-body);font-size:9.5px;letter-spacing:.32em;text-transform:uppercase;color:var(--brand-secondary);margin:0 0 7px;
       padding-bottom:5px;border-bottom:1px solid var(--brand-primary-light,var(--brand-primary));font-weight:600;
       display:flex;justify-content:space-between;align-items:baseline;}
h2.sec span{font-family:var(--type-display);font-size:11px;letter-spacing:.02em;color:var(--brand-muted);text-transform:none;font-weight:400;font-style:italic;}

table{width:100%;border-collapse:collapse;margin:0 0 14px;}
thead th{font-family:var(--type-body);font-size:7px;letter-spacing:.18em;text-transform:uppercase;color:var(--brand-muted);
         text-align:right;padding:0 7px 5px;border-bottom:1px solid var(--brand-rule);font-weight:600;}
thead th.l{text-align:left;}
tbody td{padding:5.5px 7px;border-bottom:1px solid var(--brand-rule);text-align:right;font-variant-numeric:tabular-nums;font-size:9.5px;font-weight:400;}
tbody td.l{text-align:left;}
tbody tr:nth-child(even){background:var(--brand-band);}
tr.subj{background:rgba(159,135,122,.12) !important;}
tr.subj td{border-bottom:1px solid var(--brand-secondary);}
.addr2{font-family:var(--type-display);font-weight:600;font-size:11px;color:var(--brand-ink);letter-spacing:.01em;}
.sub{color:var(--brand-muted);font-size:8.5px;font-weight:400;font-style:italic;margin-top:1px;}
.tag{display:inline-block;font-family:var(--type-body);font-size:6.5px;letter-spacing:.18em;text-transform:uppercase;padding:2px 6px;
     border-radius:1px;font-weight:600;margin-left:5px;vertical-align:middle;}
.tag.key{background:var(--brand-ink);color:var(--brand-paper);}
.tag.subjt{background:var(--brand-secondary);color:var(--brand-paper);}
.tag.note{background:var(--brand-primary);color:var(--brand-paper);}
.tag.warn{background:var(--brand-flag);color:var(--brand-paper);}
.tag.pend{background:#2563eb;color:#fff;}

.twocol{display:flex;gap:16px;}
.twocol > div{flex:1;}
.panel{background:var(--brand-band);border:1px solid var(--brand-rule);border-radius:2px;padding:11px 14px;font-size:9.5px;color:var(--brand-ink);line-height:1.55;}
.panel.accent{border-left:2px solid var(--brand-secondary);}
.panel.dark{background:var(--brand-ink);color:rgba(250,246,242,.88);border:0;}
.panel.dark b{color:#fff;}
.panel.dark .h{color:var(--brand-primary-light,var(--brand-primary));}
.panel .h{font-family:var(--type-body);font-size:7.5px;letter-spacing:.32em;text-transform:uppercase;color:var(--brand-secondary);font-weight:600;margin-bottom:7px;}
.panel b{color:var(--brand-ink);font-weight:600;}
.panel ul{margin:6px 0 0;padding-left:14px;}
.panel li{margin-bottom:4px;}
.recprice{font-family:var(--type-display);font-weight:700;font-size:17px;color:var(--brand-secondary);letter-spacing:.005em;}
.pstriped td:first-child{font-weight:500;}

/* ---------- footer: beige band + text wordmark ---------- */
.foot{background:var(--brand-accent);padding:16px 36px 16px;border-top:1px solid var(--brand-ink);margin-top:auto;}
.foot .sig{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.foot .who{font-family:var(--type-body);font-size:9px;color:var(--brand-ink);letter-spacing:.02em;}
.foot .who strong{font-family:var(--type-display);color:var(--brand-ink);font-size:13px;display:block;font-weight:600;letter-spacing:.02em;}
.foot-brand{text-align:right;}
.foot-brand .wm{font-family:var(--type-display);font-weight:700;font-size:16px;color:var(--brand-primary);letter-spacing:.18em;line-height:1;}
.foot-brand .wt{font-family:var(--type-display);font-weight:300;font-size:9px;color:var(--brand-primary);letter-spacing:.32em;margin-top:2px;}
.foot .disc{font-size:7.5px;color:var(--brand-muted);line-height:1.5;letter-spacing:.02em;font-style:italic;}

/* ---------- valuation-confidence chip (in verdict card) ---------- */
.conf{display:inline-flex;align-items:center;gap:5px;margin-top:9px;font-family:var(--type-body);font-size:7.5px;
      letter-spacing:.2em;text-transform:uppercase;font-weight:600;color:rgba(250,246,242,.92);position:relative;}
.conf::before{content:"";width:7px;height:7px;border-radius:50%;background:#fff;}
.conf.cHigh::before{background:var(--brand-good);}
.conf.cModerate::before{background:#d9a441;}
.conf.cLow::before{background:var(--brand-flag);}

/* ---------- pricing & absorption band (price -> expected DOM) ---------- */
.dband{display:flex;border-top:1px solid var(--brand-rule);border-bottom:1px solid var(--brand-rule);
       background:var(--brand-band);margin:0 0 16px;}
.dcell{flex:1;padding:10px 12px;border-right:1px solid var(--brand-rule);}
.dcell:last-child{border-right:0;}
.dcell.rec{background:rgba(159,135,122,.12);box-shadow:inset 2px 0 0 var(--brand-secondary);}
.dcell .dl{font-family:var(--type-body);font-size:7.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--brand-muted);font-weight:500;}
.dcell .dp{font-family:var(--type-display);font-size:16px;font-weight:600;color:var(--brand-ink);margin-top:3px;line-height:1;}
.dcell .dd{font-family:var(--type-display);font-size:15px;font-weight:600;color:var(--brand-secondary);margin-top:5px;line-height:1;}
.dcell .dd span{font-size:8.5px;color:var(--brand-muted);}
.dcell .dr{font-size:8.5px;color:var(--brand-muted);margin-top:3px;font-style:italic;}

@media print{
  html,body{margin:0;padding:0;background:#fff;}
  body{font-size:9.5px;}
  .page{margin:0;box-shadow:none;width:8.5in;min-height:11in;page-break-after:always;}
  .page:last-child{page-break-after:auto;}
  @page{size:8.5in 11in;margin:0;}
  table,tr,thead,tbody{page-break-inside:avoid;}
  .hero,.kpis,.kpi,.panel,.subject,.verdict,.exec{page-break-inside:avoid;}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact;}
}
"""


SKELETONS: dict[str, str] = {
    "dark_band": SKELETON_DARK_BAND,
    "cream_serif": SKELETON_CREAM_SERIF,
}


def get_skeleton(layout_style: str) -> str:
    """Return the skeleton CSS for the named layout style.

    Raises :class:`KeyError` (via dict access) for an unknown style so callers
    fail loudly during template selection.
    """
    if layout_style not in SKELETONS:
        raise ValueError(
            f"Unknown layout_style: {layout_style!r}. "
            f"Available: {sorted(SKELETONS)}"
        )
    return SKELETONS[layout_style]
