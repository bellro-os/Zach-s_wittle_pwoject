"""Generate per-parcel fact sheets for top DC candidates.

Reads the top N rows from a v3 ranked CSV and writes one Markdown fact
sheet per parcel under outputs/fact_sheets/<preset>/<rank>_<county>_<owner>.md

Each sheet has:
  - Header: rank, score, county, key dimensions
  - Site basics
  - Power infrastructure (queue tier, substation, voltage)
  - Connectivity (highway / fiber proxy)
  - Site quality (slope, flood, opp zone)
  - Setback compliance
  - Owner & tax info
  - Map links (Google Maps + county GIS lookup if known)
  - Outreach talking points (auto-generated based on data)
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:40].strip("_")


def _gmap(lat, lng) -> str:
    if not lat or not lng:
        return ""
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"


def _gmap_satellite(lat, lng) -> str:
    if not lat or not lng:
        return ""
    return f"https://www.google.com/maps/@{lat},{lng},800m/data=!3m1!1e3"


def _talking_points(r: dict) -> list[str]:
    pts: list[str] = []
    acres = float(r.get("acres") or 0)
    score = float(r.get("score_dc") or 0)
    sub_kv = r.get("min_volt_at_nearest_sub_kv") or "?"
    sub_mi = r.get("miles_to_sub_min_volt") or "?"
    queue = r.get("queue_tier") or ""
    util = r.get("primary_utility") or ""
    res_mi = r.get("miles_to_nearest_residential") or "?"
    hwy_mi = r.get("miles_to_major_highway") or "?"
    in_oz = r.get("in_opportunity_zone") == "Y"
    in_flood = r.get("in_floodplain") == "Y"
    dc_mi = r.get("miles_to_existing_dc") or "?"
    slope_p10 = r.get("pct_under_10pct_slope") or "?"
    tax_score = r.get("tax_tier_score") or "0"
    owner_type = r.get("owner_type") or "unknown"

    # Power
    if str(sub_kv) == "500":
        pts.append(f"**Adjacent to a 500 kV transmission corridor** ({sub_mi} mi to substation) — top-tier hyperscale grid access in VA.")
    elif str(sub_kv) == "230":
        pts.append(f"230 kV substation only **{sub_mi} mi** away — strong path to 100+ MW capacity.")
    elif str(sub_kv) in ("138", "115"):
        pts.append(f"{sub_kv} kV substation within {sub_mi} mi — workable for sub-100 MW phase 1.")

    # Queue
    if queue == "fast":
        pts.append(f"In **{util}** territory — historically faster new-load interconnect than Dominion.")
    elif queue == "moderate":
        pts.append(f"In {util} territory (moderate queue tier).")
    elif queue == "slow":
        pts.append(f"In Dominion territory — multi-year backlog for new large loads. Verify utility timeline before going hard.")

    # Acreage / scale
    if acres >= 500:
        pts.append(f"**{acres:.0f} acres** — supports a multi-building hyperscale campus phased over 1.4 GW range.")
    elif acres >= 250:
        pts.append(f"{acres:.0f} acres — single-building hyperscale or staged colocation campus.")
    elif acres >= 100:
        pts.append(f"{acres:.0f} acres — colocation-grade or initial phase of larger build.")
    elif acres >= 40:
        pts.append(f"{acres:.0f} acres — single-tenant or compact colocation site.")

    # Slope / buildability
    try:
        sp10 = float(slope_p10)
        if sp10 >= 90:
            pts.append(f"**{sp10:.0f}% of the parcel is under 10% slope** — minimal site grading required.")
        elif sp10 >= 75:
            pts.append(f"{sp10:.0f}% buildable under 10% slope — manageable grading.")
        elif sp10 >= 50:
            pts.append(f"Only {sp10:.0f}% under 10% slope — substantial grading needed; partial-grade prep recommended.")
    except (TypeError, ValueError):
        pass

    # Setback
    try:
        rmi = float(res_mi)
        rft = rmi * 5280
        if rft >= 5280:
            pts.append(f"**{rmi:.1f} mi from nearest residential parcel** — clears every VA county DC setback rule.")
        elif rft >= 1000:
            pts.append(f"~{rft:.0f} ft from nearest residential — meets most VA county minimums but may need site-plan tweaks.")
        elif rft >= 500:
            pts.append(f"~{rft:.0f} ft from nearest residential — at the threshold for some counties; verify.")
        else:
            pts.append(f"~{rft:.0f} ft from nearest residential — likely fails Henrico-style setback (500 ft min).")
    except (TypeError, ValueError):
        pass

    # Highway / fiber
    try:
        hmi = float(hwy_mi)
        if hmi <= 0.5:
            pts.append(f"On the doorstep of a major highway ({hmi:.2f} mi) — strong indicator of fiber backbone access.")
        elif hmi <= 2.0:
            pts.append(f"{hmi:.1f} mi to nearest interstate/US-highway — fiber accessibility likely good but verify carriers.")
        elif hmi <= 5.0:
            pts.append(f"{hmi:.1f} mi to a major highway — fiber may require last-mile build.")
    except (TypeError, ValueError):
        pass

    # Existing DC clustering
    try:
        dmi = float(dc_mi)
        if dmi <= 5:
            pts.append(f"**{dmi:.1f} mi to an existing DC campus** — local utility, fiber, and county zoning have already been worked through for the area.")
        elif dmi <= 15:
            pts.append(f"{dmi:.1f} mi to nearest existing DC — moderate clustering signal.")
    except (TypeError, ValueError):
        pass

    # Flood / OZ
    if in_flood:
        pts.append("⚠️ **Flagged as inside FEMA SFHA flood zone** — verify on a current FIRM panel before any LOI.")
    if in_oz:
        pts.append("Inside a federal Opportunity Zone — capital-gains tax treatment available for investors.")

    # Tax
    try:
        ts = int(tax_score)
        if ts >= 3:
            pts.append("County offers a **reduced DC equipment tax rate** ($0.20-$0.24/$100) — material long-term savings.")
        elif ts >= 2:
            pts.append("County DC equipment tax rate is competitive ($0.40-$0.50/$100).")
    except (TypeError, ValueError):
        pass

    # Owner
    if owner_type == "entity":
        pts.append("Owned by an entity — outreach should target the LLC's principal officers (use VA SCC Business Search to identify).")
    elif owner_type == "person":
        pts.append("Individual ownership — direct outreach via the listed mailing address.")

    return pts


def fact_sheet_md(rank: int, r: dict) -> str:
    score = r.get("score_dc", "")
    county = r.get("county", "")
    pid = r.get("parcel_id", "")
    owner = r.get("owner", "")
    owner2 = r.get("owner2", "")
    site = r.get("site") or "(no site address listed)"
    acres = r.get("acres", "")
    lat = r.get("lat", "")
    lng = r.get("lng", "")
    zoning = r.get("zoning") or "(unknown — verify with county)"
    util = r.get("primary_utility", "")
    queue = r.get("queue_tier", "")

    talking = _talking_points(r)
    talking_md = "\n".join(f"- {pt}" for pt in talking)

    mail = r.get("mail_addr1", "") or ""
    mail2 = r.get("mail_addr2", "") or ""
    mail_full = ", ".join(p for p in (mail, mail2) if p)

    return f"""# DC Candidate Fact Sheet — Rank #{rank}

