"""Comp similarity scorer + diverse top-N selection for CMA generation.

Replaces the chronological-only ``find_comparables`` in :mod:`mls_bot.analytics.cma`
with a weighted similarity score and explicit diversity enforcement, so the
top-6 comp set always includes a fresh-month anchor, similar-vintage match,
and at least one larger-acreage reference.

Public entry point: :func:`pick_comps`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from math import exp, isfinite, radians, cos, sin, atan2, sqrt
from pathlib import Path
from typing import Any, Iterable, Optional

import duckdb

from .db import connect


_MLS_LOOKUP_PARQUET = Path("data/mls_lookup.parquet")


def _fast_listings_connection() -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection with the ``listings`` view registered.

    Prefers the slim ``data/mls_lookup.parquet`` (sub-second cold-start) over
    the full JSONL-backed ``db.connect()`` (which loads 200 MB and takes
    20-80 s). Falls back to the heavy connection only when the parquet is
    missing — that keeps the comp scorer functional on a fresh checkout.

    Comp-pool OVERRIDE: when the env var ``CMA_LISTINGS_PARQUET`` points at an
    existing parquet, the ``listings`` view reads THAT pool instead of the MLS
    pool — this is how compbird's engine can price off the supplemental
    public-records sales source (set per-request by the worker / per-spawn by the
    app). When the env is unset/blank or the path is missing, this is
    BYTE-IDENTICAL to the MLS-pool default, so the Ratifyly path is unaffected.
    Mirrors the process-global ``CMA_SKIP_AVM`` convention (safe on the
    single-threaded worker + per-spawn processes)."""
    _override = os.environ.get("CMA_LISTINGS_PARQUET", "").strip()
    _pool = (
        Path(_override)
        if (_override and Path(_override).exists())
        else _MLS_LOOKUP_PARQUET
    )
    if _pool.exists():
        con = duckdb.connect(":memory:")
        con.execute(
            f"CREATE VIEW listings AS "
            f"SELECT * FROM read_parquet('{_pool.as_posix()}')"
        )
        return con
    # Heavy fallback (fresh checkout, no parquet). Expose an ``appearance``
    # column derived from the raw Paragon record so the candidate query that
    # selects it doesn't break.
    con = connect()
    try:
        con.execute(
            "CREATE OR REPLACE VIEW listings AS "
            "SELECT *, TRY_CAST(_raw['LFD_Appearance_2'] AS VARCHAR) AS appearance "
            "FROM listings"
        )
    except Exception:
        pass
    return con


# Single transparent scoring formula (Step 3).
#
# Replaces the previous stack of per-tier weight tables, cohort additive
# bonuses, BONUS_SUBDIVISION, BONUS_SCHOOL, and atypical multipliers. The
# formula pivots on a single derived dimension — ``land_heaviness`` — so the
# rural/suburban shift is one continuous knob rather than three tier tables.
#
#   score = (
#         sqft_match     * weight_sqft
#       + acres_match    * weight_acres
#       + distance_match * weight_distance
#       + recency_match  * weight_recency
#       + price_match    * weight_price
#       + beds_match     * weight_beds
#       + baths_match    * weight_baths
#       + year_match     * weight_year
#   ) * atypical_penalty
#   + same_subdivision_bonus       # +50 flat, only after normalized match
#   + same_school_bonus            # +15 flat
#
# Each ``*_match`` is a 0..1 proximity (``exp(-Δ/scale)``). Maximum possible
# raw weighted-sum is ≈ sum(weights) when every axis is a perfect match.
# Adding the subdivision bonus on top means a same-subdivision comp can
# break the +50 gap even when other dimensions are merely good.

BONUS_SUBDIVISION = 50.0   # same normalized subdivision name
BONUS_SCHOOL = 15.0        # same high school district
ATYPICAL_PENALTY = 0.80    # multiplicative penalty for distressed/outlier sales
PENDING_PENALTY = 0.90     # gentle penalty: pending prices are estimates, not settled


