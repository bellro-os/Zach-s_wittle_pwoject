"""Live neighborhood tear-sheets for compbird's landing showcase.

Exposes a single pure entrypoint, ``build_markets() -> list[dict]``, that
aggregates the top New River Valley neighborhoods (by recent sold count) into
the landing's market-card shape. It reads the SAME slim
``data/mls_lookup.parquet`` that property_profile.py's ``_market_context``
query reads, and the filters (RE_1 class, Closed status, positive sold price,
12-month window) and the median-$/sqft / DOM / months-of-inventory / split-half
trend math all mirror ``_market_context`` — but scoped per-neighborhood and
ranked instead of resolved against a single subject.

This is the CANONICAL source for the landing's live market cards. Both engine
paths call it:

  * the warm worker's GET /markets handler (cma_worker.py), and
  * the app's spawn fallback (engine.ts MARKETS_RUNNER), which imports and
    calls this so the two paths can never drift.

Design contract:
  * PURE + no printing — returns a list of dicts (the caller serializes).
  * NEVER raises: on any failure (missing parquet, DuckDB error, no rows) it
    returns ``[]`` so the landing keeps its built-in sample.
  * duckdb-only (dependency-consistent with the rest of the engine; no pyarrow).

Each card matches ``EngineMarket`` in the app's engine.ts (and
``NeighborhoodMarket`` in the app's compbird types): the field names here are
emitted verbatim so the route can hand the array straight to the client.
"""

from __future__ import annotations

import math
import traceback
from pathlib import Path
from typing import Any, Optional

# data/mls_lookup.parquet lives at the repo root (mirror property_profile.py's
# _MLS_LOOKUP_PARQUET). This module lives in scripts/, so the root is the parent.
_ROOT = Path(__file__).resolve().parent.parent
_MLS_LOOKUP_PARQUET = _ROOT / "data" / "mls_lookup.parquet"

WINDOW_MONTHS = 12          # same window as _market_context
MIN_SOLD = 6                # only surface neighborhoods with a credible sample
MAX_CARDS = 6
CLASS = "RE_1"
# Subdivision placeholders the feed uses for "no real subdivision" — never a card.
PLACEHOLDERS = ("", "NONE", "OTHER", "N/A", "NA", "UNKNOWN", "TBD")


