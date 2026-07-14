"""Predictive seller scoring — heuristic weighted-sum over parcel signals.

Of every parcel NOT currently listed, which homeowners are most likely to
list in the next 6-12 months? This module produces a ranked CSV.

Signals (positive):
  tenure_peak                  — bell curve at 8 yrs                          +0..25
  high_equity                  — assessed - last_sale_price                    +0..15
  recent_expired               — listed in last 3 yrs, didn't sell             +20
  estate_pattern               — name has ESTATE/HEIRS/TRUSTEE/LIFE ESTATE     +30
  absentee                     — mail addr ≠ site addr                         +10
  out_of_state_mail            — mail addr non-VA                              +5
  investor_3to7yr              — entity owner held 3-7 years                   +15
  hot_subdivision              — subdivision in top 25% sale velocity          +10
  vintage_estate               — year_built < 1960 + assessed > $300k          +5
  intra_family_recent          — intra-family deed + tenure<2yr                +25
  intra_family_pattern         — intra-family deed + tenure>=2yr               +10
  mail_addr_changed_18mo       — mailing-address change last 18mo              +30
  tax_delinquent               — parcel flagged tax-delinquent                 +30
  multi_property               — owner holds 5+ NRV parcels                    +5

Tier 14.6 — callable-lead-type signals (added for conversation-anchoring):
  price_cut_motivated          — expired w/ ≥15% cut from original list        +25
  serial_relister              — same parcel listed 3+ times all-time          +25
  empty_nester_pattern         — 4+BR + 15+yr tenure + person owner            +15
  recent_forced_sale_alumni    — owner closed a 180+DOM below-assessed sale    +15
  distressed_condition         — recent remarks match as-is/fixer + person     +15
  neighbor_of_recent_expired   — within 0.5mi of just-expired parcel           +10

Signals (negative):
  rate_locked_in               — bought 2020-2022 (rate-frozen seller)        -20
  recent_purchase              — bought < 18 months ago                       -25
  active_listing               — already has an active listing             exclude

Output adds a `lead_type` column (Tier 14.6) classifying each prospect into
a single dominant type for conversation-script routing and queue filtering.
Priority order puts person-callable types ABOVE estate/trust so the queue
surfaces actually-reachable prospects first.

Output: outputs/mls_analytics/leads/seller_scores.csv (sorted desc).
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from pathlib import Path

from .db import connect
from .owner_dedup import canonicalize, lookup_multi_property_count
from .deed_signals import load_parcel_signals, load_flipper_owner_ids


LEADS_DIR = Path("outputs/mls_analytics/leads")

# NRV-focused parcel files (matching merge_deed_sales.py)
NRV_PARCEL_FILES = (
    "data/montgomery_county_parcels_slope.jsonl",
    "data/blacksburg_parcels.jsonl",
    "data/pulaski_county_parcels.jsonl",
    "data/floyd_county_parcels_slope.jsonl",
    "data/giles_county_parcels_slope.jsonl",
    "data/radford_city_parcels.jsonl",
    "data/roanoke_county_parcels_slope.jsonl",
    "data/carroll_county_parcels_slope.jsonl",
    "data/wythe_county_parcels_slope.jsonl",
    "data/botetourt_county_parcels.jsonl",
    "data/bedford_county_parcels.jsonl",
)

# Match estate/heirs/trustee patterns WITHOUT firing on "REAL ESTATE LLC" or
# corporate names with the word "ESTATE" embedded. Require either:
#   - ESTATE OF / ESTATE at name start ("ESTATE OF X" / "X ESTATE")
#   - HEIRS / TRUSTEE / LIFE ESTATE / DECEASED / REVOCABLE/FAMILY/LIVING TRUST
#   - explicit "LIFE ESTATE" or "LIFE TENANT"
ESTATE_NAME_PATTERN = re.compile(
    r"(\bESTATE\s+OF\b|"
    r"\bHEIRS?\s+OF\b|"
    r"\bTRUSTEE\b|"
    r"\bLIFE\s+ESTATE\b|"
    r"\bLIFE\s+TENANT\b|"
    r"\bDEC['’]?D\b|"
    r"\bDECEASED\b|"
    r"\bREVOCABLE\s+TRUST\b|"
    r"\bFAMILY\s+TRUST\b|"
    r"\bLIVING\s+TRUST\b)",
    re.IGNORECASE,
)

_PUBLIC_OWNER_PATTERN = re.compile(
    r"\b("
    r"COMMONWEALTH|UNITED\s+STATES|U\.?S\.?A\.?|FEDERAL|"
    r"COUNTY|TOWN\s+OF|CITY\s+OF|STATE\s+OF|"
    r"COMMISSION|AUTHORITY|DEPARTMENT|AGENCY|BOARD\s+OF|"
    r"SCHOOL|UNIVERSITY|COLLEGE|VPI|VIRGINIA\s+TECH|"
    r"CHURCH|MINISTRIES|TEMPLE|MOSQUE|SYNAGOGUE|"
    r"FOUNDATION|CEMETERY|HOA|HOMEOWNERS"
    r")\b",
    re.IGNORECASE,
)


def _is_public_owner(name: str) -> bool:
    """Return True for government / utility / educational / religious owners
    that should be excluded from multi-property bonuses."""
    return bool(_PUBLIC_OWNER_PATTERN.search(name or ""))


ENTITY_PATTERN = re.compile(
    r"\b(LLC|L\.L\.C\.|INC\b|CORP\b|CORPORATION|PARTNERSHIP|LP\b|LLP\b|"
    r"HOLDINGS|PROPERTIES|REALTY|INVEST|CAPITAL|VENTURES|ASSOCIATES|"
    r"DEVELOPMENT|BUILDERS|CONSTRUCTION)\b",
    re.IGNORECASE,
)


def _load_mortgage_rates(path: Path = Path("data/fred_30yr_mortgage.csv")) -> dict:
    """Return {YYYY-MM: rate%} from FRED MORTGAGE30US weekly series.

    Aggregates each month's weekly observations to a monthly mean. If the file
    is missing, returns an empty dict and rate-locked-in signal is skipped."""
    if not path.exists():
        return {}
    rates: dict[str, list[float]] = {}
    with path.open("r", encoding="utf-8") as f:
        next(f)  # header
        for line in f:
            parts = line.strip().split(",")
            if len(parts) != 2 or parts[1] in ("", "."):
                continue
            try:
                rates.setdefault(parts[0][:7], []).append(float(parts[1]))
            except (ValueError, IndexError):
                continue
    return {ym: round(sum(vs) / len(vs), 2) for ym, vs in rates.items() if vs}


def _rate_at(rates: dict, d: date) -> float | None:
    """Look up the 30-yr rate for a given date (uses month-of-purchase mean).
    Falls back to nearest available month within ±3 mo."""
    if not rates or not d:
        return None
    ym = d.strftime("%Y-%m")
    if ym in rates:
        return rates[ym]
    # Step out ±1, ±2, ±3 months
    for off in range(1, 4):
        for delta_months in (-off, off):
            year = d.year + ((d.month - 1 + delta_months) // 12)
            month = ((d.month - 1 + delta_months) % 12) + 1
            ym2 = f"{year:04d}-{month:02d}"
            if ym2 in rates:
                return rates[ym2]
    return None


def _current_rate(rates: dict) -> float | None:
    if not rates:
        return None
    return rates[max(rates.keys())]


def _safe_float(v) -> float | None:
    if v in (None, "", "None"): return None
    try: return float(v)
    except (TypeError, ValueError): return None


def _safe_int(v) -> int | None:
    if v in (None, "", "None"): return None
    try: return int(v)
    except (TypeError, ValueError): return None


def _parse_date(v) -> date | None:
    if not v:
        return None
    s = str(v)[:10]
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _tenure_score(years: float) -> float:
    """Bell curve peaking at 8 years. 0 below 2yr, peak 25 at 8yr, decay to 5 at 20yr+."""
    if years < 2: return 0.0
    if years <= 8: return 25 * ((years - 2) / 6)
    if years <= 15: return 25 * (1 - (years - 8) / 14)
    if years <= 25: return max(5, 25 * (1 - (years - 8) / 14))
    return 5.0


def _equity_score(equity: float) -> float:
    """Linear ramp: $0 = 0pts, $200k+ equity = 15pts (capped)."""
    if equity is None or equity <= 0: return 0.0
    return min(15.0, equity / 200_000 * 15)


def _recency_multiplier(days_since: float | None, *, window_days: int, floor: float = 0.25) -> float:
    """Decay a time-based signal linearly from 1.0 at day 0 down to `floor`
    by `window_days`. Returns 0.0 when `days_since` is None/negative/past the
    window — the caller can short-circuit on a value <= 0 to skip the signal.
    Floor keeps an aged-but-in-window event worth a fraction of full strength."""
    if days_since is None or days_since < 0:
        return 0.0
    if days_since >= window_days:
        return 0.0
    return max(floor, 1.0 - days_since / window_days)


def _hot_subdivisions(con) -> set[tuple[str, str]]:
    """(city, subdivision) pairs in top 25% by closed-sale velocity, last 12mo."""
    rows = con.execute("""
        SELECT UPPER(TRIM(city)) AS c, UPPER(TRIM(subdivision)) AS s, COUNT(*) AS n
        FROM listings
        WHERE status_category='Closed' AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '12 months'
          AND subdivision IS NOT NULL AND TRIM(subdivision) NOT IN ('','-','None','OTHER','UNKNOWN')
        GROUP BY 1, 2 HAVING COUNT(*) >= 3
    """).fetchall()
    if not rows:
        return set()
    nonzero = sorted(r[2] for r in rows)
    p75 = nonzero[int(len(nonzero) * 0.75)]
    return {(c, s) for c, s, n in rows if n >= p75}


def _expired_recently(con) -> dict[str, str]:
    """parcel_id -> latest off-market signal, for listings expired in last 3 years.

    `off_market_date` is sparsely populated; fall back to `status_changed_at`
    or `list_date` to ensure we don't miss expired listings."""
    rows = con.execute("""
        SELECT parcel_id,
               MAX(COALESCE(
                 TRY_CAST(off_market_date AS DATE),
                 TRY_CAST(status_changed_at AS DATE),
                 TRY_CAST(list_date AS DATE)
               )) AS d
        FROM listings
        WHERE status_category IN ('Expired/Cancelled','Withdrawn')
          AND parcel_id IS NOT NULL AND parcel_id != ''
        GROUP BY parcel_id
        HAVING d >= CURRENT_DATE - INTERVAL '36 months'
    """).fetchall()
    return {r[0]: str(r[1])[:10] for r in rows if r[0]}


