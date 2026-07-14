"""TENURE_SWEET_SPOT — owner-occupied homes in the 3-7y bought window.

Signal:
  - site address matches mailing address (owner-occupied)
  - tenure (years since last recorded sale) falls in [tenure_min, tenure_max]
  - optionally restricted to residential zoning

This is a FARM list, not a hot-call list. Intended use: direct-mail farming,
door-knocking territories, "just-sold" / "just-listed" mailers. Expect
hundreds of rows in Blacksburg alone.

Config knobs:
  jurisdiction     "BLACKSBURG" (default) / "ALL" / etc.
  tenure_min       3
  tenure_max       7
  residential_only True (filters to R-* / RM-* / PR zones)
  min_assessed     0   (floor on assessed_total if you want to skip sheds/slivers)
"""

from __future__ import annotations

from datetime import date

from .base import Lead, register
from .helpers import (
    filter_jurisdiction,
    is_owner_occupied,
    parse_float,
    tenure_years,
)


_RESIDENTIAL_ZONE_PREFIXES = ("R-", "RM-", "PR", "RR")


def _is_residential(zoning: str | None) -> bool:
    if not zoning:
        return False
    z = zoning.strip().upper()
    return any(z.startswith(p) for p in _RESIDENTIAL_ZONE_PREFIXES)


@register("TENURE_SWEET_SPOT")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    tenure_min = int(config.get("tenure_min", 3))
    tenure_max = int(config.get("tenure_max", 7))
    residential_only = str(config.get("residential_only", True)).lower() not in ("false", "0", "no")
    min_assessed = float(config.get("min_assessed", 0))

    rows = filter_jurisdiction(rows, config.get("jurisdiction"))
    today = date.today()

    leads: list[Lead] = []
    for r in rows:
        if is_owner_occupied(r) is not True:
            continue
        t = tenure_years(r, today)
        if t is None or t < tenure_min or t > tenure_max:
            continue
        if residential_only and not _is_residential(r.get("zoning")):
            continue
        assessed = parse_float(r.get("assessed_total")) or 0
        if assessed < min_assessed:
            continue

        # score: tenure near median (6-7y) scores higher; assessed_total gives a lift
        t_score = max(0, 30 - abs(t - 6) * 5)  # peak at 6y
        a_score = 0
        if assessed >= 750_000: a_score = 20
        elif assessed >= 500_000: a_score = 15
        elif assessed >= 300_000: a_score = 10
        elif assessed >= 150_000: a_score = 5
        score = 40 + t_score + a_score

        owner = (r.get("owner1") or "").strip()
        site = (r.get("site_addr1") or "").strip()
        sale_date = r.get("last_sale_date")
        sale_price = parse_float(r.get("last_sale_price"))

        leads.append(Lead(
            category="TENURE_SWEET_SPOT",
            key=r.get("parcel_id") or f"{owner}@{site}",
            score=min(score, 100),
            parcels=[r],
            detail={
                "summary": f"{owner} — {site} — {t}y tenure, ${assessed:,.0f} assessed",
                "owner": owner,
                "site": site,
                "tenure_years": t,
                "bought_on": sale_date,
                "bought_for": f"${sale_price:,.0f}" if sale_price else "?",
                "assessed": f"${assessed:,.0f}",
                "zoning": r.get("zoning"),
                "bedrooms": r.get("bedrooms"),
                "sfla": r.get("sfla"),
                "subd_name": r.get("subd_name"),
            },
        ))

    leads.sort(key=lambda l: l.score, reverse=True)
    return leads
