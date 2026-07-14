"""CLI-friendly CMA builder.

Composes a one-page branded CMA HTML + PDF from a single function call,
covering subject lookup, comp scoring, valuation math, brand rendering, and
an auto-fit loop that tightens spacing if the first render overflows.

Example::

    from scripts.build_cma import build_cma
    result = build_cma(
        address="7423 Floyd Highway N",
        brand_name="gravity",
        agent_name="Trevan Via",
    )
    print(result.pdf_path, result.pages)

Typically invoked through ``python -m tasks cma '<address>' --brand=...`` —
see :mod:`tasks` for the user-facing CLI wrapper.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Iterable, Optional

# Make `mls_bot.*` imports work when this module is invoked from the project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC = _PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mls_bot.analytics.cma_compset import pick_comps, similarity_surface  # noqa: E402
from mls_bot.analytics.property_lookup import resolve_subject  # noqa: E402
from mls_bot.brand import AgentIdentity, Brand  # noqa: E402


# ---------------------------------------------------------------------------
# Tunable valuation knobs (env-overridable). Defaults reproduce shipped
# behavior EXACTLY (backtest-neutral); the accuracy-optimization sweep overrides
# them via CMA_* env vars and the winners are baked back in as new defaults.
# ---------------------------------------------------------------------------
def _envf(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    try:
        return float(v)
    except ValueError:
        return default


# Comp-evidence clamp: the final estimate is bounded to a multiple of the
# selected comps' realized prices (lowest_comp * LO .. highest_comp * HI).
_CLAMP_LO = _envf("CMA_CLAMP_LO", 0.40)
_CLAMP_HI = _envf("CMA_CLAMP_HI", 1.75)
# Median-comp anti-inflation cap (0 = off): also bound mid/high to median_comp *
# K, so a few expensive comps in a thin cheap-supply pool can't drag the estimate
# up (the dominant sub-$150k over-valuation failure mode). Default 1.4 set by the
# 2026-06 backtest-gated optimization (validated on a 2nd as-of).
_MEDIAN_CAP_K = _envf("CMA_MEDIAN_CAP_K", 1.4)
# AVM comp-evidence gate (drop the model if its prediction is outside this
# multiple of the comp MEDIAN) + a scalar on its triangulation weight.
# Tightened from 0.25/3.0 (min/max-anchored) to 0.65/1.80 (median-anchored) by
# the 2026-06-30 backtest: a robust median gate + tighter band drops degenerate
# AVM predictions that were dragging the blend, cutting median |APE| 9.95->8.79
# and lifting PPE10 51.4->54.1 with MAPE/MAE flat-to-better.
_AVM_ENV_LO = _envf("CMA_AVM_ENV_LO", 0.65)
_AVM_ENV_HI = _envf("CMA_AVM_ENV_HI", 1.80)
# AVM triangulation-weight scalar. Default 1.75 (from the 2026-06 optimization):
# the gradient-boosted cross-market model generalizes better than the comp
# arithmetic on the error tail, so up-weighting it cut MAPE ~36->33 and median
# APE 14.4->13.8 on BOTH the train and a held-out as-of, mid-market held.
_AVM_W_MULT = _envf("CMA_AVM_W_MULT", 1.75)
# Q7 — AVM index de-bias (env-gated; UNSET = byte-identical current behavior).
# The AVM is a frozen HistGradientBoostingRegressor with no calendar feature
# (2026-05-06 model, training cutoff 2025-09-30): it predicts at the price
# level of its training mass, measured -7..-8% stale against 2026 sales.
# CMA_AVM_INDEX_DEBIAS=1 multiplies the prediction by the S1 county market
# index ratio smoothed(as-of month)/smoothed(train-center month) BEFORE the
# comp-evidence envelope gate. When the ratio is unavailable (unknown/thin
# county, index parquet missing) the de-bias silently no-ops.
# CMA_AVM_TRAIN_CENTER overrides the training-center month; the default
# 2024-07 is the sale-count-weighted mean close date of the shipped model's
# 5,297 training rows (Closed, $30k-$3.5M, close_date < 2025-09-30 —
# recomputed 2026-07, matches meta.joblib train_n exactly).
_AVM_TRAIN_CENTER = os.environ.get("CMA_AVM_TRAIN_CENTER", "").strip() or "2024-07"
# Interval widener (1.0 = pre-tuning). Default 2.0 calibrates interval coverage
# from ~66% to ~84% (toward the ~80% nominal target) with zero effect on the
# point estimate. Set by the 2026-06 optimization.
_INTERVAL_K = _envf("CMA_INTERVAL_K", 2.0)
# Hard credibility cap on the displayed supported range: low/high are bounded to
# the mid +/- this fraction AFTER interval widening, so no brand template can
# ever show an absurd spread (e.g. $300k-$1.3M) when methods diverge. 0.15 = the
# range never exceeds +/-15% of the estimate. Set 0 to disable. Backtest-tunable
# against interval coverage.
_BAND_MAX_FRAC = _envf("CMA_BAND_MAX_FRAC", 0.15)
# Direct-comp acreage-gap premium ($/acre, low/high) applied to acres the
# subject has beyond the comps' median. Env-overridable so the acreage
# over-valuation can be backtest-calibrated. 2026-06 calibration on 500 high-
# acreage homes: the prior $12k-$15k/acre band over-valued land (+3.9% signed
# error at >=2ac), so the default band was halved to $5k-$6.5k/acre — zeroes the
# high-acreage bias, leaves <1ac homes untouched, aggregate-neutral. Override
# via CMA_LAND_RATE_LO/HI to reproduce the old band ($12000/$15000) if needed.
_LAND_RATE_LO = _envf("CMA_LAND_RATE_LO", 5000.0)
_LAND_RATE_HI = _envf("CMA_LAND_RATE_HI", 6500.0)


def _resolve_subject(address: Optional[str], parcel_id: Optional[str]) -> Optional[dict]:
    """Deprecated — kept as a thin compatibility shim.

    All real lookup now happens in
    :func:`mls_bot.analytics.property_lookup.resolve_subject`, which extends
    coverage to off-market properties via parcel data. New callers should
    import that directly. This wrapper is preserved so any external script
    that imported ``_resolve_subject`` keeps working without modification.
    """
    return resolve_subject(address=address, parcel_id=parcel_id)


# ---------------------------------------------------------------------------
# Agent control — subject-fact overrides + report composition
# ---------------------------------------------------------------------------
import html as _html  # noqa: E402


def _html_escape(s) -> str:
    """Escape operator-supplied text for safe insertion into the headless-Chrome
    render, then turn newlines into ``<br/>``. This is the XSS boundary for any
    agent narrative override — markup in the input renders literally, never as
    live HTML."""
    return _html.escape(str(s if s is not None else "")).replace("\n", "<br/>")


# Every toggleable report section. masthead / titleblock / footer are NOT here —
# they carry brand + legal identity and always render. The engine-locked
# disclaimer and the override-disclosure also render outside this set.
_ALL_SECTIONS = {"hero", "exec", "kpis", "comps", "dom_band", "methods", "strategy"}

# Subject keys an agent may override. Bath/bed/year counts stay integers so the
# 0.5-bath display math (full + half*0.5) is exact; acres/sqft stay float.
_OVERRIDE_NUM_KEYS = ("sqft", "bedrooms", "full_baths", "half_baths", "acres", "year_built")
_OVERRIDE_INT_KEYS = {"bedrooms", "full_baths", "half_baths", "year_built"}

# Server-side bounds — DEFENSE IN DEPTH. The app route already clamps via
# overrides.ts OVERRIDE_BOUNDS, but the engine must never trust a caller sanitized
# (the worker is a thin pass-through), so we re-clamp here too. Mirrors overrides.ts.
_OVERRIDE_BOUNDS = {
    "sqft": (100, 25000), "bedrooms": (0, 20), "full_baths": (0, 20),
    "half_baths": (0, 20), "acres": (0.0, 2000.0), "year_built": (1800, 2100),
}
# Condition tokens the engine will accept (the keys of _APPEARANCE_TIER); any
# other appearance value is ignored rather than passed through to the valuation.
_APPEARANCE_ALLOW = {"NEEDS REPAIR", "FAIR", "AVERAGE", "GOOD", "REMODELED", "NEW CONSTRUCTION"}

# Human labels for the non-suppressible record->adjusted disclosure block.
_OVERRIDE_DIFF_LABELS = {
    "sqft": "Finished area",
    "bedrooms": "Bedrooms",
    "full_baths": "Full baths",
    "half_baths": "Half baths",
    "acres": "Acreage",
    "year_built": "Year built",
    "property_type": "Property type",
    "appearance": "Condition",
}


def _apply_subject_overrides(subject: dict, overrides: Optional[dict]) -> dict:
    """Apply an agent overrides dict onto a RESOLVED subject, IN PLACE.

    Accepts the same snake-keyed physical keys the engine reads downstream
    (sqft, bedrooms, full_baths, half_baths, acres, year_built, property_type)
    plus ``appearance`` (the condition token — drives ``_subject_appearance_tier``
    → comp condition normalization → valuation). The accepted appearance tokens
    are exactly the keys of ``_APPEARANCE_TIER`` (e.g. "NEEDS REPAIR", "FAIR",
    "AVERAGE", "GOOD", "REMODELED", "NEW CONSTRUCTION") — which is what the shared
    contract sends — so the token flows straight through to ``_appearance_to_tier``.

    Numeric keys are coerced; bedrooms/full_baths/half_baths/year_built cast to
    int, acres/sqft stay float. None/empty values are skipped so a partial dict
    only overrides the fields the agent actually edited. Unknown keys are ignored.

    INTEGRITY: for each key that actually changes, the pre-override value is
    captured into ``subject["_override_diff"]`` as ``{key: {"from": old, "to": new}}``
    so the non-suppressible record→adjusted disclosure can show what was edited.
    Sets ``subject["_overridden"] = True`` when any change was applied.

    Applied AFTER ``_resolve_subject``'s numeric coercion and BEFORE
    ``prepare_comps`` / ``_estimate_value``, so both the AI hygiene pass and the
    deterministic valuation/AVM see the edited values."""
    if not overrides:
        return subject
    diff: dict = subject.get("_override_diff") or {}
    changed = False
    for k in _OVERRIDE_NUM_KEYS:
        raw = overrides.get(k)
        if raw is None or raw == "":
            continue
        v = _num(raw)
        if v is None:
            continue
        lo, hi = _OVERRIDE_BOUNDS[k]
        v = lo if v < lo else (hi if v > hi else v)  # defense-in-depth clamp
        new = int(v) if k in _OVERRIDE_INT_KEYS else v
        old = subject.get(k)
        if old != new:
            diff[k] = {"from": old, "to": new}
            changed = True
        subject[k] = new
    pt = overrides.get("property_type")
    if pt:
        pt = str(pt)[:60]  # bound the free-text length (render + XSS surface)
        old = subject.get("property_type")
        if str(old or "") != pt:
            diff["property_type"] = {"from": old, "to": pt}
            changed = True
        subject["property_type"] = pt
    appr = overrides.get("appearance")
    if appr and str(appr).upper() in _APPEARANCE_ALLOW:
        appr = str(appr).upper()
        old = subject.get("appearance")
        if str(old or "") != appr:
            diff["appearance"] = {"from": old, "to": appr}
            changed = True
        subject["appearance"] = appr
    if changed:
        subject["_override_diff"] = diff
        subject["_overridden"] = True
    return subject


def _override_disclosure_html(subject: dict) -> str:
    """Render the NON-SUPPRESSIBLE record→adjusted disclosure block.

    Emitted OUTSIDE the section-gating registry whenever any override was applied
    (``subject["_overridden"]``), so no section toggle can hide it. Lists each
    changed key as "<label>: <from> -> <to>" and a closing integrity line."""
    if not subject.get("_overridden"):
        return ""
    diff = subject.get("_override_diff") or {}
    if not diff:
        return ""
    lines = []
    for k, fromto in diff.items():
        label = _OVERRIDE_DIFF_LABELS.get(k, k)
        old = fromto.get("from")
        new = fromto.get("to")
        if k == "sqft":
            old_s = f"{int(old):,}" if _num(old) else "record"
            new_s = f"{int(new):,} sqft" if _num(new) else str(new)
        elif k == "acres":
            old_s = f"{float(old):.2f}" if _num(old) is not None else "record"
            new_s = f"{float(new):.2f} ac" if _num(new) is not None else str(new)
        elif k in ("appearance", "property_type"):
            old_s = str(old) if (old not in (None, "")) else "record"
            new_s = str(new)
        else:
            old_s = str(int(old)) if _num(old) is not None else "record"
            new_s = str(int(new)) if _num(new) is not None else str(new)
        lines.append(
            f'<div class="odl">{_html_escape(label)}: '
            f'{_html_escape(old_s)} &rarr; {_html_escape(new_s)}</div>'
        )
    # The value line — record-basis vs agent-adjusted — makes the MAGNITUDE of the
    # override visible (the adjusted number never stands alone). Reuses .odl so it
    # is styled consistently; bold to anchor the eye on the dollar delta.
    val_line = ""
    rec, adj = subject.get("_record_mid"), subject.get("_adjusted_mid")
    if _num(rec) is not None and _num(adj) is not None and int(rec) != int(adj):
        val_line = (
            f'<div class="odl"><b>Record-basis estimate ~{_short_money(int(rec))} '
            f'&rarr; agent-adjusted ~{_short_money(int(adj))}</b></div>'
        )
    return (
        '<div class="override-disclosure">'
        '<div class="odh">Estimate based on agent-adjusted subject details</div>'
        + val_line
        + "".join(lines)
        + '<div class="odn">Estimate reflects agent-adjusted subject details.</div>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# Agent bed/bath what-if damping (env-gated CMA_OVERRIDE_DAMPING=1)
# ---------------------------------------------------------------------------
# BUG this fixes: a bed/bath override used to re-anchor COMP SELECTION to the
# overridden counts (the ±2 hard guard in ``cma_compset._bedbath_ok`` plus the
# beds/baths proximity weights), so "what if 6 bd" pulled the comp set into a
# large/luxury cohort and imported its $/sqft wholesale — a 4bd→6bd edit at
# UNCHANGED sqft could re-price the subject to a different market segment
# (observed live: +117%). Bedroom/bath count conditional on fixed sqft is worth
# a few percent, not a segment change.
#
# Under CMA_OVERRIDE_DAMPING=1:
#   * COMP SELECTION (``pick_comps`` inside ``prepare_comps``) and the blind
#     ensemble anchor read the subject with bed/bath REVERTED to record, so the
#     comp set stays size/location-anchored (identical to the record set for a
#     pure bed/bath override). Sqft/acres/year/appearance overrides still flow
#     to selection untouched — the size lever is not damped.
#   * The valuation applies a BOUNDED explicit adjustment instead
#     (``_override_bedbath_pct``): +2.0%/bed, +1.5%/full bath, +0.75%/half
#     bath, total clamped to ±8% — the defensible appraisal-adjustment range
#     for layout differences at fixed size.
# Overrides that SUPPLY a missing record value (record bed/bath is None) are
# treated as data corrections: not damped, no adjustment.
# Unset (default) both helpers are inert pass-throughs — every caller stays
# byte-identical (Ratifyly posture).

_OVERRIDE_BEDBATH_STEP_PCT = {"bedrooms": 2.0, "full_baths": 1.5, "half_baths": 0.75}
_OVERRIDE_BEDBATH_CAP_PCT = 8.0


def _override_damping_enabled() -> bool:
    """Read CMA_OVERRIDE_DAMPING at CALL time (not import) so the worker /
    per-spawn processes honor the env they were launched with. Unset/anything-
    but-'1' = damping off = byte-identical shipped behavior."""
    return os.environ.get("CMA_OVERRIDE_DAMPING", "").strip() == "1"


def _selection_subject(subject: dict) -> dict:
    """The subject used for COMP SELECTION (and the blind-ensemble packet).

    With damping enabled and a bed/bath override applied, returns a copy with
    bedrooms/full_baths/half_baths reverted to their RECORD values (the
    ``_override_diff`` "from" side) so comp scoring + the ±2 bed/bath hard
    guard stay anchored to the property's actual segment. Keys whose record
    value is None (override = supplying missing data) are NOT reverted.
    Returns ``subject`` unchanged (same object) when damping is off, nothing
    was overridden, or no bed/bath key has a numeric record value."""
    if not _override_damping_enabled():
        return subject
    diff = subject.get("_override_diff") or {}
    out = None
    for k in _OVERRIDE_BEDBATH_STEP_PCT:
        d = diff.get(k)
        if isinstance(d, dict):
            frm = d.get("from")
            if _num(frm) is not None:
                if out is None:
                    out = dict(subject)
                # Restore the record value VERBATIM (no int/float re-coercion):
                # the blind-ensemble cache signature hashes these fields, so an
                # exact restore makes a bed/bath-only override hit the SAME
                # cached anchor as the record run (4.0 != 4 would fork it).
                out[k] = frm
    return out if out is not None else subject


def _override_bedbath_pct(subject: dict) -> float:
    """Signed % valuation adjustment for an agent bed/bath override.

    Sum of per-step percentages over the overridden bed/bath keys (delta =
    to - from, only when both ends are numeric), clamped to
    ±_OVERRIDE_BEDBATH_CAP_PCT. 0.0 when nothing applies — including for the
    record subject (no ``_override_diff``), so ``_record_basis_mid`` is never
    adjusted."""
    diff = subject.get("_override_diff") or {}
    total = 0.0
    for k, per_step in _OVERRIDE_BEDBATH_STEP_PCT.items():
        d = diff.get(k)
        if not isinstance(d, dict):
            continue
        frm, to = _num(d.get("from")), _num(d.get("to"))
        if frm is None or to is None:
            continue
        total += per_step * (to - frm)
    return max(-_OVERRIDE_BEDBATH_CAP_PCT,
               min(_OVERRIDE_BEDBATH_CAP_PCT, total))


def _comp_tuning_disclosure_html(subject: dict) -> str:
    """Non-suppressible "comp set adjusted by agent" line for tuned reports.

    Env-gated (CMA_COMP_TUNING_DISCLOSURE=1, set in the compbird engine env)
    so the shared default render is untouched until Ratifyly adopts it
    deliberately. Counts are stamped by build_cma from the caller's
    excluded/forced lists — like ``_overridden``, no section toggle hides it."""
    if os.environ.get("CMA_COMP_TUNING_DISCLOSURE", "").strip() != "1":
        return ""
    tuning = subject.get("_comp_tuning") or {}
    removed = int(tuning.get("removed") or 0)
    added = int(tuning.get("added") or 0)
    if not removed and not added:
        return ""
    parts = []
    if removed:
        parts.append(f"{removed} removed")
    if added:
        parts.append(f"{added} added")
    return (
        '<div class="override-disclosure">'
        '<div class="odn">Comp set adjusted by agent: '
        f'{_html_escape(", ".join(parts))}.</div>'
        "</div>"
    )


# Headless-Chrome binary for PDF rendering. Resolve cross-platform so the engine
# runs in a Linux container as well as on the current Windows machine:
#   (a) env CHROME_PATH if set,
#   (b) a chromium/chrome binary on PATH (Linux/macOS container names),
#   (c) the original Windows default as the final fallback.
# On the current Windows box (a) and (b) are normally unset/absent, so (c) still
# resolves and behavior is byte-identical.
_WINDOWS_CHROME_DEFAULT = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _resolve_chrome_path() -> str:
    env = os.environ.get("CHROME_PATH")
    if env and env.strip():
        return env
    for candidate in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(candidate)
        if found:
            return found
    return _WINDOWS_CHROME_DEFAULT


CHROME_PATH = _resolve_chrome_path()


# ---------------------------------------------------------------------------
# Result wrapper
# ---------------------------------------------------------------------------

@dataclass
class CmaResult:
    """Return value of :func:`build_cma`."""

    html_path: Path
    pdf_path: Path
    pages: int
    subject_address: str
    estimated_value: int
    value_low: int
    value_high: int
    comp_count: int
    elapsed_seconds: float
    autofit_attempts: int = 0
    # Blind-Haiku ensemble surface (CMA_BLIND_ENSEMBLE=1 only; the defaults
    # are what every flag-off caller sees, so the dataclass stays compatible).
    ai_blind: Optional[int] = None
    ai_ensemble: bool = False
    # Measured confidence tier "high"|"standard" (CMA_BLIND_ENSEMBLE=1 only;
    # None for every flag-off caller). Computed engine-side by
    # :func:`confidence_signals` — never from request input.
    confidence_tier: Optional[str] = None


# ---------------------------------------------------------------------------
# Valuation math
# ---------------------------------------------------------------------------

def _num(v) -> Optional[float]:
    """Best-effort numeric coercion. Returns None for blanks/garbage."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _money(n) -> str:
    f = _num(n)
    if f is None:
        return "—"
    return f"${int(round(f)):,}"