def _active_parcel_ids(con) -> set[str]:
    """Parcels with an active or pending MLS listing — exclude from scoring."""
    rows = con.execute("""
        SELECT DISTINCT parcel_id
        FROM listings WHERE status_category IN ('Active','Pending')
        AND parcel_id IS NOT NULL AND parcel_id != ''
    """).fetchall()
    return {r[0] for r in rows}


# ---------- Tier 14.6 — callable-lead-type loaders ----------------------

def _listings_history_per_parcel(con) -> dict[str, dict]:
    """Per-parcel summary across all MLS history (NOT just expired window).

    Returns dict[parcel_id] → {
        n_listings_history, n_expired, last_off_date,
        last_original_price, last_final_price,
        pct_cut_off_orig,
    }

    `n_expired` counts Expired/Cancelled or Withdrawn events that happened
    AFTER the most recent ownership transfer on the parcel — proxied by the
    later of (a) the most recent MLS 'Closed' event_date and (b) the CAMA
    `deed_last_sale_date` from the parcel join. Prior expirations were
    under a previous owner and don't make the CURRENT owner a serial
    re-lister. Parcels with no recorded sale on either side count all
    expirations (same owner since before our records start).

    Used by serial_relister (n_expired ≥ 3) and price_cut_motivated
    (pct_cut_off_orig ≥ 15 within last 12mo).
    """
    sql = """
    WITH events AS (
      SELECT
        parcel_id,
        status_category,
        COALESCE(
          TRY_CAST(off_market_date AS DATE),
          TRY_CAST(status_changed_at AS DATE),
          TRY_CAST(close_date AS DATE),
          TRY_CAST(list_date AS DATE)
        ) AS event_date,
        TRY_CAST(original_list_price AS DOUBLE) AS orig_price,
        TRY_CAST(list_price AS DOUBLE) AS final_price,
        TRY_CAST(deed_last_sale_date AS DATE) AS deed_last_sale_date
      FROM listings
      WHERE parcel_id IS NOT NULL AND parcel_id != ''
    ),
    -- Ownership-tenure cutoff: the later of (a) most recent MLS Closed
    -- event_date, (b) the CAMA-deed last_sale_date. Any expiration on or
    -- before this date was a previous owner's failed sale, not the
    -- current owner's.
    tenure AS (
      SELECT parcel_id,
             GREATEST(
               COALESCE(MAX(CASE WHEN status_category = 'Closed' THEN event_date END),
                        DATE '1900-01-01'),
               COALESCE(MAX(deed_last_sale_date), DATE '1900-01-01')
             ) AS tenure_start
      FROM events
      GROUP BY parcel_id
    ),
    summarized AS (
      SELECT
        e.parcel_id,
        COUNT(*) AS n_listings_history,
        -- Count expirations strictly AFTER the current owner's tenure
        -- start. If neither a closed sale nor a deed transfer is on file,
        -- tenure_start defaults to 1900-01-01 so all expirations still
        -- count (this matches the legacy behavior for unsold parcels).
        SUM(CASE
              WHEN e.status_category IN ('Expired/Cancelled','Withdrawn')
                AND e.event_date > t.tenure_start
              THEN 1 ELSE 0
            END) AS n_expired,
        MAX(CASE
              WHEN e.status_category IN ('Expired/Cancelled','Withdrawn')
                AND e.event_date > t.tenure_start
              THEN e.event_date
            END) AS last_off_date,
        ARG_MAX(e.orig_price,
                CASE
                  WHEN e.status_category IN ('Expired/Cancelled','Withdrawn')
                    AND e.event_date > t.tenure_start
                  THEN e.event_date
                END) AS last_original_price,
        ARG_MAX(e.final_price,
                CASE
                  WHEN e.status_category IN ('Expired/Cancelled','Withdrawn')
                    AND e.event_date > t.tenure_start
                  THEN e.event_date
                END) AS last_final_price
      FROM events e LEFT JOIN tenure t USING (parcel_id)
      GROUP BY e.parcel_id
    )
    SELECT parcel_id, n_listings_history, n_expired,
           CAST(last_off_date AS VARCHAR) AS last_off_date,
           last_original_price, last_final_price,
           CASE WHEN last_original_price > 0
                THEN ROUND((last_original_price - last_final_price)
                           / last_original_price * 100, 1)
                ELSE NULL END AS pct_cut_off_orig
    FROM summarized
    """
    out: dict[str, dict] = {}
    for r in con.execute(sql).fetchall():
        out[r[0]] = {
            "n_listings_history": int(r[1] or 0),
            "n_expired": int(r[2] or 0),
            "last_off_date": r[3] or "",
            "last_original_price": float(r[4]) if r[4] is not None else 0.0,
            "last_final_price": float(r[5]) if r[5] is not None else 0.0,
            "pct_cut_off_orig": float(r[6]) if r[6] is not None else 0.0,
        }
    return out