# ---------------------------------------------------------------------------
# Comp-quality controls (env-overridable; defaults reproduce shipped behavior,
# so they are backtest-neutral until a sweep bakes in tuned values).
# ---------------------------------------------------------------------------
def _envf(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    try:
        return float(v)
    except ValueError:
        return default


# Hard bed/bath guard: drop a comp whose bedroom OR full-bath count differs from
# the subject by more than this. Default 2 (backtest-neutral) stops a strong
# subdivision/distance match from dragging in a property with FAR more/fewer
# beds/baths while keeping +/-2 tolerance. 0 = off.
_BEDBATH_MAX_DELTA = _envf("CMA_BEDBATH_MAX_DELTA", 2.0)
# Closeness floor: keep only comps scoring >= best_score * this fraction — DROP
# loose comps rather than padding to n when close comps are scarce (returns <n,
# never below _COMP_MIN). Default 0.6 (backtest-neutral). 0 = off.
_COMP_FLOOR_FRAC = _envf("CMA_COMP_FLOOR_FRAC", 0.6)
# $/sqft outlier FLAGGING: mark a comp `_outlier` when its $/sqft is > this many
# MADs (and >25%) from the comp-set median — surfaced for the agent, kept in the
# set (value-neutral). Default 3.0. 0 = off.
_PPSF_OUTLIER_K = _envf("CMA_PPSF_OUTLIER_K", 3.0)
# $/sqft egregious DROP: also remove a comp whose $/sqft is > ratio x (or < 1/ratio
# x) the set median — these are near-certain data errors / wrong-type comps.
# Default 2.2. 0 = off (flag-only).
_PPSF_DROP_RATIO = _envf("CMA_PPSF_DROP_RATIO", 2.2)
# Floor on comp count so the quality filters never starve the estimate.
_COMP_MIN = int(_envf("CMA_COMP_MIN", 3))
# Subtype mismatch multiplier — only engages under CMA_SUBTYPE_FILTER=soft
# (see _subtype_filter_mode); inert in production.
SUBTYPE_MISMATCH_PENALTY = 0.85


# As-of anchor for recency decay + the candidate lookback cutoffs. Production
# leaves both the override and the ``as_of=`` kwargs None -> anchor is
# ``date.today()`` (byte-identical to shipped behavior). Backtest harnesses
# either pass ``as_of=`` to :func:`pick_comps` or set this module-level hook —
# ``build_cma`` has no as-of plumbing through ``prepare_comps`` yet, so the
# hook is how a harness freezes the whole chain without monkeypatching
# ``date`` itself.
AS_OF_OVERRIDE: Optional[date] = None


def _resolve_as_of(as_of: Optional[date] = None) -> date:
    return as_of or AS_OF_OVERRIDE or date.today()


def _min_candidates() -> int:
    """Candidate-pool sufficiency target (env CMA_MIN_CANDIDATES; unset = the
    shipped 30). Read at call time so experiment arms can flip it in-process."""
    v = os.environ.get("CMA_MIN_CANDIDATES", "").strip()
    try:
        return max(1, int(v)) if v else 30
    except ValueError:
        return 30


def _subtype_filter_mode() -> str:
    """CMA_SUBTYPE_FILTER experiment gate. Unset/'' = no subtype logic (shipped
    behavior). 'hard' = filter candidates to the subject's property_subtype,
    falling back to unfiltered when <10 rows survive. 'soft' = no filter but a
    0.85x score multiplier on subtype mismatch. Inactive when the subject dict
    carries no property_subtype."""
    return os.environ.get("CMA_SUBTYPE_FILTER", "").strip().lower()


def _land_heaviness(subject_acres: Optional[float]) -> float:
    """Return a 0..1 score representing how land-heavy the subject is.

    0.0 = suburban (≤ 1 ac), 1.0 = 15+ acres. Pivots the weight schedule from
    "sqft dominates" to "acreage dominates" smoothly rather than via three
    tier tables. Subjects without an acres figure default to 0.0 (suburban)."""
    a = subject_acres or 0.0
    return max(0.0, min(1.0, (a - 1.0) / 14.0))


def _weights_for_subject(subj: "Subject") -> dict[str, float]:
    """Return the single-formula weight vector for the subject.

    ``land_heaviness`` morphs the weights continuously from suburban
    (sqft dominates) to rural (acres dominates). Distance and recency stay
    constant — both always matter."""
    lh = _land_heaviness(subj.acres)
    return {
        "SQFT":    100.0 * (1.0 - lh * 0.60),     # 100 → 40
        "ACRES":    60.0 * (0.4 + lh * 1.30),     #  24 → 102
        "YEAR":     30.0,
        "DIST":     80.0,
        "RECENCY":  70.0,
        "PRICE":    50.0 * (1.0 - lh * 0.40),     #  50 → 30
        "BEDS":     25.0 * (1.0 - lh * 0.40),     #  25 → 15
        "BATHS":    15.0,
    }


def _subject_reference_ppsf(subj_dict: dict[str, Any]) -> Optional[float]:
    """Best-effort price-per-sqft anchor for the subject.

    Prefers list_price > original_list_price > deed_last_sale_price >
    assessed_total. Returns None if no price reference is usable."""
    sqft = subj_dict.get("sqft")
    try:
        sqft_f = float(sqft) if sqft else None
    except (TypeError, ValueError):
        sqft_f = None
    if not sqft_f or sqft_f <= 0:
        return None
    for key in ("list_price", "original_list_price",
                "deed_last_sale_price", "assessed_total"):
        v = subj_dict.get(key)
        try:
            f = float(v) if v else None
        except (TypeError, ValueError):
            f = None
        if f and f > 0:
            return f / sqft_f
    return None


# Acreage-tier hard filter. Each entry is (subject_min, subject_max,
# comp_min, comp_max). ``None`` for comp_max means "no upper bound".
_ACRE_BANDS: list[tuple[float, float, float, Optional[float]]] = [
    (0.0,  1.0,  0.0,  2.5),
    (1.0,  5.0,  0.5,  10.0),
    (5.0,  15.0, 3.0,  40.0),
    (15.0, 50.0, 8.0,  100.0),
    (50.0, float("inf"), 25.0, None),
]


def _acre_band_for(subject_acres: Optional[float]) -> tuple[float, Optional[float]]:
    """Return the (comp_min, comp_max) acreage band for the subject's tier."""
    a = subject_acres or 0
    for lo, hi, comp_lo, comp_hi in _ACRE_BANDS:
        if lo <= a < hi:
            return comp_lo, comp_hi
    return _ACRE_BANDS[-1][2], _ACRE_BANDS[-1][3]


def _widen_acre_band(comp_lo: float, comp_hi: Optional[float]) -> tuple[float, Optional[float]]:
    """Loosen an acreage band by ~50% on each side, used when the strict pool is thin."""
    new_lo = max(0.0, comp_lo * 0.5)
    new_hi = (comp_hi * 1.5) if comp_hi is not None else None
    return new_lo, new_hi


@dataclass
class Subject:
    """Normalized subject used for scoring. All numerics may be ``None``."""

    address: str = ""
    city: str = ""
    county: str = ""
    cls: str = "RE_1"
    sqft: Optional[float] = None
    acres: Optional[float] = None
    year_built: Optional[int] = None
    bedrooms: Optional[float] = None
    full_baths: Optional[float] = None
    half_baths: Optional[float] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    list_price: Optional[float] = None
    parcel_id: str = ""
    subdivision: str = ""
    high_school: str = ""

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> "Subject":
        def num(key):
            v = rec.get(key)
            if v in (None, "") or (isinstance(v, float) and not isfinite(v)):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return cls(
            address=str(rec.get("address") or ""),
            city=str(rec.get("city") or "").strip(),
            county=str(rec.get("county") or "").strip(),
            cls=str(rec.get("_class") or "RE_1"),
            sqft=num("sqft"),
            acres=num("acres"),
            year_built=int(num("year_built")) if num("year_built") else None,
            bedrooms=num("bedrooms"),
            full_baths=num("full_baths"),
            half_baths=num("half_baths"),
            lat=num("latitude"),
            lng=num("longitude"),
            list_price=num("list_price"),
            parcel_id=str(rec.get("parcel_id") or ""),
            subdivision=str(rec.get("subdivision") or "").strip(),
            high_school=str(rec.get("high_school") or "").strip(),
        )


# ---------------------------------------------------------------------------
# Subdivision normalization
# ---------------------------------------------------------------------------

# Includes both raw and post-normalization forms — punctuation is stripped
# before the membership check, so e.g. "N/A" becomes "NA".
_SUB_NONE = {"NONE", "OTHER", "NA", "TBD", "UNKNOWN", "NULL", ""}
_SUB_PREFIXES = ("THE ",)
_SUB_SUB_PREFIXES = (
    "VILLAS AT ", "ESTATES AT ", "VILLAGES AT ", "VILLAGE AT ",
    "RESERVE AT ", "ENCLAVE AT ", "GARDENS AT ", "HEIGHTS AT ",
)


def _normalize_subdivision(value: Any) -> Optional[str]:
    """Normalize a subdivision string for cross-source matching.

    Produces a comparable form so the parcel-side ``'FIDDLERS GREEN'`` and
    the MLS-side ``"Fiddler's Green"`` (and ``"The Villas at Fiddler's Green"``)
    all reduce to the same key. Returns ``None`` for empty / placeholder
    values (None/Other/etc.)."""
    if value is None:
        return None
    s = str(value).upper()
    s = re.sub(r"[‘’'`\"\.,\-_/]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    for pfx in _SUB_PREFIXES:
        if s.startswith(pfx):
            s = s[len(pfx):]
    for pfx in _SUB_SUB_PREFIXES:
        if s.startswith(pfx):
            s = s[len(pfx):]
    s = s.strip()
    if s in _SUB_NONE:
        return None
    return s


def _normalize_subdivision_sql(column_expr: str) -> str:
    """SQL expression mirroring :func:`_normalize_subdivision`.

    Used inline in the subdivision cohort WHERE clause so DuckDB does the
    normalization on the candidate row rather than us pulling every comp
    back to Python."""
    inner = f"UPPER(COALESCE({column_expr},''))"
    # Strip punctuation. Single-quote in the pattern must be doubled to
    # escape it inside the SQL string literal. Curly apostrophes use the
    # literal Unicode chars (DuckDB regex doesn't honour \uXXXX escapes).
    punct_pattern = (
        "[" + chr(0x2018) + chr(0x2019) + chr(0x60)
        + "''" + chr(0x22) + r".,\-_/" + "]"
    )
    inner = f"REGEXP_REPLACE({inner}, '{punct_pattern}', '', 'g')"
    inner = f"REGEXP_REPLACE({inner}, '\\s+', ' ', 'g')"
    inner = f"TRIM({inner})"
    inner = f"REGEXP_REPLACE({inner}, '^THE\\s+', '', 'g')"
    inner = (
        f"REGEXP_REPLACE({inner}, "
        f"'^(VILLAS|ESTATES|VILLAGES|VILLAGE|RESERVE|ENCLAVE|GARDENS|HEIGHTS) AT\\s+', "
        f"'', 'g')"
    )
    inner = f"TRIM({inner})"
    return inner


# ---------------------------------------------------------------------------
# Scoring primitives
# ---------------------------------------------------------------------------

def _proximity(subject_v: Optional[float], comp_v: Optional[float], scale: float) -> float:
    """Return a 0..1 proximity score using an exponential decay.

    ``scale`` is the value-distance at which the score drops to ~0.37 (one e-fold).
    If either input is missing the score is 0.5 (neutral — neither rewarded nor punished).
    """
    if subject_v is None or comp_v is None or scale <= 0:
        return 0.5
    delta = abs(subject_v - comp_v)
    return exp(-delta / scale)


def _haversine_miles(a_lat, a_lng, b_lat, b_lng) -> float:
    """Great-circle distance in miles. Returns ``float('inf')`` if any coord missing."""
    if None in (a_lat, a_lng, b_lat, b_lng):
        return float("inf")
    R = 3958.7613  # Earth radius in miles
    phi1, phi2 = radians(a_lat), radians(b_lat)
    dphi = radians(b_lat - a_lat)
    dlmb = radians(b_lng - a_lng)
    h = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlmb / 2) ** 2
    return 2 * R * atan2(sqrt(h), sqrt(1 - h))


def _coerce_close_date(close_date: Any) -> Optional[date]:
    """Parse a close-date-ish value (ISO string / pandas Timestamp / datetime /
    date) to a plain ``date``, or None when missing/unparseable. Shared by the
    recency scorer and the display-only similarity surface so the two can never
    disagree on whether a sale date exists."""
    if close_date is None:
        return None
    # Guard against pandas NaT (a date-like that fails arithmetic).
    try:
        if close_date != close_date:  # NaN / NaT
            return None
    except Exception:
        pass
    if isinstance(close_date, str):
        if not close_date or close_date[:3] == "NaT":
            return None
        try:
            return date.fromisoformat(close_date[:10])
        except ValueError:
            return None
    if hasattr(close_date, "date"):
        # pandas Timestamp / datetime.datetime — convert to a plain date.
        try:
            return close_date.date()
        except (ValueError, AttributeError):
            return None
    if isinstance(close_date, date):
        return close_date
    return None


def _recency_weight(close_date: Any, *, half_life_days: float = 180,
                    as_of: Optional[date] = None) -> float:
    """Exponential decay from ``as_of`` (default today). Sales 6 months old
    score ~0.5.

    Tightened from a 9-month half-life so a comp that sold in the last 60
    days outranks a comp from 18 months ago even when their other features
    are identical. ``as_of`` anchors the decay for backtests; production
    passes nothing and decays from the run date as before."""
    cd = _coerce_close_date(close_date)
    if cd is None:
        return 0.4
    days_old = max(0, (_resolve_as_of(as_of) - cd).days)
    return exp(-days_old / half_life_days)


def score_comp(subject: Subject, comp: dict[str, Any],
               *, subject_subdivision: Optional[str] = None,
               subject_school: Optional[str] = None,
               subject_ppsf: Optional[float] = None,
               subject_subtype: Optional[str] = None,
               as_of: Optional[date] = None,
               return_breakdown: bool = False) -> float | tuple[float, dict[str, float]]:
    """Score a comp via the single transparent formula (Step 3).

    Each axis contributes ``weight * proximity`` where proximity is 0..1
    (1 = perfect match, 0 = unrelated, 0.5 = unknown/missing data).
    Maximum possible weighted-sum is ≈ sum(weights). Subdivision and school
    bonuses are added on top. The atypical-sale penalty (0.80×) is applied
    to the weighted-sum before the bonuses.

    When ``return_breakdown=True`` returns ``(score, breakdown_dict)`` so
    callers can audit per-axis contributions and verify the score is the
    sum of the listed components — no hidden adjustments outside the formula.
    """
    sf_subj = subject.sqft
    ac_subj = subject.acres
    yr_subj = float(subject.year_built) if subject.year_built else None

    sf_comp = _safe_float(comp.get("sqft"))
    ac_comp = _safe_float(comp.get("acres"))
    yr_comp = _safe_float(comp.get("year_built"))
    bd_comp = _safe_float(comp.get("bedrooms"))
    fb_comp = _safe_float(comp.get("full_baths"))

    if yr_comp is not None and not (1800 <= yr_comp <= 2030):
        yr_comp = None

    # Proximity 0..1 per axis.
    sf_score = _proximity(sf_subj, sf_comp, scale=600)
    ac_score = _proximity(ac_subj, ac_comp, scale=max(2.0, (ac_subj or 5) * 0.5))
    yr_score = _proximity(yr_subj, yr_comp, scale=15)
    bd_score = _proximity(subject.bedrooms, bd_comp, scale=1.0)
    fb_score = _proximity(subject.full_baths, fb_comp, scale=1.0)

    dist = _haversine_miles(subject.lat, subject.lng,
                            _safe_float(comp.get("latitude")),
                            _safe_float(comp.get("longitude")))
    dist_score = exp(-dist / 5.0) if isfinite(dist) else 0.5

    rec_score = _recency_weight(comp.get("close_date"), as_of=as_of)

    # Price-per-sqft proximity, anchored on the subject's reference $/sqft.
    comp_ppsf = None
    comp_sf = _safe_float(comp.get("sqft"))
    comp_sp = _safe_float(comp.get("sold_price"))
    if comp_sf and comp_sp and comp_sf > 0:
        comp_ppsf = comp_sp / comp_sf
    price_score = _proximity(subject_ppsf, comp_ppsf, scale=80.0)  # $80/sf e-fold

    w = _weights_for_subject(subject)
    breakdown: dict[str, float] = {
        "sqft":     w["SQFT"]    * sf_score,
        "acres":    w["ACRES"]   * ac_score,
        "year":     w["YEAR"]    * yr_score,
        "distance": w["DIST"]    * dist_score,
        "recency":  w["RECENCY"] * rec_score,
        "price":    w["PRICE"]   * price_score,
        "beds":     w["BEDS"]    * bd_score,
        "baths":    w["BATHS"]   * fb_score,
    }
    weighted_sum = sum(breakdown.values())

    # Atypical penalty multiplies the weighted-sum (not the bonuses).
    atypical, _reason = _atypical_signals(comp)
    if atypical:
        weighted_sum *= ATYPICAL_PENALTY
        breakdown["_atypical_multiplier"] = ATYPICAL_PENALTY

    # Pending comps inform but shouldn't overpower confirmed closed sales —
    # their price is the list-derived estimate, not a settled number. A gentle
    # discount keeps them visible (a fresh under-contract signal) while a
    # comparable closed sale outranks them.
    if comp.get("_pending"):
        weighted_sum *= PENDING_PENALTY
        breakdown["_pending_multiplier"] = PENDING_PENALTY

    # Subdivision bonus uses the normalized form so the parcel-side
    # 'FIDDLERS GREEN' matches the MLS-side "Fiddler's Green" / "The Villas
    # at Fiddlers Green" without further casing tricks at this layer.
    bonus_total = 0.0
    if subject_subdivision:
        comp_sub_norm = _normalize_subdivision(comp.get("subdivision"))
        if comp_sub_norm and comp_sub_norm == subject_subdivision:
            bonus_total += BONUS_SUBDIVISION
            breakdown["bonus_subdivision"] = BONUS_SUBDIVISION
    if subject_school:
        comp_sch = str(comp.get("high_school") or "").strip().upper()
        school_norm = subject_school.strip().upper()
        if comp_sch and school_norm and comp_sch == school_norm:
            bonus_total += BONUS_SCHOOL
            breakdown["bonus_school"] = BONUS_SCHOOL

    score = weighted_sum + bonus_total

    # Soft subtype gate (CMA_SUBTYPE_FILTER=soft): a comp of a different
    # property_subtype is discounted, not excluded. Callers only pass
    # ``subject_subtype`` in soft mode, so this is inert in production.
    # A comp with no recorded subtype is neutral (can't judge).
    if subject_subtype:
        comp_st = str(comp.get("property_subtype") or "").strip().upper()
        if comp_st and comp_st != subject_subtype.strip().upper():
            score *= SUBTYPE_MISMATCH_PENALTY
            breakdown["_subtype_multiplier"] = SUBTYPE_MISMATCH_PENALTY

    if return_breakdown:
        return score, breakdown
    return score


# ---------------------------------------------------------------------------
# Similarity surface (comp-workshop display layer; emitted behind
# CMA_COMP_SCORE_SURFACE=1 at the serialization boundary — see build_cma /
# property_profile. Lives here because it owns the weight + subdivision
# semantics the numbers are derived from.)
# ---------------------------------------------------------------------------

def _fmt_bd_ba(beds: Optional[float], baths: Optional[float]) -> str:
    """'3 bd / 2.5 ba' from whichever of beds/baths is recorded."""
    parts = []
    if beds is not None:
        parts.append(f"{int(round(beds))} bd")
    if baths is not None:
        parts.append(f"{baths:g} ba")
    return " / ".join(parts)


def similarity_surface(subject_record: dict[str, Any],
                       comp: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Per-comp 0-100 similarity + six-axis breakdown for the comp-workshop UI.

    Pure display over the annotations :func:`pick_comps` already stamped —
    reads ``_score`` / ``_score_breakdown`` and NEVER re-runs scoring,
    selection, or floors, so the surfaced numbers cannot drift from what the
    selector actually used. Pure ``f(subject, comp)``: pinning/excluding
    OTHER comps can't move any comp's number (set-relative signals like the
    $/sqft outlier flag surface in ``atypical_flags`` only, never the score).

    Normalization is raw-anchored, never set-renormalized::

        similarity = round(100 * clamp01(_score / achievable_max(subject)))
        achievable_max = sum(_weights_for_subject(subject).values())
                         + (BONUS_SUBDIVISION if subject has a normalized
                            subdivision else 0)
                         + (BONUS_SCHOOL if subject has a high_school else 0)

    The atypical (0.80x) / pending (0.90x) discounts are already inside
    ``_score``, so they fold in before normalization — the number matches what
    the selector ranked. The price-band axis is deliberately NOT a subscore
    (it reads circular next to a valuation); it stays in the overall, and a
    price component under 0.4 appends a plain-English entry to ``reasons``.
    The overall is therefore NOT the average of the six subscores.

    Missing inputs make a subscore ``None`` with a "... not recorded" reason
    (the engine scored those axes 0.5-neutral — limited data, not a poor
    match). Returns None when the comp carries no scoring annotations.
    """
    score = _safe_float(comp.get("_score"))
    breakdown = comp.get("_score_breakdown")
    if score is None or not isinstance(breakdown, dict):
        return None

    subj = Subject.from_record(subject_record)
    w = _weights_for_subject(subj)
    subj_subdivision = _normalize_subdivision(subject_record.get("subdivision"))
    subj_school = str(subject_record.get("high_school") or "").strip() or None
    possible_bonus = ((BONUS_SUBDIVISION if subj_subdivision else 0.0)
                      + (BONUS_SCHOOL if subj_school else 0.0))
    achievable_max = sum(w.values()) + possible_bonus
    similarity = int(round(100.0 * max(0.0, min(1.0, score / achievable_max))))

    def axis01(key: str, weight: float) -> float:
        v = _safe_float(breakdown.get(key))
        return (v / weight) if (v is not None and weight > 0) else 0.5

    subscores: list[dict[str, Any]] = []
    ranked: list[tuple[float, str]] = []  # (weight_pct * |score-100|, compact reason)

    def add(key: str, label: str, weight_share: float,
            score01: Optional[float], reason: Optional[str],
            compact: Optional[str] = None) -> None:
        s = (int(round(100.0 * max(0.0, min(1.0, score01))))
             if score01 is not None else None)
        weight_pct = int(round(100.0 * weight_share / achievable_max))
        subscores.append({"key": key, "label": label, "score": s,
                          "weight_pct": weight_pct, "reason": reason})
        if s is not None:
            ranked.append((weight_pct * abs(s - 100), compact or reason))

    # --- location: distance + the earned share of this subject's bonuses ----
    dist = _safe_float(comp.get("_distance_mi"))
    if dist is None:
        d = _haversine_miles(subj.lat, subj.lng,
                             _safe_float(comp.get("latitude")),
                             _safe_float(comp.get("longitude")))
        dist = d if isfinite(d) else None
    earned_bonus = ((_safe_float(breakdown.get("bonus_subdivision")) or 0.0)
                    + (_safe_float(breakdown.get("bonus_school")) or 0.0))
    if dist is not None:
        loc01 = (((_safe_float(breakdown.get("distance")) or 0.0) + earned_bonus)
                 / (w["DIST"] + possible_bonus))
        loc_reason = f"{dist:.1f} mi away"
        if breakdown.get("bonus_subdivision"):
            loc_reason += " · same subdivision"
        if breakdown.get("bonus_school"):
            loc_reason += " · same high school"
        add("location", "Location", w["DIST"] + possible_bonus, loc01,
            loc_reason, compact=f"{dist:.1f} mi away")
    else:
        add("location", "Location", w["DIST"] + possible_bonus, None,
            "distance not recorded")

    # --- recency -------------------------------------------------------------
    cd = _coerce_close_date(comp.get("close_date"))
    if cd is not None:
        months = max(0, (_resolve_as_of(None) - cd).days) // 30
        rec_reason = ("sold this month" if months <= 0
                      else f"sold {months} month{'s' if months != 1 else ''} ago")
        add("recency", "Recency", w["RECENCY"],
            axis01("recency", w["RECENCY"]), rec_reason)
    else:
        add("recency", "Recency", w["RECENCY"], None, "sale date not recorded")

    # --- size ------------------------------------------------------------------
    sf_s, sf_c = subj.sqft, _safe_float(comp.get("sqft"))
    if sf_s and sf_s > 0 and sf_c and sf_c > 0:
        pct = int(round(abs(sf_c - sf_s) / sf_s * 100.0))
        compact = ("same size" if pct == 0
                   else f"{pct}% {'larger' if sf_c > sf_s else 'smaller'}")
        add("size", "Size", w["SQFT"], axis01("sqft", w["SQFT"]),
            f"{compact} — {int(round(sf_c)):,} vs {int(round(sf_s)):,} sqft",
            compact=compact)
    else:
        add("size", "Size", w["SQFT"], None, "sqft not recorded")

    # --- lot -------------------------------------------------------------------
    ac_s, ac_c = subj.acres, _safe_float(comp.get("acres"))
    if ac_s is not None and ac_c is not None:
        add("lot", "Lot", w["ACRES"], axis01("acres", w["ACRES"]),
            f"{ac_c:.2f} ac vs {ac_s:.2f} ac")
    else:
        add("lot", "Lot", w["ACRES"], None, "lot size not recorded")

    # --- age (mirror score_comp's 1800-2030 sanity window: junk year = unrecorded)
    yr_s = float(subj.year_built) if subj.year_built else None
    yr_c = _safe_float(comp.get("year_built"))
    if yr_c is not None and not (1800 <= yr_c <= 2030):
        yr_c = None
    if yr_s is not None and yr_c is not None:
        dy = int(round(abs(yr_s - yr_c)))
        tail = ("same year" if dy == 0
                else f"{dy} yr{'s' if dy != 1 else ''} "
                     f"{'older' if yr_c < yr_s else 'newer'}")
        add("age", "Age", w["YEAR"], axis01("year", w["YEAR"]),
            f"built {int(yr_c)} — {tail}",
            compact=("built the same year" if dy == 0 else tail))
    else:
        add("age", "Age", w["YEAR"], None, "year built not recorded")

    # --- type (beds + baths share one axis; scored on FULL baths, displayed
    #     with halves folded in as .5) --------------------------------------
    bd_s, bd_c = subj.bedrooms, _safe_float(comp.get("bedrooms"))
    fb_s, fb_c = subj.full_baths, _safe_float(comp.get("full_baths"))
    beds_known = bd_s is not None and bd_c is not None
    baths_known = fb_s is not None and fb_c is not None
    if beds_known or baths_known:
        t01 = (((_safe_float(breakdown.get("beds")) or 0.0)
                + (_safe_float(breakdown.get("baths")) or 0.0))
               / (w["BEDS"] + w["BATHS"]))
        ba_c = (fb_c + 0.5 * (_safe_float(comp.get("half_baths")) or 0.0)
                if baths_known else None)
        ba_s = (fb_s + 0.5 * (subj.half_baths or 0.0)) if baths_known else None
        ty_reason = (f"{_fmt_bd_ba(bd_c if beds_known else None, ba_c)}"
                     f" vs {_fmt_bd_ba(bd_s if beds_known else None, ba_s)}")
        if not beds_known:
            ty_reason += " · beds not recorded"
        if not baths_known:
            ty_reason += " · baths not recorded"
        add("type", "Type", w["BEDS"] + w["BATHS"], t01, ty_reason)
    else:
        add("type", "Type", w["BEDS"] + w["BATHS"], None,
            "beds/baths not recorded")

    # Top-3 axes by how hard they drag the score, in compact phrasing.
    ranked.sort(key=lambda t: t[0], reverse=True)
    reasons = [r for _drag, r in ranked[:3]]
    # Price-band axis: not a subscore (reads circular) but a component under
    # 0.4 is worth a plain-English caution. Missing $/sqft is 0.5-neutral, so
    # it can never trip this.
    if axis01("price", w["PRICE"]) < 0.4:
        reasons.append("sold well outside the subject's price band")

    # Human sentences only; provenance vocabulary is "MLS" / "public records".
    atypical_flags: list[str] = []
    _areason = str(comp.get("_atypical_reason") or "").strip()
    if _areason:
        atypical_flags.append(_areason)
    if comp.get("_pending"):
        atypical_flags.append(
            "Pending sale — the price is a list-derived estimate, not a settled number.")
    if comp.get("_outlier"):
        _onote = str(comp.get("_outlier_reason") or "").strip()
        atypical_flags.append(
            "Sold at an outlier $/sqft for this comp set"
            + (f" ({_onote})." if _onote else "."))

    return {
        "similarity": similarity,
        "subscores": subscores,
        "reasons": reasons,
        "atypical_flags": atypical_flags,
    }


# ---------------------------------------------------------------------------
# Diversity enforcement
# ---------------------------------------------------------------------------

def _acre_tier(acres: Optional[float]) -> str:
    if acres is None:
        return "?"
    if acres < 2:
        return "<2ac"
    if acres < 6:
        return "2-6ac"
    if acres < 15:
        return "6-15ac"
    if acres < 40:
        return "15-40ac"
    return "40ac+"


def _atypical_signals(comp: dict[str, Any]) -> tuple[bool, str]:
    """Return ``(is_atypical, reason)`` for a comp.

    Atypical means the closing-price economics don't match a typical
    arms-length transaction — the comp may still be informative, but the
    agent should know to weight it less. Today flags:

      * Sold/list ratio below 0.85 (distressed / under-market).
      * Sold/list ratio above 1.05 (competitive multi-bid).
      * Long marketing period (DOM > 180) — listing fatigue priced it stale.

    Returns the *first* matching reason; the score multiplier in
    :func:`pick_comps` is fixed at 0.80 regardless of which signal fired.

    Returns ``(penalize, reason)``. Normally ``reason`` is non-empty only
    when ``penalize`` is True; under ``CMA_SYMMETRIC_ATYPICAL=1`` a mild
    over-list sale (ratio 1.05-1.15) returns ``(False, reason)`` — the
    reason still surfaces on the comp (display-only) but no 0.80x penalty.
    """
    sp = comp.get("sold_price")
    olp = comp.get("original_list_price")
    dom = comp.get("dom")
    try:
        if sp and olp and float(olp) > 0:
            ratio = float(sp) / float(olp)
            if ratio < 0.85:
                pct = int(round((1 - ratio) * 100))
                return True, f"Sold ~{pct}% below list — possibly distressed."
            if ratio > 1.05:
                pct = int(round((ratio - 1) * 100))
                reason = f"Sold ~{pct}% above list — competitive bid context."
                # Q4: above-list sales concentrate in the top price tercile, so
                # the asymmetric 0.80x biases estimates downward. Symmetric mode
                # keeps mild over-list (<=1.15) display-only; unset = shipped
                # asymmetric behavior.
                if (ratio <= 1.15
                        and os.environ.get("CMA_SYMMETRIC_ATYPICAL", "").strip() == "1"):
                    return False, reason
                return True, reason
    except (TypeError, ValueError):
        pass
    # Sold far below the prior recorded deed price — a strong non-arms-length /
    # distressed signal (gift, estate, intra-family, foreclosure). Prices rarely
    # halve between true market sales, so a sale under ~55% of the last deeded
    # price is almost never arms-length. Uses deed_last_sale_price (assessor
    # record), independent of the MLS list price the sold/list check relies on —
    # so it also catches off-MLS / never-listed distressed transfers.
    dsp = comp.get("deed_last_sale_price")
    try:
        if sp and dsp and float(dsp) > 1000:
            dratio = float(sp) / float(dsp)
            if dratio < 0.55:
                pct = int(round((1 - dratio) * 100))
                return True, f"Sold ~{pct}% below prior deed price — likely non-arms-length."
    except (TypeError, ValueError):
        pass
    try:
        if dom is not None and int(dom) > 180:
            return True, f"Long marketing period ({int(dom)} DOM) — may not reflect typical demand."
    except (TypeError, ValueError):
        pass
    return False, ""


def _vintage_tier(year_built: Optional[float]) -> str:
    if year_built is None:
        return "?"
    if year_built < 1960:
        return "<1960"
    if year_built < 1990:
        return "1960-89"
    if year_built < 2010:
        return "1990-09"
    return "2010+"


def _select_diverse(ranked: list[dict[str, Any]], *, n: int) -> list[dict[str, Any]]:
    """Pick top ``n`` from a similarity-ranked list with light diversity bias.

    Greedy: always take the highest-scoring candidate, but the bonus shifts
    slightly toward candidates that cover a new acreage tier or new vintage
    tier not already in the picked set.
    """
    picked: list[dict[str, Any]] = []
    seen_acre_tiers: set[str] = set()
    seen_vintage_tiers: set[str] = set()
    pool = list(ranked)

    while pool and len(picked) < n:
        best_idx = 0
        best_score = -1.0
        for i, c in enumerate(pool):
            s = c["_score"]
            at = _acre_tier(c.get("acres"))
            vt = _vintage_tier(c.get("year_built"))
            # Light diversity bonus: +5% if new acreage tier, +3% if new vintage tier
            bonus = 1.0
            if picked and at not in seen_acre_tiers:
                bonus += 0.05
            if picked and vt not in seen_vintage_tiers:
                bonus += 0.03
            effective = s * bonus
            if effective > best_score:
                best_score = effective
                best_idx = i
        chosen = pool.pop(best_idx)
        picked.append(chosen)
        seen_acre_tiers.add(_acre_tier(chosen.get("acres")))
        seen_vintage_tiers.add(_vintage_tier(chosen.get("year_built")))
    return picked


def _safe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if isfinite(f) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Candidate pool + public entry point
# ---------------------------------------------------------------------------

_CANDIDATE_COLUMNS = """
    listing_id, address, city, county, subdivision, high_school,
    CAST(parcel_id AS VARCHAR) AS parcel_id,
    status_category,
    TRY_CAST(status_changed_at AS DATE) AS status_changed_at,
    TRY_CAST(list_price AS DOUBLE) AS list_price,
    TRY_CAST(original_list_price AS DOUBLE) AS original_list_price,
    TRY_CAST(sold_price AS DOUBLE) AS sold_price,
    TRY_CAST(feed_dom AS INT) AS dom,
    list_date, close_date,
    TRY_CAST(bedrooms AS INT) AS bedrooms,
    TRY_CAST(full_baths AS INT) AS full_baths,
    TRY_CAST(half_baths AS INT) AS half_baths,
    TRY_CAST(sqft AS INT) AS sqft,
    TRY_CAST(acres AS DOUBLE) AS acres,
    TRY_CAST(year_built AS INT) AS year_built,
    TRY_CAST(latitude AS DOUBLE) AS latitude,
    TRY_CAST(longitude AS DOUBLE) AS longitude,
    TRY_CAST(appearance AS VARCHAR) AS appearance,
    TRY_CAST(deed_last_sale_price AS DOUBLE) AS deed_last_sale_price,
    property_subtype
"""

# Effective price/date used so PENDING listings (under contract, no sold_price
# yet — only a list price) join the comp pool alongside closed sales. A pending
# is the freshest market signal: it shows what a buyer agreed to pay before the
# 30-60 day lag until it closes.
_EFFECTIVE_PRICE = "COALESCE(TRY_CAST(sold_price AS DOUBLE), TRY_CAST(list_price AS DOUBLE))"
_EFFECTIVE_DATE = "COALESCE(TRY_CAST(close_date AS DATE), TRY_CAST(status_changed_at AS DATE))"


def _haversine_sql(subj_lat: float, subj_lng: float, miles: float) -> str:
    """Return a DuckDB WHERE-clause snippet for "within ``miles`` of the subject".

    Uses the haversine formula inline so SQL filters out distant comps before
    the result lands in Python. A coarse bounding-box on lat/lng narrows the
    candidate set first (cheap), then the precise haversine prunes the corners
    of the box."""
    # Approx degrees-per-mile at this latitude. 1 degree latitude ≈ 69 mi
    # everywhere; longitude shrinks with cosine(latitude).
    from math import cos, radians
    d_lat = miles / 69.0
    cos_lat = max(0.1, cos(radians(subj_lat)))
    d_lng = miles / (69.0 * cos_lat)
    return (
        f"(latitude BETWEEN {subj_lat - d_lat} AND {subj_lat + d_lat}) "
        f"AND (longitude BETWEEN {subj_lng - d_lng} AND {subj_lng + d_lng}) "
        f"AND (3958.7613 * 2 * ASIN(SQRT("
        f"POWER(SIN(RADIANS(TRY_CAST(latitude AS DOUBLE) - {subj_lat}) / 2), 2) + "
        f"COS(RADIANS({subj_lat})) * COS(RADIANS(TRY_CAST(latitude AS DOUBLE))) * "
        f"POWER(SIN(RADIANS(TRY_CAST(longitude AS DOUBLE) - {subj_lng}) / 2), 2)"
        f")) <= {miles})"
    )


def _radius_ladder(acres: Optional[float], has_subdivision: bool) -> list[float]:
    """Radius cohort steps (miles) scaled by lot density.

    A 2-mile radius is huge in a town (crosses many price tiers) but tiny in
    the country. Lot size is the density proxy: small lot → tight ladder.
    A subject with a named subdivision but no acres is assumed in-town."""
    a = acres
    if a is None:
        a = 0.5 if has_subdivision else 3.0
    if a < 1.0:
        return [0.5, 1.0, 2.0]      # urban / in-town infill
    if a < 5.0:
        return [1.0, 3.0, 5.0]      # suburban
    return [3.0, 7.0, 12.0]         # rural


def _pull_candidates(subject: Subject, *, months_back: int = 24,
                     min_count: Optional[int] = None, max_count: int = 200,
                     as_of: Optional[date] = None,
                     subtype: Optional[str] = None) -> list[dict[str, Any]]:
    """Pull the candidate pool, with the optional hard subtype gate (Q1).

    ``min_count=None`` resolves via ``CMA_MIN_CANDIDATES`` (unset = the shipped
    30). ``as_of`` anchors the lookback cutoffs (default today — production
    behavior). When ``subtype`` is set (CMA_SUBTYPE_FILTER=hard), candidates
    are filtered to that property_subtype at the SQL layer so cohort
    accumulation still reaches ``min_count`` of *matching* rows; a filtered
    pool under 10 rows falls back to the unfiltered pull."""
    if min_count is None:
        min_count = _min_candidates()
    asof = _resolve_as_of(as_of)
    if subtype:
        st = str(subtype).strip().upper().replace("'", "''")
        clause = f"UPPER(COALESCE(property_subtype,'')) = '{st}'"
        rows = _pull_candidate_pool(
            subject, months_back=months_back, min_count=min_count,
            max_count=max_count, as_of=asof, extra_where=clause,
        )
        if len(rows) >= 10:
            return rows
    return _pull_candidate_pool(
        subject, months_back=months_back, min_count=min_count,
        max_count=max_count, as_of=asof, extra_where=None,
    )


def _pull_candidate_pool(subject: Subject, *, months_back: int = 24,
                         min_count: int = 30, max_count: int = 200,
                         as_of: Optional[date] = None,
                         extra_where: Optional[str] = None) -> list[dict[str, Any]]:
    """Pull a candidate pool via concentric cohorts (A1).

    Cohorts run in priority order, accumulating dedup-by-parcel as we go:

      1. Same subdivision (exact match)
      2. Within 2 miles
      3. Within 5 miles
      4. Within 10 miles
      5. Same county + strict acreage band  (existing behaviour)
      6. Same county + widened acreage band
      7. All counties, strict acreage band  (final fallback)
      8. All counties, no acreage band      (last resort, very rare)

    Each cohort applies the same base filters (class, closed, recent,
    acreage-tier, soft sqft/price bounds). Pull stops as soon as the
    accumulated pool has ``min_count`` rows. Earlier cohorts hold their
    "primary" status in the returned list — when the scorer's distance
    weight kicks in, same-subdivision and tight-radius matches already
    have a leg up before any score is computed.

    Skipped cohorts when subject inputs are missing:
      * No subdivision -> skip cohort 1
      * No lat/lng     -> skip cohorts 2-4 (radius)
      * No county      -> skip cohorts 5-6 (county) and fall to all-county
    """
    con = _fast_listings_connection()
    cls = subject.cls or "RE_1"
    asof = _resolve_as_of(as_of)
    cutoff = asof - timedelta(days=int(months_back * 30.4))
    # Closed sales AND pending (under-contract) listings. Pending join via the
    # effective price/date so they're valued on their list price + go-pending
    # date — a fresher market signal than closings that reflect 30-60-day-old
    # contracts.
    base_where = [
        f"_class = '{cls}'",
        "status_category IN ('Closed', 'Pending')",
        f"{_EFFECTIVE_PRICE} > 25000",
        f"{_EFFECTIVE_DATE} >= '{cutoff.isoformat()}'",
    ]
    if extra_where:
        base_where.append(extra_where)
    if subject.sqft and subject.sqft > 0:
        lo, hi = subject.sqft * 0.4, subject.sqft * 2.5
        base_where.append(
            f"(TRY_CAST(sqft AS DOUBLE) BETWEEN {lo} AND {hi} OR sqft IS NULL)"
        )
    if subject.list_price and subject.list_price > 0:
        plo, phi = subject.list_price * 0.4, subject.list_price * 3.0
        base_where.append(f"{_EFFECTIVE_PRICE} BETWEEN {plo} AND {phi}")

    def _exec(where_clauses: list[str]) -> list[dict[str, Any]]:
        sql = f"""
        SELECT {_CANDIDATE_COLUMNS}
        FROM listings
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {_EFFECTIVE_DATE} DESC NULLS LAST
        LIMIT {max_count}
        """
        return con.execute(sql).fetchdf().to_dict(orient="records")

    def _acre_clause(lo: float, hi: Optional[float]) -> str:
        if hi is None:
            return f"TRY_CAST(acres AS DOUBLE) >= {lo}"
        return f"TRY_CAST(acres AS DOUBLE) BETWEEN {lo} AND {hi}"

    def _county_clause() -> Optional[str]:
        if not subject.county:
            return None
        c = subject.county.replace("'", "''").upper()
        return f"UPPER(COALESCE(county,'')) = '{c}'"

    band_lo, band_hi = _acre_band_for(subject.acres)
    has_acres = subject.acres is not None and subject.acres > 0
    strict_acre = _acre_clause(band_lo, band_hi) if has_acres else None
    wider_lo, wider_hi = _widen_acre_band(band_lo, band_hi) if has_acres else (0.0, None)
    wider_acre = _acre_clause(wider_lo, wider_hi) if has_acres else None
    county = _county_clause()

    # --- Subdivision-first with a sufficiency gate (in-town accuracy) -----
    # In a town/city even a 1-2 mile radius spans very different price tiers
    # (Fiddler's Green vs Cedar Orchard vs downtown Blacksburg). When the
    # subject is in a real named subdivision AND that subdivision has enough
    # recent sales, use ONLY same-subdivision comps — pulled over a longer
    # window, because neighborhood dominates recency and the $/sqft
    # time-adjustment already trends older sales forward.
    SUBDIVISION_SUFFICIENT = 5
    sub_norm = _normalize_subdivision(subject.subdivision)
    sub_clause: Optional[str] = None
    if sub_norm:
        sub_clean = sub_norm.replace("'", "''")
        sub_expr = _normalize_subdivision_sql("subdivision")
        sub_clause = f"{sub_expr} = '{sub_clean}'"
        sub_cutoff = asof - timedelta(days=int(max(months_back, 48) * 30.4))
        sub_where = [
            f"_class = '{cls}'",
            "status_category IN ('Closed', 'Pending')",
            f"{_EFFECTIVE_PRICE} > 25000",
            f"{_EFFECTIVE_DATE} >= '{sub_cutoff.isoformat()}'",
            sub_clause,
        ]
        if extra_where:
            sub_where.append(extra_where)
        if subject.sqft and subject.sqft > 0:
            lo, hi = subject.sqft * 0.4, subject.sqft * 2.5
            sub_where.append(
                f"(TRY_CAST(sqft AS DOUBLE) BETWEEN {lo} AND {hi} OR sqft IS NULL)"
            )
        try:
            sub_rows = _exec(sub_where)
        except Exception:
            sub_rows = []
        if len(sub_rows) >= SUBDIVISION_SUFFICIENT:
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for r in sub_rows:
                pid = str(r.get("parcel_id") or "").strip().upper()
                ak = str(r.get("address") or "").strip().upper()
                k = pid or ak
                if not k or k in seen:
                    continue
                seen.add(k)
                r["_cohort"] = "subdivision"
                out.append(r)
            return out

    # --- Concentric fallback cohorts (thin/no subdivision) ----------------
    # Build the ordered cohort attempt list. The radius ladder is scaled by
    # lot density so 2 miles is only ever used for rural subjects.
    cohort_attempts: list[tuple[str, list[str]]] = []
    if sub_clause is not None:
        # Keep the (thin) same-subdivision comps as the highest-priority cohort.
        cohort_attempts.append(("subdivision", base_where + [sub_clause]))

    radius_ladder = _radius_ladder(subject.acres, sub_norm is not None)
    if subject.lat is not None and subject.lng is not None:
        for radius_mi in radius_ladder:
            radius_clause = _haversine_sql(float(subject.lat), float(subject.lng), float(radius_mi))
            # Within radius, use the strict acreage band if available
            inner = base_where + [radius_clause]
            if strict_acre:
                inner = inner + [strict_acre]
            cohort_attempts.append((f"within_{radius_mi:g}mi", inner))

    if county and strict_acre:
        cohort_attempts.append(("county_strict", base_where + [county, strict_acre]))
    if county and wider_acre and wider_acre != strict_acre:
        cohort_attempts.append(("county_wider", base_where + [county, wider_acre]))
    if strict_acre:
        cohort_attempts.append(("any_strict", base_where + [strict_acre]))
    if wider_acre and wider_acre != strict_acre:
        cohort_attempts.append(("any_wider", base_where + [wider_acre]))
    if county:
        cohort_attempts.append(("county_only", base_where + [county]))
    cohort_attempts.append(("any", base_where))

    accumulated: list[dict[str, Any]] = []
    seen_pids: set[str] = set()
    seen_addrs: set[str] = set()
    for cohort_name, where_clauses in cohort_attempts:
        try:
            rows = _exec(where_clauses)
        except Exception:
            # Haversine math overflow or similar — skip this cohort cleanly.
            continue
        for r in rows:
            pid = str(r.get("parcel_id") or "").strip().upper()
            addr_key = str(r.get("address") or "").strip().upper()
            key = pid or addr_key
            if not key:
                continue
            if pid and pid in seen_pids:
                continue
            if not pid and addr_key in seen_addrs:
                continue
            r["_cohort"] = cohort_name
            accumulated.append(r)
            if pid:
                seen_pids.add(pid)
            else:
                seen_addrs.add(addr_key)
        if len(accumulated) >= min_count:
            break
    return accumulated


def _normalize_pending(candidates: list[dict[str, Any]]) -> None:
    """Give pending (under-contract) comps a usable price + date, in place.

    A pending listing has no ``sold_price`` yet — only a list price and the
    date it went under contract. To value it alongside closed sales we:
      * estimate its likely sale price as ``list_price`` × the pool's median
        sold/list ratio (homes usually close at ~97-100% of list),
      * use ``status_changed_at`` (the go-pending date) as its ``close_date``
        so recency + time-adjustment treat it as the fresh signal it is,
      * tag it ``_pending`` / ``_status`` so the report can flag it.
    Closed comps are left untouched."""
    ls_ratios = []
    for c in candidates:
        if str(c.get("status_category") or "") == "Closed":
            sp = c.get("sold_price")
            olp = c.get("original_list_price") or c.get("list_price")
            if sp and olp and olp > 0:
                r = float(sp) / float(olp)
                if 0.5 < r < 1.5:
                    ls_ratios.append(r)
    ls_ratios.sort()
    ls_ratio = ls_ratios[len(ls_ratios) // 2] if ls_ratios else 0.98

    def _valid_date(v):
        if v is None:
            return None
        try:
            if v != v:  # NaN / NaT
                return None
        except Exception:
            pass
        s = str(v)
        if not s or s[:3] == "NaT":
            return None
        return v

    def _has_price(v) -> bool:
        try:
            return v is not None and v == v and float(v) > 0  # rejects None + NaN
        except (TypeError, ValueError):
            return False

    for c in candidates:
        if str(c.get("status_category") or "") != "Pending":
            continue
        lp = c.get("list_price")
        if _has_price(lp) and not _has_price(c.get("sold_price")):
            c["sold_price"] = round(float(lp) * ls_ratio)
        if not _valid_date(c.get("close_date")):
            c["close_date"] = _valid_date(c.get("status_changed_at")) or _valid_date(c.get("list_date"))
        c["_pending"] = True
        c["_status"] = "Pending"
        c["_pending_ls_ratio"] = round(ls_ratio, 3)


def _bedbath_ok(subj: "Subject", comp: dict[str, Any], max_delta: float) -> bool:
    """True unless the comp's beds OR full-baths differ from the subject by more
    than ``max_delta``. Missing values on either side never reject (can't judge)."""
    sb, cb = subj.bedrooms, _safe_float(comp.get("bedrooms"))
    if sb is not None and cb is not None and abs(sb - cb) > max_delta:
        return False
    sf, cf = subj.full_baths, _safe_float(comp.get("full_baths"))
    if sf is not None and cf is not None and abs(sf - cf) > max_delta:
        return False
    return True


def _apply_quality_floor(comps: list[dict[str, Any]], frac: float,
                         min_keep: int) -> list[dict[str, Any]]:
    """Keep only comps scoring >= best_score*frac (drop loose padding); never
    fewer than ``min_keep`` (highest-scored kept as a stability floor)."""
    if frac <= 0 or len(comps) <= min_keep:
        return comps
    best = max(c["_score"] for c in comps)
    keep = [c for c in comps if c["_score"] >= best * frac]
    if len(keep) >= min_keep:
        return keep
    return sorted(comps, key=lambda c: c["_score"], reverse=True)[:min_keep]


def _handle_ppsf_outliers(comps: list[dict[str, Any]], k: float,
                          drop_ratio: float, min_keep: int,
                          *, flag: bool = True, min_vals: int = 4,
                          min_len: Optional[int] = None) -> list[dict[str, Any]]:
    """$/sqft outlier handling within a candidate/selected set:
      * FLAG (``_outlier`` + reason) any comp > ``k`` MADs AND >25% from the set
        median — surfaced to the agent, kept in the set (value-neutral tracking).
      * DROP only the egregious ones (> ``drop_ratio`` x or < 1/``drop_ratio`` x
        the median) — near-certain data errors / wrong-type comps.
    Never drops below ``min_keep``. No-op when both knobs are 0.

    Median/MAD are computed robustly so a single bad comp can't mask itself:
    when invoked on the SCORED CANDIDATE POOL (pre-selection) the larger sample
    yields a stable median, so the pool pass (``flag=False``) only drops and
    leaves flagging to the post-selection pass.
    """
    size_floor = min_len if min_len is not None else max(min_keep, 3)
    if (k <= 0 and drop_ratio <= 0) or len(comps) <= size_floor:
        return comps
    ppsf: list[Optional[float]] = []
    for c in comps:
        sp, sf = _safe_float(c.get("sold_price")), _safe_float(c.get("sqft"))
        ppsf.append(sp / sf if sp and sf and sf > 0 else None)
    vals = sorted(v for v in ppsf if v is not None)
    if len(vals) < min_vals:
        return comps
    med = vals[len(vals) // 2]
    devs = sorted(abs(v - med) for v in vals)
    mad = devs[len(devs) // 2]
    if med <= 0:
        return comps
    kept: list[dict[str, Any]] = []
    for c, p in zip(comps, ppsf):
        if p is None:
            kept.append(c)
            continue
        rel = abs(p - med) / med
        if flag and k > 0 and mad > 0 and abs(p - med) > k * mad and rel > 0.25:
            c["_outlier"] = True
            c["_outlier_reason"] = f"$/sqft {p:.0f} vs comp-set median {med:.0f}"
        if drop_ratio > 0 and (p > med * drop_ratio or p < med / drop_ratio):
            continue  # egregious $/sqft — almost certainly a bad/wrong-type comp
        kept.append(c)
    return kept if len(kept) >= min_keep else comps


def pick_comps(subject: dict | Subject, *, n: int = 6,
               months_back: int = 24,
               overrides: Optional[Iterable[str]] = None,
               excluded: Optional[Iterable[str]] = None,
               as_of: Optional[date] = None) -> list[dict[str, Any]]:
    """Return the top-``n`` comps as a list of dicts with scoring annotations.

    Each returned dict has the comp fields plus ``_score`` (raw similarity) and
    ``_distance_mi`` (haversine miles to the subject when both have coords).

    Parameters
    ----------
    subject : dict | Subject
        Subject record (from ``find_subject``) or a pre-built ``Subject``.
    n : int
        Target comp count.
    months_back : int
        Closed-sale lookback window.
    overrides : iterable of str, optional
        Specific comp addresses (case-insensitive substring match) to force-include
        ahead of similarity scoring. Useful for the ``--comps`` CLI flag.
    excluded : iterable of str, optional
        Specific comp addresses to drop from the candidate pool. Supports the
        dashboard's "× remove" comp-preview action.
    as_of : date, optional
        Anchor for recency decay + lookback cutoffs. Default None = today
        (production behavior); backtests pass the simulated valuation date
        (or set ``AS_OF_OVERRIDE`` when they can't reach this kwarg).
    """
    subj = subject if isinstance(subject, Subject) else Subject.from_record(subject)
    # Subject-derived inputs computed once so the per-comp scorer doesn't
    # keep re-reading them off the raw dict. Subdivision uses the normalized
    # form so the comparison is symmetric with the SQL cohort filter.
    subj_dict = subject if isinstance(subject, dict) else {}
    subj_subdivision = _normalize_subdivision(subj_dict.get("subdivision"))
    subj_school = str(subj_dict.get("high_school") or "").strip() or None
    subj_ppsf = _subject_reference_ppsf(subj_dict)
    asof = _resolve_as_of(as_of)
    # Q1 subtype gate: inert unless CMA_SUBTYPE_FILTER is set AND the subject
    # dict carries a property_subtype.
    subtype_mode = _subtype_filter_mode()
    subj_subtype = str(subj_dict.get("property_subtype") or "").strip() or None

    candidates = _pull_candidates(
        subj, months_back=months_back, as_of=asof,
        subtype=subj_subtype if subtype_mode == "hard" else None,
    )
    _normalize_pending(candidates)

    # A6 — dedup + self-exclusion. The closed-listings table can contain the
    # same parcel multiple times (one row per transaction). Keep the most
    # recent close_date per parcel_id; for rows missing a parcel_id, dedup
    # by uppercased address. Drop any row whose parcel_id matches the
    # subject's so we don't pick a property as its own comp.
    subj_parcel = str(subj.parcel_id or "").strip().upper()
    seen_parcels: dict[str, dict[str, Any]] = {}
    seen_addresses: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for c in candidates:
        pid = str(c.get("parcel_id") or "").strip().upper()
        if pid and subj_parcel and pid == subj_parcel:
            continue
        addr_key = str(c.get("address") or "").strip().upper()
        close_d = c.get("close_date")
        if pid:
            existing = seen_parcels.get(pid)
            if existing is None or (close_d and (
                not existing.get("close_date") or close_d > existing["close_date"]
            )):
                seen_parcels[pid] = c
        elif addr_key:
            existing = seen_addresses.get(addr_key)
            if existing is None or (close_d and (
                not existing.get("close_date") or close_d > existing["close_date"]
            )):
                seen_addresses[addr_key] = c
        else:
            # No parcel_id and no address — surface anyway, can't dedup safely.
            deduped.append(c)
    candidates = list(seen_parcels.values()) + list(seen_addresses.values()) + deduped

    if excluded:
        excl = [e.strip().upper() for e in excluded if e and e.strip()]
        if excl:
            candidates = [
                c for c in candidates
                if not any(x in str(c.get("address") or "").upper() for x in excl)
            ]

    forced: list[dict[str, Any]] = []
    def _score(c: dict[str, Any]) -> tuple[float, dict[str, float]]:
        result = score_comp(
            subj, c,
            subject_subdivision=subj_subdivision,
            subject_school=subj_school,
            subject_ppsf=subj_ppsf,
            subject_subtype=subj_subtype if subtype_mode == "soft" else None,
            as_of=asof,
            return_breakdown=True,
        )
        return result  # type: ignore[return-value]

    if overrides:
        wanted = [o.strip().upper() for o in overrides if o.strip()]
        remaining = []
        for c in candidates:
            addr_u = str(c.get("address") or "").upper()
            if any(w in addr_u for w in wanted):
                c2 = dict(c)
                s, breakdown = _score(c)
                atypical, reason = _atypical_signals(c)
                c2["_score"] = s
                c2["_score_breakdown"] = breakdown
                # Display-only signals (Q4 symmetric mode) carry a reason with
                # penalize=False — keep the badge without the score penalty.
                c2["_atypical_sale"] = atypical or bool(reason)
                c2["_atypical_reason"] = reason
                c2["_distance_mi"] = _haversine_miles(
                    subj.lat, subj.lng, c.get("latitude"), c.get("longitude")
                )
                c2["_forced"] = True
                forced.append(c2)
            else:
                remaining.append(c)
        candidates = remaining

    # Step 3 — cohort priority drives WHERE we look (SQL pull order in
    # ``_pull_candidates``); the scorer no longer adds cohort bonuses on top.
    # Cohort labels are preserved on each comp for the dashboard preview.
    scored = []
    for c in candidates:
        s, breakdown = _score(c)
        atypical, reason = _atypical_signals(c)
        c2 = dict(c)
        c2["_score"] = s
        c2["_score_breakdown"] = breakdown
        # Display-only (Q4): reason without penalty still flags the comp.
        c2["_atypical_sale"] = atypical or bool(reason)
        c2["_atypical_reason"] = reason
        c2["_distance_mi"] = _haversine_miles(
            subj.lat, subj.lng, c.get("latitude"), c.get("longitude")
        )
        scored.append(c2)
    scored.sort(key=lambda r: r["_score"], reverse=True)

    # Comp-quality controls (no-ops at default knob values):
    #  (1) bed/bath hard guard BEFORE selection — never let a strong
    #      subdivision/distance match pull in a far-off bed/bath property;
    #  (2) closeness floor + (3) $/sqft outlier exclusion AFTER selection —
    #      drop loose padding / extreme comps rather than reaching for 6.
    # Forced (operator-requested) comps bypass all three.
    if _BEDBATH_MAX_DELTA > 0:
        guarded = [c for c in scored if _bedbath_ok(subj, c, _BEDBATH_MAX_DELTA)]
        if len(guarded) >= min(_COMP_MIN, n):
            scored = guarded

    # (3a) Drop egregious $/sqft comps on the SCORED CANDIDATE POOL *before*
    #      selection, so a bad comp can't mask itself in the small final-6
    #      median. The robust pool median anchors the drop; flagging is left to
    #      the post-selection pass below (value-neutral on the final set).
    if _PPSF_DROP_RATIO > 0:
        # Wider ratio on the pool: only the near-certain data errors / wrong-type
        # comps (a robust pool median anchors it); normal spread is left for the
        # selector to weigh.
        _pool_ratio = max(_PPSF_DROP_RATIO, 3.0)
        scored = _handle_ppsf_outliers(
            scored, 0.0, _pool_ratio, min(_COMP_MIN, n),
            flag=False, min_vals=8, min_len=max(n, 8),
        )

    remaining_slots = max(0, n - len(forced))
    diverse = _select_diverse(scored, n=remaining_slots) if remaining_slots else []
    diverse = _apply_quality_floor(diverse, _COMP_FLOOR_FRAC, _COMP_MIN)
    diverse = _handle_ppsf_outliers(diverse, _PPSF_OUTLIER_K, _PPSF_DROP_RATIO, _COMP_MIN)
    return forced + diverse


__all__ = ["Subject", "pick_comps", "score_comp", "similarity_surface"]
