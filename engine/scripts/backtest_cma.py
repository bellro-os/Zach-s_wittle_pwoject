"""Temporal leave-one-out backtest of the production CMA valuation path.

This script measures how accurate the *shipped* CMA estimator is by replaying
recent closed sales as if each were an off-market subject being valued on its
own list date, then comparing the predicted mid to the real sold price.

It does NOT reimplement any valuation logic. It imports and calls the exact
production functions:

    mls_bot.analytics.cma_compset.pick_comps      # comp pool + scoring
    build_cma._estimate_value                      # triangulated valuation
    build_cma._num                                 # numeric coercion (same as web)

so every number it reports describes the product that ships. The web-cma Next
app drives the same path via ``spawn("python", ["-X","utf8", ...])`` with
``cwd = PROJECT_ROOT`` and ``sys.path`` seeded with ``ROOT/scripts`` then
``ROOT/src`` (see web-cma/app/api/cma/preview/route.ts). This script replicates
that import + path setup exactly (see ``_bootstrap_path`` below) so it loads the
identical modules.

-----------------------------------------------------------------------------
LEAKAGE CONTROLS (the whole point — these are applied per subject, in memory,
without touching any production file)
-----------------------------------------------------------------------------
The production code anchors all of its recency / trend / appreciation math to
``date.today()`` and pulls comps from the *full* ``data/mls_lookup.parquet``.
Left alone, valuing a 2025 sale "today" (2026) would let the estimator (a) see
sales that closed AFTER the subject listed, and (b) anchor its appreciation
trend and recency half-life to the future. Both are look-ahead leakage.

We close every seam by monkeypatching, per subject, the two time anchors and
the comp data source that production reads from — never by editing production:

  1. SELF + FUTURE EXCLUSION (comp pool).
     We patch ``cma_compset._fast_listings_connection`` to return an in-memory
     DuckDB connection whose ``listings`` view is the parquet filtered to
     ``COALESCE(close_date, status_changed_at) < as_of`` AND
     ``parcel_id != subject``. No row that closed on/after the as-of date, and
     no row for the subject's own parcel, can ever enter the candidate pool —
     this is enforced at the SQL source, upstream of every cohort query.
     ``pick_comps`` additionally drops the subject parcel itself (belt and
     suspenders). We assert post-hoc that zero returned comps violate either
     rule and skip any subject that somehow does.

  2. RECENCY / MONTHS_BACK / APPRECIATION ANCHOR = AS-OF, not today.
     ``cma_compset`` imports ``from datetime import date`` and calls
     ``date.today()`` in ``_recency_weight`` (comp recency half-life) and in
     ``_pull_candidates`` (the ``months_back`` cutoff and the subdivision
     cutoff). We replace ``cma_compset.date`` with a ``date`` subclass whose
     ``.today()`` returns the as-of date, so recency decay and the lookback
     window are measured from when the subject listed — not from now.
     ``build_cma`` routes ALL of its valuation-side time math through
     ``build_cma._today_date()`` (``_months_since`` -> appreciation-rate
     estimate, $/sqft time-trending, prior-sale trend + weight). We patch
     ``build_cma._today_date`` to return the as-of date, anchoring the trend
     to the past. Result: the appreciation rate is estimated only from sales
     that had already closed, and trended forward only to the as-of date.

  3. NO TARGET LEAKAGE (subject record).
     The subject dict we hand to ``pick_comps`` / ``_estimate_value`` is built
     from the sale's PHYSICAL attributes only — sqft, acres, beds, baths,
     year_built, class, city/county/subdivision/high_school, lat/lng,
     parcel_id. We deliberately set ``list_price``, ``original_list_price``,
     ``sold_price`` (and every price-derived field) to ``None`` so the
     estimator gets exactly what an off-market subject would expose. (Note:
     ``pick_comps`` uses ``list_price`` only as a soft price-band filter on
     candidates; with it None the pool is selected purely on physical
     similarity + distance + recency, which is the off-market case we ship.)

  4. PRIOR-SALE ANCHOR (subject's own MLS history).
     ``build_cma._mls_confirmed_prior_sale`` reads
     ``_PROJECT_ROOT/data/mls_lookup.parquet`` directly to find the subject
     parcel's prior closed sale. Against the full parquet that could surface a
     FUTURE sale of the same parcel. We write a one-time as-of-agnostic... —
     actually we re-point ``build_cma._PROJECT_ROOT`` at a temp dir whose
     ``data/mls_lookup.parquet`` is the parquet filtered to
     ``close_date < as_of`` (rebuilt per as-of via a tiny COPY). That keeps the
     prior-sale anchor honest (a genuine pre-list resale of the subject is fair
     game; a post-list one is not). ``_PROJECT_ROOT`` is used by production
     ONLY for this parquet path, so the re-point has no other effect.

After scoring we restore every patched symbol.

-----------------------------------------------------------------------------
OUTPUT
-----------------------------------------------------------------------------
Per-error metrics: median |APE|, MAPE, MAE, PPE10 / PPE20 (share of subjects
whose predicted mid is within +/-10% / +/-20% of the actual sold price), and
interval coverage (how often the actual sold price falls inside the predicted
[low, high] band). Segmented by property class, price band, acreage tier,
county, and join-success (subject had usable lat/lng vs not). Prints a readable
summary to stdout and writes JSON + a Markdown report under
``outputs/cma_backtest/``.

CLI:
    python -X utf8 scripts/backtest_cma.py --limit 25
    python -X utf8 scripts/backtest_cma.py --months 18 --class RE_1
    python -X utf8 scripts/backtest_cma.py --out outputs/cma_backtest
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Path bootstrap — replicate exactly what web-cma's runPython does:
#   cwd = PROJECT_ROOT;  sys.path = [ROOT/scripts, ROOT/src, ...]
# (see web-cma/app/api/cma/preview/route.ts and generate/route.ts)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bootstrap_path() -> None:
    """Seed sys.path like the web app's spawned python and chdir to root.

    web-cma spawns ``python -X utf8 -c <runner>`` with ``cwd = PROJECT_ROOT``
    and prepends ``ROOT/scripts`` then ``ROOT/src`` to sys.path. The CMA code
    reads its data via *relative* paths (``data/mls_lookup.parquet``,
    ``data/mls/*.jsonl``), so the cwd must be the project root."""
    import os

    scripts_dir = str(_PROJECT_ROOT / "scripts")
    src_dir = str(_PROJECT_ROOT / "src")
    # Match the web app's insertion order: scripts first, then src.
    if src_dir in sys.path:
        sys.path.remove(src_dir)
    sys.path.insert(0, src_dir)
    if scripts_dir in sys.path:
        sys.path.remove(scripts_dir)
    sys.path.insert(0, scripts_dir)
    os.chdir(_PROJECT_ROOT)


_bootstrap_path()

import duckdb  # noqa: E402

# The exact production modules + entry points (no reimplementation).
import build_cma as _bc  # noqa: E402  (scripts/build_cma.py)
import mls_bot.analytics.cma_compset as _cc  # noqa: E402
import mls_bot.analytics.dom_model as _dm  # noqa: E402  (AVM feature-row builder)
from build_cma import _estimate_value, _num, prepare_comps  # noqa: E402
from mls_bot.analytics.cma_compset import pick_comps  # noqa: E402

# When CMA_BACKTEST_HYGIENE=1, route comp selection through the production
# AI-hygiene wrapper (prepare_comps with ai_hygiene=True) instead of the raw
# deterministic pick_comps. This is the ONLY way the comp-hygiene LLM (and thus
# the CMA_HYGIENE_MODEL override) affects backtest accuracy. Default = off, so
# the baseline numbers are identical to the unmodified harness.
import os as _os  # noqa: E402
_USE_HYGIENE = _os.environ.get("CMA_BACKTEST_HYGIENE", "").strip() in ("1", "true", "True")


_MLS_PARQUET = _PROJECT_ROOT / "data" / "mls_lookup.parquet"

# Implied DOM beyond this many days means list_date is almost certainly a stale
# relist of the same MLS record, not a realistic listing horizon — clamp the as-of.
_RELIST_CAP_DAYS = 365

# Parcel ids that are placeholders aggregating unrelated properties; unusable for
# self-exclusion or prior-sale anchoring.
_PLACEHOLDER_PARCELS = {"", "0", "00", "000", "0000", "N/A", "NONE", "NULL"}


# ---------------------------------------------------------------------------
# Frozen-date machinery for the time-anchor leakage controls
# ---------------------------------------------------------------------------

def _make_frozen_date(asof: date) -> type:
    """Return a ``datetime.date`` subclass whose ``.today()`` is ``asof``.

    Patched over ``cma_compset.date`` so that production's ``date.today()``
    calls in ``_recency_weight`` and ``_pull_candidates`` see the as-of date.
    Subtraction etc. still produce plain ``date`` results, so downstream math
    is unaffected.
    """

    class _Frozen(date):
        @classmethod
        def today(cls):  # type: ignore[override]
            return asof

    return _Frozen


# ---------------------------------------------------------------------------
# As-of comp-pool connection (leakage control #1)
# ---------------------------------------------------------------------------

def _make_asof_listings_conn(asof: date, subject_parcel: str):
    """Build a factory for ``_fast_listings_connection`` patched per subject.

    The returned callable yields an in-memory DuckDB connection whose
    ``listings`` view is ``mls_lookup.parquet`` filtered to:
      * effective close/status-change date strictly before ``asof``, and
      * parcel_id different from the subject's parcel_id.

    Production's ``_fast_listings_connection`` derives an ``appearance`` column
    in its heavy fallback; the slim parquet already carries ``appearance``, and
    every column ``_CANDIDATE_COLUMNS`` selects exists in the parquet, so a
    straight ``SELECT *`` view matches the production contract.
    """
    if isinstance(asof, datetime):
        asof = asof.date()
    pid = (subject_parcel or "").replace("'", "''").strip()
    asof_s = asof.isoformat()
    # Match parcels case-insensitively and trimmed, mirroring pick_comps's own
    # self-exclusion (uppercased, stripped). Compare on the raw + uppercased
    # forms so multi-parcel ids ("a,b") that equal the subject are also dropped.
    pid_clause = (
        f"AND UPPER(TRIM(COALESCE(CAST(parcel_id AS VARCHAR),''))) "
        f"<> UPPER(TRIM('{pid}'))"
        if pid
        else ""
    )

    def _factory():
        con = duckdb.connect(":memory:")
        con.execute(
            f"""
            CREATE VIEW listings AS
            SELECT * FROM read_parquet('{_MLS_PARQUET.as_posix()}')
            WHERE COALESCE(
                    TRY_CAST(close_date AS DATE),
                    TRY_CAST(status_changed_at AS DATE)
                  ) < DATE '{asof_s}'
            {pid_clause}
            """
        )
        return con

    return _factory


# ---------------------------------------------------------------------------
# As-of prior-sale parquet (leakage control #4)
# ---------------------------------------------------------------------------

class _AsOfPriorSaleRoot:
    """Context manager that re-points ``build_cma._PROJECT_ROOT`` at a temp
    dir whose ``data/mls_lookup.parquet`` is filtered to ``close_date < asof``.

    ``build_cma._mls_confirmed_prior_sale`` is the only production consumer of
    ``_PROJECT_ROOT`` (it builds ``_PROJECT_ROOT/data/mls_lookup.parquet``).
    Filtering that parquet to pre-as-of closes keeps the subject's prior-sale
    anchor from ever seeing a future resale of the same parcel.

    We rebuild the filtered parquet once per distinct as-of date and cache it,
    because many subjects can share an as-of month.
    """

    _cache: dict[str, Path] = {}
    _tmp_root: Optional[Path] = None

    def __init__(self, asof: date):
        self.asof = asof.date() if isinstance(asof, datetime) else asof
        self._orig_root = _bc._PROJECT_ROOT

    @classmethod
    def _ensure_tmp_root(cls) -> Path:
        if cls._tmp_root is None:
            import tempfile

            cls._tmp_root = Path(tempfile.mkdtemp(prefix="cma_backtest_priorsale_"))
        return cls._tmp_root

    def _filtered_parquet_for(self, asof_s: str) -> Path:
        if asof_s in self._cache:
            return self._cache[asof_s]
        root = self._ensure_tmp_root()
        sub = root / asof_s
        (sub / "data").mkdir(parents=True, exist_ok=True)
        out = sub / "data" / "mls_lookup.parquet"
        con = duckdb.connect(":memory:")
        con.execute(
            f"""
            COPY (
                SELECT * FROM read_parquet('{_MLS_PARQUET.as_posix()}')
                WHERE TRY_CAST(close_date AS DATE) < DATE '{asof_s}'
            ) TO '{out.as_posix()}' (FORMAT PARQUET)
            """
        )
        con.close()
        self._cache[asof_s] = sub
        return sub

    def __enter__(self):
        sub_root = self._filtered_parquet_for(self.asof.isoformat())
        _bc._PROJECT_ROOT = sub_root
        return self

    def __exit__(self, *exc):
        _bc._PROJECT_ROOT = self._orig_root
        return False


# ---------------------------------------------------------------------------
# Subject construction (leakage control #3 — physical attrs only)
# ---------------------------------------------------------------------------

def _as_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_subject(row: dict[str, Any]) -> dict[str, Any]:
    """Make an off-market-shaped subject from a closed-sale row.

    PRICE-DERIVED FIELDS ARE DELIBERATELY OMITTED (set None): list_price,
    original_list_price, sold_price, assessed_total, deed_last_sale_*. Only
    physical / location attributes are passed through — exactly what an
    off-market subject exposes. The numeric coercion mirrors the web preview
    runner so the records are byte-identical in shape to production.
    """
    subj: dict[str, Any] = {
        "address": row.get("address"),
        "city": row.get("city"),
        "county": row.get("county"),
        "subdivision": row.get("subdivision"),
        "high_school": row.get("high_school"),
        "parcel_id": str(row.get("parcel_id") or ""),
        "_class": row.get("_class") or "RE_1",
        "status_category": "Off-Market",
        "sqft": row.get("sqft"),
        "acres": row.get("acres"),
        "year_built": row.get("year_built"),
        "bedrooms": row.get("bedrooms"),
        "full_baths": row.get("full_baths"),
        "half_baths": row.get("half_baths"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        # Price-derived fields are intentionally withheld (target leakage).
        "list_price": None,
        "original_list_price": None,
        "sold_price": None,
        "feed_dom": None,
        "list_date": None,
    }
    # Same coercion the web preview/generate runners apply to subjects.
    for key in (
        "sqft", "acres", "bedrooms", "full_baths", "half_baths",
        "year_built", "latitude", "longitude",
    ):
        v = _num(subj.get(key))
        if v is not None:
            subj[key] = v
    return subj


# ---------------------------------------------------------------------------
# Per-subject backtest (drives the REAL pick_comps + _estimate_value as-of)
# ---------------------------------------------------------------------------

def _score_one(row: dict[str, Any], *, months_back: int, n_comps: int,
               typical_dom: int) -> dict[str, Any]:
    """Estimate one subject as-of its list date and compare to actual.

    Returns a result dict with prediction + error + segmentation keys, or a
    ``{"skipped": reason}`` dict if the subject can't be scored cleanly.
    """
    sold = _num(row.get("sold_price"))
    if not sold or sold <= 0:
        return {"skipped": "no_sold_price"}

    subject_pid = str(row.get("parcel_id") or "").strip()
    # Placeholder parcel ids ('', '0', '000', ...) aggregate multiple unrelated
    # properties — keying self-exclusion / prior-sale on them mis-anchors the
    # estimate, so drop these subjects rather than score them dishonestly.
    if subject_pid.upper() in _PLACEHOLDER_PARCELS:
        return {"skipped": "placeholder_parcel"}

    close_d = _as_date(row.get("close_date"))
    list_d = _as_date(row.get("list_date"))
    used_relist_cap = False
    # As-of = list date when present; else close date minus a typical DOM.
    if list_d is not None:
        asof = list_d
    elif close_d is not None:
        asof = close_d - timedelta(days=typical_dom)
    else:
        return {"skipped": "no_asof_date"}
    # Stale-relist guard: a list_date implying an absurd DOM (e.g. a multi-year
    # relist of the same MLS record) yields an unrealistically early as-of that
    # starves the comp pool and over-extends the trend. Clamp to a realistic
    # listing horizon (close - typical DOM) instead.
    if close_d is not None and list_d is not None and (close_d - list_d).days > _RELIST_CAP_DAYS:
        asof = close_d - timedelta(days=typical_dom)
        used_relist_cap = True
    # Guard: as-of must precede the close (a sane listing timeline).
    if close_d is not None and asof >= close_d:
        asof = close_d - timedelta(days=max(1, typical_dom))

    subj = _build_subject(row)
    has_geo = subj.get("latitude") is not None and subj.get("longitude") is not None

    # ---- install leakage controls (patch production symbols) ----
    frozen = _make_frozen_date(asof)
    orig_cc_date = _cc.date
    orig_today = _bc._today_date
    orig_conn = _cc._fast_listings_connection
    orig_dm_date = _dm.date

    _cc.date = frozen                      # control #2a: comp recency + cutoff
    _bc._today_date = lambda: asof         # control #2b: valuation trend anchor
    _cc._fast_listings_connection = _make_asof_listings_conn(asof, subject_pid)  # #1
    # control #2c: the AVM's feature-row builder (dom_model._row_for_subject)
    # derives age_at_list / list_month from date.today(); anchor those to the
    # as-of date too so the AVM ensemble member sees no look-ahead seasonality.
    _dm.date = frozen

    try:
        with _AsOfPriorSaleRoot(asof):     # control #4: prior-sale anchor
            if _USE_HYGIENE:
                # Production AI-hygiene path: pick_comps + LLM review + trim.
                comps = prepare_comps(subj, n_comps=n_comps,
                                      months_back=months_back, ai_hygiene=True)
            else:
                comps = pick_comps(subj, n=n_comps, months_back=months_back)
            if not comps:
                return {"skipped": "empty_comp_pool", "asof": asof.isoformat()}

            # Post-hoc leakage assertion: nothing future, nothing self. Mirror the
            # SQL source filter's effective date (close_date, else status_changed_at)
            # so the backstop is at least as strict as the filter it backstops.
            for c in comps:
                cd = _as_date(c.get("close_date")) or _as_date(c.get("status_changed_at"))
                cpid = str(c.get("parcel_id") or "").strip().upper()
                if cd is not None and cd >= asof:
                    return {"skipped": "leak_future_comp", "asof": asof.isoformat()}
                if subject_pid and cpid == subject_pid.upper():
                    return {"skipped": "leak_self_comp", "asof": asof.isoformat()}

            val = _estimate_value(subj, comps)
    finally:
        # ---- restore production symbols no matter what ----
        _cc.date = orig_cc_date
        _bc._today_date = orig_today
        _cc._fast_listings_connection = orig_conn
        _dm.date = orig_dm_date

    mid = _num(val.mid)
    low = _num(val.low)
    high = _num(val.high)
    if not mid or mid <= 0:
        return {"skipped": "zero_estimate", "asof": asof.isoformat(),
                "comp_count": len(comps)}

    abs_err = abs(mid - sold)
    ape = abs_err / sold  # absolute percentage error (fraction)
    covered = bool(low and high and low <= sold <= high)

    return {
        "skipped": None,
        "address": row.get("address"),
        "parcel_id": subject_pid,
        "county": str(row.get("county") or "") or "(unknown)",
        "_class": str(row.get("_class") or "") or "(unknown)",
        "asof": asof.isoformat(),
        "close_date": close_d.isoformat() if close_d else None,
        "sold_price": sold,
        "predicted_mid": mid,
        "predicted_low": low,
        "predicted_high": high,
        "abs_error": abs_err,
        "ape": ape,
        "signed_error_pct": (mid - sold) / sold,
        "covered": covered,
        "comp_count": len(comps),
        "has_geo": has_geo,
        "acres": _num(row.get("acres")),
        "sqft": _num(row.get("sqft")),
        "used_dom_fallback": list_d is None,
        "used_relist_cap": used_relist_cap,
    }


# ---------------------------------------------------------------------------
# Subject selection
# ---------------------------------------------------------------------------

# MLS classes whose "Closed" means a lease executed (sold_price = monthly rent),
# not an arms-length sale. Excluded from ground-truth selection by default so
# rents can never contaminate the sale-accuracy metrics.
_RENTAL_CLASSES = ("RN_6",)


def _pick_test_sales(months: int, limit: Optional[int],
                     class_filter: Optional[str], asof_run: date,
                     min_price: float, min_ppsf: float = 0.0,
                     min_sqft: float = 0.0, min_acres: float = 0.0) -> list[dict[str, Any]]:
    """Pull the closed sales to backtest, most-recent first.

    Ground truth = Closed listings with an arms-length sold_price (>= min_price),
    a close date, and (preferably) a list date, that closed within the lookback
    window ending at ``asof_run`` (pinned for reproducibility). Rental/lease
    classes are excluded unless explicitly requested via ``--class`` so monthly
    rents don't pollute the sale-accuracy metrics.
    """
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW l AS SELECT * FROM read_parquet('{_MLS_PARQUET.as_posix()}')"
    )
    cutoff = (asof_run - timedelta(days=int(months * 30.4))).isoformat()
    where = [
        "status_category = 'Closed'",
        f"TRY_CAST(sold_price AS DOUBLE) >= {float(min_price)}",
        "close_date IS NOT NULL",
        f"close_date >= DATE '{cutoff}'",
        f"close_date < DATE '{asof_run.isoformat()}'",
    ]
    if min_ppsf and min_ppsf > 0:
        # Arms-length hygiene: drop non-market recordings (gift/quitclaim/distress)
        # and 0-sqft mislabeled lots. Multiply (not divide) to avoid div-by-zero.
        where.append("TRY_CAST(sqft AS DOUBLE) > 0")
        where.append(f"TRY_CAST(sold_price AS DOUBLE) >= {float(min_ppsf)} * TRY_CAST(sqft AS DOUBLE)")
    if min_sqft and min_sqft > 0:
        # Large-home focus: isolate the tier where the $/sqft size elasticity bites.
        where.append(f"TRY_CAST(sqft AS DOUBLE) >= {float(min_sqft)}")
    if min_acres and min_acres > 0:
        # High-acreage focus: isolate the tier where the land/acreage premium over-values.
        where.append(f"TRY_CAST(acres AS DOUBLE) >= {float(min_acres)}")
    if class_filter:
        where.append(f"_class = '{class_filter.replace(chr(39), chr(39) * 2)}'")
    else:
        # Exclude lease/rental classes from the default ground-truth pool.
        rentals = ", ".join(f"'{c}'" for c in _RENTAL_CLASSES)
        where.append(f"COALESCE(_class,'') NOT IN ({rentals})")
    sql = f"""
        SELECT listing_id, address, city, county, subdivision, high_school,
               CAST(parcel_id AS VARCHAR) AS parcel_id, _class,
               TRY_CAST(sold_price AS DOUBLE) AS sold_price,
               TRY_CAST(list_price AS DOUBLE) AS list_price,
               close_date, list_date, feed_dom,
               TRY_CAST(sqft AS INT) AS sqft,
               TRY_CAST(acres AS DOUBLE) AS acres,
               TRY_CAST(year_built AS INT) AS year_built,
               TRY_CAST(bedrooms AS DOUBLE) AS bedrooms,
               TRY_CAST(full_baths AS DOUBLE) AS full_baths,
               TRY_CAST(half_baths AS DOUBLE) AS half_baths,
               TRY_CAST(latitude AS DOUBLE) AS latitude,
               TRY_CAST(longitude AS DOUBLE) AS longitude
        FROM l
        WHERE {' AND '.join(where)}
        ORDER BY close_date DESC, listing_id
        {f'LIMIT {int(limit)}' if limit else ''}
    """
    rows = con.execute(sql).fetchdf().to_dict(orient="records")
    con.close()
    return rows


def _typical_dom() -> int:
    """Median closed-sale DOM, used as the as-of fallback when list_date is
    missing (as-of = close_date - typical DOM)."""
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW l AS SELECT * FROM read_parquet('{_MLS_PARQUET.as_posix()}')"
    )
    r = con.execute(
        "SELECT median(TRY_CAST(feed_dom AS DOUBLE)) FROM l "
        "WHERE status_category='Closed' AND TRY_CAST(sold_price AS DOUBLE)>0 "
        "AND TRY_CAST(feed_dom AS DOUBLE) > 0"
    ).fetchone()
    con.close()
    try:
        return max(1, int(round(float(r[0]))))
    except (TypeError, ValueError):
        return 30


# ---------------------------------------------------------------------------
# Metrics + segmentation
# ---------------------------------------------------------------------------

def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the headline accuracy metrics over a set of scored rows."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    apes = [r["ape"] for r in rows]
    abs_errs = [r["abs_error"] for r in rows]
    covered = sum(1 for r in rows if r["covered"])
    ppe10 = sum(1 for r in rows if r["ape"] <= 0.10)
    ppe20 = sum(1 for r in rows if r["ape"] <= 0.20)
    signed = [r["signed_error_pct"] for r in rows]
    return {
        "n": n,
        "median_ape_pct": round(median(apes) * 100, 2),
        "mape_pct": round(sum(apes) / n * 100, 2),
        "mae": round(sum(abs_errs) / n, 0),
        "median_abs_error": round(median(abs_errs), 0),
        "ppe10_pct": round(ppe10 / n * 100, 1),
        "ppe20_pct": round(ppe20 / n * 100, 1),
        "interval_coverage_pct": round(covered / n * 100, 1),
        "median_signed_error_pct": round(median(signed) * 100, 2),
        "mean_signed_error_pct": round(sum(signed) / n * 100, 2),
    }


def _price_band(sold: float) -> str:
    if sold < 150_000:
        return "<150k"
    if sold < 300_000:
        return "150-300k"
    if sold < 500_000:
        return "300-500k"
    if sold < 750_000:
        return "500-750k"
    if sold < 1_000_000:
        return "750k-1M"
    return "1M+"


def _acre_tier(acres: Optional[float]) -> str:
    if acres is None:
        return "(no acres)"
    if acres < 1:
        return "<1ac"
    if acres < 2:
        return "1-2ac"
    if acres < 6:
        return "2-6ac"
    if acres < 15:
        return "6-15ac"
    if acres < 40:
        return "15-40ac"
    return "40ac+"


def _sqft_tier(sqft: Optional[float]) -> str:
    """Finished-area buckets — surfaces the large-home over-valuation that the
    $/sqft size elasticity is meant to correct."""
    try:
        s = float(sqft)
    except (TypeError, ValueError):
        return "(no sqft)"
    if s <= 0:
        return "(no sqft)"
    if s < 1500:
        return "<1.5k"
    if s < 2500:
        return "1.5-2.5k"
    if s < 3500:
        return "2.5-3.5k"
    if s < 5000:
        return "3.5-5k"
    return "5k+"


def _segment(rows: list[dict[str, Any]], key_fn, label: str) -> dict[str, Any]:
    """Group scored rows by ``key_fn`` and compute metrics per group."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        k = key_fn(r)
        buckets.setdefault(k, []).append(r)
    out = {}
    for k in sorted(buckets):
        out[k] = _metrics(buckets[k])
    return out


def _build_segments(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "by_class": _segment(rows, lambda r: r["_class"], "class"),
        "by_price_band": _segment(rows, lambda r: _price_band(r["sold_price"]), "price"),
        "by_acre_tier": _segment(rows, lambda r: _acre_tier(r.get("acres")), "acreage"),
        "by_sqft_tier": _segment(rows, lambda r: _sqft_tier(r.get("sqft")), "sqft"),
        "by_county": _segment(rows, lambda r: r["county"], "county"),
        "by_join_success": _segment(
            rows, lambda r: "has_geo" if r["has_geo"] else "no_geo", "geo"
        ),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt_money(n) -> str:
    try:
        return f"${int(round(float(n))):,}"
    except (TypeError, ValueError):
        return "-"


def _print_summary(overall: dict[str, Any], segments: dict[str, Any],
                   meta: dict[str, Any], args) -> None:
    line = "=" * 72
    scored = meta["scored"]
    skipped = meta["skipped_breakdown"]
    print(line)
    print("CMA TEMPORAL LEAVE-ONE-OUT BACKTEST  (production path, as-of list date)")
    print(line)
    print(f"lookback months : {args.months}   class filter: {args.cls or 'ALL'}   "
          f"limit: {args.limit or 'none'}   as-of run: {meta['as_of_run']}")
    print(f"eligible subjects: {meta['eligible']}   scored: {scored}   "
          f"coverage: {meta['coverage_pct']}%  "
          f"(metrics below describe SCORED subjects only)")
    skipped_total = sum(skipped.values())
    print(f"subjects skipped: {skipped_total}")
    for reason, cnt in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"    - {reason:<22} {cnt}")
    print(line)
    if overall.get("n"):
        print("OVERALL ACCURACY")
        print(f"  median |APE|        : {overall['median_ape_pct']}%")
        print(f"  MAPE                : {overall['mape_pct']}%")
        print(f"  MAE                 : {_fmt_money(overall['mae'])}")
        print(f"  median abs error    : {_fmt_money(overall['median_abs_error'])}")
        print(f"  PPE10 (within +-10%): {overall['ppe10_pct']}%")
        print(f"  PPE20 (within +-20%): {overall['ppe20_pct']}%")
        print(f"  interval coverage   : {overall['interval_coverage_pct']}%")
        print(f"  median signed err   : {overall['median_signed_error_pct']}%  "
              f"(>0 = over-valuing)")
        print(f"  mean signed err     : {overall['mean_signed_error_pct']}%")
    else:
        print("No subjects scored — nothing to report.")
    print(line)

    def _seg_block(title: str, seg: dict[str, Any]) -> None:
        print(f"\n{title}")
        print(f"  {'segment':<14}{'n':>5}{'medAPE':>9}{'MAPE':>8}"
              f"{'PPE10':>8}{'PPE20':>8}{'cover':>8}")
        for k, m in seg.items():
            if not m.get("n"):
                continue
            print(f"  {k:<14}{m['n']:>5}{m['median_ape_pct']:>8}%{m['mape_pct']:>7}%"
                  f"{m['ppe10_pct']:>7}%{m['ppe20_pct']:>7}%{m['interval_coverage_pct']:>7}%")

    _seg_block("BY PROPERTY CLASS", segments["by_class"])
    _seg_block("BY PRICE BAND", segments["by_price_band"])
    _seg_block("BY ACREAGE TIER", segments["by_acre_tier"])
    _seg_block("BY SQFT TIER", segments["by_sqft_tier"])
    geo_seg = segments["by_join_success"]
    if set(k for k, m in geo_seg.items() if m.get("n")) <= {"has_geo"}:
        print("\nBY JOIN SUCCESS (geo): all scored subjects geocoded (no_geo n=0)")
    else:
        _seg_block("BY JOIN SUCCESS (geo)", geo_seg)
    _seg_block("BY COUNTY", segments["by_county"])
    # Survivorship: how many eligible subjects actually scored, by close quarter.
    cbq = meta.get("coverage_by_quarter") or {}
    if cbq:
        print("\nSCORED-RATE BY CLOSE QUARTER (survivorship check)")
        print(f"  {'quarter':<10}{'eligible':>10}{'scored':>8}{'rate':>8}")
        for q in sorted(cbq):
            b = cbq[q]
            print(f"  {q:<10}{b['eligible']:>10}{b['scored']:>8}{b['scored_pct']:>7}%")
    print(line)


def _write_reports(out_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"backtest_{stamp}.json"
    md_path = out_dir / f"backtest_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    # Also write/refresh a stable "latest" pair for convenience.
    (out_dir / "backtest_latest.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "backtest_latest.md").write_text(
        _render_markdown(payload), encoding="utf-8"
    )
    return json_path, md_path


def _md_metric_table(seg: dict[str, Any]) -> str:
    lines = [
        "| segment | n | median \\|APE\\| | MAPE | MAE | PPE10 | PPE20 | coverage |",
        "|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for k, m in seg.items():
        if not m.get("n"):
            continue
        lines.append(
            f"| {k} | {m['n']} | {m['median_ape_pct']}% | {m['mape_pct']}% | "
            f"{_fmt_money(m['mae'])} | {m['ppe10_pct']}% | {m['ppe20_pct']}% | "
            f"{m['interval_coverage_pct']}% |"
        )
    return "\n".join(lines)


def _render_markdown(p: dict[str, Any]) -> str:
    o = p["overall"]
    meta = p["meta"]
    seg = p["segments"]
    md: list[str] = []
    md.append("# CMA Temporal Leave-One-Out Backtest")
    md.append("")
    md.append(f"_Generated {meta['generated_at']}_")
    md.append("")
    md.append(
        "Each recent **Closed** sale is replayed as an off-market subject valued "
        "**as-of its list date** through the production CMA path "
        "(`pick_comps` + `_estimate_value`). Comps are restricted to sales that "
        "had already closed before the as-of date, the subject's own parcel is "
        "excluded, and the recency / appreciation anchors are frozen to the "
        "as-of date — so no number here peeks at the future."
    )
    md.append("")
    md.append("## Run configuration")
    md.append("")
    md.append(f"- Lookback window: **{meta['months']} months** of closes")
    md.append(f"- Class filter: **{meta['class_filter'] or 'ALL'}**")
    md.append(f"- Limit: **{meta['limit'] or 'none'}**")
    md.append(f"- Comps per subject (n): **{meta['n_comps']}**, "
              f"months_back: **{meta['months_back']}**")
    md.append(f"- Typical DOM fallback (when list_date missing): "
              f"**{meta['typical_dom']} days**")
    md.append(f"- As-of run (selection cutoff): **{meta.get('as_of_run', 'today')}**, "
              f"min sale price: **{_fmt_money(meta.get('min_price', 0))}**")
    md.append(f"- Eligible subjects: **{meta.get('eligible', meta['scored'])}**, "
              f"scored: **{meta['scored']}**, skipped: **{meta['skipped_total']}** "
              f"(coverage **{meta.get('coverage_pct', 0)}%** — metrics below describe "
              f"scored subjects only)")
    if meta.get("mls_parquet_mtime"):
        md.append(f"- Data: `mls_lookup.parquet` {meta.get('mls_parquet_rows')} rows, "
                  f"mtime {meta['mls_parquet_mtime']}")
    md.append("")
    if meta.get("skipped_breakdown"):
        md.append("### Skip reasons")
        md.append("")
        for reason, cnt in sorted(meta["skipped_breakdown"].items(), key=lambda kv: -kv[1]):
            md.append(f"- `{reason}`: {cnt}")
        md.append("")
    md.append("## Overall accuracy")
    md.append("")
    if o.get("n"):
        md.append("| metric | value |")
        md.append("|---|--:|")
        md.append(f"| subjects (n) | {o['n']} |")
        md.append(f"| median \\|APE\\| | {o['median_ape_pct']}% |")
        md.append(f"| MAPE | {o['mape_pct']}% |")
        md.append(f"| MAE | {_fmt_money(o['mae'])} |")
        md.append(f"| median abs error | {_fmt_money(o['median_abs_error'])} |")
        md.append(f"| PPE10 (within +-10%) | {o['ppe10_pct']}% |")
        md.append(f"| PPE20 (within +-20%) | {o['ppe20_pct']}% |")
        md.append(f"| interval coverage | {o['interval_coverage_pct']}% |")
        md.append(f"| median signed error | {o['median_signed_error_pct']}% |")
        md.append(f"| mean signed error | {o['mean_signed_error_pct']}% |")
    else:
        md.append("_No subjects scored._")
    md.append("")
    titles = {
        "by_class": "By property class",
        "by_price_band": "By price band",
        "by_acre_tier": "By acreage tier",
        "by_county": "By county",
        "by_join_success": "By join success (subject geocode)",
    }
    for skey, title in titles.items():
        md.append(f"## {title}")
        md.append("")
        md.append(_md_metric_table(seg[skey]))
        md.append("")
    md.append("## Leakage controls applied")
    md.append("")
    for c in p["meta"]["leakage_controls"]:
        md.append(f"- {c}")
    md.append("")
    return "\n".join(md)


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Temporal leave-one-out backtest of the production CMA path."
    )
    ap.add_argument("--limit", type=int, default=None,
                    help="Max number of recent closed sales to score.")
    ap.add_argument("--months", type=int, default=15,
                    help="Lookback window (months of closes) to draw subjects from. "
                         "Default 15.")
    ap.add_argument("--class", dest="cls", type=str, default=None,
                    help="Restrict to one MLS _class (e.g. RE_1, LD_3, CM_4).")
    ap.add_argument("--as-of-run", dest="as_of_run", type=str, default=None,
                    help="Pin the selection cutoff to this date (YYYY-MM-DD) for "
                         "reproducibility. Default: today.")
    ap.add_argument("--min-price", dest="min_price", type=float, default=20_000.0,
                    help="Minimum sold_price for a ground-truth subject (excludes "
                         "leases/micro / non-arms-length sales). Default 20000.")
    ap.add_argument("--min-ppsf", dest="min_ppsf", type=float, default=0.0,
                    help="Arms-length hygiene: require a subject's sold $/sqft >= this "
                         "(and sqft>0), excluding gift/quitclaim/distress recordings and "
                         "0-sqft mislabeled lots. 0 = off (raw). ~30 = clean residential.")
    ap.add_argument("--min-sqft", dest="min_sqft", type=float, default=0.0,
                    help="Restrict ground-truth subjects to finished sqft >= this "
                         "(large-home focus for size-elasticity calibration). 0 = off.")
    ap.add_argument("--min-acres", dest="min_acres", type=float, default=0.0,
                    help="Restrict ground-truth subjects to acreage >= this "
                         "(high-acreage focus for land-premium calibration). 0 = off.")
    ap.add_argument("--n-comps", type=int, default=6,
                    help="Comps per subject (production default 6).")
    ap.add_argument("--months-back", type=int, default=18,
                    help="pick_comps lookback window for the comp pool. Default 18.")
    ap.add_argument("--out", type=str, default=str(_PROJECT_ROOT / "outputs" / "cma_backtest"),
                    help="Output directory for JSON + markdown reports.")
    ap.add_argument("--progress-every", type=int, default=25,
                    help="Print a progress line every N subjects.")
    return ap.parse_args(argv)


_LEAKAGE_CONTROLS = [
    "Comp pool filtered at SQL source to close/status-change date < as-of AND "
    "parcel_id != subject (patched cma_compset._fast_listings_connection).",
    "Recency half-life + months_back cutoff anchored to as-of by patching "
    "cma_compset.date.today() (a frozen date subclass).",
    "Appreciation-rate / $-per-sqft trend / prior-sale trend anchored to as-of "
    "by patching build_cma._today_date().",
    "Subject record built from physical attributes only; list_price / "
    "original_list_price / sold_price / assessed_total withheld (no target leakage).",
    "Prior-sale anchor (build_cma._mls_confirmed_prior_sale) pointed at an "
    "as-of-filtered parquet via temporary build_cma._PROJECT_ROOT re-point.",
    "Post-hoc assertion: any subject whose returned comps include a future or "
    "self comp is skipped (leak_future_comp / leak_self_comp).",
]


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    t0 = time.perf_counter()

    if not _MLS_PARQUET.exists():
        print(f"ERROR: {_MLS_PARQUET} not found. The backtest needs the slim "
              f"MLS lookup parquet (build via scripts/build_parcel_lookup.py).",
              file=sys.stderr)
        return 2

    typical_dom = _typical_dom()
    asof_run = _as_date(args.as_of_run) or date.today()
    sales = _pick_test_sales(args.months, args.limit, args.cls, asof_run, args.min_price,
                             args.min_ppsf, args.min_sqft, args.min_acres)
    if not sales:
        print("No closed sales matched the selection — widen --months or drop --class.",
              file=sys.stderr)
        return 1

    scored_rows: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    errors = 0
    for i, row in enumerate(sales, 1):
        try:
            res = _score_one(row, months_back=args.months_back,
                             n_comps=args.n_comps, typical_dom=typical_dom)
        except Exception as e:  # never let one bad subject kill the run
            errors += 1
            skipped["exception:" + type(e).__name__] = (
                skipped.get("exception:" + type(e).__name__, 0) + 1
            )
            if errors <= 3:
                print(f"  [warn] subject {row.get('address')!r} raised: {e}",
                      file=sys.stderr)
                traceback.print_exc()
            continue
        reason = res.get("skipped")
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        scored_rows.append(res)
        if args.progress_every and i % args.progress_every == 0:
            print(f"  ... {i}/{len(sales)} processed "
                  f"({len(scored_rows)} scored, {sum(skipped.values())} skipped)")

    overall = _metrics(scored_rows)
    segments = _build_segments(scored_rows)
    skipped_total = sum(skipped.values())
    eligible = len(sales)
    coverage_pct = round(len(scored_rows) / eligible * 100, 1) if eligible else 0.0

    # Survivorship transparency: scored-rate by close quarter makes it explicit
    # that headline metrics describe only the subjects with a deep-enough pool.
    def _quarter(d: date) -> str:
        return f"{d.year}Q{(d.month - 1) // 3 + 1}"

    total_by_q: dict[str, int] = {}
    scored_by_q: dict[str, int] = {}
    for r in sales:
        cd = _as_date(r.get("close_date"))
        if cd:
            total_by_q[_quarter(cd)] = total_by_q.get(_quarter(cd), 0) + 1
    for r in scored_rows:
        cd = _as_date(r.get("close_date"))
        if cd:
            scored_by_q[_quarter(cd)] = scored_by_q.get(_quarter(cd), 0) + 1
    coverage_by_quarter = {
        q: {
            "eligible": total_by_q[q],
            "scored": scored_by_q.get(q, 0),
            "scored_pct": round(scored_by_q.get(q, 0) / total_by_q[q] * 100, 1),
        }
        for q in sorted(total_by_q)
    }

    try:
        pq_mtime = datetime.fromtimestamp(_MLS_PARQUET.stat().st_mtime).isoformat(timespec="seconds")
        pq_rows = duckdb.connect(":memory:").execute(
            f"SELECT COUNT(*) FROM read_parquet('{_MLS_PARQUET.as_posix()}')"
        ).fetchone()[0]
    except Exception:
        pq_mtime, pq_rows = None, None

    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_run": asof_run.isoformat(),
        "min_price": args.min_price,
        "min_ppsf": args.min_ppsf,
        "months": args.months,
        "class_filter": args.cls,
        "limit": args.limit,
        "n_comps": args.n_comps,
        "months_back": args.months_back,
        "typical_dom": typical_dom,
        "candidates_pulled": eligible,
        "eligible": eligible,
        "scored": len(scored_rows),
        "coverage_pct": coverage_pct,
        "skipped_total": skipped_total,
        "skipped_breakdown": skipped,
        "coverage_by_quarter": coverage_by_quarter,
        "used_relist_cap_count": sum(1 for r in scored_rows if r.get("used_relist_cap")),
        "used_dom_fallback_count": sum(1 for r in scored_rows if r.get("used_dom_fallback")),
        "mls_parquet_mtime": pq_mtime,
        "mls_parquet_rows": pq_rows,
        "elapsed_seconds": round(time.perf_counter() - t0, 1),
        "leakage_controls": _LEAKAGE_CONTROLS,
        "production_entry_points": [
            "mls_bot.analytics.cma_compset.pick_comps",
            "build_cma._estimate_value",
            "build_cma._num",
        ],
    }
    payload = {
        "meta": meta,
        "overall": overall,
        "segments": segments,
        "subjects": scored_rows,
    }

    out_dir = Path(args.out)
    json_path, md_path = _write_reports(out_dir, payload)

    _print_summary(overall, segments, meta, args)
    print(f"\nelapsed: {meta['elapsed_seconds']}s")
    print(f"JSON report : {json_path}")
    print(f"MD report   : {md_path}")
    print(f"(also wrote backtest_latest.json / .md in {out_dir})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