def _distressed_remarks_per_parcel(con) -> dict[str, dict]:
    """For each parcel, pull the most-recent listing's public_remarks and
    flag whether it matches the 'distressed' lexicon from condition.py.

    Returns dict[parcel_id] → {has_distressed_remarks, recent_remarks (truncated)}.
    """
    sql = """
    WITH ranked AS (
      SELECT parcel_id, public_remarks,
             ROW_NUMBER() OVER (PARTITION BY parcel_id
                                ORDER BY list_date DESC NULLS LAST) AS rn
      FROM listings
      WHERE parcel_id IS NOT NULL AND parcel_id != ''
        AND public_remarks IS NOT NULL
    )
    SELECT parcel_id, public_remarks
    FROM ranked
    WHERE rn = 1
    """
    try:
        from .condition import score_remarks
    except ImportError:
        return {}
    out: dict[str, dict] = {}
    for pid, remarks in con.execute(sql).fetchall():
        if not pid or not remarks:
            continue
        s = score_remarks(remarks)
        if s.get("is_distressed"):
            out[pid] = {
                "has_distressed_remarks": True,
                "recent_remarks": (remarks or "")[:240],
            }
    return out


def _recent_forced_sale_canonical_owners(con) -> set[str]:
    """Canonical owner IDs whose most-recent transaction (last 12mo) was a
    forced-style sale: DOM ≥ 180 AND sold below assessed.

    Returns set[canonical_owner_id]. Used by recent_forced_sale_alumni
    signal — when one of these canonical owners ALSO holds another parcel,
    that other parcel gets the signal."""
    sql = """
    SELECT DISTINCT parcel_owner1
    FROM listings
    WHERE status_category = 'Closed'
      AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '12 months'
      AND TRY_CAST(feed_dom AS INT) >= 180
      AND TRY_CAST(sold_price AS DOUBLE) > 0
      AND TRY_CAST(parcel_assessed_total AS DOUBLE) > 0
      AND TRY_CAST(sold_price AS DOUBLE) < TRY_CAST(parcel_assessed_total AS DOUBLE)
    """
    owners: set[str] = set()
    for (raw_owner,) in con.execute(sql).fetchall():
        if not raw_owner:
            continue
        canon = canonicalize(raw_owner)
        if canon:
            owners.add(canon[0])
    return owners


