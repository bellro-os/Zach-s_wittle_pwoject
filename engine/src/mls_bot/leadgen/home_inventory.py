"""HOME_INVENTORY — every home in the jurisdiction.

A "home" is a parcel that:
  - has a building (year_built > 0 OR assessed_bldg > 0 OR sfla > 0)
  - is residentially zoned (R-*, RM-*, PR, RR)
  - isn't government / HOA / institution owned

Output is the same rich-detail schema as SUBDIVISION_REPORT: owner info,
tenure, sale history, assessment, specs, and how many other Blacksburg
parcels the owner holds (by mailing address and by name).

Config knobs:
  jurisdiction    "BLACKSBURG" (default)
  owner_type      "all" (default) | "person" | "entity"
  include_govt    False (exclude HOAs, town-owned homes, etc.)
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


_RESIDENTIAL_ZONE_PREFIXES = ("R-", "RM-", "PR", "RR")


def _is_residential(zoning: str | None) -> bool:
    if not zoning:
        return False
    z = zoning.strip().upper()
    return any(z.startswith(p) for p in _RESIDENTIAL_ZONE_PREFIXES)


def _has_building(row: dict) -> bool:
    year_built = row.get("year_built")
    assessed_bldg = parse_float(row.get("assessed_bldg")) or 0
    sfla = row.get("sfla")
    try:
        sfla_val = int(sfla) if sfla not in (None, "") else 0
    except (TypeError, ValueError):
        sfla_val = 0
    try:
        yb = int(year_built) if year_built not in (None, "") else 0
    except (TypeError, ValueError):
        yb = 0
    return yb > 0 or assessed_bldg > 0 or sfla_val > 0


@register("HOME_INVENTORY")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    owner_type = str(config.get("owner_type", "all")).lower()
    include_govt = str(config.get("include_govt", False)).lower() in ("true", "1", "yes")

    all_rows = filter_jurisdiction(rows, config.get("jurisdiction", "BLACKSBURG"))

    # Indexes for "other properties owned" — built across the whole jurisdiction
    # so we capture cross-subdivision ownership.
    by_mail: dict[str, list[dict]] = defaultdict(list)
    by_owner: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        mk = mail_key(r)
        if mk:
            by_mail[mk].append(r)
        owner = (r.get("owner1") or "").strip().upper()
        if owner:
            by_owner[owner].append(r)

    leads: list[Lead] = []
    today = date.today()

    for r in all_rows:
        if not _has_building(r):
            continue
        if not _is_residential(r.get("zoning")):
            continue
        otype = classify_owner(r.get("owner1"))
        if not include_govt and otype == "govt_or_institution":
            continue
        if owner_type != "all" and otype != owner_type:
            continue

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
            category="HOME_INVENTORY",
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
                "owner_type": otype,
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

    def _sort_key(lead: Lead) -> tuple[int, str]:
        t = lead.detail.get("tenure_years")
        tenure = t if isinstance(t, int) else -1
        return (-tenure, (lead.detail.get("site") or "").upper())

    # Longest-held first. Homes with no recorded sale date fall to the bottom.
    leads.sort(key=_sort_key)
    return leads
