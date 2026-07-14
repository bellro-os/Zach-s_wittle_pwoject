"""Full HOUSE PROFILE backend for the CMA tool's property-profile UI.

Given an address (and optional ``--parcel``), returns ONE JSON object that
bundles everything the property-profile page renders:

    facts          — property identifiers + structure (address, parcel, sqft,
                     beds/baths, year built, assessed/tax, lat/lng)
    valuation      — triangulated mid/low/high + per-method breakdown
    comps          — the scored comparable set used for the valuation
    saleHistory    — the subject parcel's MLS-CONFIRMED prior closed sales
                     (the trusted path — assessor deed junk is ignored)
    marketContext  — area (subdivision else county) median $/sqft + trend,
                     median DOM, active/sold counts + months-of-inventory
    meta           — generated/as-of timestamps + per-section availability flags

This reuses the EXACT production path the branded CMA + quick_comp use:
``resolve_subject`` -> ``pick_comps`` -> ``_estimate_value``, plus
``build_cma._mls_confirmed_prior_sale`` for the trusted sale history. The
market-context section reads the same slim ``data/mls_lookup.parquet`` that the
comp scorer + prior-sale lookup use, scoped to the subject's area, so the whole
profile resolves in well under a second without touching the 200 MB JSONL.

CLI (matches web-cma's ``__JSON__`` marker convention so the Next route can
parse this the same way it parses build_cma's output)::

    python -X utf8 scripts/property_profile.py "509 Jefferson St Blacksburg VA"
    python -X utf8 scripts/property_profile.py "..." --parcel 140331 --pretty

On error it still prints a ``__JSON__`` line with ``ok=False`` + an error
message (never raises out of ``main``), so the caller always gets parseable
JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path bootstrap — mirror quick_comp.py so `build_cma` + `mls_bot.*` import.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT / "scripts"), str(_ROOT / "src")):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
import os  # noqa: E402

os.chdir(_ROOT)

# The property-profile UI is interactive and spawns a FRESH Python process per
# request, so the AVM's ~5s+ cold scikit-learn import (and ~13s total) is the
# dominant latency. Default this path to fast mode (skip the AVM ensemble member;
# the comp methods renormalize). The full CMA / PDF generate path leaves this
# unset and keeps the AVM. Override with CMA_SKIP_AVM=0 if a profile must use it.
os.environ.setdefault("CMA_SKIP_AVM", "1")

from build_cma import (  # noqa: E402
    _apply_blind_ensemble,
    _apply_subject_overrides,
    _blind_ensemble_enabled,
    _estimate_value,
    _mls_confirmed_prior_sale,
    _num,
    _resolve_subject,
    _round_to_5k,
    _score_surface_enabled,
    _similarity_summary,
    confidence_tier,
    prepare_comps,
)
from mls_bot.analytics.cma_compset import (  # noqa: E402
    _normalize_subdivision,
    pick_comps,
    similarity_surface,
)

# Same slim parquet the comp scorer + prior-sale lookup read.
_MLS_LOOKUP_PARQUET = _ROOT / "data" / "mls_lookup.parquet"

# Numeric columns the DuckDB-over-JSONL driver hands back as strings; coerce the
# ones we do math on (identical list to quick_comp / build_cma).
_COERCE = (
    "sqft", "acres", "list_price", "original_list_price", "sold_price",
    "bedrooms", "full_baths", "half_baths", "year_built", "feed_dom",
    "latitude", "longitude",
)

# Recent window (months) for the market-context aggregates.
_MARKET_WINDOW_MONTHS = 12


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _int_or_none(v) -> Optional[int]:
    f = _num(v)
    return int(round(f)) if f is not None else None


def _round_or_none(v, ndigits: int = 1) -> Optional[float]:
    f = _num(v)
    return round(f, ndigits) if f is not None else None


def _date_str(v) -> Optional[str]:
    """Coerce a date-ish value to a 'YYYY-MM-DD' string, or None."""
    if v is None:
        return None
    try:
        if v != v:  # NaN / NaT
            return None
    except Exception:
        pass
    s = str(v).strip()
    if not s or s[:3] == "NaT" or s.lower() == "none":
        return None
    return s[:10]


# ---------------------------------------------------------------------------
# Section: facts
# ---------------------------------------------------------------------------

def _build_facts(subject: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Property identifiers + structure. Returns (facts, missing_field_flags)."""
    facts = {
        "address": subject.get("address") or None,
        "city": subject.get("city") or None,
        "county": subject.get("county") or None,
        "parcel_id": str(subject.get("parcel_id") or "") or None,
        "subdivision": subject.get("subdivision") or None,
        "property_type": subject.get("_class") or None,
        "status": subject.get("status_category") or None,
        "sqft": _int_or_none(subject.get("sqft")),
        "acres": _round_or_none(subject.get("acres"), 3),
        "beds": _int_or_none(subject.get("bedrooms")),
        "full_baths": _int_or_none(subject.get("full_baths")),
        "half_baths": _int_or_none(subject.get("half_baths")),
        "year_built": _int_or_none(subject.get("year_built")),
        # Assessor value is the only "tax" anchor we carry; surface it plainly.
        "assessed_value": _int_or_none(subject.get("assessed_total")),
        "lat": _round_or_none(subject.get("latitude"), 6),
        "lng": _round_or_none(subject.get("longitude"), 6),
        # Live list price only exists for on-market subjects.
        "list_price": _int_or_none(subject.get("list_price")),
    }
    missing = [k for k, v in facts.items() if v is None]
    return facts, missing


