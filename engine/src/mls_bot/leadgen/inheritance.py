"""INHERITANCE_MULTI — likely heirs who just received 2+ parcels via estate transfer.

Signal:
  - owner is classified as a person (LLC / trust transfers also record
    sale_price=0 for recapitalizations and are excluded)
  - last_sale_price is 0 or null on every parcel in the bundle
  - 2+ parcels share the same normalized mailing address
  - those parcels were acquired on the same date
  - acquisition date is within the last `recency_years` (default 2)

Scoring prioritizes signals that indicate a real estate transfer over
self-directed estate planning (a living couple moving their property into
their own revocable trust also shows up with sale_price=0):
  - "ESTATE" in owner name → +20 (posthumous by definition)
  - "ETAL" in owner2 → +10 (multiple heirs)
  - distinct_sites >= 3 → +10 (real portfolio, not one split-parcel home)
  - owner2 contains "LIVING TRUST" or "REVOCABLE TRUST" AND
    distinct_sites == 1 → this is almost certainly self-estate-planning
    and is DOWNGRADED heavily (still listed in case user wants it).

Grouping key: (normalized mail address, sale date). Each matching group
becomes one lead — the heir who received the bundle.

Config knobs:
  jurisdiction        "BLACKSBURG" (default) / "ALL" / etc.
  recency_years       2
  min_parcels         2
  min_distinct_sites  1 (set to 2 if you only want heirs of dispersed portfolios,
                         not estate bundles where all parcels are at one address)
"""

from __future__ import annotations

from datetime import date
from collections import defaultdict

from .base import Lead, register
from .helpers import (
    _BAD_MAIL_KEYS,
    filter_jurisdiction,
    is_person,
    mail_key,
    parse_float,
    site_key,
    tenure_years,
)


@register("INHERITANCE_MULTI")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    recency_years = int(config.get("recency_years", 2))
    min_parcels = int(config.get("min_parcels", 2))
    min_distinct_sites = int(config.get("min_distinct_sites", 1))

    rows = filter_jurisdiction(rows, config.get("jurisdiction"))
    today = date.today()
    cutoff = date(today.year - recency_years, today.month, today.day)

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if not is_person(r):
            continue
        sale_price = parse_float(r.get("last_sale_price"))
        if sale_price not in (None, 0.0):
            continue
        sale_date = r.get("last_sale_date")
        if not sale_date:
            continue
        m = mail_key(r)
        if not m or m in _BAD_MAIL_KEYS:
            continue
        groups[(m, sale_date)].append(r)

    leads: list[Lead] = []
    for (m, sale_date), parcels in groups.items():
        if len(parcels) < min_parcels:
            continue
        # cutoff check on the sale date (same for all in the group by construction)
        sd = parcels[0].get("last_sale_date") or ""
        try:
            if date.fromisoformat(sd) < cutoff:
                continue
        except ValueError:
            continue

        distinct_sites = len({site_key(p) for p in parcels if p.get("site_addr1")})
        if distinct_sites < min_distinct_sites:
            continue

        owner_names = sorted({(p.get("owner1") or "").strip() for p in parcels if p.get("owner1")})
        owner2_names = sorted({(p.get("owner2") or "").strip() for p in parcels if p.get("owner2")})
        total_assessed = sum(parse_float(p.get("assessed_total")) or 0 for p in parcels)

        preview = []
        for p in parcels[:8]:
            site = (p.get("site_addr1") or "").strip()
            assessed = parse_float(p.get("assessed_total")) or 0
            zoning = p.get("zoning") or "?"
            preview.append(f"{site}  |  assessed ${assessed:,.0f}  |  zone {zoning}")

        # Score breakdown — see module docstring for rationale
        score = 40
        score += min(len(parcels) * 4, 20)
        if total_assessed >= 2_000_000: score += 15
        elif total_assessed >= 1_000_000: score += 10
        elif total_assessed >= 500_000:   score += 5

        owners_joined = " | ".join(owner_names)
        owner2_joined = " | ".join(owner2_names).upper()

        has_estate = "ESTATE" in owners_joined.upper()
        has_etal = "ETAL" in owner2_joined or "ET AL" in owner2_joined
        is_self_trust = (
            distinct_sites <= 1
            and ("LIVING TRUST" in owner2_joined or "REVOCABLE TRUST" in owner2_joined)
        )

        if has_estate:
            score += 20
        if has_etal:
            score += 10
        if distinct_sites >= 3:
            score += 10
        if is_self_trust:
            score -= 30  # likely self-directed estate planning, not a real inheritance

        primary_owner = owner_names[0] if owner_names else "?"
        signal = "ESTATE" if has_estate else "ETAL" if has_etal else (
            "SELF_TRUST" if is_self_trust else "HEIR"
        )
        leads.append(Lead(
            category="INHERITANCE_MULTI",
            key=f"{m} @ {sale_date}",
            score=max(0, min(score, 100)),
            parcels=parcels,
            detail={
                "summary": f"[{signal}] {primary_owner} — {len(parcels)} parcels at "
                           f"{distinct_sites} site(s), ${total_assessed:,.0f} assessed, "
                           f"transferred {sale_date}, mails to {m}",
                "signal": signal,
                "owner_names": ", ".join(owner_names),
                "owner2_names": ", ".join(n for n in owner2_names if n),
                "mail_key": m,
                "sale_date": sale_date,
                "total_assessed": round(total_assessed, 0),
                "distinct_sites": distinct_sites,
                "tenure_years": tenure_years(parcels[0], today),
                "parcels_preview": preview,
            },
        ))

    # Sort true heirs/estates above self-trust moves
    signal_rank = {"ESTATE": 3, "ETAL": 2, "HEIR": 1, "SELF_TRUST": 0}
    leads.sort(
        key=lambda l: (signal_rank.get(l.detail.get("signal", ""), 0), l.score, len(l.parcels)),
        reverse=True,
    )
    return leads