def _f(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        v = float(v)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _trend_series(con: Any, scope_clause: str) -> Optional[list[int]]:
    """12-point oldest->newest price series for the sparkline. Per-month median,
    then forward/back-filled and lightly smoothed toward the overall median so a
    thin month doesn't spike the line. Cosmetic only — headline figures are the
    real aggregates."""
    try:
        rows = con.execute(
            f"""WITH sold AS (
                    SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                           11 - date_diff('month', date_trunc('month', close_date),
                                          date_trunc('month', CURRENT_DATE)) AS idx
                    FROM l
                    WHERE _class = '{CLASS}' AND status_category = 'Closed'
                      AND TRY_CAST(sold_price AS DOUBLE) > 0
                      AND close_date >= (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS} months')
                      AND {scope_clause}
                )
                SELECT idx, MEDIAN(sp) m FROM sold
                WHERE idx BETWEEN 0 AND 11 GROUP BY idx ORDER BY idx"""
        ).fetchall()
    except Exception:
        return None
    by_idx = {int(i): _f(m) for i, m in rows if _f(m) is not None}
    if not by_idx:
        return None
    vals = list(by_idx.values())
    overall = sorted(vals)[len(vals) // 2]
    # Forward-fill gaps; seed the head from the first known value.
    series, last = [], None
    for i in range(12):
        v = by_idx.get(i)
        if v is None:
            v = last if last is not None else overall
        series.append(v)
        last = v
    # Light smoothing (3-pt moving avg, ends held) so the line reads clean.
    sm = []
    for i in range(12):
        lo, hi = max(0, i - 1), min(11, i + 1)
        win = series[lo:hi + 1]
        sm.append(round(sum(win) / len(win)))
    return sm


def _note(scope_label: str, med_dom: Optional[int], moi: Optional[float],
          trend_pct: Optional[float], n_sold: int) -> str:
    bits = []
    if moi is not None:
        if moi < 3:
            bits.append("tight supply favors sellers")
        elif moi < 6:
            bits.append("supply and demand are balanced")
        else:
            bits.append("ample supply favors buyers")
    if med_dom is not None:
        if med_dom <= 14:
            bits.append("homes clear in under two weeks")
        elif med_dom <= 30:
            bits.append(f"a typical sale takes about {int(med_dom)} days")
        else:
            bits.append(f"listings sit ~{int(med_dom)} days before closing")
    if trend_pct is not None and abs(trend_pct) >= 1.0:
        bits.append(f"$/sqft is {'up' if trend_pct > 0 else 'down'} {abs(trend_pct):.1f}% year over year")
    head = "; ".join(bits[:2]) if bits else f"{int(n_sold)} closings in the trailing year"
    return head[:1].upper() + head[1:] + "."


def build_markets() -> list[dict]:
    """Return up to MAX_CARDS live neighborhood cards (see module docstring).

    Never raises: returns [] on any failure so the landing keeps its sample."""
    try:
        import duckdb
    except Exception:
        return []

    try:
        parquet = _MLS_LOOKUP_PARQUET
        if not parquet.exists():
            return []

        con = duckdb.connect(":memory:")
        con.execute(f"CREATE VIEW l AS SELECT * FROM read_parquet('{parquet.as_posix()}')")

        placeholders_sql = ", ".join("'" + p + "'" for p in PLACEHOLDERS)
        # Top neighborhoods by recent sold count. Group on the raw subdivision but
        # drop feed placeholders so we only surface real, named neighborhoods.
        ranked = con.execute(
            f"""WITH sold AS (
                    SELECT subdivision, city, county,
                           TRY_CAST(sold_price AS DOUBLE) sp,
                           TRY_CAST(sqft AS DOUBLE) sf,
                           TRY_CAST(feed_dom AS INT) dom
                    FROM l
                    WHERE _class = '{CLASS}' AND status_category = 'Closed'
                      AND TRY_CAST(sold_price AS DOUBLE) > 0
                      AND close_date >= (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS} months')
                      AND subdivision IS NOT NULL
                      AND UPPER(TRIM(subdivision)) NOT IN ({placeholders_sql})
                )
                SELECT subdivision,
                       ANY_VALUE(city) city, ANY_VALUE(county) county,
                       COUNT(*) n_sold,
                       MEDIAN(sp) med_price,
                       MEDIAN(CASE WHEN sf > 0 THEN sp / sf END) med_ppsf,
                       MEDIAN(dom) med_dom
                FROM sold
                GROUP BY subdivision
                HAVING COUNT(*) >= {MIN_SOLD}
                ORDER BY n_sold DESC
                LIMIT {MAX_CARDS}"""
        ).fetchall()

        markets: list[dict] = []
        for sub, city, county, n_sold, med_price, med_ppsf, med_dom in ranked:
            sub_sql = str(sub).replace("'", "''")
            scope_clause = f"subdivision = '{sub_sql}'"

            active = con.execute(
                f"SELECT COUNT(*) FROM l WHERE _class = '{CLASS}' "
                f"AND status_category = 'Active' AND {scope_clause}"
            ).fetchone()
            active_count = int(active[0]) if active and active[0] is not None else 0

            n = int(n_sold)
            moi = None
            if n > 0:
                per_month = n / float(WINDOW_MONTHS)
                if per_month > 0:
                    moi = active_count / per_month

            # Split-half $/sqft trend — identical idea to _market_context.
            trend_pct = None
            try:
                halves = con.execute(
                    f"""WITH sold AS (
                            SELECT TRY_CAST(sold_price AS DOUBLE) sp,
                                   TRY_CAST(sqft AS DOUBLE) sf, close_date
                            FROM l
                            WHERE _class = '{CLASS}' AND status_category = 'Closed'
                              AND TRY_CAST(sold_price AS DOUBLE) > 0
                              AND TRY_CAST(sqft AS DOUBLE) > 0
                              AND close_date >= (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS} months')
                              AND {scope_clause}
                        ),
                        tagged AS (
                            SELECT sp / sf AS ppsf,
                                   CASE WHEN close_date >=
                                        (CURRENT_DATE - INTERVAL '{WINDOW_MONTHS // 2} months')
                                        THEN 'recent' ELSE 'older' END AS half
                            FROM sold
                        )
                        SELECT half, MEDIAN(ppsf) med, COUNT(*) c FROM tagged GROUP BY half"""
                ).fetchall()
                by_half = {h: (m, c) for h, m, c in halves}
                recent, older = by_half.get("recent"), by_half.get("older")
                if recent and older and recent[1] >= 3 and older[1] >= 3 and older[0]:
                    trend_pct = (recent[0] - older[0]) / older[0] * 100.0
            except Exception:
                trend_pct = None

            trend = _trend_series(con, scope_clause)
            med_price_f = _f(med_price)
            med_ppsf_f = _f(med_ppsf)
            if med_price_f is None or med_ppsf_f is None:
                continue  # a card with no headline is useless — skip it
            if not trend:
                trend = [round(med_price_f)] * 12

            med_dom_i = int(med_dom) if med_dom is not None else 0
            trend_pct_r = round(trend_pct, 1) if trend_pct is not None else 0.0
            moi_r = round(moi, 1) if moi is not None else 0.0
            area = ", ".join([str(x) for x in (city, (str(county) + " County") if county else None) if x]) or "New River Valley, VA"
            markets.append({
                "name": str(sub),
                "area": area,
                "medianPrice": int(round(med_price_f)),
                "ppsf": int(round(med_ppsf_f)),
                "ppsfTrendPct": trend_pct_r,
                "medianDom": med_dom_i,
                "monthsOfInventory": moi_r,
                "soldCount": n,
                "activeCount": active_count,
                "trend": trend,
                "note": _note(str(sub), med_dom_i, moi, trend_pct, n),
            })

        return markets
    except Exception:
        # Never crash the landing — fall back to the sample by returning empty.
        traceback.print_exc()
        return []


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    import json
    print(json.dumps({"ok": True, "markets": build_markets()}, allow_nan=False, indent=2))