def _short_money(n) -> str:
    f = _num(n)
    if f is None:
        return "—"
    if f >= 1_000_000:
        return f"${f / 1_000_000:.2f}M"
    if f >= 1_000:
        return f"${int(round(f / 1000))}k"
    return f"${int(round(f))}"


def _round_to_5k(n: float) -> int:
    return int(round(n / 5000)) * 5000


@dataclass
class ValuationMethod:
    """Result of one of the three triangulation methods.

    ``value`` is the central estimate from this method; ``low`` / ``high`` are
    the soft band around it. ``rationale`` is a one-line explanation surfaced
    in the report's Valuation Methods panel. Methods that lack enough data to
    produce a defensible number return ``value=None``.
    """

    name: str
    value: Optional[float]
    low: Optional[float]
    high: Optional[float]
    rationale: str


@dataclass
class ValuationResult:
    """Triangulated valuation. ``low``/``mid``/``high`` are UNROUNDED floats —
    downstream math (ensemble blends, backtests, record-vs-adjusted deltas)
    must not inherit display quantization (up to +2.3pp APE on sub-$150k
    homes). Presentation surfaces apply ``_round_to_5k`` at the render/API
    boundary so DISPLAYED values keep the $5k convention."""

    methods: list[ValuationMethod]
    low: float
    mid: float
    high: float
    ppsf: float           # median $/sqft of comps, retained for KPI display
    divergence_pct: float  # percentage spread between high-low across methods


# ---------------------------------------------------------------------------
# Layer 0 — deterministic accuracy adjustments
# ---------------------------------------------------------------------------

# $/sqft size elasticity: a smaller home sells at a higher $/sqft. To apply a
# comp's $/sqft to a differently-sized subject we scale by
# (comp_sqft / subject_sqft) ** ELASTICITY. A comp 14% smaller than the subject
# has its $/sqft reduced ~3.5% before it's applied to the larger subject —
# correcting the bias the audit flagged.
_SIZE_ELASTICITY = _envf("CMA_SIZE_ELASTICITY", 0.25)
# Bounds on the annual appreciation rate we'll trust from the data.
_APPR_MIN, _APPR_MAX, _APPR_DEFAULT = 0.0, 0.12, 0.04


def _today_date() -> date:
    return date.today()


def _parse_date(d) -> Optional[date]:
    from datetime import datetime as _dt
    if d is None:
        return None
    if isinstance(d, date) and not isinstance(d, _dt):
        return d
    if isinstance(d, _dt):
        return d.date()
    s = str(d)[:10]
    try:
        return _dt.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_since(close_date) -> Optional[float]:
    cd = _parse_date(close_date)
    if cd is None:
        return None
    days = (_today_date() - cd).days
    return max(0.0, days / 30.4)


def _estimate_appreciation_rate(comps: list[dict]) -> float:
    """Estimate annualized $/sqft appreciation from the comp pool.

    Splits the comps into an older half and a newer half by close date,
    compares median $/sqft, and annualizes the delta over the median time
    gap. Clamped to a sane band and falls back to a default when the pool
    is too thin or the math is degenerate. Deterministic — no model call."""
    rows = []
    for c in comps:
        sf = _num(c.get("sqft"))
        sp = _num(c.get("sold_price"))
        m = _months_since(c.get("close_date"))
        if sf and sp and sf > 0 and m is not None:
            rows.append((m, sp / sf))
    if len(rows) < 4:
        return _APPR_DEFAULT
    rows.sort(key=lambda r: r[0])  # ascending months-ago (newest first)
    half = len(rows) // 2
    newer = rows[:half]
    older = rows[half:]
    newer_ppsf = median(p for _m, p in newer)
    older_ppsf = median(p for _m, p in older)
    newer_age = median(m for m, _p in newer)
    older_age = median(m for m, _p in older)
    gap_years = (older_age - newer_age) / 12.0
    if gap_years <= 0.1 or older_ppsf <= 0:
        return _APPR_DEFAULT
    # newer / older = (1 + r) ** gap_years  ->  r = (ratio) ** (1/gap) - 1
    ratio = newer_ppsf / older_ppsf
    if ratio <= 0:
        return _APPR_DEFAULT
    try:
        r = ratio ** (1.0 / gap_years) - 1.0
    except (ValueError, ZeroDivisionError):
        return _APPR_DEFAULT
    return max(_APPR_MIN, min(_APPR_MAX, r))


# LFD_Appearance condition tiers (0 worst → 5 best). Values are comma-
# delimited token sets ("Custom Features,Remodeled,Very Good"); we take the
# highest tier any token maps to.
_APPEARANCE_TIER = {
    "NEW CONSTRUCTION-FIN": 5, "NEW CONSTRUCTION": 5,
    "REMODELED": 4, "UPGRADES": 4, "CUSTOM FEATURES": 4,
    "DECORATOR TOUCHES": 4, "VERY GOOD": 4,
    "GOOD": 3,
    "AVERAGE": 2,
    "FAIR": 1,
    "NEEDS REPAIR": 0, "POOR": 0, "FIXER": 0,
}


def _appearance_to_tier(value) -> Optional[int]:
    """Map an LFD_Appearance string to a 0–5 condition tier (max token)."""
    if not value:
        return None
    s = str(value).upper()
    tiers = [t for token, t in _APPEARANCE_TIER.items() if token in s]
    return max(tiers) if tiers else None


def _appearance_adjustment_pct(comp_tier: Optional[int], subject_tier: int) -> float:
    """% $/sqft adjustment to normalize a comp's CONDITION to the subject.

    Negative when the comp is nicer than the subject (discount its $/sqft);
    positive when inferior. ~4% per tier, clamped ±15%."""
    if comp_tier is None:
        return 0.0
    return max(-15.0, min(15.0, (subject_tier - comp_tier) * 4.0))


def _adjusted_ppsf(comp: dict, subject_sqft: float, appr_rate: float,
                   subject_tier: int = 2) -> Optional[float]:
    """Return a comp's $/sqft adjusted for time, size, and condition.

    Time: trend the comp's $/sqft forward at ``appr_rate``. Size: scale by
    (comp_sqft/subject_sqft)**elasticity. Condition precedence:
      1. LLM hygiene verdict (``_hygiene.ppsf_adjustment_pct``) when present,
      2. else the free LFD_Appearance tier delta vs the subject,
      3. else no condition adjustment.
    Returns None if the comp lacks sqft + price."""
    sf = _num(comp.get("sqft"))
    sp = _num(comp.get("sold_price"))
    if not sf or not sp or sf <= 0:
        return None
    ppsf = sp / sf
    months = _months_since(comp.get("close_date"))
    if months:
        ppsf *= (1.0 + appr_rate) ** (months / 12.0)
    if subject_sqft and subject_sqft > 0:
        ppsf *= (sf / subject_sqft) ** _SIZE_ELASTICITY

    cond_pct = None
    hyg = comp.get("_hygiene")
    if isinstance(hyg, dict):
        cond_pct = _num(hyg.get("ppsf_adjustment_pct"))
    if cond_pct is None:
        comp_tier = _appearance_to_tier(comp.get("appearance"))
        if comp_tier is not None:
            cond_pct = _appearance_adjustment_pct(comp_tier, subject_tier)
            comp["_appearance_tier"] = comp_tier
            comp["_appearance_adj_pct"] = cond_pct
    if cond_pct is not None:
        cond_pct = max(-30.0, min(30.0, cond_pct))
        ppsf *= (1.0 + cond_pct / 100.0)
    return ppsf


def _subject_appearance_tier(subject: dict, comps: list[dict]) -> int:
    """The condition tier to normalize comps against.

    Uses the subject's own LFD_Appearance when it's an MLS listing; for an
    off-market subject (no appearance) assumes it's typical for its
    neighborhood — the median tier of its comps — rather than a fixed
    "Average", so a nice off-market home isn't systematically under-valued.
    Falls back to 2 (Average)."""
    own = _appearance_to_tier(subject.get("appearance"))
    if own is not None:
        return own
    comp_tiers = [
        t for t in (_appearance_to_tier(c.get("appearance")) for c in comps)
        if t is not None
    ]
    if comp_tiers:
        comp_tiers.sort()
        return comp_tiers[len(comp_tiers) // 2]
    return 2


# Arms-length / sanity guards for the prior-sale anchor. A genuine open-market
# resale of the subject is the single strongest signal of its value; a tiny or
# deeply-discounted sale is not (foreclosure / quitclaim / family transfer that
# slipped through as "Closed"). Guard against both before anchoring.
_PRIOR_SALE_MIN_PRICE = 40_000          # below this, treat as non-market noise
_PRIOR_SALE_MIN_LIST_RATIO = 0.65       # sold < 65% of original list => distressed

# Placeholder parcel ids the feed carries ('TBD' x19, '1/1', '0', ...). These
# collide across unrelated properties, so any parcel-keyed join must treat them
# as non-joinable — a junk-pid join once anchored a $604k home on another
# property's $803k prior sale.
_PARCEL_ID_SENTINELS = {"TBD", "NA", "N/A", "NONE", "0", "UNKNOWN"}


def _valid_parcel_id(pid) -> bool:
    """True when ``pid`` looks like a real, joinable parcel identifier.

    Rejects None/blank, the known sentinel placeholders (case-insensitive),
    ids with fewer than 4 alphanumeric characters (e.g. '1/1'), and ids whose
    alphanumerics are all one repeated character ('0000', 'XXX-X')."""
    s = str(pid or "").strip()
    if not s or s.upper() in _PARCEL_ID_SENTINELS:
        return False
    alnum = [ch.upper() for ch in s if ch.isalnum()]
    if len(alnum) < 4:
        return False
    if len(set(alnum)) == 1:
        return False
    return True


# Directional prefixes skipped when locating the street-NAME token, so
# "123 N Main St" and "123 Main St" agree on ("123", "MAIN").
_ADDR_DIRECTIONALS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW",
                      "NORTH", "SOUTH", "EAST", "WEST"}


def _addr_street_key(addr) -> Optional[tuple[str, str]]:
    """(leading street number, first street-name token), uppercased.

    Returns None when the address has no leading house number to compare on
    (bare street names, lot descriptions, blanks)."""
    toks = re.findall(r"[A-Za-z0-9]+", str(addr or "").upper())
    if len(toks) < 2 or not toks[0][0].isdigit():
        return None
    for t in toks[1:]:
        if t not in _ADDR_DIRECTIONALS:
            return toks[0], t
    return None


def _addresses_agree(a, b) -> bool:
    """Same leading street number AND first street-name token, case-insensitive.

    Unparseable on either side counts as DISAGREEMENT — the caller must reject
    the parcel match rather than anchor on a row it cannot verify. This is the
    identity backstop for parcel-keyed joins: even a well-formed parcel_id can
    be misassigned in the feed, and a wrong-property prior sale is a 30-180%
    valuation error when it anchors the blend."""
    ka = _addr_street_key(a)
    kb = _addr_street_key(b)
    return ka is not None and ka == kb