# ---------------------------------------------------------------------------
# Section: valuation
# ---------------------------------------------------------------------------

def _build_valuation(subject: dict[str, Any], comps: list[dict[str, Any]],
                     valuation) -> dict[str, Any]:
    sqft = _num(subject.get("sqft"))
    # Presentation boundary — the profile UI displays these, so apply the $5k
    # display rounding here (ValuationResult now carries unrounded floats).
    mid, low, high = (_round_to_5k(valuation.mid), _round_to_5k(valuation.low),
                      _round_to_5k(valuation.high))
    implied_ppsf = (mid / sqft) if (sqft and mid) else None
    return {
        "mid": mid or None,
        "low": low or None,
        "high": high or None,
        "comp_ppsf": _round_or_none(valuation.ppsf, 1),
        "implied_subject_ppsf": _round_or_none(implied_ppsf, 1),
        "divergence_pct": _round_or_none(valuation.divergence_pct, 1),
        "methods": [
            {
                "name": m.name,
                "value": _int_or_none(m.value),
                # Rationale strings carry inline <b>..</b> markup the branded
                # report uses; keep them as-is so the UI can render or strip.
                "rationale": m.rationale,
            }
            for m in valuation.methods
        ],
    }


# ---------------------------------------------------------------------------
# Section: comps
# ---------------------------------------------------------------------------