**Score: {score} / 100**  ·  {acres} acres  ·  {county} County, VA

---

## Site

| | |
|---|---|
| **Owner** | {owner}{f' / {owner2}' if owner2 else ''} ({r.get('owner_type','')}) |
| **Parcel ID** | `{pid}` |
| **Site address** | {site} |
| **Coordinates** | {lat}, {lng} |
| **Zoning** | {zoning} |
| **County jurisdiction** | {r.get('jurisdiction') or county} |
| **Acres (sourced)** | {acres} |
| **Year built** | {r.get('year_built') or '—'} |
| **Last sale** | {r.get('last_sale_date') or '—'} for ${r.get('last_sale_price') or '—'} |
| **Assessed value (total / land / bldg)** | ${r.get('assessed_total') or '—'} / ${r.get('assessed_land') or '—'} / ${r.get('assessed_bldg') or '—'} |

[Open in Google Maps →]({_gmap(lat, lng)})  ·  [Satellite view →]({_gmap_satellite(lat, lng)})

---

## Power infrastructure

| | |
|---|---|
| **Primary utility** | {util} |
| **Queue tier** | {queue} |
| **Nearest substation (≥115 kV)** | {r.get('miles_to_sub_min_volt')} mi at {r.get('min_volt_at_nearest_sub_kv')} kV |
| **Nearest substation (any voltage)** | {r.get('miles_to_any_sub')} mi at {r.get('any_sub_voltage_kv')} kV |
| **Existing DC cluster proximity** | {r.get('miles_to_existing_dc')} mi |