def _parcel_coords_from_listings(con) -> dict[str, tuple[float, float]]:
    """Pull lat/lng from the most-recent listing record per parcel.

    Parcels never listed have no coords here; they silently skip spatial
    signals. Returns dict[parcel_id] → (lat, lng)."""
    sql = """
    WITH ranked AS (
      SELECT parcel_id,
             TRY_CAST(latitude AS DOUBLE)  AS lat,
             TRY_CAST(longitude AS DOUBLE) AS lng,
             ROW_NUMBER() OVER (PARTITION BY parcel_id
                                ORDER BY list_date DESC NULLS LAST) AS rn
      FROM listings
      WHERE parcel_id IS NOT NULL AND parcel_id != ''
        AND latitude IS NOT NULL AND longitude IS NOT NULL
    )
    SELECT parcel_id, lat, lng FROM ranked WHERE rn = 1
    """
    out: dict[str, tuple[float, float]] = {}
    for pid, lat, lng in con.execute(sql).fetchall():
        if pid and lat is not None and lng is not None:
            try:
                out[pid] = (float(lat), float(lng))
            except (TypeError, ValueError):
                continue
    return out


def _recent_expired_parcels(con) -> list[str]:
    """Parcel IDs that expired/withdrew in the last 30 days. Used to anchor
    neighbor_of_recent_expired BallTree."""
    sql = """
    SELECT DISTINCT parcel_id FROM listings
    WHERE status_category IN ('Expired/Cancelled','Withdrawn')
      AND parcel_id IS NOT NULL AND parcel_id != ''
      AND COALESCE(
          TRY_CAST(off_market_date AS DATE),
          TRY_CAST(status_changed_at AS DATE),
          TRY_CAST(list_date AS DATE)
      ) >= CURRENT_DATE - INTERVAL '30 days'
    """
    return [r[0] for r in con.execute(sql).fetchall() if r[0]]


def _build_neighbor_tree(coords_by_pid: dict, anchor_pids: list[str]):
    """Build a BallTree over the anchor parcel coords for nearest-neighbor
    proximity queries. Returns (tree, anchor_coords_list, anchor_pids_list)
    or (None, [], []) when sklearn/numpy unavailable or no coords."""
    try:
        import numpy as np
        from sklearn.neighbors import BallTree
    except ImportError:
        return None, [], []
    pts = []
    pids = []
    for pid in anchor_pids:
        c = coords_by_pid.get(pid)
        if c:
            pts.append(c)
            pids.append(pid)
    if not pts:
        return None, [], []
    arr = np.radians(np.array(pts))
    tree = BallTree(arr, metric="haversine")
    return tree, pts, pids


def _is_near_anchor(lat: float, lng: float, tree, radius_mi: float = 0.5) -> bool:
    """Query the neighbor BallTree: True if at least one anchor is within
    radius_mi miles of (lat, lng)."""
    if tree is None:
        return False
    try:
        import numpy as np
    except ImportError:
        return False
    EARTH_R_MI = 3958.7613
    radius_rad = radius_mi / EARTH_R_MI
    pt = np.radians([[lat, lng]])
    idx = tree.query_radius(pt, r=radius_rad)[0]
    return len(idx) > 0


# ---------- Lead-type classifier ----------------------------------------

LEAD_TYPE_PRIORITY = [
    "price_cut_motivated",
    "serial_relister",
    "recent_forced_sale_alumni",
    "tax_delinquent_person",   # tax_delinquent + person owner
    "distressed_condition",
    "neighbor_of_recent_expired",
    "empty_nester_pattern",
    "estate",                  # estate_pattern
    "expired_recent",          # expired
    "mail_changed",            # mail_addr_changed_18mo
    "intra_family",            # intra_family_recent OR intra_family_pattern
    "absentee_investor",       # absentee + tenure>=3
    "long_tenure",             # tenure>=8
    "unclassified",
]


