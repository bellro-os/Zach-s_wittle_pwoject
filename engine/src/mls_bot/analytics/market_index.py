"""County monthly $/sqft market index (S1 — trending infrastructure).

Per (county_norm, month): the median sold $/sqft over Closed RE_1
arm's-length-ish sales (is_auction / is_reo / is_short_sale TRUE rows
excluded; sqft must be > 200 and sold_price >= $80k — the same floors the
backtest subject draw uses), the sale count, and a 3-month *centered*
smoothed value (sale-count-weighted mean of the monthly medians over
[m-1, m, m+1]; edge months use whichever neighbors exist). Only the most
recent 48 months (anchored on the newest qualifying sale) are kept.

Two access paths — pick the right one:

``index_ratio(county, from_month, to_month)``
    PRODUCTION ONLY. Reads ``data/market_index.parquet`` (built by
    ``scripts/build_market_index.py`` / ``python tasks.py
    mls-rebuild-market-index``). The parquet is aggregated from ALL sales
    present at build time, so it is **not** as-of-aware: consulting it for a
    historical valuation date would let post-as-of sales leak into the
    trend. Never call this from a backtest.

``index_ratio_asof(county, from_month, to_month, as_of)``
    Backtest-safe. Ignores the parquet entirely and recomputes the index
    from the raw MLS pool using only sales with ``close_date`` strictly
    before ``as_of``. Because the comparison is strict, a backtest
    subject's own sale (``close_date == as_of``) can never enter the index
    it is valued against.

Both return ``smoothed(to_month) / smoothed(from_month)`` as a float, and
**degrade to None** whenever either endpoint month is absent or has
``n_sales < MIN_SALES`` (8) — callers must treat None as "no index
available" and fall back to existing behavior (e.g. the comp-pool
appreciation estimate). Nothing in the engine consults this module by
default; wiring it into a valuation path is a separate, gated change.

County keys are normalized with :func:`cma_regions._norm_county` (the same
normalization region knobs use), so ``"Montgomery"``, ``"MONTGOMERY
COUNTY"`` and ``"montgomery co."`` all hit the same series. Note the
normalizer also strips "(City)" — independent city feeds that share a name
with a county (e.g. "Roanoke (City)" vs "Roanoke") merge into one series;
both are far below MIN_SALES per month in this feed today, so the collision
is currently moot, but revisit if a city market ever gets thick.

Path overrides (unset = defaults, no behavior change anywhere):
  CMA_MARKET_INDEX_PARQUET — where ``index_ratio`` finds the built parquet.
  MLS_TEST_PARQUET         — raw pool for ``index_ratio_asof`` (the same
                             snapshot-pinning env the accuracy harness uses).
"""
from __future__ import annotations

import os
import re
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import duckdb

from .cma_regions import _norm_county

MIN_SALES = 8
WINDOW_MONTHS = 48

_INDEX_PARQUET_DEFAULT = Path("data/market_index.parquet")
_MLS_PARQUET_DEFAULT = Path("data/mls_lookup.parquet")
# Engine convention is cwd-relative "data/..." paths; fall back to the repo
# root (three levels up from src/mls_bot/analytics) so harnesses running from
# a scratch cwd still resolve.
_ROOT = Path(__file__).resolve().parents[3]

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})")

# The three flags the index must exclude. Older parquets (pre-D1) may lack
# them; filters are applied only for columns that exist so the module stays
# usable against pinned historical snapshots.
_DISTRESS_COLS = ("is_auction", "is_reo", "is_short_sale")


# --------------------------------------------------------------------------
# small helpers

def _resolve(p: Optional[Path | str], env: str, default: Path) -> Path:
    if p:
        return Path(p)
    e = os.environ.get(env, "").strip()
    if e:
        return Path(e)
    return default if default.exists() else _ROOT / default


def _month_key(x: Any) -> Optional[str]:
    """'2026-03' | '2026-03-15' | date | datetime -> '2026-03' (else None)."""
    if isinstance(x, (date, datetime)):
        return f"{x.year:04d}-{x.month:02d}"
    m = _MONTH_RE.match(str(x or "").strip())
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _month_idx(key: str) -> int:
    y, m = key.split("-")
    return int(y) * 12 + (int(m) - 1)


def _idx_month(i: int) -> str:
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def _as_of_date(as_of: Any) -> date:
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    return date.fromisoformat(str(as_of).strip()[:10])


# --------------------------------------------------------------------------
# core computation (shared verbatim by the builder script and the as-of path)

