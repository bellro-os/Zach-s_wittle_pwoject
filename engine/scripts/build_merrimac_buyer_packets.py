"""Buyer-side outreach packets for the Merrimac small-farm shortlist.

Different from the seller-pitch mail_merge: here the user is the buyer
asking the property owner if they'd consider selling. Different tone, different
template, but reuses the agent_card branding + Edge-headless PDF rendering.

Output:
  outputs/merrimac_buyer_packets/<tracking_id>.html
  outputs/merrimac_buyer_packets/<tracking_id>.pdf
  outputs/merrimac_buyer_packets/index.csv  (skip-trace URLs + owner contact)

Run:
  PYTHONPATH=src python scripts/build_merrimac_buyer_packets.py
"""

from __future__ import annotations

import csv
import hashlib
import sys
import urllib.parse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mls_bot.analytics.cma import _load_agent_card, render_pdf

CANDIDATES_CSV = ROOT / "outputs" / "merrimac_farm_candidates.csv"
OUT_DIR = ROOT / "outputs" / "merrimac_buyer_packets"
TOP_N = 10
LOCALITY_FOR_SKIPTRACE = "BLACKSBURG"


# ---------- skip-trace URL helpers ------------------------------------------

def _q(s: str) -> str:
    return urllib.parse.quote(s or "")


def scc_lookup_url(name: str) -> str:
    return ("https://cis.scc.virginia.gov/EntitySearch/AdvancedSearch?searchType=BUSINESS"
            f"&name={_q(name.strip())}")


def whitepages_url(owner: str, locality: str) -> str:
    return (f"https://www.whitepages.com/name/"
            f"{_q(owner.replace(' ', '-'))}/"
            f"{_q(locality.upper())}-VA")


def true_people_url(owner: str, locality: str) -> str:
    return (f"https://www.truepeoplesearch.com/results?"
            f"name={_q(owner)}&citystatezip={_q(locality + ' VA')}")


def google_url(owner: str, mail_addr: str) -> str:
    return f"https://www.google.com/search?q={_q(owner + ' ' + mail_addr)}"


def linkedin_url(owner: str) -> str:
    # LinkedIn search by name
    return f"https://www.linkedin.com/search/results/people/?keywords={_q(owner)}"


def montva_search_url(parcel_id: str) -> str:
    """Montgomery County GIS direct parcel link."""
    return f"https://maps.montva.com/?parcelId={_q(parcel_id)}"


# ---------- entity vs person -----------------------------------------------

def is_entity(owner: str) -> bool:
    import re
    return bool(re.search(
        r"\b(LLC|INC|CORP|TRUST|LP|LLP|LTD|FOUNDATION|HOLDINGS|PROPERTIES|"
        r"REALTY|PARTNERSHIP|ASSOCIATES)\b", owner, re.I))


def owner_first_name(owner: str) -> str:
    """Best-effort first-name guess from county records.
    County format is usually LASTNAME FIRSTNAME [MIDDLE]."""
    import re
    if is_entity(owner):
        return "Property Owner"
    if re.search(r"\b(TRUSTEE|LIFE\s+ESTATE|HEIRS)\b", owner, re.I):
        return "Property Owner"
    parts = owner.replace(",", " ").split("&")[0].split()
    if len(parts) >= 2:
        cand = parts[1]
        if cand.isalpha() and len(cand) >= 2:
            return cand.title()
    return "Property Owner"


def addressee(owner: str) -> str:
    """How to address the recipient — Mr/Ms or 'Trustees/Executors'."""
    import re
    if re.search(r"TRUSTEE|TRUST\b", owner, re.I):
        return "To the trustees,"
    if re.search(r"ESTATE|HEIRS", owner, re.I):
        return "To the heirs / estate representatives,"
    if is_entity(owner):
        return "To whom it may concern,"
    return f"Dear {owner_first_name(owner)},"


# ---------- tracking id ----------------------------------------------------

def tracking_id(parcel_id: str) -> str:
    h = hashlib.sha1(f"merrimac|{parcel_id}".encode()).hexdigest()
    return ("M" + h[:5]).upper()


# ---------- letter HTML ----------------------------------------------------

def _fmt_money(v) -> str:
    try:
        f = float(v)
        return f"${f:,.0f}" if f else ""
    except (TypeError, ValueError):
        return ""