def _classify_lead_type(signal_keys: set[str], owner_type: str,
                        tenure_yrs: float | None) -> str:
    """Pick the dominant lead type for a prospect based on which signals
    fired. Person-callable types are listed first in LEAD_TYPE_PRIORITY."""
    is_person = (owner_type or "").lower() == "person"
    t = tenure_yrs or 0.0

    # The "person-elevated" types fire only when the signal is present
    # AND the owner is callable.
    if "price_cut_motivated" in signal_keys and is_person:
        return "price_cut_motivated"
    if "serial_relister" in signal_keys and is_person:
        return "serial_relister"
    if "recent_forced_sale_alumni" in signal_keys and is_person:
        return "recent_forced_sale_alumni"
    if "tax_delinquent" in signal_keys and is_person:
        return "tax_delinquent_person"
    if "distressed_condition" in signal_keys and is_person:
        return "distressed_condition"
    if "neighbor_of_recent_expired" in signal_keys and is_person:
        return "neighbor_of_recent_expired"
    if "empty_nester_pattern" in signal_keys:
        return "empty_nester_pattern"

    # Fallbacks — apply to all owners
    if "estate_pattern" in signal_keys:
        return "estate"
    if "expired" in signal_keys:
        return "expired_recent"
    if "mail_addr_changed_18mo" in signal_keys:
        return "mail_changed"
    if "intra_family_recent" in signal_keys or "intra_family_pattern" in signal_keys:
        return "intra_family"
    if "absentee" in signal_keys and t >= 3:
        return "absentee_investor"
    if t >= 8:
        return "long_tenure"
    return "unclassified"


def _scc_url(name: str) -> str:
    if not name: return ""
    import urllib.parse as _p
    return f"https://cis.scc.virginia.gov/EntitySearch/EntitySearchByName?searchName={_p.quote(name.strip())}"


def _whitepages_url(name: str, city: str | None) -> str:
    if not name: return ""
    import urllib.parse as _p
    n = _p.quote(name.strip().replace(",", "").replace("/", " ").replace(" ", "-"))
    c = _p.quote(city.strip()) if city else ""
    return f"https://www.whitepages.com/name/{n}/{c}-VA"


def _truepeople_url(name: str, city: str | None) -> str:
    if not name: return ""
    import urllib.parse as _p
    return (f"https://www.truepeoplesearch.com/results?name={_p.quote(name.strip())}"
            f"&citystatezip={_p.quote(city.strip()) if city else ''}%20VA")