def compute_monthly_series(
    mls_parquet: Optional[Path | str] = None,
    as_of: Any = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Recompute the full index from raw MLS sales.

    Returns {county_norm: {month: {median_ppsf, n_sales, smoothed_ppsf}}}.
    ``as_of=None`` -> all sales (this is what the builder persists);
    ``as_of=<date>`` -> only sales with close_date STRICTLY before as_of
    (leak-free for backtests). The 48-month window anchors on the newest
    qualifying sale actually visible, so both variants share one rule.
    """
    pool = _resolve(mls_parquet, "MLS_TEST_PARQUET", _MLS_PARQUET_DEFAULT)
    con = duckdb.connect()
    try:
        have = {
            r[0]
            for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{pool.as_posix()}')"
            ).fetchall()
        }
        distress = " ".join(
            f"AND NOT COALESCE({c}, false)" for c in _DISTRESS_COLS if c in have
        )
        params: list[Any] = []
        asof_sql = ""
        if as_of is not None:
            asof_sql = "AND close_date < ?"
            params.append(_as_of_date(as_of).isoformat())
        rows = con.execute(
            f"""
            SELECT county, strftime(close_date, '%Y-%m') AS month,
                   sold_price / sqft AS ppsf
            FROM read_parquet('{pool.as_posix()}')
            WHERE status_category = 'Closed' AND _class = 'RE_1'
              AND close_date IS NOT NULL
              AND sqft > 200 AND sold_price >= 80000
              {distress} {asof_sql}
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    buckets: dict[str, dict[str, list[float]]] = {}
    for county, month, ppsf in rows:
        ck = _norm_county(str(county or ""))
        if not ck or not month or not ppsf or ppsf <= 0:
            continue
        buckets.setdefault(ck, {}).setdefault(month, []).append(float(ppsf))

    all_months = [m for c in buckets.values() for m in c]
    if not all_months:
        return {}
    anchor = max(_month_idx(m) for m in all_months)
    cutoff = anchor - (WINDOW_MONTHS - 1)

    out: dict[str, dict[str, dict[str, float]]] = {}
    for ck, months in buckets.items():
        med = {
            m: statistics.median(v)
            for m, v in months.items()
            if _month_idx(m) >= cutoff
        }
        if not med:
            continue
        cnt = {m: len(months[m]) for m in med}
        series: dict[str, dict[str, float]] = {}
        for m in sorted(med):
            i = _month_idx(m)
            win = [k for k in (_idx_month(i - 1), m, _idx_month(i + 1)) if k in med]
            wsum = sum(cnt[k] for k in win)
            series[m] = {
                "median_ppsf": round(med[m], 4),
                "n_sales": cnt[m],
                "smoothed_ppsf": round(
                    sum(med[k] * cnt[k] for k in win) / wsum, 4
                ),
            }
        out[ck] = series
    return out


def _ratio(series: dict[str, dict[str, float]] | None,
           from_month: Any, to_month: Any) -> Optional[float]:
    """Shared degrade logic: None unless BOTH endpoint months exist with
    n_sales >= MIN_SALES and positive smoothed values."""
    fk, tk = _month_key(from_month), _month_key(to_month)
    if not series or not fk or not tk:
        return None
    f, t = series.get(fk), series.get(tk)
    if not f or not t:
        return None
    if f["n_sales"] < MIN_SALES or t["n_sales"] < MIN_SALES:
        return None
    if f["smoothed_ppsf"] <= 0 or t["smoothed_ppsf"] <= 0:
        return None
    return float(t["smoothed_ppsf"]) / float(f["smoothed_ppsf"])


# --------------------------------------------------------------------------
# production path (prebuilt parquet)

_parquet_cache: dict[tuple, dict[str, dict[str, dict[str, float]]]] = {}


def _load_parquet_series(path: Optional[Path | str] = None,
                         ) -> dict[str, dict[str, dict[str, float]]] | None:
    p = _resolve(path, "CMA_MARKET_INDEX_PARQUET", _INDEX_PARQUET_DEFAULT)
    if not p.exists():
        return None
    st = p.stat()
    key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    hit = _parquet_cache.get(key)
    if hit is not None:
        return hit
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""SELECT county_norm, month, median_ppsf, n_sales, smoothed_ppsf
                FROM read_parquet('{p.as_posix()}')"""
        ).fetchall()
    finally:
        con.close()
    series: dict[str, dict[str, dict[str, float]]] = {}
    for ck, month, med, n, sm in rows:
        series.setdefault(ck, {})[month] = {
            "median_ppsf": float(med), "n_sales": int(n),
            "smoothed_ppsf": float(sm),
        }
    _parquet_cache.clear()  # single-entry cache: the file only changes on rebuild
    _parquet_cache[key] = series
    return series


def index_ratio(county: str, from_month: Any, to_month: Any,
                parquet_path: Optional[Path | str] = None) -> Optional[float]:
    """smoothed(to_month)/smoothed(from_month) from the PREBUILT parquet.

    PRODUCTION ONLY — the parquet aggregates all sales known at build time,
    so this is not as-of-aware; backtests must use :func:`index_ratio_asof`.
    None when the parquet is missing, the county is unknown, or either
    month is absent / has n_sales < MIN_SALES (callers fall back).
    """
    series = _load_parquet_series(parquet_path)
    if series is None:
        return None
    return _ratio(series.get(_norm_county(county)), from_month, to_month)


# --------------------------------------------------------------------------
# backtest path (leak-free recompute)

_asof_cache: dict[tuple, dict[str, dict[str, dict[str, float]]]] = {}
_ASOF_CACHE_MAX = 256


def index_ratio_asof(county: str, from_month: Any, to_month: Any, as_of: Any,
                     mls_parquet: Optional[Path | str] = None,
                     ) -> Optional[float]:
    """Leak-free index ratio for backtests: recomputed from raw sales with
    close_date STRICTLY before ``as_of`` (the prebuilt parquet is never
    touched). Same degrade contract as :func:`index_ratio`: None when either
    month is missing or thin (n_sales < MIN_SALES) *as seen from as_of* —
    note a month can be thick in production yet thin/absent here because
    later sales are invisible. Results are memoized per (pool, mtime, as_of).
    """
    pool = _resolve(mls_parquet, "MLS_TEST_PARQUET", _MLS_PARQUET_DEFAULT)
    if not pool.exists():
        return None
    asod = _as_of_date(as_of)
    st = pool.stat()
    key = (str(pool.resolve()), st.st_mtime_ns, st.st_size, asod.isoformat())
    series = _asof_cache.get(key)
    if series is None:
        series = compute_monthly_series(pool, as_of=asod)
        if len(_asof_cache) >= _ASOF_CACHE_MAX:
            _asof_cache.clear()
        _asof_cache[key] = series
    return _ratio(series.get(_norm_county(county)), from_month, to_month)
