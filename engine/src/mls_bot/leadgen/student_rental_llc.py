"""STUDENT_RENTAL_LLC — Blacksburg-specific tired-landlord signal.

Signal (all must hold):
  - jurisdiction = BLACKSBURG
  - zoning in a configurable set of student-rental-dense zones
    (defaults to R-4, RM-27, RM-48 which cover most of the
    Progress/Prices Fork / near-campus corridor)
  - absentee (mail != site)
  - classify_owner = entity (LLC, INC, Properties, etc.)
  - tenure >= min_tenure years (default 7) — "tired" means they've
    weathered at least one student turnover cycle

Hook: owner holds a cash-flowing but low-hands-on student rental they
bought when the market was cheaper; current rates + operating costs +
student-tenant wear-and-tear make them a candidate to exit. The higher
the tenure and assessed uplift, the more incentive to 1031 into
something easier.

Config knobs:
  jurisdiction   "BLACKSBURG"  (usually leave as is)
  zones          "R-4,RM-27,RM-48"  (comma-separated)
  min_tenure     7
  min_equity_pct 40   (assessed / paid threshold; 0 to disable)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .base import Lead, register
from .helpers import (
    _norm_addr,
    filter_jurisdiction,
    is_entity,
    is_owner_occupied,
    mail_key,
    parse_float,
    tenure_years,
)


def _parse_zones(raw: str | None) -> set[str]:
    default = {"R-4", "RM-27", "RM-48"}
    if not raw:
        return default
    return {z.strip().upper() for z in raw.split(",") if z.strip()}


@register("STUDENT_RENTAL_LLC")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    jurisdiction = config.get("jurisdiction", "BLACKSBURG")
    min_tenure = int(config.get("min_tenure", 7))
    min_equity_pct = float(config.get("min_equity_pct", 40))
    zones = _parse_zones(config.get("zones"))

    rows = filter_jurisdiction(rows, jurisdiction)
    today = date.today()

    # Group by (mail_key, normalized site address) so a 3-unit building with
    # three PARCEL_IDs collapses to one lead.
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if not is_entity(r):
            continue
        if is_owner_occupied(r) is not False:
            continue
        z = (r.get("zoning") or "").strip().upper()
        if z not in zones:
            continue
        t = tenure_years(r, today)
        if t is None or t < min_tenure:
            continue
        mk = mail_key(r)
        sk = _norm_addr(r.get("site_addr1"))
        if not mk or not sk:
            continue
        groups[(mk, sk)].append(r)

    leads: list[Lead] = []
    for (mk, sk), parcels in groups.items():
        # use the most-recent sale from the group for pricing/tenure
        parcels.sort(key=lambda p: (p.get("last_sale_date") or ""), reverse=True)
        head = parcels[0]
        assessed = sum(parse_float(p.get("assessed_total")) or 0 for p in parcels)
        paid = parse_float(head.get("last_sale_price")) or 0
        equity_pct = 0.0
        if paid > 0 and assessed > paid:
            equity_pct = (1 - paid / assessed) * 100
        if equity_pct < min_equity_pct and paid > 0:
            continue

        t = tenure_years(head, today) or 0
        z = (head.get("zoning") or "").strip().upper()
        owner = (head.get("owner1") or "").strip()
        site = (head.get("site_addr1") or "").strip()

        score = 40
        score += min(t, 20)
        score += int(min(equity_pct, 50) / 2)
        if assessed >= 500_000:
            score += 10
        if len(parcels) > 1:
            score += 5  # multi-parcel building = bigger handle

        leads.append(Lead(
            category="STUDENT_RENTAL_LLC",
            key=f"{owner} @ {site}",
            score=min(score, 100),
            parcels=parcels,
            detail={
                "summary": f"{owner} — {site} — zone {z}, {t}y held, "
                           f"{equity_pct:.0f}% equity proxy, {len(parcels)} parcel(s)",
                "owner": owner,
                "site": site,
                "mail": mk,
                "zoning": z,
                "tenure_years": t,
                "bought_on": head.get("last_sale_date"),
                "bought_for": f"${paid:,.0f}" if paid else "?",
                "assessed_total": f"${assessed:,.0f}",
                "equity_pct": round(equity_pct, 1),
                "parcel_count": len(parcels),
                "bedrooms": head.get("bedrooms"),
                "sfla": head.get("sfla"),
                "subd_name": head.get("subd_name"),
            },
        ))

    leads.sort(key=lambda l: l.score, reverse=True)
    return leads