def score_parcels(out_path: Path = LEADS_DIR / "seller_scores.csv",
                  *, min_score: int = 40) -> int:
    con = connect()
    today = date.today()
    today_year = today.year

    print(f"loading hot subdivisions...")
    hot_sds = _hot_subdivisions(con)
    print(f"  {len(hot_sds)} (city, subdivision) pairs in top quartile")

    print(f"loading expired-listing index...")
    expired_index = _expired_recently(con)
    print(f"  {len(expired_index):,} parcels with recent expired listings")

    print(f"loading active listings (to exclude)...")
    active_ids = _active_parcel_ids(con)
    print(f"  {len(active_ids):,} active/pending parcels")

    print(f"loading FRED 30-yr mortgage rate history...")
    rates = _load_mortgage_rates()
    cur_rate = _current_rate(rates)
    if rates and cur_rate:
        print(f"  {len(rates)} months of history; current rate {cur_rate}%")
    else:
        print(f"  rate file missing — rate lock-in signal will be skipped")

    # Tier-12 signal sources (all best-effort — empty dict if not yet built)
    print(f"loading multi-property owner portfolios...")
    multi_prop = lookup_multi_property_count()
    print(f"  {len(multi_prop):,} canonical owners with 2+ NRV parcels")

    print(f"loading deed-pattern signals...")
    deed_sigs = load_parcel_signals()
    flippers = load_flipper_owner_ids()
    print(f"  {len(deed_sigs):,} parcels with deed signals  |  {len(flippers):,} flipper-pattern owners")

    print(f"loading mail-address-changed snapshot diff...")
    try:
        from ..ingest.parcel_mail_snapshot import changed_parcel_ids as _mail_changed
        mail_changed = _mail_changed(baseline_age_months=18)
    except Exception as e:
        print(f"  unavailable: {e}")
        mail_changed = set()
    print(f"  {len(mail_changed):,} parcels with mailing-address change in last 18mo")

    print(f"loading tax-delinquency cross-reference...")
    try:
        from ..ingest.tax_delinquent import load_delinquent_parcel_ids, load_delinquent_amounts
        delinquent_ids = load_delinquent_parcel_ids()
        delinquent_amts = load_delinquent_amounts()
    except Exception as e:
        print(f"  unavailable: {e}")
        delinquent_ids = set()
        delinquent_amts = {}
    print(f"  {len(delinquent_ids):,} parcels flagged tax-delinquent")

    # ---------- Tier 14.6 — callable-lead-type data sources ----------
    print(f"loading per-parcel listing history (serial + price-cut)...")
    try:
        listings_hist = _listings_history_per_parcel(con)
    except Exception as e:
        print(f"  unavailable: {e}")
        listings_hist = {}
    print(f"  {len(listings_hist):,} parcels with listing history")

    print(f"loading distressed-condition lexicon hits...")
    try:
        distressed_remarks = _distressed_remarks_per_parcel(con)
    except Exception as e:
        print(f"  unavailable: {e}")
        distressed_remarks = {}
    print(f"  {len(distressed_remarks):,} parcels with distressed remarks")

    print(f"loading recent-forced-sale alumni (canonical owners)...")
    try:
        forced_sale_owners = _recent_forced_sale_canonical_owners(con)
    except Exception as e:
        print(f"  unavailable: {e}")
        forced_sale_owners = set()
    print(f"  {len(forced_sale_owners):,} canonical owners with recent forced sales")

    print(f"loading parcel coords + recent-expired BallTree...")
    try:
        parcel_coords = _parcel_coords_from_listings(con)
        recent_expired_pids = _recent_expired_parcels(con)
        neighbor_tree, _, neighbor_anchor_pids = _build_neighbor_tree(
            parcel_coords, recent_expired_pids
        )
    except Exception as e:
        print(f"  unavailable: {e}")
        parcel_coords, neighbor_tree, neighbor_anchor_pids = {}, None, []
    print(f"  {len(parcel_coords):,} parcels with coords  |  "
          f"{len(neighbor_anchor_pids):,} recent-expired anchors")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows_out: list[dict] = []
    n_total = n_excluded_active = 0

    for fname in NRV_PARCEL_FILES:
        p = Path(fname)
        if not p.exists():
            continue
        county_label = (p.stem.replace("_parcels_slope", "")
                              .replace("_parcels", "")
                              .replace("_county", "")
                              .upper())
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                n_total += 1
                pid = (r.get("parcel_id") or "").strip()
                if not pid:
                    continue
                if pid in active_ids:
                    n_excluded_active += 1
                    continue

                owner = (r.get("owner1") or "").strip()
                if not owner:
                    continue

                # Build signals
                signals_pos: list[str] = []
                signals_neg: list[str] = []
                score = 0.0

                # Tenure
                last_sale = _parse_date(r.get("last_sale_date"))
                tenure_yrs: float | None = None
                rate_at_purchase: float | None = None
                rate_delta: float | None = None
                if last_sale:
                    tenure_yrs = (today - last_sale).days / 365.25
                    s = _tenure_score(tenure_yrs)
                    if s > 0:
                        signals_pos.append(f"tenure:{tenure_yrs:.1f}y(+{s:.0f})")
                        score += s
                    if tenure_yrs < 1.5:
                        signals_neg.append("recent_purchase(-25)")
                        score -= 25
                    # FRED-based rate lock-in: scale penalty by rate delta
                    rate_at_purchase = _rate_at(rates, last_sale)
                    if rate_at_purchase is not None and cur_rate is not None:
                        rate_delta = round(cur_rate - rate_at_purchase, 2)
                        # Penalty proportional to delta. 0%-1% delta = 0pts;
                        # 3%+ delta = -20pts (max). Linear ramp.
                        if rate_delta >= 1.0:
                            penalty = min(20.0, (rate_delta - 1.0) * 10)
                            if penalty >= 5:
                                signals_neg.append(f"rate_locked:{rate_at_purchase}%->[{cur_rate}%](-{penalty:.0f})")
                                score -= penalty

                # Equity (assessed - last_sale_price)
                assessed = _safe_float(r.get("assessed_total")) or 0
                last_price = _safe_float(r.get("last_sale_price")) or 0
                equity = assessed - last_price if (assessed > 0 and last_price > 0) else 0
                e_s = _equity_score(equity)
                if e_s > 0:
                    signals_pos.append(f"equity:${int(equity):,}(+{e_s:.0f})")
                    score += e_s

                # Estate / heirs / trustee
                if ESTATE_NAME_PATTERN.search(owner):
                    signals_pos.append("estate_pattern(+30)")
                    score += 30

                # Absentee + out-of-state mail
                site = (r.get("site_addr1") or "").upper().strip()
                mail = (r.get("mail_addr1") or "").upper().strip()
                mail2 = (r.get("mail_addr2") or "").upper()
                if site and mail and site != mail:
                    signals_pos.append("absentee(+10)")
                    score += 10
                    if mail2 and "VA" not in mail2:
                        signals_pos.append("oos_mail(+5)")
                        score += 5

                # Recent expired — uses the listings_hist `last_off_date`
                # (ownership-filtered: pre-transfer expirations don't count
                # against the current owner) and decays linearly across 18
                # months so a fresh expiration outweighs a stale one.
                # NOTE: `expired_index` from `_expired_recently()` is kept
                # for the load-time stat print but no longer drives scoring.
                _last_off = (listings_hist.get(pid) or {}).get("last_off_date") or ""
                if _last_off:
                    try:
                        _d = (today - date.fromisoformat(_last_off[:10])).days
                        _mult = _recency_multiplier(_d, window_days=540)
                        if _mult > 0:
                            _pts = 20 * _mult
                            signals_pos.append(f"expired:{_last_off}({_d}d ago)(+{_pts:.0f})")
                            score += _pts
                    except Exception:
                        pass

                # Investor LLC held 3-7 years
                is_entity = bool(ENTITY_PATTERN.search(owner))
                if is_entity and tenure_yrs is not None and 3 <= tenure_yrs <= 7:
                    signals_pos.append(f"investor_dispose:{tenure_yrs:.1f}y(+15)")
                    score += 15

                # Hot subdivision
                subd = (r.get("subd_name") or r.get("subdivision") or "").upper().strip()
                jurisdiction = (r.get("jurisdiction") or "").upper().strip()
                # Try a few candidate (city, subd) pairs — county label, jurisdiction, etc.
                if subd:
                    candidates = [(jurisdiction, subd), (county_label, subd)]
                    if any(c in hot_sds for c in candidates):
                        signals_pos.append("hot_subdivision(+10)")
                        score += 10

                # Vintage estate
                yb = _safe_int(r.get("year_built")) or 0
                if yb and yb < 1960 and assessed >= 300000:
                    signals_pos.append(f"vintage_estate:{yb}(+5)")
                    score += 5

                # ---------- Tier-12 signals ----------
                canon = canonicalize(owner)
                canon_id = canon[0] if canon else None
                is_flipper_pattern = bool(canon_id and canon_id in flippers)

                # Multi-property private owner — small bonus, capped.
                # Skip for entities matching gov/utility/edu (already filtered as
                # public types in owner_dedup, but be doubly safe).
                if canon_id and not is_flipper_pattern:
                    n_parc = multi_prop.get(canon_id, 0)
                    if n_parc >= 5 and not _is_public_owner(owner):
                        signals_pos.append(f"multi_prop:{n_parc}parc(+5)")
                        score += 5

                # Deed-pattern signals (parcel-level)
                ds = deed_sigs.get((county_label, pid)) or {}
                if ds.get("intra_family_transfer_recent_24mo"):
                    # Heir/divorce/intra-family transfer + low tenure ⇒ very motivated
                    if tenure_yrs is not None and tenure_yrs < 2:
                        signals_pos.append("intra_family_recent(+25)")
                        score += 25
                    else:
                        signals_pos.append("intra_family_pattern(+10)")
                        score += 10

                # Mailing-address change in last 18 months
                if (county_label, pid) in mail_changed:
                    signals_pos.append("mail_addr_changed_18mo(+30)")
                    score += 30

                # Tax delinquency — scale by amount owed. Any delinquency
                # gets a base of +10 (could be clerical); each $1k owed adds
                # +4 up to a +30 ceiling at $5k+. Prevents a $50 missed
                # payment from scoring identically to $8k in arrears.
                if (county_label, pid) in delinquent_ids:
                    amt = delinquent_amts.get((county_label, pid), 0) or 0
                    _td_pts = 10 + min(20.0, amt / 250.0)
                    label = (
                        f"tax_delinquent:${int(amt):,}(+{_td_pts:.0f})"
                        if amt
                        else f"tax_delinquent(+{_td_pts:.0f})"
                    )
                    signals_pos.append(label)
                    score += _td_pts

                # ---------- Tier 14.6 — callable-lead-type signals ----------
                hist = listings_hist.get(pid) or {}
                n_expired = hist.get("n_expired", 0)
                pct_cut = hist.get("pct_cut_off_orig", 0.0)
                last_off_date_str = hist.get("last_off_date", "")

                # Price-cut motivated: ≥15% cut + expired within 12mo, decayed
                # by age so a cut last week scores higher than a cut 11mo ago.
                # `last_off_date` is already ownership-filtered (the serial-
                # relister fix's tenure cutoff applies to it via listings_hist).
                if pct_cut and pct_cut >= 15 and last_off_date_str:
                    try:
                        last_off = date.fromisoformat(last_off_date_str[:10])
                        days_off = (today - last_off).days
                        _pc_mult = _recency_multiplier(days_off, window_days=365)
                        if _pc_mult > 0:
                            _pc_pts = 25 * _pc_mult
                            signals_pos.append(
                                f"price_cut_motivated:{pct_cut:.0f}%({days_off}d ago)(+{_pc_pts:.0f})"
                            )
                            score += _pc_pts
                    except Exception:
                        pass

                # Serial re-lister: 3+ expired/withdrawn lifetime
                if n_expired >= 3:
                    signals_pos.append(f"serial_relister:{n_expired}x(+25)")
                    score += 25

                # Empty-nester pattern: 4+BR + 15+yr tenure + person owner + older home
                bedrooms = _safe_int(r.get("bedrooms")) or 0
                if (bedrooms >= 4 and tenure_yrs is not None
                        and tenure_yrs >= 15 and yb and yb < 1975
                        and not is_entity):
                    signals_pos.append(
                        f"empty_nester_pattern:{bedrooms}br/{tenure_yrs:.0f}y(+15)"
                    )
                    score += 15

                # Recent-forced-sale alumni: canonical owner had a 180+DOM
                # below-assessed sale in last 12mo (applied to OTHER parcels)
                if canon_id and canon_id in forced_sale_owners and not is_entity:
                    signals_pos.append("recent_forced_sale_alumni(+15)")
                    score += 15

                # Distressed condition: recent remarks match as-is/fixer
                # lexicon + person owner + not currently listed (we already
                # excluded active listings, so the second clause is implicit)
                if pid in distressed_remarks and not is_entity:
                    signals_pos.append("distressed_condition(+15)")
                    score += 15

                # Neighbor of recent expired: within 0.5mi of a parcel that
                # expired/withdrew in the last 30 days
                if neighbor_tree is not None and not is_entity:
                    coords = parcel_coords.get(pid)
                    if coords and pid not in set(neighbor_anchor_pids):
                        if _is_near_anchor(coords[0], coords[1], neighbor_tree, 0.5):
                            signals_pos.append("neighbor_of_recent_expired(+10)")
                            score += 10

                if score < min_score and not is_flipper_pattern:
                    continue

                # Classify lead type from the signal mix
                signal_key_set = {s.split(":", 1)[0].split("(", 1)[0]
                                  for s in signals_pos}
                lead_type = _classify_lead_type(
                    signal_key_set,
                    "entity" if is_entity else "person",
                    tenure_yrs,
                )

                row = {
                    "score": round(score, 0),
                    "lead_type": lead_type,
                    "owner": owner,
                    "owner_type": "entity" if is_entity else "person",
                    "is_flipper_pattern": is_flipper_pattern,
                    "canonical_owner_id": canon_id or "",
                    "county": county_label,
                    "parcel_id": pid,
                    "site_addr": (r.get("site_addr1") or ""),
                    "mail_addr": (r.get("mail_addr1") or ""),
                    "year_built": yb or "",
                    "bedrooms": bedrooms or "",
                    "tenure_years": round(tenure_yrs, 1) if tenure_yrs is not None else "",
                    "last_sale_date": str(last_sale) if last_sale else "",
                    "last_sale_price": int(last_price) if last_price else "",
                    "assessed_total": int(assessed) if assessed else "",
                    "estimated_equity": int(equity) if equity else "",
                    "rate_at_purchase": rate_at_purchase if rate_at_purchase else "",
                    "rate_delta_now": rate_delta if rate_delta is not None else "",
                    "subdivision": (r.get("subd_name") or r.get("subdivision") or "")[:40],
                    "signals_pos": ";".join(signals_pos),
                    "signals_neg": ";".join(signals_neg),
                    "scc_lookup_url": _scc_url(owner) if is_entity else "",
                    "whitepages_url": _whitepages_url(owner, jurisdiction or county_label) if not is_entity else "",
                    "true_people_url": _truepeople_url(owner, jurisdiction or county_label) if not is_entity else "",
                }
                rows_out.append(row)

    # Dedupe by (parcel_id, county) — keep highest score
    by_key: dict[tuple[str, str], dict] = {}
    for r in rows_out:
        k = (r["parcel_id"], r["county"])
        if k not in by_key or r["score"] > by_key[k]["score"]:
            by_key[k] = r
    rows_out = sorted(by_key.values(), key=lambda x: -x["score"])

    if not rows_out:
        out_path.write_text("score,owner,county\n", encoding="utf-8-sig")
        return 0

    # Snapshot prior CSV for delta-report BEFORE we overwrite it
    prior_by_key: dict[tuple[str, str], dict] = {}
    if out_path.exists():
        try:
            with out_path.open("r", encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    pid = (r.get("parcel_id") or "").strip()
                    cnty = (r.get("county") or "").strip().upper()
                    if pid:
                        prior_by_key[(pid, cnty)] = r
        except Exception:
            prior_by_key = {}

    fields = list(rows_out[0].keys())
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)

    # Delta report — what's new, dropped, score-changed
    if prior_by_key:
        delta_rows = []
        cur_by_key = {(r["parcel_id"], r["county"]): r for r in rows_out}
        for k, cur in cur_by_key.items():
            prev = prior_by_key.get(k)
            try:
                cur_score = float(cur.get("score") or 0)
            except (TypeError, ValueError):
                cur_score = 0.0
            if prev is None:
                delta_rows.append({**cur, "delta_kind": "NEW",
                                    "prev_score": "", "score_change": cur_score})
            else:
                try:
                    prev_score = float(prev.get("score") or 0)
                except (TypeError, ValueError):
                    prev_score = 0.0
                if abs(cur_score - prev_score) >= 5:
                    delta_rows.append({**cur, "delta_kind": "CHANGED",
                                        "prev_score": prev_score,
                                        "score_change": cur_score - prev_score})
        for k, prev in prior_by_key.items():
            if k not in cur_by_key:
                try:
                    prev_score = float(prev.get("score") or 0)
                except (TypeError, ValueError):
                    prev_score = 0.0
                delta_rows.append({**prev, "delta_kind": "DROPPED",
                                    "prev_score": prev_score, "score_change": -prev_score})
        if delta_rows:
            delta_rows.sort(key=lambda x: (
                {"NEW": 0, "CHANGED": 1, "DROPPED": 2}.get(x.get("delta_kind", ""), 3),
                -float(x.get("score_change") or 0),
            ))
            delta_path = out_path.parent / f"seller_scores_delta_{date.today().isoformat()}.csv"
            delta_fields = ["delta_kind", "score_change", "prev_score"] + [f for f in fields if f != "score"]
            delta_fields = ["score"] + delta_fields
            with delta_path.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=delta_fields, extrasaction="ignore")
                w.writeheader()
                for r in delta_rows:
                    w.writerow(r)
            n_new = sum(1 for r in delta_rows if r.get("delta_kind") == "NEW")
            n_chg = sum(1 for r in delta_rows if r.get("delta_kind") == "CHANGED")
            n_drp = sum(1 for r in delta_rows if r.get("delta_kind") == "DROPPED")
            print(f"  delta vs previous: NEW={n_new:,}  CHANGED={n_chg:,}  DROPPED={n_drp:,}")
            print(f"  delta report: {delta_path}")

    print()
    print(f"=== seller scoring complete ===")
    print(f"  parcels scanned: {n_total:,}")
    print(f"  excluded (active listing): {n_excluded_active:,}")
    print(f"  scored at >= {min_score}: {len(rows_out):,}")
    return len(rows_out)
