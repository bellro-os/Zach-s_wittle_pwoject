"""EMPTY_LOTS — parcels with no building on them.

Signal (all must hold):
  - year_built is null / 0
  - assessed_bldg is null / 0
  - sfla (living area) is null / 0
  - parcel isn't government / HOA / institution owned (those are usually
    roads, parks, common areas — not sellable lots)
  - assessed_total > 0  (screens out HOA-common-area zero-value placeholders)
  - acres >= min_acres (default 0.05 — filters out slivers)

Optional distance filter:
  - max_miles_from_vt  straight-line miles from VT campus center
  - max_drive_min       approximate drive minutes (converted to miles)
  - reference           named anchor: "VT" (default), "DOWNTOWN_BLACKSBURG",
                        "CHRISTIANSBURG"; or pass explicit
                        reference_lat / reference_lng.

Distance requires lat/lng in the input JSONL. Run
`python scripts/enrich_coords.py --in ... --out ...` to add them.

Output: one lead per lot, ranked by acreage (biggest = most developable).
Shows acres, address, owner, mailing address, zoning, assessed value,
and — when a reference point is set — miles and approximate drive minutes.

Config knobs:
  jurisdiction       "BLACKSBURG" (default)
  min_acres          0.05
  owner_type         "person" (default) | "entity" | "all"
                     — "person" excludes LLCs, corps, trusts, developers,
                       investment groups. "entity" returns only those.
  include_govt       False   (include VDOT / town / park parcels)
  residential_only   False   (restrict to R-* / RM-* / PR zoning)
  max_miles_from_vt  unset (no geo filter)
  max_drive_min      unset (no geo filter)
  reference          "VT"
  reference_lat      — override
  reference_lng      — override
  road_factor        1.6     (straight-line miles -> driving miles)
  avg_mph            30      (for drive-minute conversion)
"""

from __future__ import annotations

from .base import Lead, register
from .helpers import (
    classify_owner,
    filter_jurisdiction,
    parse_float,
)
from .geo import (
    DEFAULT_AVG_MPH,
    DEFAULT_ROAD_FACTOR,
    REFERENCE_POINTS,
    drive_minutes_approx,
    miles_to_reference,
    resolve_reference,
)


_RESIDENTIAL_ZONE_PREFIXES = ("R-", "RM-", "PR", "RR")


def _is_residential(zoning: str | None) -> bool:
    if not zoning:
        return False
    z = zoning.strip().upper()
    return any(z.startswith(p) for p in _RESIDENTIAL_ZONE_PREFIXES)


def _is_empty(row: dict) -> bool:
    year_built = row.get("year_built")
    bldg_value = parse_float(row.get("assessed_bldg"))
    sfla = row.get("sfla")
    return (
        (year_built is None or year_built == 0)
        and (bldg_value is None or bldg_value == 0)
        and (sfla is None or sfla == 0)
    )