def _mls_confirmed_prior_sale(subject: dict) -> Optional[tuple[float, str]]:
    """Return the subject's most recent MLS-CONFIRMED closed sale, or None.

    Looks up ``data/mls_lookup.parquet`` for a Closed listing of the subject's
    parcel with a positive sold price. This deliberately ignores the assessor
    ``deed_last_sale_*`` fields, which include refinances / intra-family
    transfers / misdated records and are NOT validated arms-length sales (e.g.
    509 Jefferson's bogus "$775k").

    Self-exclusion rule: when the subject is itself a LIVE (active/pending/
    off-market) record, the parcel's most recent closed sale on the same
    ``close_date`` would be that same listing and must be skipped. But when the
    subject record IS a closed sale being valued as-of-today (the benchmark and
    "what did this just sell for" case), that closed sale is exactly the recent
    arms-length transaction we want to anchor on — so we keep it.

    Identity guards: junk/sentinel parcel ids are non-joinable (see
    ``_valid_parcel_id``), and even a valid pid must land on a row whose
    address agrees with the subject's (``_addresses_agree``) — the feed
    misassigns parcel ids, and a wrong-property anchor is a 30-180% error.

    AS-OF AWARENESS: the lookup goes through
    ``cma_compset._fast_listings_connection()`` (the same seam the LOO
    backtests patch) and requires ``close_date < _today_date()``. In
    production ``_today_date()`` is today, so every already-closed sale
    passes and behavior is unchanged; in a backtest with a frozen as-of the
    anchor can only see sales strictly before the valuation date — the leak
    that used to force harnesses to disable this function entirely.

    Tiny / distressed sales are rejected (see ``_PRIOR_SALE_MIN_*``). Returns
    ``(sold_price, "YYYY-MM-DD")`` or None."""
    pid = str(subject.get("parcel_id") or "").strip()
    if not _valid_parcel_id(pid):
        return None
    # Only self-exclude the current close_date when the subject is NOT itself a
    # closed sale. A closed subject's close_date IS the recent arms-length sale
    # we want as the anchor; excluding it discards the strongest signal and
    # forces a comp-only (systematically low) estimate.
    status = str(subject.get("status_category") or subject.get("status") or "").strip().lower()
    subject_is_closed = status == "closed"
    try:
        # Module-attribute access ON PURPOSE: backtests monkeypatch
        # cma_compset._fast_listings_connection, and a from-import would
        # freeze the unpatched function here.
        from mls_bot.analytics import cma_compset as _compset
        con = _compset._fast_listings_connection()
        cur = str(subject.get("close_date") or "")[:10]
        cur_clause = (
            f"AND CAST(close_date AS VARCHAR) <> '{cur}'"
            if (cur and not subject_is_closed) else ""
        )
        rows = con.execute(
            f"""SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                       CAST(close_date AS VARCHAR) cd,
                       TRY_CAST(original_list_price AS DOUBLE) olp,
                       TRY_CAST(list_price AS DOUBLE) lp,
                       CAST(address AS VARCHAR) addr
                FROM listings
                WHERE CAST(parcel_id AS VARCHAR) = '{pid.replace("'", "''")}'
                  AND status_category = 'Closed'
                  AND TRY_CAST(sold_price AS DOUBLE) > 0
                  AND TRY_CAST(close_date AS DATE)
                      < DATE '{_today_date().isoformat()}'
                  {cur_clause}
                ORDER BY close_date DESC NULLS LAST
                LIMIT 1"""
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    sp, cd, olp, lp, sale_addr = rows[0]
    if not sp or sp <= 0:
        return None
    # Identity backstop: the parcel-keyed row must be the SAME property. Reject
    # the anchor outright on any address disagreement (or unparseable address)
    # rather than fall back to an older row of the same suspect pid.
    if not _addresses_agree(subject.get("address"), sale_addr):
        return None
    # Tiny-sale guard (non-market transfers slipping through as "Closed").
    if sp < _PRIOR_SALE_MIN_PRICE:
        return None
    # Distressed-sale guard: a sale that closed far below its own list price is
    # not a clean arms-length comp. Only applies when list data exists.
    ref_list = olp if (olp and olp > 0) else (lp if (lp and lp > 0) else None)
    if ref_list and sp < ref_list * _PRIOR_SALE_MIN_LIST_RATIO:
        return None
    return float(sp), str(cd)[:10]


def _method_prior_sale(subject: dict, appr_rate: float) -> ValuationMethod:
    """Anchor on the subject's prior MLS-CONFIRMED sale, trended forward.

    Only fires when a real arms-length MLS closed sale of the subject's parcel
    exists — assessor deed records are explicitly NOT trusted. Weighted as a
    minor input (max 0.40, see ``_prior_sale_weight``), never the sole anchor.
    For a purely off-market subject like 509 Jefferson (no MLS history) this
    returns ``value=None`` and the value becomes fully comp-driven."""
    found = _mls_confirmed_prior_sale(subject)
    if not found:
        return ValuationMethod(
            "Prior sale + trend", None, None, None,
            "No MLS-confirmed prior sale (assessor deeds are not trusted as anchors).",
        )
    price, cd = found
    months = _months_since(cd)
    if months is None:
        return ValuationMethod("Prior sale + trend", None, None, None,
                               "Prior sale date unparseable.")
    if months > 84:  # older than 7 years — too stale to anchor on
        return ValuationMethod(
            "Prior sale + trend", None, None, None,
            f"Last MLS sale was {months/12:.0f} yrs ago — too old to anchor.",
        )
    trended = price * (1.0 + appr_rate) ** (months / 12.0)
    d = _parse_date(cd)
    when = d.strftime("%m/%Y") if d else "prior"
    rationale = (
        f"Subject's prior MLS sale {_short_money(price)} ({when}); trended "
        f"{months/12:.1f} yrs at {appr_rate*100:.0f}%/yr = <b>{_short_money(trended)}</b> "
        f"(minor weight)."
    )
    return ValuationMethod(
        name="Prior sale + trend",
        value=trended,
        low=trended * 0.95,
        high=trended * 1.05,
        rationale=rationale,
    )


def _method_per_sqft(subject: dict, comps: list[dict],
                     appr_rate: float = _APPR_DEFAULT,
                     subject_tier: int = 2) -> ValuationMethod:
    """Median time+size+condition-adjusted $/sqft × subject sqft.

    Each comp's $/sqft is trended to today, size-normalized, and
    condition-normalized to the subject before the median is taken. Works
    best for suburban subjects; weighted down for land-heavy ones."""
    sf_subj = _num(subject.get("sqft"))
    adj = [
        p for p in (_adjusted_ppsf(c, sf_subj or 0, appr_rate, subject_tier) for c in comps)
        if p is not None
    ]
    if not adj or not sf_subj:
        return ValuationMethod("$/sqft", None, None, None, "Not enough sqft data.")
    med = median(adj)
    mid = med * sf_subj
    return ValuationMethod(
        name="$/sqft",
        value=mid,
        low=mid * 0.93,
        high=mid * 1.07,
        rationale=(
            f"Median time+size-adjusted ${int(round(med))}/sf × {int(sf_subj):,} sqft = "
            f"<b>{_short_money(mid)}</b>."
        ),
    )


def _method_direct_comp(subject: dict, comps: list[dict],
                        appr_rate: float = _APPR_DEFAULT,
                        subject_tier: int = 2) -> ValuationMethod:
    """Anchor on the top-3 comps (median time+size+condition-adjusted $/sqft),
    then add an acreage gap premium.

    Comps are already sorted by score in ``pick_comps``. Using the median of
    the top 3 instead of the single top comp prevents an outlier "great score,
    atypical price" anchor from dragging the method."""
    sf_subj = _num(subject.get("sqft"))
    ac_subj = _num(subject.get("acres")) or 0
    if not sf_subj or not comps:
        return ValuationMethod("Direct comp", None, None, None, "No top comp available.")
    top = [
        c for c in comps[:3]
        if c.get("sqft") and c.get("sold_price") and c["sqft"] > 0
    ]
    if not top:
        return ValuationMethod("Direct comp", None, None, None, "Top comps missing sqft.")
    adj_ppsfs = [
        p for p in (_adjusted_ppsf(c, sf_subj, appr_rate, subject_tier) for c in top) if p is not None
    ]
    if not adj_ppsfs:
        return ValuationMethod("Direct comp", None, None, None, "Top comps missing sqft.")
    median_ppsf = median(adj_ppsfs)
    median_acres = median(float(c.get("acres") or 0) for c in top)
    sqft_basis = median_ppsf * sf_subj
    gap = max(0.0, ac_subj - median_acres)
    land_low = sqft_basis + gap * _LAND_RATE_LO
    land_high = sqft_basis + gap * _LAND_RATE_HI
    mid = (land_low + land_high) / 2
    top_label = " / ".join(str(c.get("address") or "?") for c in top[:3])
    rationale = (
        f"Top 3 comps ({top_label}) median time+size-adj ${int(round(median_ppsf))}/sf "
        f"× {int(sf_subj):,} sqft = {_short_money(sqft_basis)}"
        + (f"; plus {gap:.1f} ac extra at ${_LAND_RATE_LO/1000:.0f}-{_LAND_RATE_HI/1000:.0f}k/ac"
           if gap > 0.5 else "")
        + f" = <b>{_short_money(mid)}</b>."
    )
    return ValuationMethod(
        name="Direct comp + acreage adjustment",
        value=mid,
        low=land_low,
        high=land_high,
        rationale=rationale,
    )


# Diminishing marginal land value. The first ~acre is the homesite and carries
# almost all of a small lot's land premium; each additional acre is worth
# progressively less (utility, road frontage, and buildability don't scale
# linearly). Modeling land value as linear in acres — `land_rate * acres` —
# systematically OVER-values large parcels, because the per-acre rate is
# calibrated on mostly-small comps (homesite-dominated) and then extrapolated
# straight out to 15-40+ acres. We instead convert acres to a concave
# "effective acres" and apply it on BOTH sides (comp residual calibration and
# the subject), so a comp identical in size to the subject still round-trips to
# its own price while large lots stop inheriting a small lot's $/acre.
_LAND_HOMESITE_ACRES = 1.0   # first acre at full rate (the homesite)
# Diminishing-returns exponent (env-overridable; default reproduces shipped
# behavior exactly). The acreage over-valuation can be backtest-calibrated by
# lowering CMA_LAND_EXP (more concave = large lots discounted harder).
_LAND_MARGINAL_EXP = _envf("CMA_LAND_EXP", 0.5)  # marginal acres beyond homesite diminish ~sqrt
# Land-residual per-acre rate multiplier. 2026-06 backtest calibration halved it
# (was 1.0) alongside the $/acre band above — together they zero the high-acreage
# over-valuation (+3.9% -> +0.85% signed error at >=2ac) while leaving <1ac homes
# untouched and the aggregate neutral. Override to 1.0 to restore prior behavior.
_LAND_RESID_MULT = _envf("CMA_LAND_RESID_MULT", 0.5)


def _eff_acres(acres: float, base: float = _LAND_HOMESITE_ACRES,
               exp: float = _LAND_MARGINAL_EXP) -> float:
    """Concave acreage: full credit up to ``base``, diminishing beyond.

    eff(0.5)=0.5, eff(1)=1, eff(2)=2.0, eff(6)≈3.24, eff(15)≈4.74, eff(40)≈7.24
    (vs. linear 0.5/1/2/6/15/40). Identity at/below ``base`` so the dominant
    small-lot comps — and the rate they calibrate — are unchanged."""
    ac = max(float(acres or 0.0), 0.0)
    if ac <= base:
        return ac
    return base + (ac - base) ** exp


def _method_acreage_residual(subject: dict, comps: list[dict]) -> ValuationMethod:
    """Land-residual method.

    For each usable comp, subtract the value of its improvements (sqft ×
    average $/sf of similar-improvement comps) from the sold price to get the
    residual land value, then divide by acres to get $/acre. Apply that rate
    to the subject's acres and add the subject's improvement value. Captures
    acreage premium that the pure $/sqft method ignores.

    Returns ``value=None`` when no comp has a credible (sqft + acres + price)
    triple — typical for land-only subjects, where the $/sqft method also
    can't produce a number."""
    triples = [
        (float(c["sqft"]), float(c["acres"]), float(c["sold_price"]))
        for c in comps
        if c.get("sqft") and c.get("acres") and c.get("sold_price")
        and c["sqft"] > 0 and c["acres"] > 0
    ]
    sf_subj = _num(subject.get("sqft"))
    ac_subj = _num(subject.get("acres"))
    if not triples or not sf_subj or not ac_subj:
        return ValuationMethod(
            "Land residual",
            None, None, None,
            "Not enough (sqft + acres + price) triples in the comp set.",
        )
    # Estimate $/sf for improvements only — use the median across comps.
    improvement_ppsf = median(sp / sf for sf, _ac, sp in triples)
    # For each comp, residual after the improvements value is the land + lot
    # premium. Divide by EFFECTIVE acres (concave) rather than raw acres so the
    # per-(effective-)acre rate isn't depressed by the occasional large comp and,
    # crucially, isn't extrapolated linearly onto a large subject below.
    per_acre = []
    for sf, ac, sp in triples:
        residual = sp - improvement_ppsf * sf
        eff = _eff_acres(ac)
        if eff > 0 and residual > 0:
            per_acre.append(residual / eff)
    if not per_acre:
        return ValuationMethod(
            "Land residual",
            None, None, None,
            "Comp residuals went negative — improvement $/sf may be too high.",
        )
    land_rate = median(per_acre) * _LAND_RESID_MULT  # *1.0 default = unchanged
    eff_subj = _eff_acres(ac_subj)
    mid = improvement_ppsf * sf_subj + land_rate * eff_subj
    low = improvement_ppsf * sf_subj + (land_rate * 0.85) * eff_subj
    high = improvement_ppsf * sf_subj + (land_rate * 1.15) * eff_subj
    rationale = (
        f"Comp improvement avg ${int(round(improvement_ppsf))}/sf; "
        f"residual land rate ${int(round(land_rate)):,}/eff-ac. "
        f"{int(sf_subj):,} sqft + {ac_subj:.1f} ac (≈{eff_subj:.1f} eff-ac) → "
        f"<b>{_short_money(mid)}</b>."
    )
    return ValuationMethod(
        name="Acreage residual",
        value=mid,
        low=low,
        high=high,
        rationale=rationale,
    )


# Pluggable index-ratio source for the AVM de-bias. Production (None) lazily
# uses mls_bot.analytics.market_index.index_ratio — the PREBUILT parquet,
# which aggregates all sales known at build time and is therefore correct
# only for valuing "now". Backtests MUST inject the leak-free variant, e.g.
#   build_cma._avm_index_ratio_fn = lambda county, fm, tm: \
#       market_index.index_ratio_asof(county, fm, tm, as_of=<subject as-of>)
# so no post-as-of sale can enter the trend.
_avm_index_ratio_fn = None


def _avm_index_debias_ratio(subject: dict) -> Optional[float]:
    """County market-index ratio train-center -> as-of month for the AVM
    de-bias (None = caller must no-op).

    The as-of month comes from ``_today_date()`` (production = today;
    backtests freeze it per subject). A just-started month can be thin
    (n_sales < MIN_SALES -> the loader returns None), so we fall back one,
    then two months — a few weeks of extra lag against the 10-22 months of
    model staleness being corrected."""
    county = str(subject.get("county") or "").strip()
    if not county:
        return None
    fn = _avm_index_ratio_fn
    if fn is None:
        try:
            from mls_bot.analytics.market_index import index_ratio as fn
        except Exception:
            return None
    today = _today_date()
    y, m = today.year, today.month
    for _ in range(3):
        try:
            r = fn(county, _AVM_TRAIN_CENTER, f"{y:04d}-{m:02d}")
        except Exception:
            return None
        if r and r > 0:
            return float(r)
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return None


def _method_avm(subject: dict, comps: list[dict]) -> ValuationMethod:
    """Predict the subject's value with the trained AVM (ML ensemble member).

    The AVM (``mls_bot.analytics.avm``) is a HistGradientBoostingRegressor
    fit on closed sales from physical + assessed features. It deliberately
    drops every price-derived input (``list_price``, ``price_per_sqft``,
    ``price_to_assessed_ratio``, ...), so predicting from the off-market
    subject (physical attrs only) preserves the backtest's leakage controls —
    no comp price ever enters this method.

    The AVM is an INDEPENDENT signal from the comp arithmetic: it generalizes
    across the whole market rather than the handful of selected comps, which
    is why it complements (not replaces) them. It enters the triangulation
    with a modest fixed weight (see ``_triangulation_weights``) so a good model
    nudges the comp blend without dominating it.

    Returns ``value=None`` on ANY failure (model missing, import error, no
    usable features) so it simply renormalizes out of the blend — never a
    crash. A prediction is also rejected (None) if it falls outside a sane
    multiple of the comp-evidence envelope, so a degenerate model output can't
    poison the estimate.

    FAST MODE: interactive callers (the property-profile UI) set CMA_SKIP_AVM=1
    to skip this method. The AVM lazily imports scikit-learn, which costs ~5s+ to
    import on a COLD process spawn — negligible for the batch backtest (one
    long-lived process) and acceptable for the deliberate full-CMA/PDF generate,
    but it makes an interactive request (fresh spawn per call) take ~13s instead
    of ~2s. Skipping renormalizes the comp methods back in; the cost is ~1.3pp of
    median APE (14.0% -> 15.3%) for a ~6x latency win on the profile path."""
    import os
    _skip = os.environ.get("CMA_SKIP_AVM", "").strip().lower()
    if _skip and _skip not in ("0", "false", "no", "off"):
        return ValuationMethod("AVM (model)", None, None, None,
                               "Skipped (fast / interactive mode).")
    sf_subj = _num(subject.get("sqft"))
    if not sf_subj or sf_subj <= 0:
        return ValuationMethod("AVM (model)", None, None, None,
                               "AVM needs subject sqft.")
    try:
        from mls_bot.analytics.avm import predict as _avm_predict
    except Exception:
        return ValuationMethod("AVM (model)", None, None, None,
                               "AVM model unavailable.")
    try:
        pred = _avm_predict(subject)
    except Exception:
        pred = None
    pred = _num(pred)
    if not pred or pred <= 0:
        return ValuationMethod("AVM (model)", None, None, None,
                               "AVM produced no usable prediction.")

    # Q7 index de-bias (env-gated, default OFF): trend the frozen model's
    # prediction from its training-center price level to the as-of month
    # BEFORE the envelope gate, so the gate judges the de-biased value.
    _debias_note = ""
    _flag = os.environ.get("CMA_AVM_INDEX_DEBIAS", "").strip().lower()
    if _flag and _flag not in ("0", "false", "no", "off"):
        _ratio = _avm_index_debias_ratio(subject)
        if _ratio:
            pred *= _ratio
            _debias_note = (
                f" Index de-biased ×{_ratio:.3f} "
                f"({_AVM_TRAIN_CENTER} → as-of)."
            )

    # Guard against a degenerate prediction relative to the comp evidence. The
    # downstream comp-evidence clamp already bounds the final blend, but if the
    # AVM is wildly off for this subject we drop it entirely rather than let it
    # drag the blend toward a clamp boundary.
    comp_prices = sorted(
        p for p in (_num(c.get("sold_price")) for c in comps) if p and p > 0
    )
    if comp_prices:
        # Gate against the comp MEDIAN (robust) rather than the min/max extremes,
        # so a single cheap/expensive comp can't widen the envelope enough to
        # admit a degenerate AVM prediction.
        _med = comp_prices[len(comp_prices) // 2]
        lo_ok = _med * _AVM_ENV_LO
        hi_ok = _med * _AVM_ENV_HI
        if pred < lo_ok or pred > hi_ok:
            return ValuationMethod(
                "AVM (model)", None, None, None,
                f"AVM {_short_money(pred)} outside comp-evidence envelope — dropped.",
            )

    return ValuationMethod(
        name="AVM (model)",
        value=pred,
        low=pred * 0.90,
        high=pred * 1.10,
        rationale=(
            f"Gradient-boosted model on physical+assessed features (no price "
            f"inputs) predicts <b>{_short_money(pred)}</b>; blended as an "
            f"independent cross-market signal.{_debias_note}"
        ),
    )


def _triangulation_weights(subject_acres: float) -> dict[str, float]:
    """Return the base tier weights for the three comp-based methods.

    Replaces the previous "drop a method when rural" rule with explicit
    per-tier weights. The prior-sale method's weight is computed separately
    in ``_estimate_value`` (scaled by recency) and added on top of these."""
    # The AVM (ML, ~15% median APE) enters every tier with a modest fixed
    # weight so it complements the comp arithmetic without dominating it. The
    # comp-method weights are kept at their prior proportions; AVM is additive
    # and the whole set is renormalized over the methods that actually fire in
    # ``_estimate_value``. A failed AVM predict returns None and drops out, so
    # the comp methods simply re-absorb its weight.
    if subject_acres < 2.0:
        return {"Direct comp + acreage adjustment": 0.40,
                "$/sqft": 0.50,
                "Acreage residual": 0.10,
                "AVM (model)": 0.30}
    if subject_acres < 15.0:
        return {"Direct comp + acreage adjustment": 0.45,
                "$/sqft": 0.30,
                "Acreage residual": 0.25,
                "AVM (model)": 0.25}
    return     {"Direct comp + acreage adjustment": 0.40,
                "$/sqft": 0.15,
                "Acreage residual": 0.45,
                "AVM (model)": 0.20}


# Prior-sale weighting. A RECENT, arms-length, MLS-confirmed resale of the
# subject itself — trended to today — is the single strongest evidence of its
# current value, so it is allowed to be a STRONG anchor scaled by recency:
#   * a ~1-month-old sale  -> near-decisive (weight ~_PRIOR_SALE_MAX_WEIGHT,
#     which is large relative to the comp methods' ~1.0 combined weight);
#   * tapering to a MODEST nudge by ~18 months;
#   * fading to ~0 by ~3 years, where market drift dominates the stale price.
# The comp-method weights (Direct 0.40-0.45, $/sqft 0.15-0.50, Acreage
# 0.10-0.45, AVM ~0.5) sum to ~1.0-1.5; a max weight near 3.0 lets a very
# fresh sale carry ~2/3 of the blend without ever fully overriding the comps.
_PRIOR_SALE_MAX_WEIGHT = _envf("CMA_PRIOR_SALE_MAX_W", 3.0)
# Recency half-decay: weight is scaled by exp(-months / _PRIOR_SALE_DECAY_M).
# At ~18 months the multiplier is ~exp(-18/13) ~= 0.25 (modest); the >84-month
# hard gate in _method_prior_sale still drops genuinely stale anchors entirely.
_PRIOR_SALE_DECAY_M = _envf("CMA_PRIOR_SALE_DECAY_M", 13.0)
# Below this recency-multiplier the prior sale is too stale to bother anchoring.
_PRIOR_SALE_MIN_FRAC = 0.02


def _prior_sale_recency_frac(months: float) -> float:
    """Smooth recency multiplier in [0, 1]: ~1.0 for a fresh sale, ~0.25 at
    18 months, ~0.10 at 30 months. Exponential decay keeps a 1-month sale
    near-decisive while letting older sales fade to a modest nudge."""
    import math
    return math.exp(-max(0.0, months) / _PRIOR_SALE_DECAY_M)


def _prior_sale_weight(subject: dict) -> float:
    """Recency-scaled weight for the prior-sale method.

    Based on the subject's MLS-CONFIRMED prior sale date (not the assessor
    deed). Returns 0.0 when no MLS-confirmed sale exists or the sale is too
    stale, so the method and its weight stay consistent with
    ``_method_prior_sale``."""
    found = _mls_confirmed_prior_sale(subject)
    if not found:
        return 0.0
    _price, cd = found
    months = _months_since(cd)
    if months is None:
        return 0.0
    frac = _prior_sale_recency_frac(months)
    if frac < _PRIOR_SALE_MIN_FRAC:
        return 0.0
    return _PRIOR_SALE_MAX_WEIGHT * frac


# --- Q8 prior-sale anchor guards (env-gated; unset = shipped behavior) -----
# Flip guard: a subject that resold <~12 months before the valuation date at a
# price far below what the comps imply is adversely selected — fresh resales
# skew fix-and-flip, and the pre-renovation price is a bad anchor. Skip the
# anchor when the implied annualized appreciation (comp blend vs raw prior
# price) exceeds the threshold.
_PS_FLIP_MONTHS = _envf("CMA_PS_FLIP_MONTHS", 12.0)
_PS_FLIP_APPR = _envf("CMA_PS_FLIP_APPR", 0.40)
# Divergence gate: a trended anchor >25% away from the comp blend is evidence
# the ANCHOR is wrong (misassigned parcel, quiet non-arms-length transfer,
# major renovation), not the comps — ignore it.
_PS_DIVERGENCE_MAX = _envf("CMA_PS_DIVERGENCE_MAX", 0.25)


def _prior_sale_guards_enabled() -> bool:
    """Read CMA_PRIOR_SALE_GUARDS at CALL time (not import) so backtest arms
    can toggle the guards per-run in one process. Unset/anything-but-'1' =
    guards off = byte-identical shipped behavior."""
    return os.environ.get("CMA_PRIOR_SALE_GUARDS", "").strip() == "1"


def _prior_sale_guard_reason(subject: dict, anchor_trended: float,
                             blend_excl: Optional[float]) -> Optional[str]:
    """Return a human-readable skip reason when a guard trips, else None.

    ``blend_excl`` is the tier-weighted blend over the OTHER usable methods
    (the estimate the CMA would produce without the anchor) — the reference
    both guards compare against."""
    if not blend_excl or blend_excl <= 0:
        return None
    found = _mls_confirmed_prior_sale(subject)
    if not found:
        return None
    price, cd = found
    months = _months_since(cd)
    # Flip guard — raw prior price vs the blend, annualized.
    if (months is not None and months < _PS_FLIP_MONTHS and price > 0):
        implied = (blend_excl / price) ** (12.0 / max(months, 1.0)) - 1.0
        if implied > _PS_FLIP_APPR:
            return (
                f"sold {months:.0f} mo ago at {_short_money(price)}; comps imply "
                f"{implied * 100:.0f}%/yr appreciation — likely renovated/flipped "
                f"since, prior price not representative."
            )
    # Divergence gate — trended anchor vs the blend.
    if abs(anchor_trended / blend_excl - 1.0) > _PS_DIVERGENCE_MAX:
        return (
            f"trended anchor {_short_money(anchor_trended)} diverges more than "
            f"{_PS_DIVERGENCE_MAX * 100:.0f}% from the comp blend "
            f"{_short_money(blend_excl)} — anchor ignored."
        )
    return None


def _estimate_value(subject: dict, comps: list[dict]) -> ValuationResult:
    """Triangulate value via tier-weighted aggregation of up to four methods.

    Methods: Prior Sale + trend (Layer 0a), Direct Comp, $/sqft, Acreage
    Residual. Each comp-based method's $/sqft is time- and size-adjusted
    (Layer 0b/0c). The headline ``mid`` is a weighted average of the
    per-method midpoints; the prior-sale method gets a recency-scaled weight
    on top of the acreage-tier weights for the comp methods. Methods that
    returned ``value=None`` are still surfaced so agents see what couldn't run."""
    appr_rate = _estimate_appreciation_rate(comps)
    subject_tier = _subject_appearance_tier(subject, comps)

    methods = [
        _method_prior_sale(subject, appr_rate),
        _method_direct_comp(subject, comps, appr_rate, subject_tier),
        _method_per_sqft(subject, comps, appr_rate, subject_tier),
        _method_acreage_residual(subject, comps),
        _method_avm(subject, comps),
    ]
    usable = [m for m in methods if m.value is not None and m.value > 0]

    ppsfs = [
        float(c["sold_price"]) / float(c["sqft"])
        for c in comps
        if c.get("sqft") and c.get("sold_price") and c["sqft"] > 0
    ]
    ppsf_med = median(ppsfs) if ppsfs else 0.0

    if not usable:
        return ValuationResult(methods=methods, low=0, mid=0, high=0,
                               ppsf=ppsf_med, divergence_pct=0.0)

    ac_subj = _num(subject.get("acres")) or 0
    weights = dict(_triangulation_weights(ac_subj))
    if _AVM_W_MULT != 1.0 and "AVM (model)" in weights:
        weights["AVM (model)"] *= _AVM_W_MULT
    ps_w = _prior_sale_weight(subject)

    # Q8 guards (CMA_PRIOR_SALE_GUARDS=1): before the anchor enters the blend,
    # sanity-check it against what the OTHER methods say. A tripped guard
    # nulls the method (the rationale still discloses why) so it drops out of
    # the blend, the low/high envelope, and the weights.
    ps_method = next((m for m in methods if m.name == "Prior sale + trend"), None)
    if (ps_w > 0 and ps_method is not None and ps_method.value is not None
            and _prior_sale_guards_enabled()):
        others = {m.name: m for m in usable if m.name != "Prior sale + trend"}
        ow = {n: w for n, w in weights.items()
              if n in others and n != "Prior sale + trend"}
        ow_total = sum(ow.values())
        blend_excl = (
            sum(others[n].value * (w / ow_total) for n, w in ow.items())
            if ow_total > 0 else None
        )
        reason = _prior_sale_guard_reason(subject, ps_method.value, blend_excl)
        if reason:
            ps_method.value = None
            ps_method.low = None
            ps_method.high = None
            ps_method.rationale = f"Prior-sale guard: {reason}"
            usable = [m for m in usable if m.name != "Prior sale + trend"]
            ps_w = 0.0
            if not usable:
                return ValuationResult(methods=methods, low=0, mid=0, high=0,
                                       ppsf=ppsf_med, divergence_pct=0.0)
    if ps_w > 0:
        weights["Prior sale + trend"] = ps_w

    method_by_name = {m.name: m for m in usable}
    active_weights = {name: w for name, w in weights.items() if name in method_by_name}
    total = sum(active_weights.values())
    if total <= 0:
        active_weights = {m.name: 1.0 for m in usable}
        total = float(len(usable))

    mid_raw = sum(
        method_by_name[name].value * (w / total) for name, w in active_weights.items()
    )
    low_raw = min(m.low or m.value for m in usable)
    high_raw = max(m.high or m.value for m in usable)

    # Sanity clamp to the comp evidence: a CMA must never output a value the
    # comps can't support. The $/sqft and acreage-residual methods explode on
    # extreme-size / high-acreage subjects (e.g. a 16,000 sqft / 24 ac outlier
    # predicting $20M against $700k comps). Bound the estimate to a generous
    # envelope around the selected comps' realized prices — wide enough never to
    # touch a normal subject (whose value already sits inside the comp range),
    # tight enough to defuse the blow-ups that dominate MAPE/MAE.
    comp_prices = sorted(
        p for p in (_num(c.get("sold_price")) for c in comps) if p and p > 0
    )
    if comp_prices:
        lo_cap = comp_prices[0] * _CLAMP_LO
        hi_cap = comp_prices[-1] * _CLAMP_HI
        # Optional median-comp anti-inflation cap — defuses the thin-cheap-supply
        # over-valuation (a handful of pricier comps pulling a cheap subject up).
        if _MEDIAN_CAP_K > 0:
            hi_cap = min(hi_cap, median(comp_prices) * _MEDIAN_CAP_K)
        mid_raw = min(max(mid_raw, lo_cap), hi_cap)
        low_raw = min(max(low_raw, lo_cap), hi_cap)
        high_raw = min(max(high_raw, lo_cap), hi_cap)
        # Interval calibration — widen the [low, high] band around the (clamped)
        # mid so reported coverage approaches the ~80% nominal target.
        if _INTERVAL_K != 1.0:
            low_raw = max(mid_raw * 0.25, mid_raw - (mid_raw - low_raw) * _INTERVAL_K)
            high_raw = mid_raw + (high_raw - mid_raw) * _INTERVAL_K

    # CREDIBILITY CAP (applies to every brand template — the displayed "supported
    # range" must never imply an absurd spread like $300k-$1.3M). Bound the band
    # to +/- _BAND_MAX_FRAC of the mid regardless of method divergence. The
    # divergence itself is still disclosed in the Methods panel, but the headline
    # range stays defensible. This is the last word on low/high.
    if mid_raw > 0 and _BAND_MAX_FRAC > 0:
        low_raw = max(low_raw, mid_raw * (1.0 - _BAND_MAX_FRAC))
        high_raw = min(high_raw, mid_raw * (1.0 + _BAND_MAX_FRAC))

    # Divergence reports the spread across the COMP-BASED methods (the prior
    # sale and the AVM are independent signals, not part of the comp-method
    # spread).
    comp_vals = sorted(
        m.value for m in usable
        if m.name not in ("Prior sale + trend", "AVM (model)")
    )
    divergence = (
        (max(comp_vals) - min(comp_vals)) / median(comp_vals) * 100.0
        if len(comp_vals) > 1 else 0.0
    )
    # Agent bed/bath what-if adjustment (CMA_OVERRIDE_DAMPING=1 only): with
    # comp selection record-anchored (see _selection_subject), the override's
    # value effect is this BOUNDED explicit step (±8% cap) instead of a comp
    # cohort re-anchor. Applied LAST — after the comp-evidence clamp and the
    # credibility band — so each bed/bath step stays visible (monotonic) even
    # when the baseline sits on a cap; the shift is bounded and disclosed via
    # the non-suppressible record→adjusted block. Multiplying low/mid/high by
    # the same factor preserves the band's relative width. 0.0 for the record
    # subject (no _override_diff), so _record_basis_mid is never adjusted.
    if _override_damping_enabled():
        _bb_pct = _override_bedbath_pct(subject)
        if _bb_pct:
            _f = 1.0 + _bb_pct / 100.0
            mid_raw *= _f
            low_raw *= _f
            high_raw *= _f
    # UNROUNDED on purpose — the $5k display rounding happens at the render/API
    # boundary (see ValuationResult docstring), never inside the math.
    return ValuationResult(
        methods=methods,
        low=float(low_raw),
        mid=float(mid_raw),
        high=float(high_raw),
        ppsf=ppsf_med,
        divergence_pct=divergence,
    )


# ---------------------------------------------------------------------------
# Layer 2 — blind-Haiku ensemble fold (env-gated CMA_BLIND_ENSEMBLE=1)
# ---------------------------------------------------------------------------

def _blind_ensemble_enabled() -> bool:
    """CMA_BLIND_ENSEMBLE gate for the certified blind-Haiku ensemble.

    Read at CALL time (not import) so the worker / per-spawn processes honor
    the env they were launched with. Set only in compbird's own engine
    environment (same isolation pattern as CMA_COMP_SCORE_SURFACE); unset
    keeps every valuation + serialization byte-identical for Ratifyly."""
    return os.environ.get("CMA_BLIND_ENSEMBLE", "").strip() == "1"


def _apply_blind_ensemble(subject: dict, comps: list[dict],
                          valuation: ValuationResult, *,
                          untuned: bool,
                          fetch_untuned=None) -> tuple[ValuationResult, Optional[int], bool]:
    """Fold the subject's cached blind anchor into the valuation.

    Certified recipe (2026-07, held-out n=1000): final mid =
    mean(engine unrounded mid, blind Haiku read of the untuned comp packet).
    low/high shift by the same delta as mid so the band width is preserved;
    the $5k display rounding still happens at the render/API boundary, so
    every surface shows round_to_5k(mean(engine, blind)) — one number
    everywhere. A methods row ("AI comparable read") discloses the anchor.

    ``untuned`` — True when ``comps`` are the engine's own untuned picks (no
    user comp pins/exclusions); the anchor is then computable directly from
    them. Tuned recomputes pass False and reuse the subject's cached anchor
    (no new LLM call); on the rare cold tuned path ``fetch_untuned`` derives
    the untuned picks first.

    Returns ``(valuation, ai_blind, applied)``. Any failure — no API key,
    timeout (8s budget), unparseable reply — returns the valuation unchanged
    (engine-only), logged by the valuer, never raising.
    """
    if not (valuation.mid and valuation.mid > 0):
        return valuation, None, False
    try:
        from mls_bot.analytics.blind_valuer import get_blind_anchor
        # Damped posture (CMA_OVERRIDE_DAMPING=1): the blind read sees the
        # SELECTION subject — bed/bath overrides reverted to record — so its
        # packet matches the record-anchored comps and the anchor (and its
        # cache signature) is bed/bath-override-invariant. The override's
        # value effect stays the bounded _estimate_value adjustment instead of
        # an uncontrolled LLM re-read. Flag unset = `subject` unchanged.
        blind = get_blind_anchor(
            _selection_subject(subject), comps if untuned else None,
            fetch_untuned=None if untuned else fetch_untuned,
            as_of=_today_date().isoformat(),
        )
    except Exception:
        return valuation, None, False
    if not blind or blind <= 0:
        return valuation, None, False
    new_mid = (float(valuation.mid) + float(blind)) / 2.0
    delta = new_mid - float(valuation.mid)
    methods = list(valuation.methods) + [ValuationMethod(
        name="AI comparable read",
        value=float(blind),
        low=None,
        high=None,
        rationale=("Independent AI valuation from a blind read of the "
                   "selected comparables (no list price, AVM, or prior-sale "
                   "input); averaged 50/50 into the final estimate."),
    )]
    return ValuationResult(
        methods=methods,
        low=float(valuation.low) + delta,
        mid=new_mid,
        high=float(valuation.high) + delta,
        ppsf=valuation.ppsf,
        divergence_pct=valuation.divergence_pct,
    ), int(blind), True


# ---------------------------------------------------------------------------
# Layer 2b — measured confidence tier (env-gated CMA_BLIND_ENSEMBLE=1)
# ---------------------------------------------------------------------------

# Tier gates — COPIED from the Compbird app's src/lib/compbird/confidence.ts
# (the studio's measured two-tier gate) so the engine-computed tier and the
# app's client-side fallback always agree. MEASURED 2026-07-13 on the
# 1000-subject regional certification pool: the ensemble-arm gate carves out a
# 6.13% median-APE slice @ 31.0% coverage (pool-wide ensemble median 11.54%;
# the STANDARD complement measures 14.95% — the honest gap the range hero
# exists for); the no-blind fallback arm measures 9.21% @ 42.9%. Keep these
# constants in lockstep with confidence.ts whenever the gate is retuned.
_CONF_HIGH_MIN_COMPS = 5
# ensemble arm — blind anchor folded (valuation carries ai_blind + ai_ensemble)
_CONF_ENS_MAX_NEAREST_MI = 0.3
_CONF_ENS_MAX_FARTHEST_MI = 1.0
_CONF_ENS_MAX_AGREEMENT_PCT = 10.0
# fallback arm — no blind anchor (distance + method-spread gate)
_CONF_MAX_NEAREST_MI = 0.5
_CONF_MAX_FARTHEST_MI = 0.8
_CONF_MAX_SPREAD_PCT = 10.0


def confidence_signals(comps: list[dict], valuation: "ValuationResult",
                       ai_blind: Optional[int], ai_ensemble: bool) -> dict:
    """Measured confidence tier + the signals it was computed from.

    ENGINE-LOCKED by construction: every input is engine-owned — the selected
    comps' stamped ``_distance_mi``/``source``, the UNROUNDED valuation, and
    the blind anchor the engine itself fetched and cached. Nothing here reads
    ``report_config`` / ``subject_overrides`` / any request field, so an API
    caller cannot force the tier. (Subject overrides can move the tier only
    the honest way — by changing the valuation the tier then describes.)

    Mirrors ``computeConfidenceFromSignals`` in the app's confidence.ts:

      ensemble arm (anchor folded):  HIGH iff >= 5 comps AND nearest <= 0.3 mi
        AND farthest <= 1.0 mi AND |engine - blind| / ensemble <= 10%
      fallback arm (no anchor):      HIGH iff >= 5 comps AND nearest <= 0.5 mi
        AND farthest <= 0.8 mi AND method spread (max - min) / mid <= 10%
      either arm: a mostly-supplemental comp set (> 50%) caps at "standard".
    """
    mid = float(valuation.mid or 0)
    dists = [d for c in comps
             if (d := _num(c.get("_distance_mi"))) is not None
             and d >= 0 and d != float("inf")]
    nearest = min(dists) if dists else None
    farthest = max(dists) if dists else None

    # Arm agreement: the folded mid IS the ensemble mean, so the engine-only
    # arm is 2*mid - blind and the denominator is mid itself — identical to
    # the app's reconstruction and the derivation pool's |engine-blind|/ens.
    agreement_pct = None
    if ai_ensemble and ai_blind and ai_blind > 0 and mid > 0:
        agreement_pct = abs((2.0 * mid - float(ai_blind)) - float(ai_blind)) / mid * 100.0

    values = [float(m.value) for m in valuation.methods
              if m.value is not None and float(m.value) > 0]
    spread_pct = ((max(values) - min(values)) / mid * 100.0
                  if len(values) >= 2 and mid > 0 else None)

    supplemental_share = (sum(1 for c in comps if c.get("source") == "supplemental")
                          / len(comps)) if comps else 0.0

    ensemble_arm = agreement_pct is not None
    if ensemble_arm:
        distance_ok = (nearest is not None and nearest <= _CONF_ENS_MAX_NEAREST_MI
                       and (farthest is None or farthest <= _CONF_ENS_MAX_FARTHEST_MI))
        evidence_ok = agreement_pct <= _CONF_ENS_MAX_AGREEMENT_PCT
    else:
        distance_ok = (nearest is not None and nearest <= _CONF_MAX_NEAREST_MI
                       and (farthest is None or farthest <= _CONF_MAX_FARTHEST_MI))
        evidence_ok = spread_pct is not None and spread_pct <= _CONF_MAX_SPREAD_PCT

    tier = ("high" if mid > 0 and len(comps) >= _CONF_HIGH_MIN_COMPS
            and distance_ok and evidence_ok and supplemental_share <= 0.5
            else "standard")
    return {"tier": tier, "count": len(comps), "nearest_mi": nearest,
            "farthest_mi": farthest, "agreement_pct": agreement_pct,
            "spread_pct": spread_pct, "ensemble_arm": ensemble_arm}


def confidence_tier(comps: list[dict], valuation: "ValuationResult",
                    ai_blind: Optional[int], ai_ensemble: bool) -> str:
    """The measured two-tier gate: ``"high" | "standard"`` (see
    :func:`confidence_signals` for the gates and the integrity argument)."""
    return confidence_signals(comps, valuation, ai_blind, ai_ensemble)["tier"]


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _fmt_date(d) -> str:
    if d is None:
        return "—"
    s = str(d)[:10]
    if len(s) == 10 and s[4] == "-":
        return f"{s[5:7]}/{s[2:4]}"   # e.g. "2026-05-27" → "05/26"
    return s


def _comp_row(c: dict, is_subject: bool = False) -> str:
    addr = str(c.get("address") or "—")
    city = str(c.get("city") or "")
    sub_line = []
    if city:
        sub_line.append(city)
    if c.get("subdivision"):
        sub_line.append(str(c["subdivision"]))
    if not is_subject:
        sub_line.append(f"{int(c.get('dom') or 0)} DOM")
    # Surface the condition basis (LFD_Appearance tier) when it drove an adjustment.
    if not is_subject and c.get("_appearance_tier") is not None:
        _names = {5: "new-build", 4: "renovated", 3: "good", 2: "average", 1: "fair", 0: "needs work"}
        _t = c.get("_appearance_tier")
        _adj = c.get("_appearance_adj_pct") or 0
        if abs(_adj) >= 1:
            sub_line.append(f"cond: {_names.get(_t, '?')} ({_adj:+.0f}%)")
    sub = " · ".join(sub_line)
    tag = '<span class="tag subjt">Subject</span>' if is_subject else ""
    if not is_subject and c.get("_forced"):
        tag = '<span class="tag key">Selected</span>'
    # Pending comps are under contract — price is the agreed-near-list estimate,
    # not a closed sale. Flag so the agent reads them as a leading signal.
    if not is_subject and c.get("_pending"):
        tag += ' <span class="tag pend">Pending</span>'
    if not is_subject and c.get("_atypical_sale"):
        reason = str(c.get("_atypical_reason") or "Atypical sale signal")
        tag += f' <span class="tag warn" title="{reason}">Atypical</span>'
    # Surface the reason as a small italic note under the subdivision so the
    # tag isn't the only carrier — print/PDF doesn't render tooltips.
    if not is_subject and c.get("_atypical_sale"):
        sub_line.append(str(c.get("_atypical_reason") or "Atypical"))
        sub = " · ".join(sub_line)
    status_raw = str(c.get("status_category") or "").strip().lower()
    is_off_market = is_subject and status_raw == "off-market"
    if is_subject:
        sold_d = "Off-Market" if is_off_market else "Active"
    else:
        sold_d = _fmt_date(c.get("close_date"))
    price = c.get("list_price") if is_subject else c.get("sold_price")
    sf = c.get("sqft") or 0
    ac = c.get("acres") or 0
    bd = c.get("bedrooms") or 0
    fb = c.get("full_baths") or 0
    hb = c.get("half_baths") or 0
    bath = f"{int(bd)}/{_fmt_baths(fb, hb)}"
    yb = c.get("year_built") or 0
    ppsf = (float(price) / float(sf)) if (sf and price) else 0
    if is_subject:
        ls = "—"
    else:
        olp = c.get("original_list_price") or price or 0
        ls = f"{(float(price) / float(olp)) * 100:.0f}%" if olp else "—"
    # For an off-market subject we have no current list price — render an em-dash
    # rather than the literal "$0" / "$0/sf" that the comp-row formula would emit.
    price_cell = "—" if (is_subject and not price) else _money(price or 0)
    ppsf_cell = "—" if (is_subject and not price) else f"${int(ppsf)}"
    row_class = ' class="subj"' if is_subject else ""
    return (
        f"<tr{row_class}>"
        f'<td class="l"><span class="addr2">{addr}</span>{tag}'
        f'<div class="sub">{sub}</div></td>'
        f"<td>{sold_d}</td>"
        f"<td>{price_cell}</td>"
        f"<td>{int(sf) if sf else '—'}</td>"
        f"<td>{ac:.1f}</td>"
        f"<td>{bath}</td>"
        f"<td>{int(yb) if (yb and yb < 2100) else '—'}</td>"
        f"<td>{(int(c.get('dom') or 0) if c.get('dom') is not None else '—') if not is_subject else ('—' if is_off_market else 'Active')}</td>"
        f"<td>{ppsf_cell}</td>"
        f"<td>{ls}</td>"
        "</tr>"
    )


def _exec_paragraph(subject: dict, comps: list[dict], mid: int,
                    recommended_price: Optional[int] = None) -> str:
    sf = subject.get("sqft") or 0
    ac = subject.get("acres") or 0
    yb = subject.get("year_built") or 0
    city = subject.get("city") or ""
    parts = []
    if yb and 1800 <= yb < 2100:
        parts.append(f"{int(yb)}-built")
    if sf:
        parts.append(f"{int(sf):,} sqft")
    if ac:
        parts.append(f"{ac:.2f}-acre")
    descriptor = " ".join(parts) if parts else "subject property"
    list_price = subject.get("list_price")
    # Price-reduction framing: when an explicit recommended price below the
    # current list is set, the exec argues the required reduction from the hard
    # market evidence (days-on-market + the closed-comp ceiling), not the model mid.
    if list_price and recommended_price and int(recommended_price) < float(list_price):
        _d = subject.get("feed_dom")
        dom = int(_d) if isinstance(_d, (int, float)) and _d else 0
        closed = sorted(
            float(c["sold_price"]) for c in comps
            if c.get("sold_price") and not c.get("_pending")
        )
        ceil_phrase = (
            f" closed comparable sales top out near {_short_money(closed[-1])}, yet the home remains unsold."
            if closed else " yet the home remains unsold."
        )
        lead = f"After {dom} days on market with no contract, the " if dom else "The "
        return (
            f"{lead}{_short_money(list_price)} ask on this {descriptor} home sits above what buyers "
            f"have paid nearby in {city} —{ceil_phrase} A reduction to "
            f"{_short_money(int(recommended_price))} prices it within the proven market range to "
            f"re-engage buyers and convert showings to an offer."
        )
    delta_phrase = ""
    if list_price and mid:
        gap = (float(list_price) - mid) / mid
        if gap > 0.05:
            delta_phrase = f" Current list runs ~{abs(gap)*100:.0f}% above comp value."
        elif gap < -0.05:
            delta_phrase = f" Current list runs ~{abs(gap)*100:.0f}% below comp value."
    return (
        f"The {descriptor} home sits in {city} and indexes against "
        f"a comp set of {len(comps)} recent closings nearby.{delta_phrase}"
    )


def _verdict_delta(subject: dict, mid: int, list_price: Optional[float],
                   divergence_pct: float = 0.0,
                   recommended_price: Optional[int] = None) -> str:
    diverge_warn = ""
    if divergence_pct > 15.0:
        diverge_warn = (
            f" Triangulation methods diverge by ~{int(round(divergence_pct))}% — "
            f"review the comp set carefully."
        )
    # Price-reduction framing: contrast the current ask against the recommended
    # price and the days-on-market, not the model mid (which can sit near a
    # stale, above-market list and wrongly read as "tracks").
    if list_price and recommended_price and int(recommended_price) < float(list_price):
        _d = subject.get("feed_dom")
        dom = int(_d) if isinstance(_d, (int, float)) and _d else 0
        cut = (float(list_price) - int(recommended_price)) / float(list_price) * 100.0
        dom_clause = f" and unsold after {dom} days" if dom else ""
        # No divergence caveat in the verdict here: when the value is anchored on
        # the closed-comp ceiling, "review the comp set" misreads (the comps are
        # sound; it's the $/sqft method that over-extrapolates). The method spread
        # is still disclosed in the Methods panel.
        return (
            f"Current list ({_short_money(list_price)}) runs <b>~{cut:.0f}% above</b> the recommended "
            f"{_short_money(int(recommended_price))}{dom_clause} — a price reduction is required to "
            f"meet the market."
        )
    if not list_price or not mid:
        return (
            "Triangulated mid reflects the median across three valuation methods." + diverge_warn
        )
    gap = (float(list_price) - mid) / mid
    if abs(gap) < 0.03:
        return f"Current list ({_short_money(list_price)}) tracks the triangulated mid.{diverge_warn}"
    direction = "above" if gap > 0 else "below"
    return (
        f"Current list ({_short_money(list_price)}) runs <b>~{abs(gap)*100:.0f}% {direction}</b> "
        f"the triangulated mid of {_short_money(mid)}.{diverge_warn}"
    )


def _docmeta_rows(subject: dict) -> list[tuple[str, str]]:
    from datetime import date
    rows = [("Prepared", date.today().strftime("%B %-d, %Y") if sys.platform != "win32"
             else date.today().strftime("%B %#d, %Y"))]
    status = str(subject.get("status_category") or "").strip()
    dom = subject.get("feed_dom")
    if status and status.lower() == "active":
        rows.append(("Status", f"Active · {int(dom or 0)} DOM" if dom else "Active"))
    elif status:
        rows.append(("Status", status))
    lp = subject.get("list_price")
    if lp:
        rows.append(("Current List", _money(lp)))
    return rows


def _confidence(subject: dict, comps: list[dict], valuation: "ValuationResult") -> tuple[str, str]:
    """Heuristic valuation-confidence tier + one-line reason.

    Surfaces the size-outlier failure mode (a subject materially larger than
    every comp, where the $/sqft + acreage methods over-extrapolate — e.g. a
    4,290 sqft home priced off ~2,500 sqft comps) and method divergence, so the
    report itself flags when the headline number should be trusted less.
    Returns ``(tier, reason)`` with tier in {High, Moderate, Low}."""
    n = len(comps)
    div = float(getattr(valuation, "divergence_pct", 0) or 0)
    s_sf = _num(subject.get("sqft")) or 0
    comp_sf = [(_num(c.get("sqft")) or 0) for c in comps if _num(c.get("sqft"))]
    max_sf = max(comp_sf) if comp_sf else 0

    # Distance signal — comps are stamped with ``_distance_mi`` (haversine to the
    # subject) in pick_comps. A valuation anchored on far-away comps must never
    # read "High": when nearby sales are scarce the selector falls back to
    # cross-region comps, so the headline number is geographic, not local. Without
    # this, a subject with its nearest comp 80+ mi away was still flagged "High".
    _NEAR_MAX_MI = 15.0   # nearest comp beyond this ⇒ not local ⇒ never "High"
    _FAR_MI = 40.0        # nearest comp beyond this ⇒ "Low" (the evidence is elsewhere)
    dists = [d for c in comps if (d := _num(c.get("_distance_mi"))) is not None and d >= 0]
    nearest = min(dists) if dists else None

    if s_sf and max_sf and s_sf > max_sf * 1.4:
        return ("Low", "Subject is materially larger than every comp — value is extrapolated; weight the comp ceiling.")
    if nearest is not None and nearest > _FAR_MI:
        return ("Low", f"Nearest comparable is ~{nearest:.0f} mi away — too far to anchor value; treat the range as indicative only.")
    if div > 25 or n < 3:
        return ("Low", "Methods diverge or comps are thin — treat the range as wide.")
    far = nearest is not None and nearest > _NEAR_MAX_MI
    if div > 12 or n < 5 or far:
        if far:
            return ("Moderate", f"Adequate methods, but the nearest comparable is ~{nearest:.0f} mi away — local evidence is limited.")
        return ("Moderate", "Adequate comps with some spread across methods.")
    return ("High", "Tight method agreement across a full comp set.")


def _dom_pricing_band(subject: dict, mid: int, recommended_price: Optional[int],
                      band_dom: int) -> str:
    """Model-backed "list price → expected days on market" band (4 price points).

    The trained DOM quantile model takes list price as a feature, so we sweep a
    few prices around the anchor (recommended price if pinned, else the midpoint)
    and surface predicted p50 days plus the p25–p75 envelope. The "sweet spot"
    (highlighted) is the HIGHEST price still expected to clear within a healthy
    window. Returns "" (section omitted) if the model is unavailable or errors —
    the report degrades to deterministic exactly like the AI comp-hygiene pass."""
    try:
        from pathlib import Path as _P
        from mls_bot.analytics.dom_model import load as _load_dom, predict_dom, MODEL_DIR
        if not (_P(MODEL_DIR) / "bundle_meta.joblib").exists():
            return ""
        bundle = _load_dom()
        anchor = int(recommended_price) if recommended_price else int(mid)
        if anchor <= 0:
            return ""
        points = [("Aggressive", 0.95), ("Market", 1.00), ("Ambitious", 1.05), ("Stretch", 1.10)]
        rows = []
        for label, mult in points:
            price = _round_to_5k(anchor * mult)
            pred = predict_dom(subject, float(price), bundle=bundle)
            rows.append((label, price, pred.get("p25"), pred.get("p50"), pred.get("p75")))
        # Highlight the Market anchor (the CMA's recommended price point) so the
        # band reads as "list here — and here is the speed tradeoff above/below",
        # rather than nudging toward the top of the range.
        sweet = _round_to_5k(anchor)
        cells = []
        for label, price, p25, p50, p75 in rows:
            rec = " rec" if price == sweet else ""
            p50i = int(round(p50)) if p50 is not None else "—"
            rng = (f"{int(round(p25))}–{int(round(p75))}d typical"
                   if p25 is not None and p75 is not None else "")
            cells.append(
                f'<div class="dcell{rec}"><div class="dl">{label}</div>'
                f'<div class="dp">{_short_money(price)}</div>'
                f'<div class="dd">{p50i}<span> days</span></div>'
                f'<div class="dr">{rng}</div></div>'
            )
        return (
            '<h2 class="sec">Pricing &amp; Absorption '
            '<span>predicted days on market by list price</span></h2>'
            f'<div class="dband">{"".join(cells)}</div>'
        )
    except Exception:
        return ""


def _build_html(brand: Brand, agent: AgentIdentity, subject: dict, comps: list[dict],
                valuation: "ValuationResult", recommended_price: Optional[int] = None,
                report_config: Optional[dict] = None,
                measured_confidence: Optional[dict] = None) -> str:
    """Compose the full HTML string ready for headless rendering.

    ``recommended_price`` (optional) pins an explicit recommended list price on
    the report — shown in the Strategy panel and used to lead the strategy copy.
    When omitted, the strategy is derived from the list-vs-comp gap as before.

    ``report_config`` (optional) is the agent report-composition dict
    ({sections?, execText?, strategyText?}). When None/empty the full report
    renders exactly as before. Section gating, the agent narrative override, and
    the both-value-sections guard are applied here; the masthead/titleblock/
    footer, the engine-locked disclaimer, and the record→adjusted disclosure
    always render regardless of the section toggles.

    ``measured_confidence`` (optional) is the :func:`confidence_signals` dict —
    passed ONLY by CMA_BLIND_ENSEMBLE=1 callers (build_cma computes it
    engine-side; it is never derived from request input, so the hero treatment
    below is not caller-forgeable). None (every flag-off caller) renders the
    legacy hero byte-identically. "high" keeps today's hero and adds one small
    evidence line; "standard" flips the hero to the honest RANGE with the
    midpoint demoted to the support row."""
    cfg = report_config or {}
    sections = set(cfg.get("sections") or _ALL_SECTIONS)
    # Value-bearing guard: hero + comps carry the report. If a config drops BOTH,
    # force comps back in so the PDF is never empty.
    if not (sections & {"hero", "comps"}):
        sections.add("comps")

    # Presentation boundary: the report shows $5k-rounded numbers (and derives
    # the DOM pricing band from the rounded anchor); the ValuationResult itself
    # stays unrounded for any downstream math.
    low, mid, high, ppsf = (_round_to_5k(valuation.low), _round_to_5k(valuation.mid),
                            _round_to_5k(valuation.high), valuation.ppsf)
    addr = subject.get("address") or "Subject Property"
    city = subject.get("city") or ""
    county = subject.get("county") or ""
    sf = subject.get("sqft") or 0
    ac = subject.get("acres") or 0
    bd = subject.get("bedrooms") or 0
    fb = subject.get("full_baths") or 0
    hb = subject.get("half_baths") or 0
    yb = subject.get("year_built") or 0
    list_price = subject.get("list_price")

    masthead = brand.masthead_html(_docmeta_rows(subject))
    footer = brand.footer_html(agent, use_short_disclaimer=True)
    # Skeleton divider: dark_band uses ``<hr class="rule">``, cream_serif uses
    # ``<hr class="divider">``. Emit both — only the one styled by the active
    # skeleton renders visibly.
    divider = '<hr class="rule" /><hr class="divider" />'

    subtitle_parts = []
    if city:
        subtitle_parts.append(f"{city}, {county or 'Virginia'}")
    if bd or fb:
        subtitle_parts.append(f"{int(bd)}bd / {_fmt_baths(fb, hb)}ba")
    if sf:
        subtitle_parts.append(f"{int(sf):,} sqft")
    if ac:
        subtitle_parts.append(f"{ac:.2f} ac")
    subtitle = " · ".join(subtitle_parts)

    subject_row = _comp_row(subject, is_subject=True)
    comp_rows = "".join(_comp_row(c) for c in comps)
    _n_pending = sum(1 for c in comps if c.get("_pending"))
    comps_subtitle = (
        "recent closings & pendings · ranked by similarity"
        if _n_pending else "recent closings · ranked by similarity"
    )

    range_phrase = f"Supported range {_money(low)} – {_money(high)}" if low and high else ""
    delta_html = _verdict_delta(subject, mid, list_price, valuation.divergence_pct,
                                recommended_price=recommended_price)
    if cfg.get("execText"):
        # Agent-supplied executive summary — escaped at this boundary (markup
        # renders literally, never live HTML).
        exec_html = _html_escape(str(cfg["execText"])[:1200])
    else:
        exec_html = _exec_paragraph(subject, comps, mid, recommended_price=recommended_price)

    # KPI strip
    band_dom = int(median([int(c.get("dom") or 0) for c in comps]) if comps else 0)
    band_ls = [
        (float(c.get("sold_price") or 0) / float(c.get("original_list_price") or 1)) * 100
        for c in comps if c.get("sold_price") and c.get("original_list_price")
    ]
    median_ls = int(round(median(band_ls))) if band_ls else 0
    kpis = [
        (_short_money(mid), "Estimated Value", "3-method midpoint"),
        (f"${int(round(ppsf))}/sf", "Comp $/SQFT", f"{len(comps)} comps"),
        (f"{band_dom} d", "Median DOM", "in comp set"),
        (f"{median_ls}%", "Median L/S", "in comp set"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="n">{n}</div><div class="l">{l}</div>'
        f'<div class="s">{s}</div></div>'
        for n, l, s in kpis
    )

    # Valuation-confidence chip (surfaces the size-outlier signal) + the
    # model-backed DOM pricing band. Both are best-effort and self-omit on error.
    conf_tier, _conf_reason = _confidence(subject, comps, valuation)
    conf_html = f'<div class="conf c{conf_tier}">{conf_tier} confidence</div>'
    dom_band = _dom_pricing_band(subject, int(mid), recommended_price, band_dom)

    # Valuation methods bullet list — one bullet per triangulation method.
    method_bullets: list[str] = []
    for m in valuation.methods:
        if m.value is None:
            method_bullets.append(
                f"<li><b>{m.name}.</b> <i>{m.rationale}</i></li>"
            )
        else:
            method_bullets.append(f"<li><b>{m.name}.</b> {m.rationale}</li>")
    if valuation.divergence_pct > 15.0:
        method_bullets.append(
            f"<li><b>Methods diverge by {int(round(valuation.divergence_pct))}%.</b> "
            f"Mid is the median across methods; the range reflects the outer envelope.</li>"
        )
    val_methods = "".join(method_bullets)
    strategy_bullets = []
    # Days-on-market is direct market evidence and OUTRANKS the comp-midpoint gap:
    # a listing sitting well past the local norm is priced ahead of buyers, so the
    # move is a reduction — never "test higher" — regardless of where the comp
    # extrapolation lands. (The $/sqft + acreage methods over-extrapolate on large
    # / high-acreage subjects, which is exactly when a listing is most likely to
    # stall, so the gap-only rule gives backwards advice precisely there.)
    _fd = subject.get("feed_dom")
    feed_dom = int(_fd) if isinstance(_fd, (int, float)) and _fd else 0
    stale = feed_dom >= max(60, band_dom * 5)
    recprice_html = ""
    if recommended_price:
        # An explicit agent-set recommended list price leads the strategy and is
        # surfaced as a prominent line above the bullets.
        recprice_html = (
            f'<div class="recprice">Recommended list price · {_money(int(recommended_price))}</div>'
        )
        if list_price and int(recommended_price) < float(list_price):
            cut_pct = (float(list_price) - int(recommended_price)) / float(list_price) * 100.0
            lead = (
                f"{feed_dom} days on market against a {band_dom}-day comp median signals the current "
                f"{_money(int(list_price))} ask is ahead of buyers — "
                if stale else
                f"repricing from the current {_money(int(list_price))} ask, "
            )
            strategy_bullets.append(
                f"<li><b>Price reduction required — list at {_money(int(recommended_price))}.</b> {lead}"
                f"a ~{cut_pct:.0f}% reduction resets portal alerts and renews showing activity.</li>"
            )
        else:
            strategy_bullets.append(
                f"<li><b>List at {_money(int(recommended_price))}</b>, positioned within the comp set.</li>"
            )
        strategy_bullets.append(
            "<li><b>Refresh photography / drone</b> to support the new price at relaunch.</li>"
        )
    elif list_price and mid and stale:
        strategy_bullets.append(
            f"<li><b>Reduce to re-engage the market.</b> {feed_dom} days on market with no contract — "
            f"against a {band_dom}-day median in the comp set — signals the ask is ahead of buyers; "
            f"a visible price cut resets portal alerts and renews showing activity.</li>"
        )
    elif list_price and mid:
        gap = (float(list_price) - mid) / mid
        if gap > 0.05:
            strategy_bullets.append(
                f"<li><b>Refresh toward {_short_money(mid)}</b> to align with the comp midpoint.</li>"
            )
        elif gap < -0.05:
            strategy_bullets.append(
                f"<li><b>Room to test slightly higher.</b> Comp midpoint sits {abs(gap)*100:.0f}% above current ask.</li>"
            )
        else:
            strategy_bullets.append(
                "<li><b>List price aligns</b> with the comp midpoint — hold and let activity speak.</li>"
            )
    else:
        strategy_bullets.append(
            f"<li>Recommend marketing the property around <b>{_short_money(mid)}</b>.</li>"
        )
    if not recommended_price:
        strategy_bullets.append(
            "<li><b>Refresh photography / drone now</b> to support the reset.</li>"
            if stale else
            "<li><b>Refresh photography / drone</b> if the listing crosses 30 DOM in this band.</li>"
        )

    # Agent strategy override — one bullet per non-blank line, escaped. Replaces
    # the auto-generated bullets (and the recommended-price lead) entirely.
    if cfg.get("strategyText"):
        strategy_bullets = [
            f"<li>{_html_escape(line)}</li>"
            for line in str(cfg["strategyText"])[:1500].splitlines() if line.strip()
        ]
        recprice_html = ""

    # Measured-tier hero treatment (CMA_BLIND_ENSEMBLE=1 callers pass
    # ``measured_confidence``; None renders the legacy hero byte-identically —
    # the defaults below reproduce the exact legacy strings).
    verdict_lbl = "Estimated Value"
    val_html = f"~{_short_money(mid)}"
    range_line = range_phrase
    tier_line = ""
    if measured_confidence:
        _mc = measured_confidence
        if _mc.get("tier") == "high":
            # Today's layout unchanged + one small evidence line under the value.
            # Same formatting conventions as the app's badge (fmtMi clamp so a
            # 400-ft comp never prints "0.0 mi"; agreement ceil'd, floor 1%).
            _far = max(0.1, round(float(_mc.get("farthest_mi") or 0) * 10) / 10)
            _agr = (_mc.get("agreement_pct") if _mc.get("ensemble_arm")
                    else _mc.get("spread_pct"))
            _agr_txt = (f"; methods agree within {max(1, int(-(-float(_agr) // 1)))}%"
                        if _agr is not None else "")
            tier_line = (f'<div class="range">High confidence — '
                         f'{_mc.get("count")} comparable sales within '
                         f'{_far:.1f} mi{_agr_txt}.</div>')
            # Keep the chip consistent with the measured tier (the legacy
            # heuristic can disagree — never let the report contradict itself).
            conf_html = '<div class="conf cHigh">High confidence</div>'
        else:
            # STANDARD: the honest RANGE is the headline figure; the midpoint
            # demotes to the support row. Falls back to the mid hero only if a
            # degenerate valuation shipped no band.
            if low and high:
                verdict_lbl = "Estimated Range"
                val_html = f"{_short_money(low)} – {_short_money(high)}"
                range_line = f"Midpoint {_money(mid)}"
            tier_line = ('<div class="range">Comparables are farther or methods '
                         'diverge — treat this estimate as a range.</div>')
            # Never a "High confidence" chip under a range hero; the honest
            # line above carries the story.
            conf_html = ""

    # ---- Composed, section-gated blocks. Omitted sections render "". --------
    hero_block = (
        f"""<div class="hero">
      <div class="subject">
        <div class="lbl">Subject Property</div>
        <div class="addr">{addr}</div>
        <div class="loc">{city}{', built ' + str(int(yb)) if yb and 1800 <= yb < 2100 else ''}</div>
        <div class="specs">
          <div><b>{int(bd)}</b> Bedrooms</div><div><b>{_fmt_baths(fb, hb)}</b> Baths</div>
          <div><b>{int(sf):,}</b> Sq Ft</div><div><b>{ac:.2f}</b> Acres</div>
        </div>
      </div>
      <div class="verdict">
        <div class="lbl">{verdict_lbl}</div>
        <div class="val">{val_html}</div>
        <div class="range">{range_line}</div>{tier_line}
        <div class="delta">{delta_html}</div>
        {conf_html}
      </div>
    </div>"""
        if "hero" in sections else ""
    )
    exec_block = f'<p class="exec">{exec_html}</p>' if "exec" in sections else ""
    kpis_block = f'<div class="kpis">{kpi_html}</div>' if "kpis" in sections else ""
    comps_block = (
        f"""<h2 class="sec">Comparable Sales <span>{comps_subtitle}</span></h2>
    <table>
      <thead><tr>
        <th class="l" style="width:28%">Address</th><th>Sold</th><th>Price</th>
        <th>Sq Ft</th><th>Acres</th><th>Bd/Ba</th><th>Built</th><th>DOM</th><th>$/SF</th><th>S/L</th>
      </tr></thead>
      <tbody>{subject_row}{comp_rows}</tbody>
    </table>"""
        if "comps" in sections else ""
    )
    domband_block = dom_band if "dom_band" in sections else ""

    # Non-suppressible record→adjusted disclosure (renders OUTSIDE section gating).
    disclosure_block = _override_disclosure_html(subject) \
        + _comp_tuning_disclosure_html(subject)

    methods_panel = (
        f"""<div class="panel accent"><div class="h">Valuation Methods</div>
        <ul>{val_methods}</ul></div>"""
        if "methods" in sections else ""
    )
    strategy_panel = (
        f"""<div class="panel dark"><div class="h">Strategy</div>
        {recprice_html}<ul>{''.join(strategy_bullets)}</ul></div>"""
        if "strategy" in sections else ""
    )
    if methods_panel and strategy_panel:
        twocol_block = (
            f'<div class="twocol">\n      <div>{methods_panel}</div>\n'
            f'      <div>{strategy_panel}</div>\n    </div>'
        )
    elif methods_panel or strategy_panel:
        # Only one present — render it full-width (drop the .twocol wrapper).
        twocol_block = methods_panel or strategy_panel
    else:
        twocol_block = ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<title>{_html.escape(str(brand.display_name or ""))} — CMA · {_html.escape(str(addr or ""))}</title>
<style>{brand.print_css()}</style>
</head>
<body>
<div class="page">
  {masthead}
  <div class="titleblock">
    <div class="kicker">Comparative Market Analysis</div>
    <div class="title">{addr}</div>
    <div class="subtitle">{subtitle}</div>
  </div>
  {divider}
  <div class="body">
    {hero_block}
    {exec_block}
    {disclosure_block}
    {kpis_block}
    {comps_block}
    {domband_block}
    {twocol_block}
  </div>
  {footer}
</div></body></html>"""


# ---------------------------------------------------------------------------
# Headless render + auto-fit loop
# ---------------------------------------------------------------------------

_TIGHTEN_CSS_OVERLAYS = [
    # Attempt 1: standard tightening
    """
    @media print{
      .body{padding:10px 28px 12px !important;}
      .hero{margin:0 0 10px !important;}
      .exec{margin:0 0 8px !important;}
      .kpis{margin:0 0 10px !important;}
      .kpi{padding:6px 9px !important;}
      .kpi .n{font-size:14px !important;}
      h2.sec{margin:0 0 4px !important;padding-bottom:2px !important;}
      table{margin:0 0 8px !important;}
      tbody td{padding:3px 5px !important;}
      .panel{padding:8px 11px !important;}
      .foot{padding:8px 30px 9px !important;}
    }
    """,
    # Attempt 2: aggressive tightening — drop one comp + shrink type
    """
    @media print{
      body{font-size:9px !important;}
      .body{padding:8px 28px 10px !important;}
      .hero{margin:0 0 7px !important;gap:10px !important;}
      .verdict .val{font-size:24px !important;}
      .subject{padding:8px 11px !important;}
      .verdict{padding:8px 11px !important;}
      .exec{font-size:10px !important;margin:0 0 6px !important;}
      .kpis{margin:0 0 7px !important;}
      .kpi{padding:4px 8px !important;}
      .kpi .n{font-size:13px !important;}
      h2.sec{margin:0 0 3px !important;padding-bottom:2px !important;}
      table{margin:0 0 6px !important;}
      tbody td{padding:2px 4px !important;font-size:9px !important;}
      .panel{padding:6px 10px !important;font-size:9px !important;}
      .panel li{margin-bottom:1.5px !important;}
      .foot{padding:6px 30px 8px !important;}
      .foot .disc{font-size:6.5px !important;}
    }
    """,
]

# Extra autofit rung for measured-confidence renders ONLY (CMA_BLIND_ENSEMBLE=1).
# The tier evidence line + the blind fold's "AI comparable read" methods row add
# a few vertical px, which can tip a report that already sat at the flag-off
# ladder's limit onto page 2. Flag-off callers keep _TIGHTEN_CSS_OVERLAYS
# exactly (byte-identical autofit sequence); flag-on renders get one deeper cut
# before the drop-a-comp-row last resort.
_TIGHTEN_CSS_OVERLAYS_CONF = _TIGHTEN_CSS_OVERLAYS + [
    # Attempt 3 (flag-on only): deepest tightening
    """
    @media print{
      body{font-size:8.6px !important;}
      .body{padding:7px 26px 9px !important;}
      .hero{margin:0 0 6px !important;gap:9px !important;}
      .verdict .val{font-size:21px !important;}
      .verdict .range{font-size:8.5px !important;}
      .verdict .delta{margin-top:5px !important;padding-top:5px !important;font-size:8.5px !important;}
      .conf{margin-top:5px !important;}
      .subject{padding:7px 10px !important;}
      .verdict{padding:7px 10px !important;}
      .exec{font-size:9.5px !important;margin:0 0 5px !important;}
      .kpis{margin:0 0 6px !important;}
      .kpi{padding:3px 7px !important;}
      .kpi .n{font-size:12px !important;}
      h2.sec{margin:0 0 2px !important;padding-bottom:1px !important;}
      table{margin:0 0 5px !important;}
      tbody td{padding:2px 3px !important;font-size:8.5px !important;}
      .panel{padding:5px 9px !important;font-size:8.5px !important;}
      .panel li{margin-bottom:1px !important;}
      .dcell{padding:4px 6px !important;}
      .foot{padding:5px 30px 7px !important;}
      .foot .disc{font-size:6.5px !important;}
    }
    """,
]


def _render_pdf(html_path: Path, pdf_path: Path, chrome: str = CHROME_PATH) -> int:
    """Render an HTML file to a single-page-friendly PDF with headless Chromium.

    Flags are chosen so this works in a Debian python:3.12-slim container running
    AS ROOT (the deployed engine) as well as on a desktop:
      * --headless=new   modern headless mode (stable PDF output across versions)
      * --no-sandbox     MANDATORY as root — the sandbox refuses to start as uid 0,
                         and Chromium then exits without producing a PDF. Harmless
                         on Windows/desktop.
      * --disable-dev-shm-usage  containers ship a tiny (64MB) /dev/shm; without
                         this Chromium can crash mid-render. No-op outside Linux.
      * --disable-gpu / --no-pdf-header-footer  as before.

    Raises RuntimeError (never a bare FileNotFoundError) when Chromium exits
    nonzero OR fails to leave a non-empty PDF behind, surfacing the decoded
    stderr + returncode so the failure is never silent.
    """
    url = "file:///" + str(html_path.resolve()).replace("\\", "/").replace(" ", "%20")
    argv = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        url,
    ]
    proc = subprocess.run(argv, capture_output=True, check=False)

    def _stderr() -> str:
        try:
            return (proc.stderr or b"").decode("utf-8", "replace").strip()
        except Exception:
            return repr(proc.stderr)

    if proc.returncode != 0:
        raise RuntimeError(
            f"Chromium PDF render failed (exit {proc.returncode}) for {url}\n"
            f"cmd: {' '.join(argv)}\n"
            f"stderr:\n{_stderr()}"
        )
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError(
            f"Chromium exited 0 but produced no PDF at {pdf_path} for {url}\n"
            f"cmd: {' '.join(argv)}\n"
            f"stderr:\n{_stderr()}"
        )

    data = pdf_path.read_bytes()
    matches = re.findall(rb"/Count\s+(\d+)", data)
    return int(matches[0]) if matches else 0


def _inject_tighten(html: str, overlay_css: str) -> str:
    """Insert an override <style> block right before </head>."""
    block = f"<style>{overlay_css}</style>"
    return html.replace("</head>", block + "</head>", 1)


def _drop_one_comp_row(html: str) -> str:
    """Remove the last ``<tr>...</tr>`` from the comp table to claw back space."""
    table_close = html.rfind("</tbody>")
    if table_close == -1:
        return html
    tbody_open = html.rfind("<tbody>", 0, table_close)
    if tbody_open == -1:
        return html
    body_segment = html[tbody_open + len("<tbody>"):table_close]
    rows = re.findall(r"<tr[^>]*>.*?</tr>", body_segment, flags=re.DOTALL)
    if len(rows) <= 2:  # keep at least subject + 1 comp
        return html
    new_body = "".join(rows[:-1])
    return html[:tbody_open + len("<tbody>")] + new_body + html[table_close:]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _fmt_baths(full, half) -> str:
    """Render baths as full + 0.5*half (a half bath = 0.5, NOT 0.1). Drops a
    trailing .0 — (2 full, 1 half) -> '2.5'; (3 full, 0 half) -> '3'."""
    total = int(full or 0) + 0.5 * int(half or 0)
    return f"{total:.1f}".rstrip("0").rstrip(".")


def prepare_comps(subject: dict, *, n_comps: int = 6, months_back: int = 24,
                  comp_overrides=None, excluded_comps=None,
                  ai_hygiene: bool = True,
                  subject_remarks=None) -> list[dict]:
    """Pick comps and (when ``ai_hygiene``) run the LLM comp-hygiene pass, then
    trim to ``n_comps`` — returning the EXACT comp set used for valuation.

    Shared by ``build_cma`` (the PDF) and ``property_profile.build_profile`` (the
    interactive estimate) so both triangulate the SAME comps. This is what keeps
    the price shown when you type an address consistent with the generated CMA's
    value: without the shared pass, the profile valued raw comps while the CMA
    valued hygiene-adjusted comps, so the two numbers diverged.

    ``subject_remarks`` (optional) is the subject's own masked remarks dict,
    threaded to ``review_comps`` so the hygiene reviewer judges condition
    against the ACTUAL subject instead of its stock assumption. Default None
    keeps the stock prompt.

    Hygiene resilience: the shortlist is pulled ``n_comps + 10`` deep so that
    when the reviewer drops comps (measured drop rates run ~50%), the next-best
    already-scored candidates backfill the set to ``n_comps``. If fewer than
    ``max(3, n_comps // 2)`` comps survive even then, hygiene falls back to
    FLAGS-ONLY on the deterministic top-``n_comps`` set — a CMA must never
    value off a 1-2 comp remnant.
    """
    pull_n = n_comps + 10 if ai_hygiene else n_comps
    # SELECTION uses the damped subject (CMA_OVERRIDE_DAMPING=1: bed/bath
    # overrides reverted to record so the comp set stays size/location-
    # anchored — see _selection_subject). Flag unset returns `subject` as-is,
    # so the default path is byte-identical. Hygiene + valuation below keep
    # the overridden subject.
    comps = pick_comps(
        _selection_subject(subject), n=pull_n, months_back=months_back,
        overrides=comp_overrides, excluded=excluded_comps,
        as_of=_today_date(),
    )
    if not comps:
        return []
    if ai_hygiene:
        try:
            from mls_bot.analytics.cma_hygiene import review_comps, apply_hygiene
            from mls_bot.analytics.llm import llm_available
            if llm_available():
                shortlist = comps
                # Pass subject_remarks only when provided, so this call keeps
                # working against a review_comps without the kwarg.
                _kw = {"subject_remarks": subject_remarks} if subject_remarks is not None else {}
                verdicts = review_comps(subject, comps, **_kw)
                if verdicts:
                    survivors = apply_hygiene(comps, verdicts)
                    if len(survivors) >= max(3, n_comps // 2):
                        # apply_hygiene preserves score order, so trimming the
                        # (n+10)-deep survivor list below IS the backfill:
                        # dropped comps are replaced by the next-best scored
                        # candidates that passed review.
                        comps = survivors
                    else:
                        # Hygiene floor: the reviewer gutted the set. Fall back
                        # to the deterministic top-n with verdicts as
                        # annotations only — keep-verdicts still condition-
                        # adjust via _hygiene; drop-verdicts become a
                        # _hygiene_flag note instead of a removal.
                        fallback = []
                        for c in shortlist[:n_comps]:
                            c2 = dict(c)
                            c2.pop("_hygiene_dropped", None)  # set by apply_hygiene above
                            v = verdicts.get(str(c.get("address") or ""))
                            if v is not None:
                                if (v.get("keep", True) and v.get("property_type_match", True)
                                        and v.get("arms_length", True)):
                                    c2["_hygiene"] = v
                                else:
                                    c2["_hygiene_flag"] = v.get("reason") or "flagged by hygiene review"
                            fallback.append(c2)
                        comps = fallback
        except Exception:
            # Any failure in the optional AI path must not break valuation.
            pass
    # Trim back to the requested count (forced comps + highest-scoring survivors).
    return comps[:n_comps]


def _preview_clean(o):
    """Scrub NaN/inf to None so the result is valid JSON (no math import)."""
    if isinstance(o, float):
        if o != o or o in (float("inf"), float("-inf")):
            return None
        return o
    if isinstance(o, dict):
        return {k: _preview_clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_preview_clean(v) for v in o]
    return o


def _score_surface_enabled() -> bool:
    """CMA_COMP_SCORE_SURFACE gate for the comp-workshop similarity fields.

    Read at CALL time (not import) so the worker / per-spawn processes honor
    the env they were launched with. Set only in compbird's own engine
    environment (same isolation pattern as CMA_LISTINGS_PARQUET); unset keeps
    the preview/profile serialization byte-identical for Ratifyly."""
    return os.environ.get("CMA_COMP_SCORE_SURFACE", "").strip() == "1"


def _similarity_summary(sims: list[int]) -> dict:
    """Subject-level aggregate of the per-comp similarity scores (avg/top feed
    the FREE teaser; low is internal). Nulls when nothing was computable."""
    return {
        "avg": int(round(sum(sims) / len(sims))) if sims else None,
        "top": max(sims) if sims else None,
        "low": min(sims) if sims else None,
    }


def _preview_comp_dict(c: dict) -> dict:
    """The comp shape the interactive studio consumes (mirrors the legacy
    PREVIEW_RUNNER output so the app contract is unchanged)."""
    return {
        "address": c.get("address"), "city": c.get("city"), "county": c.get("county"),
        "subdivision": c.get("subdivision"), "parcel_id": c.get("parcel_id"),
        "sold_price": c.get("sold_price"), "original_list_price": c.get("original_list_price"),
        "sqft": c.get("sqft"), "acres": c.get("acres"), "year_built": c.get("year_built"),
        "bedrooms": c.get("bedrooms"), "full_baths": c.get("full_baths"), "half_baths": c.get("half_baths"),
        "dom": c.get("dom"), "close_date": str(c.get("close_date") or "") or None,
        "score": c.get("_score"), "distance_mi": c.get("_distance_mi"), "cohort": c.get("_cohort"),
        "atypical_sale": bool(c.get("_atypical_sale")), "atypical_reason": c.get("_atypical_reason") or None,
        "appearance_tier": c.get("_appearance_tier"), "pending": bool(c.get("_pending")),
        "status": c.get("_status") or c.get("status_category") or "Closed", "forced": bool(c.get("_forced")),
        "latitude": _num(c.get("latitude")), "longitude": _num(c.get("longitude")),
        # Comp provenance: which pool the sale came from. MLS rows predate the
        # column (absent -> "mls"); the supplemental public-records pool stamps
        # source='supplemental' at build time. Additive JSON-only field — the
        # PDF/HTML render path (_comp_row) does not read it.
        "source": (c.get("source") or "mls"),
    }


def _record_basis_mid(record_subject: dict, *, n_comps: int, months_back: int,
                      comp_overrides=None, excluded_comps=None,
                      ai_hygiene: bool = False) -> Optional[int]:
    """Value at the UN-overridden (record) subject — the honest baseline the
    record->adjusted disclosure shows ALONGSIDE the agent-adjusted value, so the
    MAGNITUDE of an override ($540k -> $590k) is always visible, never hidden.
    Best-effort: returns None if the record subject yields no comps or anything
    fails (the disclosure simply omits the value line)."""
    try:
        comps = prepare_comps(
            record_subject, n_comps=n_comps, months_back=months_back,
            comp_overrides=comp_overrides, excluded_comps=excluded_comps,
            ai_hygiene=ai_hygiene,
        )
        if not comps:
            return None
        # Display value (feeds the disclosure line) — round like the report.
        return _round_to_5k(_estimate_value(record_subject, comps).mid)
    except Exception:
        return None


def build_preview(*, address: Optional[str] = None,
                  parcel_id: Optional[str] = None,
                  comp_overrides: Optional[Iterable[str]] = None,
                  excluded_comps: Optional[Iterable[str]] = None,
                  n_comps: int = 6,
                  months_back: int = 24,
                  ai_hygiene: bool = True,
                  subject_sqft: Optional[int] = None,
                  subject_overrides: Optional[dict] = None,
                  report_config: Optional[dict] = None) -> dict:
    """Compute the comp set + valuation for the interactive studio WITHOUT
    rendering a PDF — through the EXACT same ``prepare_comps`` + ``_estimate_value``
    pipeline ``build_cma`` uses, so the on-screen estimate equals the generated
    CMA's value (preview == PDF).

    This replaces the legacy preview path that valued raw ``pick_comps`` output
    (no hygiene, AVM off), which structurally diverged from the downloaded report.
    ``ai_hygiene`` defaults True to MATCH ``build_cma``'s default — it manages
    ``CMA_SKIP_AVM`` exactly like ``build_profile`` so the AVM + Haiku hygiene pass
    run identically. Returns a JSON-safe dict {ok, subject, comps[], valuation,
    elapsed_seconds}.
    """
    if not address and not parcel_id:
        return {"ok": False, "error": "Provide either address or parcel_id."}
    t0 = time.perf_counter()

    subject = _resolve_subject(address=address, parcel_id=parcel_id)
    if not subject:
        return {"ok": False, "error": "Could not locate subject in MLS or parcel data."}
    for key in ("sqft", "acres", "list_price", "original_list_price", "sold_price",
                "bedrooms", "full_baths", "half_baths", "year_built", "feed_dom",
                "latitude", "longitude"):
        v = _num(subject.get(key))
        if v is not None:
            subject[key] = v
    if subject_sqft:
        subject["sqft"] = int(subject_sqft)

    # Agent subject-fact overrides — applied at the SAME post-coercion /
    # post-subject_sqft / pre-comps point as build_cma so the studio's live
    # estimate reflects the edits (preview == PDF). report_config is accepted for
    # signature parity (preview renders no HTML) but only affects the generated
    # report, so it is intentionally unused here. No-op when overrides is None.
    _record_subject = dict(subject) if subject_overrides else None
    subject = _apply_subject_overrides(subject, subject_overrides)

    # AVM ON ALWAYS — match the generated PDF, whose worker pops CMA_SKIP_AVM
    # unconditionally — so the on-screen estimate equals the download (preview ==
    # PDF). ``ai_hygiene`` gates ONLY the LLM comp-hygiene pass (in prepare_comps),
    # never the AVM; the public surface runs AVM-on + hygiene-off for exact parity
    # with zero LLM spend. Restore env after so no process state leaks.
    _prev_skip_avm = os.environ.get("CMA_SKIP_AVM")
    os.environ.pop("CMA_SKIP_AVM", None)
    record_mid = None
    try:
        comps = prepare_comps(
            subject, n_comps=n_comps, months_back=months_back,
            comp_overrides=comp_overrides, excluded_comps=excluded_comps,
            ai_hygiene=ai_hygiene,
        )
        if not comps:
            return {"ok": False, "error": "Comp pool was empty after filtering — try widening months_back."}
        valuation = _estimate_value(subject, comps)
        # Blind-Haiku ensemble fold (CMA_BLIND_ENSEMBLE=1 only; unset = the
        # valuation above is untouched). Tuned recomputes (pins/exclusions)
        # reuse the subject's cached anchor — no new LLM call — so the studio
        # stays fast and tuned/untuned fold the SAME anchor.
        _ai_blind, _ai_ens = None, False
        if _blind_ensemble_enabled():
            _untuned = not (comp_overrides or excluded_comps)
            valuation, _ai_blind, _ai_ens = _apply_blind_ensemble(
                subject, comps, valuation, untuned=_untuned,
                fetch_untuned=lambda: prepare_comps(
                    subject, n_comps=n_comps, months_back=months_back,
                    ai_hygiene=ai_hygiene))
        # Record-basis value (un-overridden) for the on-screen disclosure — same
        # AVM-on posture as the adjusted estimate. Best-effort; only when overridden.
        if subject.get("_overridden") and _record_subject is not None:
            record_mid = _record_basis_mid(
                _record_subject, n_comps=n_comps, months_back=months_back,
                comp_overrides=comp_overrides, excluded_comps=excluded_comps, ai_hygiene=ai_hygiene)
    finally:
        if _prev_skip_avm is None:
            os.environ.pop("CMA_SKIP_AVM", None)
        else:
            os.environ["CMA_SKIP_AVM"] = _prev_skip_avm

    elapsed = time.perf_counter() - t0
    out = {
        "ok": True,
        "subject": {
            "address": subject.get("address"), "city": subject.get("city"),
            "county": subject.get("county"), "subdivision": subject.get("subdivision"),
            "parcel_id": subject.get("parcel_id"), "status": subject.get("status_category"),
            "list_price": subject.get("list_price"), "sqft": subject.get("sqft"),
            "acres": subject.get("acres"), "year_built": subject.get("year_built"),
            "bedrooms": subject.get("bedrooms"), "full_baths": subject.get("full_baths"),
            "half_baths": subject.get("half_baths"), "assessed_total": subject.get("assessed_total"),
            "feed_dom": subject.get("feed_dom"),
            "_overridden": bool(subject.get("_overridden")),
            "_override_diff": subject.get("_override_diff") or None,
            "_record_mid": record_mid,
            "_adjusted_mid": _round_to_5k(valuation.mid),
        },
        "comps": [_preview_comp_dict(c) for c in comps],
        # Presentation boundary: the studio displays these — $5k-rounded to
        # match the generated report (preview == PDF, byte-identical numbers).
        "valuation": {
            "low": _round_to_5k(valuation.low), "mid": _round_to_5k(valuation.mid),
            "high": _round_to_5k(valuation.high),
            "ppsf": valuation.ppsf, "divergence_pct": valuation.divergence_pct,
            "methods": [{"name": m.name, "value": m.value, "low": m.low,
                         "high": m.high, "rationale": m.rationale} for m in valuation.methods],
        },
        "elapsed_seconds": elapsed,
    }
    # Blind-ensemble wire surface — additive fields appended AFTER the stable
    # shape above so the unset path stays byte-identical (no key reordering).
    # ai_blind is int|null (null = blind read unavailable, engine-only fold);
    # ai_ensemble says whether the mid actually folds the anchor. The methods
    # list already carries the "AI comparable read" row when applied.
    if _blind_ensemble_enabled():
        out["valuation"]["ai_blind"] = _ai_blind
        out["valuation"]["ai_ensemble"] = _ai_ens
        # Engine-computed measured tier — the app treats this as authoritative
        # over its client-side fallback (confidence.ts). Computed server-side
        # from engine-owned inputs only; no request field can force it.
        out["valuation"]["confidence_tier"] = confidence_tier(
            comps, valuation, _ai_blind, _ai_ens)
    # Comp-workshop similarity surface — additive fields appended AFTER the
    # stable shape above so the unset path stays byte-identical (no key
    # reordering). similarity_surface is pure display over the _score /
    # _score_breakdown annotations pick_comps stamped; it never re-scores.
    if _score_surface_enabled():
        sims: list[int] = []
        for c, d in zip(comps, out["comps"]):
            surface = similarity_surface(subject, c)
            if surface:
                d.update(surface)
                if surface.get("similarity") is not None:
                    sims.append(surface["similarity"])
        out["subject"]["similarity_summary"] = _similarity_summary(sims)
    return _preview_clean(out)


def build_cma(*, address: Optional[str] = None,
              parcel_id: Optional[str] = None,
              brand_name: str = "ratifyly",
              agent_name: Optional[str] = None,
              comp_overrides: Optional[Iterable[str]] = None,
              excluded_comps: Optional[Iterable[str]] = None,
              n_comps: int = 6,
              months_back: int = 24,
              out_dir: Optional[Path] = None,
              allow_multi_page: bool = False,
              ai_hygiene: bool = True,   # default ON; degrades to deterministic w/o ANTHROPIC_API_KEY
              subject_sqft: Optional[int] = None,
              recommended_price: Optional[int] = None,
              brand_profile: Optional[dict] = None,
              subject_overrides: Optional[dict] = None,
              report_config: Optional[dict] = None) -> CmaResult:
    """Build a one-page branded CMA HTML + PDF for the given subject.

    When ``ai_hygiene`` is True and an ``ANTHROPIC_API_KEY`` is configured,
    the shortlisted comps' MLS remarks are reviewed (Layer 1) to drop
    non-arms-length / wrong-property-type comps and condition-adjust the rest.
    Degrades silently to the deterministic comp set when the key is absent.

    ``brand_profile`` (optional) is a saved tenant BrandProfile dict (see
    :meth:`mls_bot.brand.Brand.from_profile` for accepted keys). When it's a
    non-empty dict, the report is rendered with the tenant's OWN brand instead
    of a disk YAML brand. Resolution is wrapped in try/except: ANY failure (bad
    palette, malformed dict, etc.) falls back to the ``brand_name`` YAML path,
    so existing behavior can never regress. When ``brand_profile`` is None or
    empty, behavior is exactly as before.

    Raises ``ValueError`` if the subject cannot be located.
    """
    if not address and not parcel_id:
        raise ValueError("Provide either address or parcel_id.")
    t0 = time.perf_counter()

    brand = None
    if brand_profile:
        # Tenant's own saved brand. Never let a bad profile break generation —
        # fall back to the YAML-brand path on ANY error.
        try:
            brand = Brand.from_profile(brand_profile)
        except Exception:
            brand = None
    if brand is None:
        brand = Brand.load(brand_name)
    agent = brand.agent
    if agent_name:
        agent = AgentIdentity(
            name=agent_name,
            license=agent.license,
            brokerage=agent.brokerage,
            jurisdiction=agent.jurisdiction,
        )

    subject = _resolve_subject(address=address, parcel_id=parcel_id)
    if not subject:
        raise ValueError(
            f"Could not locate subject (address={address!r}, parcel_id={parcel_id!r})."
        )
    # The DuckDB-over-JSONL driver returns most numeric columns as strings.
    # Coerce the ones we use downstream so f-strings + math don't blow up.
    for key in ("sqft", "acres", "list_price", "original_list_price", "sold_price",
                "bedrooms", "full_baths", "half_baths", "year_built", "feed_dom",
                "latitude", "longitude"):
        v = _num(subject.get(key))
        if v is not None:
            subject[key] = v

    # Operator override: correct the subject's finished sqft — e.g. to include a
    # finished basement the assessor/MLS recorded as above-grade-only. Comps keep
    # their reported sqft (the feed carries no basement breakdown), so the
    # closed-comp clamp (not the $/sqft extrapolation) remains the value anchor.
    if subject_sqft:
        subject["sqft"] = int(subject_sqft)

    # Agent subject-fact overrides — applied AFTER coercion + the legacy
    # subject_sqft hook (so the richer dict wins) and BEFORE prepare_comps /
    # _estimate_value, so both the AI hygiene pass and the deterministic
    # valuation/AVM see the edited values. No-op when subject_overrides is None.
    # Snapshot the record (pre-override) subject so the disclosure can show the
    # honest record-basis value alongside the agent-adjusted one.
    _record_subject = dict(subject) if subject_overrides else None
    subject = _apply_subject_overrides(subject, subject_overrides)

    # Pick + (optionally) AI-hygiene-clean the comps via the shared helper, so the
    # interactive profile estimate and this generated value triangulate identically.
    comps = prepare_comps(
        subject, n_comps=n_comps, months_back=months_back,
        comp_overrides=comp_overrides, excluded_comps=excluded_comps,
        ai_hygiene=ai_hygiene,
    )
    if not comps:
        raise ValueError("Comp pool was empty after filtering — try widening months_back.")

    valuation = _estimate_value(subject, comps)
    # Blind-Haiku ensemble fold (CMA_BLIND_ENSEMBLE=1 only) — same anchor +
    # same 50/50 fold as /profile and /preview, applied BEFORE the display
    # rounding below, so the generated PDF equals the on-screen number. The
    # "AI comparable read" methods row renders in the report's methods panel.
    _ai_blind, _ai_ens = None, False
    _conf = None
    if _blind_ensemble_enabled():
        _untuned = not (comp_overrides or excluded_comps)
        valuation, _ai_blind, _ai_ens = _apply_blind_ensemble(
            subject, comps, valuation, untuned=_untuned,
            fetch_untuned=lambda: prepare_comps(
                subject, n_comps=n_comps, months_back=months_back,
                ai_hygiene=ai_hygiene))
        # Measured confidence tier — engine-owned inputs only (comps' stamped
        # distances, the unrounded valuation, the engine's own blind anchor);
        # drives the report's hero treatment + the wire field. Flag-off callers
        # keep _conf=None → the legacy hero, byte-identical.
        _conf = confidence_signals(comps, valuation, _ai_blind, _ai_ens)
    # Presentation boundary: CmaResult + the record→adjusted disclosure carry
    # the $5k-rounded display values (matching the rendered report).
    low, mid, high = (_round_to_5k(valuation.low), _round_to_5k(valuation.mid),
                      _round_to_5k(valuation.high))
    # Record-basis value for the non-suppressible disclosure (shows the override's
    # magnitude). Best-effort; only when an override actually changed a fact.
    if subject.get("_overridden") and _record_subject is not None:
        subject["_record_mid"] = _record_basis_mid(
            _record_subject, n_comps=n_comps, months_back=months_back,
            comp_overrides=comp_overrides, excluded_comps=excluded_comps, ai_hygiene=ai_hygiene)
        subject["_adjusted_mid"] = mid

    # Comp-tuning counts for the non-suppressible "adjusted by agent" line
    # (rendered only under CMA_COMP_TUNING_DISCLOSURE=1 — compbird's env).
    _n_removed = len(set(excluded_comps or []))
    _n_added = len(set(comp_overrides or []))
    if _n_removed or _n_added:
        subject["_comp_tuning"] = {"removed": _n_removed, "added": _n_added}

    out_dir = Path(out_dir) if out_dir else _PROJECT_ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", (subject.get("address") or "subject").lower()).strip("_")
    # Tuned renders (overrides / report-config / comp pins / exclusions) make the
    # CONTENT subject-specific while the address slug is shared, so two different
    # tuned reports of the same address would otherwise collide on one file and
    # cross-serve a wrong-valued report. Append a short content hash of the tuning
    # so each distinct tuned report gets its own file; an UN-tuned render keeps the
    # bare slug (byte-identical filename to before — back-compat preserved).
    _tuning = [subject_overrides, report_config,
               sorted(comp_overrides or []), sorted(excluded_comps or [])]
    if any(_tuning):
        import hashlib
        import json as _json
        _tag = hashlib.sha1(
            _json.dumps(_tuning, sort_keys=True, default=str).encode()
        ).hexdigest()[:10]
        slug = f"{slug}_{_tag}"
    html_path = out_dir / f"cma_{brand.name}_{slug}.html"
    pdf_path = out_dir / f"CMA_{brand.name}_{slug}.pdf"

    html = _build_html(brand, agent, subject, comps, valuation,
                       recommended_price=recommended_price, report_config=report_config,
                       measured_confidence=_conf)
    html_path.write_text(html, encoding="utf-8")
    pages = _render_pdf(html_path, pdf_path)

    attempts = 0
    if pages > 1 and not allow_multi_page:
        # Auto-fit loop: progressively tighter overlays, last resort drops a row.
        # Measured-confidence renders (flag-on) get one extra rung — see
        # _TIGHTEN_CSS_OVERLAYS_CONF; flag-off keeps the exact legacy ladder.
        for overlay in (_TIGHTEN_CSS_OVERLAYS_CONF if _conf is not None
                        else _TIGHTEN_CSS_OVERLAYS):
            attempts += 1
            html = _inject_tighten(html, overlay)
            html_path.write_text(html, encoding="utf-8")
            pages = _render_pdf(html_path, pdf_path)
            if pages == 1:
                break
        if pages > 1:
            attempts += 1
            html = _drop_one_comp_row(html)
            html_path.write_text(html, encoding="utf-8")
            pages = _render_pdf(html_path, pdf_path)

    elapsed = time.perf_counter() - t0
    return CmaResult(
        html_path=html_path,
        pdf_path=pdf_path,
        pages=pages,
        subject_address=str(subject.get("address") or ""),
        estimated_value=mid,
        value_low=low,
        value_high=high,
        comp_count=len(comps),
        elapsed_seconds=elapsed,
        autofit_attempts=attempts,
        ai_blind=_ai_blind,
        ai_ensemble=_ai_ens,
        confidence_tier=(_conf["tier"] if _conf else None),
    )


__all__ = ["build_cma", "CmaResult"]