---

## Connectivity & site access

| | |
|---|---|
| **Nearest major highway (fiber proxy)** | {r.get('miles_to_major_highway')} mi |
| **Nearest wastewater plant** | {r.get('miles_to_wwtp')} mi |

---

## Site quality

| | |
|---|---|
| **Slope (mean)** | {r.get('slope_mean_pct')}% |
| **Slope (max)** | {r.get('slope_max_pct')}% |
| **% under 5% slope** | {r.get('pct_under_5pct_slope')}% |
| **% under 10% slope** | {r.get('pct_under_10pct_slope')}% |
| **% under 15% slope** | {r.get('pct_under_15pct_slope')}% |
| **In FEMA flood zone** | {r.get('in_floodplain')} |
| **In Opportunity Zone** | {r.get('in_opportunity_zone')} |

---

## Setback / regulatory

| | |
|---|---|
| **Distance to nearest residential parcel** | {r.get('miles_to_nearest_residential')} mi |
| **County DC tax tier** (0-3, higher = better) | {r.get('tax_tier_score')} |

---

## Owner outreach

**Mailing address:** {mail_full or '(not in source data)'}

---

## Talking points

{talking_md}

---

## Methodology caveats

- Slope is based on a 30 m DEM sampled across an equivalent-area circle around the parcel centroid. For final due diligence, verify against a 1 m LiDAR or polygon-aware grading study.
- Substation distance assumes nearest qualifying voltage; **does not** reflect available capacity. Confirm with the utility's interconnection desk.
- Highway proximity is a fiber proxy, not a guarantee of carrier diversity. Verify routes with Lumen / Zayo / Crown Castle / Lumos.
- Zoning shown is from the source layer; some counties' zoning fields are unreliable (Charlotte, Brunswick, Wythe, Floyd, Patrick, Wise) — always verify with the county GIS or zoning office.
- FEMA flood data is ~74% complete for VA (some bad-offset gaps in the federal data feed). A `N` on flood doesn't 100% rule it out — pull a FIRM panel for any property going under contract.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="hyperscale",
                    choices=("piedmont", "appalachian", "hyperscale"))
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--in-csv", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    root = Path(__file__).parent.parent
    in_path = Path(args.in_csv) if args.in_csv else (
        root / "outputs" / f"all_parcels_dc_metrics_{args.preset}_v3.csv"
    )
    out_dir = Path(args.out_dir) if args.out_dir else (
        root / "outputs" / "fact_sheets" / args.preset
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    with in_path.open("r", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("passed_hard_filters") == "Y"]
    rows.sort(key=lambda r: -float(r.get("score_dc") or 0))
    rows = rows[: args.top_n]

    print(f"Generating {len(rows)} fact sheets in {out_dir}/")
    index_lines = [f"# {args.preset.title()} preset — top {len(rows)} fact sheets\n"]
    for i, r in enumerate(rows, 1):
        owner_slug = _slug(r.get("owner", "unknown"))
        county_slug = _slug(r.get("county", ""))
        fname = f"{i:02d}_{county_slug}_{owner_slug}.md"
        md = fact_sheet_md(i, r)
        (out_dir / fname).write_text(md, encoding="utf-8")
        index_lines.append(
            f"- **#{i}** · score {r.get('score_dc')} · {r.get('county')} · "
            f"{r.get('acres')} ac · {r.get('owner','')[:50]} → "
            f"[{fname}]({fname})"
        )
        print(f"  {fname}  (score {r.get('score_dc')})")

    (out_dir / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")
    print(f"\nWrote INDEX.md ({len(rows)+1} files total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
