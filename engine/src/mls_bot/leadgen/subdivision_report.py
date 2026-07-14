"""SUBDIVISION_REPORT — every property in a named subdivision.

Not really a "lead" category — it's a neighborhood inventory for circle
prospecting, client buyer searches, comp pulls, or understanding who owns
what inside a specific pocket of town.

Per property the output includes:
  - site address, parcel_id, owner name(s), owner type, owner-occupied flag
  - mailing address
  - tenure (years since last recorded sale)
  - last sale date and price
  - current assessed total / land / building, + assessed/paid gain %
  - acres, year built, beds/baths, SFLA, zoning, subdivision
  - other_parcels_same_mail  : how many *other* parcels share their mailbox
  - other_parcels_same_name  : how many *other* parcels share the owner name
  - other_parcels_combined   : unique count combining both (excludes this one)

Config knobs:
  jurisdiction    "BLACKSBURG" (default)
  subdivision     required; case-insensitive substring match on subd_name
                  (e.g. "STROUBLES MILL" matches "STROUBLES MILL SUBD")
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .base import Lead, register
from .helpers import (
    classify_owner,
    filter_jurisdiction,
    is_owner_occupied,
    mail_key,
    parse_float,
    tenure_years,
)


@register("SUBDIVISION_REPORT")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    subdivision = str(config.get("subdivision", "")).strip().upper()
    if not subdivision:
        print("!! SUBDIVISION_REPORT requires --cfg subdivision=NAME")
        return []

    all_rows = filter_jurisdiction(rows, config.get("jurisdiction", "BLACKSBURG"))

    # Pre-compute "everything at this mailbox / by this owner name" across the
    # whole jurisdiction, so we can answer "do they own anything else?".
    by_mail: dict[str, list[dict]] = defaultdict(list)
    by_owner: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        mk = mail_key(r)
        if mk:
            by_mail[mk].append(r)
        owner = (r.get("owner1") or "").strip().upper()
        if owner:
            by_owner[owner].append(r)

    matching = [r for r in all_rows if subdivision in (r.get("subd_name") or "").upper()]
    if not matching:
        query_words = set(subdivision.split())
        similar: set[str] = set()
        for r in all_rows:
            raw = r.get("subd_name") or ""
            if not raw:
                continue
            if query_words & set(raw.upper().split()):
                similar.add(raw)
        print(f"!! No parcels have a subdivision containing {subdivision!r}.")
        if similar:
            print("   Subdivisions sharing a word with your query:")
            for s in sorted(similar)[:25]:
                print(f"     - {s}")
        return []

    leads: list[Lead] = []
    today = date.today()
    for r in matching:
        owner = (r.get("owner1") or "").strip()
        owner_key = owner.upper()
        owner2 = (r.get("owner2") or "").strip()
        site = (r.get("site_addr1") or "").strip()
        parcel_id = r.get("parcel_id")
        mk = mail_key(r)

        same_mail_group = by_mail.get(mk, [])
        same_name_group = by_owner.get(owner_key, [])

        same_mail_count = max(0, len(same_mail_group) - 1)
        same_name_count = max(0, len(same_name_group) - 1)

        combined_ids: set[str] = set()
        for p in same_mail_group:
            pid = p.get("parcel_id")
            if pid and pid != parcel_id:
                combined_ids.add(pid)
        for p in same_name_group:
            pid = p.get("parcel_id")
            if pid and pid != parcel_id:
                combined_ids.add(pid)

        assessed_total = parse_float(r.get("assessed_total")) or 0
        assessed_land = parse_float(r.get("assessed_land")) or 0
        assessed_bldg = parse_float(r.get("assessed_bldg")) or 0
        paid = parse_float(r.get("last_sale_price")) or 0
        t = tenure_years(r, today)
        occ = is_owner_occupied(r)

        gain_pct: float | str = ""
        if paid > 0 and assessed_total > 0:
            gain_pct = round((assessed_total / paid - 1) * 100, 1)

        leads.append(Lead(
            category="SUBDIVISION_REPORT",
            key=parcel_id or f"{owner}@{site}",
            score=0,
            parcels=[r],
            detail={
                "summary": f"{site}  |  {owner}  |  tenure {t}y  |  "
                           f"assessed ${assessed_total:,.0f}",
                "site": site,
                "parcel_id": parcel_id,
                "owner": owner,
                "owner2": owner2,
                "owner_type": classify_owner(r.get("owner1")),
                "owner_occupied": "" if occ is None else occ,
                "mail": mk,
                "tenure_years": t if t is not None else "",
                "bought_on": r.get("last_sale_date") or "",
                "bought_for": paid if paid else "",
                "assessed_total": assessed_total,
                "assessed_land": assessed_land,
                "assessed_bldg": assessed_bldg,
                "gain_vs_sale_pct": gain_pct,
                "acres": parse_float(r.get("acres")) or "",
                "year_built": r.get("year_built") or "",
                "bedrooms": r.get("bedrooms") or "",
                "full_baths": r.get("full_baths") or "",
                "half_baths": r.get("half_baths") or "",
                "sfla": r.get("sfla") or "",
                "zoning": r.get("zoning") or "",
                "subd_name": r.get("subd_name") or "",
                "other_parcels_same_mail": same_mail_count,
                "other_parcels_same_name": same_name_count,
                "other_parcels_combined": len(combined_ids),
            },
        ))

    leads.sort(key=lambda l: (l.detail.get("site") or "").upper())
    return leads
