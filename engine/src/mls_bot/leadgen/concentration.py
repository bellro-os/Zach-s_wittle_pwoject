"""CONCENTRATION — mini-landlord: 3+ parcels in one subdivision, same mail key.

Signal:
  - same normalized mailing address holds >= min_parcels parcels
  - those parcels are all within one `subd_name`
  - majority owner type is person (entity counterpart is better served by
    STUDENT_RENTAL_LLC or the existing top_by_mail view)
  - mostly absentee (landlord pattern) OR majority owner-occupied + adjacent
    owned parcels (expansion-minded homeowner)

This bridges from the existing top_by_mail work: instead of ranking by total
portfolio size, rank by density within one neighborhood. A mini-landlord with
three SFHs on the same street is a very different conversation than someone
with three scattered parcels countywide.

Config knobs:
  jurisdiction   "BLACKSBURG" (default)
  min_parcels    3
  owner_type     "person" (default) / "entity" / "all"
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .base import Lead, register
from .helpers import (
    _BAD_MAIL_KEYS,
    _norm_addr,
    classify_owner,
    filter_jurisdiction,
    is_owner_occupied,
    mail_key,
    parse_float,
)


@register("CONCENTRATION")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    min_parcels = int(config.get("min_parcels", 3))
    owner_type = str(config.get("owner_type", "person")).lower()

    rows = filter_jurisdiction(rows, config.get("jurisdiction"))

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        subd = (r.get("subd_name") or "").strip()
        if not subd:
            continue
        m = mail_key(r)
        if not m or m in _BAD_MAIL_KEYS:
            continue
        if owner_type != "all":
            if classify_owner(r.get("owner1")) != owner_type:
                continue
        groups[(m, subd)].append(r)

    leads: list[Lead] = []
    for (m, subd), parcels in groups.items():
        if len(parcels) < min_parcels:
            continue

        owner_occ = 0
        absentee = 0
        for p in parcels:
            occ = is_owner_occupied(p)
            if occ is True:
                owner_occ += 1
            elif occ is False:
                absentee += 1

        total_assessed = sum(parse_float(p.get("assessed_total")) or 0 for p in parcels)
        owner_names = Counter(p.get("owner1") or "?" for p in parcels)
        top_name, _ = owner_names.most_common(1)[0]

        sites = [(p.get("site_addr1") or "").strip() for p in parcels]
        sites = [s for s in sites if s]
        distinct_sites = len({_norm_addr(s) for s in sites})

        # score: distinct buildings is a far stronger signal than raw parcel
        # count, since one building can be split across many parcel_ids.
        score = 40 + min(distinct_sites * 8, 40)
        if absentee > owner_occ:
            score += 10
        if total_assessed >= 2_000_000:
            score += 10
        elif total_assessed >= 1_000_000:
            score += 5

        preview = []
        for p in parcels[:8]:
            site = (p.get("site_addr1") or "").strip()
            assessed = parse_float(p.get("assessed_total")) or 0
            zone = p.get("zoning") or "?"
            preview.append(f"{site}  |  assessed ${assessed:,.0f}  |  zone {zone}")

        leads.append(Lead(
            category="CONCENTRATION",
            key=f"{m} @ {subd}",
            score=min(score, 100),
            parcels=parcels,
            detail={
                "summary": f"{top_name} — {distinct_sites} building(s) ({len(parcels)} parcels) "
                           f"in {subd}, ${total_assessed:,.0f} assessed, mails to {m}",
                "top_owner": top_name,
                "owner_variants": dict(owner_names.most_common(4)),
                "subdivision": subd,
                "mail_key": m,
                "distinct_sites": distinct_sites,
                "parcel_count": len(parcels),
                "owner_occupied": owner_occ,
                "absentee": absentee,
                "total_assessed": round(total_assessed, 0),
                "parcels_preview": preview,
            },
        ))

    # Rank by distinct buildings first, then portfolio size
    leads.sort(
        key=lambda l: (l.detail.get("distinct_sites", 0), l.score, len(l.parcels)),
        reverse=True,
    )
    return leads