def _build_comps(comps: list[dict[str, Any]],
                 subject: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    # Comp-workshop similarity surface (CMA_COMP_SCORE_SURFACE=1, compbird's
    # engine env only): additive per-comp fields appended AFTER the stable
    # shape so the unset path stays byte-identical for Ratifyly.
    surface_on = _score_surface_enabled() and subject is not None
    out: list[dict[str, Any]] = []
    for c in comps:
        sp = _num(c.get("sold_price"))
        sf = _num(c.get("sqft"))
        ppsf = (sp / sf) if (sp and sf and sf > 0) else None
        dist = _num(c.get("_distance_mi"))
        # haversine returns inf when either side lacks coords — surface null
        # (inf isn't valid JSON; _num already drops NaN).
        if dist is not None and dist == float("inf"):
            dist = None
        row = {
            "address": c.get("address") or None,
            "city": c.get("city") or None,
            "subdivision": c.get("subdivision") or None,
            "sold_price": _int_or_none(sp),
            "ppsf": _round_or_none(ppsf, 1),
            "sqft": _int_or_none(sf),
            "acres": _round_or_none(c.get("acres"), 2),
            "beds": _int_or_none(c.get("bedrooms")),
            "baths": _int_or_none(c.get("full_baths")),
            "year_built": _int_or_none(c.get("year_built")),
            "close_date": _date_str(c.get("close_date")),
            "dom": _int_or_none(c.get("dom")),
            "distance_mi": _round_or_none(dist, 2),
            # Coordinates so the UI can plot the comp on a neighborhood map
            # alongside the subject (facts.lat/lng). The comp dicts from
            # pick_comps carry latitude/longitude; surface them as lat/lng.
            "lat": _round_or_none(c.get("latitude"), 6),
            "lng": _round_or_none(c.get("longitude"), 6),
            # Carry the leading-signal / data-quality flags the scorer set so
            # the UI can badge pending / atypical comps like the branded report.
            "pending": bool(c.get("_pending")),
            "atypical": bool(c.get("_atypical_sale")),
            # Comp provenance: which pool the sale came from ("mls" default;
            # the supplemental public-records pool stamps source='supplemental').
            "source": (c.get("source") or "mls"),
            # Engine reasoning for the UI's rationale tooltips.
            "atypical_reason": c.get("_atypical_reason") or None,
            "cohort": c.get("_cohort") or None,
        }
        if surface_on:
            surface = similarity_surface(subject, c)
            if surface:
                row.update(surface)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Section: saleHistory (trusted MLS-confirmed path only)
# ---------------------------------------------------------------------------

def _build_sale_history(subject: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Subject parcel's MLS-CONFIRMED closed sales — newest first.

    Builds on ``build_cma._mls_confirmed_prior_sale`` (which returns only the
    single most-recent confirmed sale) but pulls the FULL closed-sale chain for
    the parcel from the same slim parquet, applying the same trust rules:
    Closed status + positive sold price. Assessor ``deed_last_sale_*`` records
    are deliberately excluded (they include refis / intra-family transfers /
    misdated rows — e.g. 509 Jefferson's bogus $775k).
    """
    info: dict[str, Any] = {"source": "mls_confirmed", "deed_ignored": True}
    pid = str(subject.get("parcel_id") or "").strip()
    if not pid:
        info["available"] = False
        info["reason"] = "no parcel_id on subject"
        return [], info
    if not _MLS_LOOKUP_PARQUET.exists():
        info["available"] = False
        info["reason"] = "mls_lookup.parquet missing"
        return [], info

    try:
        import duckdb
        con = duckdb.connect(":memory:")
        con.execute(
            f"CREATE VIEW l AS SELECT * FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}')"
        )
        rows = con.execute(
            f"""SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                       CAST(close_date AS VARCHAR) cd,
                       listing_id
                FROM l
                WHERE CAST(parcel_id AS VARCHAR) = '{pid.replace("'", "''")}'
                  AND status_category = 'Closed'
                  AND TRY_CAST(sold_price AS DOUBLE) > 0
                ORDER BY close_date DESC NULLS LAST"""
        ).fetchall()
    except Exception as e:  # pragma: no cover - defensive
        info["available"] = False
        info["reason"] = f"query failed: {e}"
        return [], info

    history: list[dict[str, Any]] = []
    seen: set[tuple[Optional[int], Optional[str]]] = set()
    for sp, cd, _lid in rows:
        price = _int_or_none(sp)
        when = _date_str(cd)
        key = (price, when)
        if key in seen:
            continue
        seen.add(key)
        history.append({"price": price, "date": when})

    info["available"] = bool(history)
    info["count"] = len(history)
    if not history:
        # Note the bogus deed value we deliberately skipped, for transparency.
        deed_price = _int_or_none(subject.get("deed_last_sale_price"))
        if deed_price:
            info["reason"] = (
                "no MLS-confirmed closed sale; assessor deed value "
                f"(${deed_price:,}) excluded as untrusted"
            )
        else:
            info["reason"] = "no MLS-confirmed closed sale for this parcel"
    return history, info


# ---------------------------------------------------------------------------
# Section: marketContext (area-scoped aggregates from the slim parquet)
# ---------------------------------------------------------------------------

def _market_context(subject: dict[str, Any]) -> dict[str, Any]:
    """Area market snapshot: median $/sqft + trend, median DOM, active/sold
    counts, months-of-inventory.

    Scope precedence: same normalized subdivision (when the subject has one and
    it has enough recent sales) else same county. Computed inline from the slim
    ``data/mls_lookup.parquet`` because the analytics market modules
    (dom/velocity/spread/performance) only emit county×class CSVs off the heavy
    JSONL connection — too coarse + too slow for a single-property profile.

    The trend is a simple split-half median-$/sqft comparison over the recent
    window (same idea as ``build_cma._estimate_appreciation_rate``, expressed as
    a window-over-window % so the UI can show an up/down arrow).
    """
    out: dict[str, Any] = {
        "scope": None,
        "scope_value": None,
        "window_months": _MARKET_WINDOW_MONTHS,
        "available": False,
    }
    if not _MLS_LOOKUP_PARQUET.exists():
        out["reason"] = "mls_lookup.parquet missing"
        return out

    cls = str(subject.get("_class") or "RE_1")
    county = str(subject.get("county") or "").strip()
    sub_norm = _normalize_subdivision(subject.get("subdivision"))

    try:
        import duckdb
        con = duckdb.connect(":memory:")
        con.execute(
            f"CREATE VIEW l AS SELECT * FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}')"
        )
    except Exception as e:  # pragma: no cover - defensive
        out["reason"] = f"connect failed: {e}"
        return out

    cls_q = cls.replace("'", "''")
    window_clause = (
        f"close_date >= (CURRENT_DATE - INTERVAL '{_MARKET_WINDOW_MONTHS} months')"
    )

    def _scope_clause(scope: str) -> Optional[str]:
        if scope == "subdivision" and sub_norm:
            # Mirror the scorer's normalized-subdivision comparison in SQL by
            # upper/strip — good enough for the snapshot (the exact normalizer
            # is reproduced in cma_compset for scoring; here we just need a
            # neighborhood bucket).
            sv = sub_norm.replace("'", "''")
            return (
                "UPPER(REGEXP_REPLACE(COALESCE(subdivision,''), '[^A-Za-z0-9 ]', '', 'g')) "
                f"LIKE '%{sv}%'"
            )
        if scope == "county" and county:
            cv = county.replace("'", "''").upper()
            return f"UPPER(COALESCE(county,'')) = '{cv}'"
        return None

    def _closed_count(scope_clause: str) -> int:
        try:
            r = con.execute(
                f"""SELECT COUNT(*) FROM l
                    WHERE _class = '{cls_q}'
                      AND status_category = 'Closed'
                      AND TRY_CAST(sold_price AS DOUBLE) > 0
                      AND {window_clause}
                      AND {scope_clause}"""
            ).fetchone()
            return int(r[0]) if r else 0
        except Exception:
            return 0

    # Choose scope: prefer subdivision when it has >= 5 recent closings.
    scope = None
    scope_clause = None
    scope_value = None
    sub_clause = _scope_clause("subdivision")
    if sub_clause and _closed_count(sub_clause) >= 5:
        scope, scope_clause, scope_value = "subdivision", sub_clause, sub_norm
    else:
        cty_clause = _scope_clause("county")
        if cty_clause:
            scope, scope_clause, scope_value = "county", cty_clause, county

    if not scope_clause:
        out["reason"] = "subject has neither a usable subdivision nor county"
        return out

    out["scope"] = scope
    out["scope_value"] = scope_value

    # --- median $/sqft + DOM + sold count over the window -------------------
    try:
        agg = con.execute(
            f"""WITH sold AS (
                    SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                           TRY_CAST(sqft AS DOUBLE) sf,
                           TRY_CAST(feed_dom AS INT) dom,
                           close_date
                    FROM l
                    WHERE _class = '{cls_q}'
                      AND status_category = 'Closed'
                      AND TRY_CAST(sold_price AS DOUBLE) > 0
                      AND {window_clause}
                      AND {scope_clause}
                )
                SELECT
                    COUNT(*) AS n_sold,
                    MEDIAN(CASE WHEN sf > 0 THEN sp / sf END) AS med_ppsf,
                    MEDIAN(sp) AS med_price,
                    MEDIAN(dom) AS med_dom
                FROM sold"""
        ).fetchone()
    except Exception as e:
        out["reason"] = f"aggregate failed: {e}"
        return out

    n_sold = int(agg[0]) if agg and agg[0] is not None else 0
    out["sold_count"] = n_sold
    out["median_ppsf"] = _round_or_none(agg[1], 1) if agg else None
    out["median_sold_price"] = _int_or_none(agg[2]) if agg else None
    out["median_dom"] = _int_or_none(agg[3]) if agg else None

    # --- active count + months-of-inventory --------------------------------
    try:
        active = con.execute(
            f"""SELECT COUNT(*) FROM l
                WHERE _class = '{cls_q}'
                  AND status_category = 'Active'
                  AND {scope_clause}"""
        ).fetchone()
        out["active_count"] = int(active[0]) if active and active[0] is not None else 0
    except Exception:
        out["active_count"] = None

    # Months of inventory = active / (sold per month over the window). Only
    # meaningful with some sales volume.
    moi = None
    if out.get("active_count") is not None and n_sold > 0:
        per_month = n_sold / float(_MARKET_WINDOW_MONTHS)
        if per_month > 0:
            moi = out["active_count"] / per_month
    out["months_of_inventory"] = _round_or_none(moi, 1)
    if moi is not None:
        if moi < 3:
            out["market_label"] = "seller's market"
        elif moi < 6:
            out["market_label"] = "balanced"
        else:
            out["market_label"] = "buyer's market"
    else:
        out["market_label"] = None

    # --- simple $/sqft trend (window-over-window split half) ----------------
    trend_pct = None
    trend_dir = None
    try:
        halves = con.execute(
            f"""WITH sold AS (
                    SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                           TRY_CAST(sqft AS DOUBLE) sf,
                           close_date
                    FROM l
                    WHERE _class = '{cls_q}'
                      AND status_category = 'Closed'
                      AND TRY_CAST(sold_price AS DOUBLE) > 0
                      AND TRY_CAST(sqft AS DOUBLE) > 0
                      AND {window_clause}
                      AND {scope_clause}
                ),
                tagged AS (
                    SELECT sp / sf AS ppsf,
                           CASE WHEN close_date >=
                                (CURRENT_DATE - INTERVAL '{_MARKET_WINDOW_MONTHS // 2} months')
                                THEN 'recent' ELSE 'older' END AS half
                    FROM sold
                )
                SELECT half, MEDIAN(ppsf) AS med, COUNT(*) AS n
                FROM tagged GROUP BY half"""
        ).fetchall()
        by_half = {h: (med, n) for h, med, n in halves}
        recent = by_half.get("recent")
        older = by_half.get("older")
        # Require a few sales on each side before claiming a trend.
        if recent and older and recent[1] >= 3 and older[1] >= 3 and older[0]:
            trend_pct = (recent[0] - older[0]) / older[0] * 100.0
            if trend_pct > 1.0:
                trend_dir = "up"
            elif trend_pct < -1.0:
                trend_dir = "down"
            else:
                trend_dir = "flat"
    except Exception:
        pass
    out["ppsf_trend_pct"] = _round_or_none(trend_pct, 1)
    out["ppsf_trend_direction"] = trend_dir

    out["available"] = n_sold > 0
    if not out["available"]:
        out["reason"] = "no recent closed sales in scope window"
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_profile(address: Optional[str], parcel_id: Optional[str],
                  *, n_comps: int = 6, months_back: int = 24,
                  ai_hygiene: bool = False,
                  full_valuation: bool = False,
                  subject_overrides: Optional[dict] = None) -> dict[str, Any]:
    """Resolve the subject and assemble the full profile JSON object.

    ``ai_hygiene`` selects the valuation pipeline:
      * False (default — fast, interactive): raw comps, AVM skipped. Sub-second.
      * True (full accuracy): runs the SAME AVM + Haiku comp-hygiene pass the
        generated CMA uses, so the displayed estimate equals the CMA's value.
        Costs an LLM call + the AVM (resident in the warm worker, so no cold start
        on the hosted path). The app's profile route opts into this; the public
        compbird surface + CLI default to fast.

    ``full_valuation`` (default False = byte-identical legacy behavior) forces
    the AVM ON regardless of ``ai_hygiene`` — the exact posture
    ``build_cma.build_preview`` / ``build_cma`` always run — so the profile's
    number matches /preview and the generated PDF for the SAME ``ai_hygiene``
    flag. This decouples the two knobs the way build_preview does: the AVM is
    never LLM spend, so it can run for every caller, while ``ai_hygiene`` keeps
    gating ONLY the Haiku comp-hygiene pass. compbird's profile route always
    sets it (one number everywhere); callers that leave it unset keep today's
    fast interactive path.
    """
    now = datetime.now(timezone.utc)
    meta: dict[str, Any] = {
        "generated_at": now.isoformat(timespec="seconds"),
        "as_of_date": date.today().isoformat(),
        "query": {"address": address, "parcel_id": parcel_id},
        "n_comps_requested": n_comps,
        "months_back": months_back,
        "ai_hygiene": ai_hygiene,
        "sections": {},
    }
    # Additive: only serialized when the caller opted in, so the unset path's
    # output stays byte-identical for existing (Ratifyly) callers.
    if full_valuation:
        meta["full_valuation"] = True

    subject = _resolve_subject(address=address, parcel_id=parcel_id)
    if not subject:
        return {
            "ok": False,
            "error": f"Could not locate subject (address={address!r}, parcel_id={parcel_id!r}).",
            "facts": None,
            "valuation": None,
            "comps": [],
            "saleHistory": [],
            "marketContext": None,
            "meta": meta,
        }

    # Coerce the numeric columns the driver returns as strings (same as the
    # production builder + quick_comp do before scoring).
    for k in _COERCE:
        v = _num(subject.get(k))
        if v is not None:
            subject[k] = v

    # Agent subject-fact overrides — applied at the SAME post-coercion / pre-comps
    # point as build_cma / build_preview so the displayed live estimate matches the
    # generated CMA. No-op when subject_overrides is None.
    subject = _apply_subject_overrides(subject, subject_overrides)
    meta["overridden"] = bool(subject_overrides)

    facts, missing_facts = _build_facts(subject)
    meta["sections"]["facts"] = {
        "available": True,
        "source": str(subject.get("status_category") or "").lower() == "off-market"
        and "parcel" or "mls",
        "missing_fields": missing_facts,
    }

    # Valuation + comps share the comp set. In full-accuracy mode (ai_hygiene) run
    # the SAME pipeline the generated CMA uses — the Haiku comp-hygiene pass (inside
    # prepare_comps) AND the AVM (CMA_SKIP_AVM unset) — so the estimate shown here
    # equals the CMA's value. full_valuation forces the AVM on even with hygiene
    # off (build_preview's exact posture, see the docstring); plain fast mode
    # keeps the AVM off + no LLM (sub-second).
    # CMA_SKIP_AVM is managed here and restored so we never leak process state.
    comps_raw: list[dict[str, Any]] = []
    valuation_section: Optional[dict[str, Any]] = None
    comps_section: list[dict[str, Any]] = []
    _prev_skip_avm = os.environ.get("CMA_SKIP_AVM")
    if ai_hygiene or full_valuation:
        os.environ.pop("CMA_SKIP_AVM", None)   # AVM on — match build_cma/build_preview
    else:
        os.environ["CMA_SKIP_AVM"] = "1"       # AVM off — fast interactive path
    try:
        try:
            comps_raw = prepare_comps(
                subject, n_comps=n_comps, months_back=months_back, ai_hygiene=ai_hygiene
            )
        except Exception as e:
            meta["sections"]["comps"] = {"available": False, "reason": f"comp prep failed: {e}"}

        if comps_raw:
            valuation = _estimate_value(subject, comps_raw)
            # Blind-Haiku ensemble fold (CMA_BLIND_ENSEMBLE=1 only — compbird's
            # engine env; unset keeps this byte-identical for Ratifyly). The
            # profile has no comp tuning, so its comps ARE the untuned picks —
            # this is where a fresh subject's anchor gets computed + cached,
            # and /preview + /generate then fold the SAME cached anchor.
            _ai_blind, _ai_ens = None, False
            if _blind_ensemble_enabled():
                valuation, _ai_blind, _ai_ens = _apply_blind_ensemble(
                    subject, comps_raw, valuation, untuned=True)
            valuation_section = _build_valuation(subject, comps_raw, valuation)
            if _blind_ensemble_enabled():
                # Additive wire fields appended AFTER the stable shape (same
                # pattern as the similarity surface — no key reordering).
                valuation_section["ai_blind"] = _ai_blind
                valuation_section["ai_ensemble"] = _ai_ens
                # Engine-computed measured tier — authoritative for the app's
                # confidence badge (confidence.ts falls back to client-side
                # computation only when this field is absent).
                valuation_section["confidence_tier"] = confidence_tier(
                    comps_raw, valuation, _ai_blind, _ai_ens)
            comps_section = _build_comps(comps_raw, subject)
            meta["sections"]["valuation"] = {
                "available": bool(valuation.mid),
                "method_count": sum(1 for m in valuation.methods if m.value is not None),
                "divergence_pct": _round_or_none(valuation.divergence_pct, 1),
                "ai_hygiene": ai_hygiene,
            }
            meta["sections"]["comps"] = {"available": True, "count": len(comps_section)}
        else:
            meta["sections"].setdefault(
                "comps", {"available": False, "reason": "no comps found in window"}
            )
            meta["sections"]["valuation"] = {
                "available": False,
                "reason": "no comps — cannot triangulate value",
            }
    finally:
        if _prev_skip_avm is None:
            os.environ.pop("CMA_SKIP_AVM", None)
        else:
            os.environ["CMA_SKIP_AVM"] = _prev_skip_avm

    sale_history, sale_info = _build_sale_history(subject)
    meta["sections"]["saleHistory"] = sale_info

    market = _market_context(subject)
    meta["sections"]["marketContext"] = {
        "available": market.get("available", False),
        "scope": market.get("scope"),
        "reason": market.get("reason"),
    }

    result = {
        "ok": True,
        "facts": facts,
        "valuation": valuation_section,
        "comps": comps_section,
        "saleHistory": sale_history,
        "marketContext": market,
        "meta": meta,
    }
    # Subject-level similarity aggregate (same CMA_COMP_SCORE_SURFACE gate as
    # the per-comp fields in _build_comps; absent = today's exact shape).
    if _score_surface_enabled():
        result["similarity_summary"] = _similarity_summary(
            [c["similarity"] for c in comps_section
             if c.get("similarity") is not None]
        )
    return result


# Schema descriptor — the shape downstream (the Next module) consumes. Surfaced
# both as a module constant and via ``--schema`` for quick reference.
PROFILE_SCHEMA: dict[str, Any] = {
    "ok": "bool",
    "error": "string | absent when ok",
    "facts": {
        "address": "string|null", "city": "string|null", "county": "string|null",
        "parcel_id": "string|null", "subdivision": "string|null",
        "property_type": "string|null (MLS class, e.g. RE_1)",
        "status": "string|null", "sqft": "int|null", "acres": "float|null",
        "beds": "int|null", "full_baths": "int|null", "half_baths": "int|null",
        "year_built": "int|null", "assessed_value": "int|null (assessor total)",
        "lat": "float|null", "lng": "float|null", "list_price": "int|null",
    },
    "valuation": {
        "mid": "int|null", "low": "int|null", "high": "int|null",
        "comp_ppsf": "float|null", "implied_subject_ppsf": "float|null",
        "divergence_pct": "float|null",
        "methods": "[{name:string, value:int|null, rationale:string}]",
    },
    "comps": "[{address, city, subdivision, sold_price:int, ppsf:float, "
             "sqft:int, acres:float, beds:int, baths:int, year_built:int, "
             "close_date:str, dom:int, distance_mi:float|null, "
             "lat:float|null, lng:float|null, "
             "pending:bool, atypical:bool}]",
    "saleHistory": "[{price:int|null, date:str|null}]  (MLS-confirmed only)",
    "marketContext": {
        "scope": "'subdivision'|'county'|null", "scope_value": "string|null",
        "window_months": "int", "available": "bool",
        "median_ppsf": "float|null", "median_sold_price": "int|null",
        "median_dom": "int|null", "sold_count": "int", "active_count": "int|null",
        "months_of_inventory": "float|null", "market_label": "string|null",
        "ppsf_trend_pct": "float|null", "ppsf_trend_direction": "'up'|'down'|'flat'|null",
    },
    "meta": {
        "generated_at": "ISO8601 UTC", "as_of_date": "YYYY-MM-DD",
        "query": "{address, parcel_id}", "n_comps_requested": "int",
        "months_back": "int",
        "sections": "{<section>: {available:bool, ...per-section flags}}",
    },
}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Full house profile JSON for the CMA property-profile UI.")
    ap.add_argument("address", nargs="?", default=None)
    ap.add_argument("--parcel", default=None)
    ap.add_argument("--n", type=int, default=6, help="target comp count")
    ap.add_argument("--months", type=int, default=24, help="comp lookback window")
    ap.add_argument("--ai-hygiene", action=argparse.BooleanOptionalAction, default=False,
                    help="full-accuracy mode: run the AVM + Haiku comp-hygiene so the "
                         "estimate matches the generated CMA (slower; needs ANTHROPIC_API_KEY)")
    ap.add_argument("--full-valuation", action=argparse.BooleanOptionalAction, default=False,
                    help="force the AVM on regardless of --ai-hygiene (build_preview's "
                         "posture) so the profile number matches /preview + the PDF")
    ap.add_argument("--pretty", action="store_true", help="indent the JSON")
    ap.add_argument("--schema", action="store_true", help="print PROFILE_SCHEMA and exit")
    a = ap.parse_args(argv)

    if a.schema:
        print(json.dumps(PROFILE_SCHEMA, indent=2))
        return 0

    if not a.address and not a.parcel:
        ap.error("provide an address or --parcel")

    try:
        result = build_profile(a.address, a.parcel, n_comps=a.n, months_back=a.months,
                               ai_hygiene=a.ai_hygiene, full_valuation=a.full_valuation)
    except Exception as e:  # never raise out of main — emit parseable error JSON
        result = {
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "facts": None, "valuation": None, "comps": [],
            "saleHistory": [], "marketContext": None, "meta": None,
        }

    payload = json.dumps(result, indent=2 if a.pretty else None, default=str)
    # Match web-cma's marker convention so the Next route parses this identically
    # to build_cma's output (parseBuilderResult takes the slice after __JSON__).
    print("__JSON__" + payload)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