def render_packet(c: dict, agent: dict, today: str) -> str:
    """One-page acquisition packet HTML for a single prospect."""
    tid = tracking_id(c["parcel_id"])
    owner = c["owner"]
    addr_line = addressee(owner)
    site = (c.get("site") or "").strip() or f"your {c['acres']}-acre parcel off {c.get('subd_name') or 'Merrimac Road'}"
    acres = c["acres"]
    zoning = c.get("zoning", "")
    yb = c.get("year_built") or ""
    has_struct = c.get("has_structure", "False") == "True" or c.get("has_structure") is True
    slope = c.get("slope_mean")
    try:
        slope_str = f"{float(slope):.1f}%"
    except (TypeError, ValueError):
        slope_str = "—"
    last_sale_date = (c.get("last_sale_date") or "")[:10]
    last_sale_price = _fmt_money(c.get("last_sale_price"))
    assessed = _fmt_money(c.get("assessed_total"))

    purchase_line = ""
    if last_sale_date and last_sale_price:
        purchase_line = f"County records show the property last transferred {last_sale_date} for {last_sale_price}."
    elif last_sale_date:
        purchase_line = f"County records show the property last transferred {last_sale_date}."

    # Skip-trace URLs (also surfaced on the index CSV)
    locality = LOCALITY_FOR_SKIPTRACE
    if not is_entity(owner):
        skip_links = (
            f'<a href="{whitepages_url(owner, locality)}">Whitepages</a> · '
            f'<a href="{true_people_url(owner, locality)}">TruePeople</a> · '
            f'<a href="{google_url(owner, c.get("mail",""))}">Google</a>'
        )
    else:
        skip_links = (
            f'<a href="{scc_lookup_url(owner)}">VA SCC entity lookup</a> · '
            f'<a href="{google_url(owner, c.get("mail",""))}">Google</a>'
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{owner} — {site}</title>
<style>
  @page {{ size: letter; margin: 0.85in 0.75in; }}
  body {{ font-family: Georgia, serif; color: #1d1d1d; line-height: 1.55; font-size: 12pt; }}
  .header {{ border-bottom: 2px solid #2d6a3e; padding-bottom: 8px; margin-bottom: 22px; }}
  .header .agent-name {{ font-size: 16pt; font-weight: 700; color: #2d6a3e; }}
  .header .agent-meta {{ font-size: 10pt; color: #555; margin-top: 2px; }}
  .date {{ color: #555; font-size: 10.5pt; margin-bottom: 8px; }}
  .recipient {{ margin-bottom: 18px; font-size: 11pt; }}
  .stat-box {{ background: #f3f7f4; border-left: 4px solid #2d6a3e; padding: 12px 16px; margin: 14px 0; }}
  .stat-box .row {{ display: flex; justify-content: space-between; font-size: 11pt; padding: 2px 0; }}
  .stat-box .label {{ color: #555; }}
  .stat-box .val {{ font-weight: 600; }}
  ul {{ padding-left: 24px; margin: 6px 0 12px; }}
  li {{ margin: 3px 0; }}
  .signature {{ margin-top: 26px; }}
  .signature .name {{ font-weight: 700; font-size: 12pt; }}
  .footer {{ margin-top: 36px; border-top: 1px solid #ddd; padding-top: 10px;
             font-size: 9pt; color: #777; }}
  .skip {{ margin-top: 12px; font-size: 10pt; color: #444;
           padding: 8px 12px; background: #fafafa; border: 1px dashed #ccc; }}
  .tracking {{ font-family: "Courier New", monospace; font-size: 8pt; color: #aaa; margin-top: 6px; }}
</style></head><body>

<div class="header">
  <div class="agent-name">{agent.get('name','')}</div>
  <div class="agent-meta">
    {agent.get('brokerage','')} · {agent.get('phone','')} · {agent.get('email','')}
  </div>
</div>

<div class="date">{today}</div>

<div class="recipient">
  {owner.title()}<br>
  {(c.get('mail') or '').title()}
</div>

<p>{addr_line}</p>

<p>I'm a local New River Valley agent specializing in small farms and
acreage in the Merrimac corridor. I'm reaching out about your property at
<strong>{site}</strong>.</p>

<p>I'm in active conversation with buyers — and in some cases I represent
myself — looking for 5-to-50-acre parcels in this exact area. Properties like
yours, with A1 zoning and gentle slope, are surprisingly hard to find on the
open market. Most never get listed publicly because they sell privately
between neighbors.</p>

<div class="stat-box">
  <div class="row"><span class="label">Address</span><span class="val">{site}</span></div>
  <div class="row"><span class="label">Acreage</span><span class="val">{acres}</span></div>
  <div class="row"><span class="label">Zoning</span><span class="val">{zoning}</span></div>
  <div class="row"><span class="label">Mean slope</span><span class="val">{slope_str}</span></div>
  <div class="row"><span class="label">Structure</span><span class="val">{('Yes' if has_struct else 'Vacant land')}{(' (built ' + str(yb) + ')') if yb and has_struct else ''}</span></div>
  <div class="row"><span class="label">Current assessment</span><span class="val">{assessed}</span></div>
  <div class="row"><span class="label">Parcel #</span><span class="val">{c['parcel_id']}</span></div>
</div>

<p>{purchase_line}</p>

<p>If you've ever thought about selling — even casually — I'd love to share
two things with you:</p>

<ul>
  <li><strong>What your property would actually bring today</strong> — based on
      the most recent comps in the Merrimac corridor, not assessed value.
      The two numbers are usually quite different.</li>
  <li><strong>How a private sale works</strong> — no MLS listing, no showings,
      no signs in the yard. A clean conventional or cash offer with a
      flexible closing window. You stay in control of the timeline.</li>
</ul>

<p>If the answer is "not interested," that's a perfectly fine answer and you
won't hear from me again. If you'd like a no-obligation conversation, the
best way to reach me is by phone or text — my number is at the top of this
letter.</p>

<div class="signature">
  <p>Respectfully,</p>
  <div class="name">{agent.get('name','')}</div>
  <div>{agent.get('brokerage','')}</div>
  <div>{agent.get('phone','')} · {agent.get('email','')}</div>
</div>

<div class="footer">
  <strong>For my own records (research links — do not include in mailed copy):</strong>
  <div class="skip">{skip_links}</div>
  <div class="tracking">ref: {tid} · parcel {c['parcel_id']}</div>
</div>

</body></html>"""


# ---------- main ------------------------------------------------------------

def pick_top(rows: list[dict], n: int) -> list[dict]:
    """Sort by farm score; dedupe owner-only when same address (keep the highest-fs
    parcel per owner-site pair). Also drop research/educational/non-farm parcels
    that slipped past zone filter."""
    import re
    rows = [r for r in rows
            if not re.search(r"VPI|VA TECH CORP|RESEARCH CENTER", r.get("owner", ""), re.I)]
    rows = sorted(rows, key=lambda x: -float(x.get("_farm_score") or 0))
    seen = set()
    picked = []
    for r in rows:
        # Allow same owner across DIFFERENT parcels (Sult has 2 parcels of interest)
        key = (r["owner"], r["parcel_id"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)
        if len(picked) >= n:
            break
    return picked


def main() -> int:
    if not CANDIDATES_CSV.exists():
        print(f"missing {CANDIDATES_CSV}; run the Merrimac search first")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with CANDIDATES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    rows = pick_top(rows, TOP_N)
    print(f"top {len(rows)} prospects selected")

    agent_card = _load_agent_card() or {}
    agent = agent_card.get("agent") or {}
    today = date.today().strftime("%B %d, %Y")

    index_rows = []
    n_pdf = 0
    for c in rows:
        tid = tracking_id(c["parcel_id"])
        html = render_packet(c, agent, today)
        html_path = OUT_DIR / f"{tid}.html"
        html_path.write_text(html, encoding="utf-8")
        pdf_path = render_pdf(html_path)
        if pdf_path:
            n_pdf += 1

        owner = c["owner"]
        locality = LOCALITY_FOR_SKIPTRACE
        index_rows.append({
            "tracking_id": tid,
            "farm_score": c.get("_farm_score"),
            "parcel_id": c["parcel_id"],
            "owner": owner,
            "owner_type": "entity" if is_entity(owner) else "person",
            "site": c.get("site", ""),
            "mail_addr": c.get("mail", ""),
            "acres": c.get("acres"),
            "zoning": c.get("zoning"),
            "year_built": c.get("year_built"),
            "has_structure": c.get("has_structure"),
            "slope_mean": c.get("slope_mean"),
            "assessed_total": c.get("assessed_total"),
            "last_sale_date": c.get("last_sale_date"),
            "last_sale_price": c.get("last_sale_price"),
            "html": str(html_path),
            "pdf": str(pdf_path) if pdf_path else "",
            "scc_lookup_url": scc_lookup_url(owner) if is_entity(owner) else "",
            "whitepages_url": whitepages_url(owner, locality) if not is_entity(owner) else "",
            "true_people_url": true_people_url(owner, locality) if not is_entity(owner) else "",
            "google_url": google_url(owner, c.get("mail", "")),
            "linkedin_url": linkedin_url(owner) if not is_entity(owner) else "",
            "montva_gis_url": montva_search_url(c["parcel_id"]),
        })

    idx_path = OUT_DIR / "index.csv"
    if index_rows:
        with idx_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(index_rows[0].keys()))
            w.writeheader()
            for r in index_rows:
                w.writerow(r)

    print(f"  HTML packets: {len(rows)}")
    print(f"  PDF packets:  {n_pdf}")
    print(f"  out dir:      {OUT_DIR}")
    print(f"  index:        {idx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