def _float_or_none(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@register("EMPTY_LOTS")
def detect(rows: list[dict], config: dict) -> list[Lead]:
    jurisdiction = config.get("jurisdiction", "BLACKSBURG")
    min_acres = float(config.get("min_acres", 0.05))
    max_acres = _float_or_none(config.get("max_acres"))
    price_multiplier = float(config.get("price_multiplier", 1.3))
    min_est_price = _float_or_none(config.get("min_est_price"))
    near_anchor_miles = _float_or_none(config.get("near_anchor_miles"))
    owner_type = str(config.get("owner_type", "person")).lower()
    include_govt = str(config.get("include_govt", False)).lower() in ("true", "1", "yes")
    residential_only = str(config.get("residential_only", False)).lower() in ("true", "1", "yes")
    # Buildability filters — only apply when the parcel actually has slope data.
    max_slope_pct = _float_or_none(config.get("max_slope_pct"))
    min_pct_under_10 = _float_or_none(config.get("min_pct_under_10pct_slope"))

    road_factor = float(config.get("road_factor", DEFAULT_ROAD_FACTOR))
    avg_mph = float(config.get("avg_mph", DEFAULT_AVG_MPH))
    max_miles = _float_or_none(config.get("max_miles_from_vt"))
    max_drive_min = _float_or_none(config.get("max_drive_min"))
    # If only max_drive_min is set, convert to an equivalent miles cap.
    if max_miles is None and max_drive_min is not None:
        max_miles = (max_drive_min * avg_mph / 60) / road_factor

    geo_filter_active = max_miles is not None
    ref_lat, ref_lng = resolve_reference(config)

    rows = filter_jurisdiction(rows, jurisdiction)

    rows_checked = 0
    rows_with_coords = 0

    leads: list[Lead] = []
    for r in rows:
        if not _is_empty(r):
            continue
        acres = parse_float(r.get("acres"))
        if acres is None or acres < min_acres:
            continue
        if max_acres is not None and acres > max_acres:
            continue
        assessed_total = parse_float(r.get("assessed_total")) or 0
        if assessed_total <= 0:
            continue
        otype = classify_owner(r.get("owner1"))
        if not include_govt and otype == "govt_or_institution":
            continue
        if owner_type != "all" and otype != owner_type:
            continue
        if residential_only and not _is_residential(r.get("zoning")):
            continue

        # Buildability checks — only enforce when the parcel actually has a
        # slope reading. Parcels without slope data (acres-fallback rows) get
        # a free pass rather than being silently dropped.
        slope_mean = parse_float(r.get("slope_mean_pct"))
        pct_under_10 = parse_float(r.get("pct_under_10pct_slope"))
        if max_slope_pct is not None and slope_mean is not None and slope_mean > max_slope_pct:
            continue
        if min_pct_under_10 is not None and pct_under_10 is not None and pct_under_10 < min_pct_under_10:
            continue

        rows_checked += 1
        miles = miles_to_reference(r, ref_lat, ref_lng)
        if miles is not None:
            rows_with_coords += 1
        if geo_filter_active:
            if miles is None:
                continue
            if miles > max_miles:
                continue

        owner = (r.get("owner1") or "").strip()
        owner2 = (r.get("owner2") or "").strip()
        site = (r.get("site_addr1") or "").strip() or "(no street address)"
        mail = f"{(r.get('mail_addr1') or '').strip()}, {(r.get('mail_addr2') or '').strip()}".strip(", ")
        zoning = (r.get("zoning") or "?").strip()
        subd = (r.get("subd_name") or "").strip()

        score = 30
        if acres >= 10:   score += 60
        elif acres >= 5:  score += 45
        elif acres >= 1:  score += 30
        elif acres >= 0.5: score += 20
        elif acres >= 0.25: score += 10
        if _is_residential(zoning):
            score += 5

        detail: dict = {
            "summary": f"{acres:.2f}ac  |  {site}  |  zone {zoning}  |  "
                       f"assessed ${assessed_total:,.0f}  |  {owner}",
            "acres": round(acres, 3),
            "site": site,
            "zoning": zoning,
            "subd_name": subd,
            "assessed": f"${assessed_total:,.0f}",
            "owner": owner,
            "owner2": owner2,
            "mail": mail,
            "parcel_id": r.get("parcel_id"),
            "slope_mean_pct": slope_mean if slope_mean is not None else "",
            "pct_under_10pct_slope": pct_under_10 if pct_under_10 is not None else "",
        }
        if miles is not None:
            drive_min = drive_minutes_approx(miles, factor=road_factor, avg_mph=avg_mph)
            detail["miles_to_ref"] = round(miles, 2)
            detail["drive_min_approx"] = round(drive_min, 1)
            detail["summary"] += f"  |  ~{miles:.1f}mi / ~{drive_min:.0f}min drive"

        vt_lat, vt_lng = REFERENCE_POINTS["VT"]
        miles_vt = miles_to_reference(r, vt_lat, vt_lng)
        if miles_vt is not None:
            detail["miles_to_vt"] = round(miles_vt, 2)
            detail["drive_min_vt"] = round(
                drive_minutes_approx(miles_vt, factor=road_factor, avg_mph=avg_mph), 1
            )

        cb_lat, cb_lng = REFERENCE_POINTS["CHRISTIANSBURG"]
        miles_cb = miles_to_reference(r, cb_lat, cb_lng)
        if miles_cb is not None:
            detail["miles_to_christiansburg"] = round(miles_cb, 2)
            detail["drive_min_christiansburg"] = round(
                drive_minutes_approx(miles_cb, factor=road_factor, avg_mph=avg_mph), 1
            )

        est_price = round(assessed_total * price_multiplier)
        detail["est_price"] = est_price

        if min_est_price is not None and est_price < min_est_price:
            continue
        if near_anchor_miles is not None:
            best = min(
                m for m in (miles_vt, miles_cb) if m is not None
            ) if (miles_vt is not None or miles_cb is not None) else None
            if best is None or best > near_anchor_miles:
                continue

        leads.append(Lead(
            category="EMPTY_LOTS",
            key=r.get("parcel_id") or f"{owner}@{site}",
            score=min(score, 100),
            parcels=[r],
            detail=detail,
        ))

    # If a geo filter is requested but nothing has coords, surface the reason.
    if geo_filter_active and rows_checked > 0 and rows_with_coords == 0:
        print(
            "!! geo filter requested but no lat/lng found on any row.\n"
            "   Run: python scripts/enrich_coords.py --in <in.jsonl> --out <enriched.jsonl>\n"
            "   then pass --path <enriched.jsonl> to this command."
        )

    sort_by = str(config.get("sort_by", "acres")).lower()
    if sort_by == "price":
        leads.sort(key=lambda l: -l.detail.get("est_price", 0))
    else:
        leads.sort(
            key=lambda l: (
                -l.detail.get("acres", 0),
                l.detail.get("miles_to_ref", 9_999),
            ),
        )
    return leads
