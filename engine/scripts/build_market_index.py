"""Build data/market_index.parquet — county monthly median $/sqft index (S1).

Run from the repo root:

    python scripts/build_market_index.py

or via the task entrypoint (registered alongside mls-rebuild-parquet, so any
schedule that rebuilds mls_lookup.parquet can rebuild this right after):

    python tasks.py mls-rebuild-market-index

One row per (county_norm, month): median $/sqft over Closed RE_1
arm's-length-ish sales (is_auction / is_reo / is_short_sale excluded;
sqft > 200; sold_price >= $80k), n_sales, and a 3-month centered
sale-count-weighted smoothed value. Last 48 months, anchored on the newest
qualifying sale. All computation lives in
mls_bot.analytics.market_index.compute_monthly_series so this artifact and
the backtest-safe recompute (index_ratio_asof) can never drift apart.

PRODUCTION-ONLY ARTIFACT: it aggregates every sale present at build time and
is therefore NOT as-of-aware. Backtests must call
mls_bot.analytics.market_index.index_ratio_asof(...), which recomputes from
raw sales with close_date < as_of and never reads this file.

Env (unset = defaults):
  MLS_TEST_PARQUET          — source pool override (harness snapshot pinning)
  CMA_MARKET_INDEX_PARQUET  — output path override
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402

from mls_bot.analytics.market_index import (  # noqa: E402
    MIN_SALES,
    WINDOW_MONTHS,
    compute_monthly_series,
)

OUT_DEFAULT = ROOT / "data" / "market_index.parquet"


def main() -> int:
    out = Path(
        os.environ.get("CMA_MARKET_INDEX_PARQUET", "").strip() or OUT_DEFAULT
    )
    series = compute_monthly_series()  # as_of=None -> all sales, 48-mo window
    rows = [
        (ck, month, v["median_ppsf"], v["n_sales"], v["smoothed_ppsf"])
        for ck, months in sorted(series.items())
        for month, v in sorted(months.items())
    ]
    if not rows:
        print("[market-index] no qualifying sales — nothing written")
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f".tmp{os.getpid()}.parquet")
    con = duckdb.connect()
    try:
        con.execute(
            """CREATE TABLE idx (
                   county_norm VARCHAR, month VARCHAR, median_ppsf DOUBLE,
                   n_sales INTEGER, smoothed_ppsf DOUBLE)"""
        )
        con.executemany("INSERT INTO idx VALUES (?, ?, ?, ?, ?)", rows)
        con.execute(
            f"""COPY (SELECT * FROM idx ORDER BY county_norm, month)
                TO '{tmp.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    os.replace(tmp, out)  # atomic publish — readers never see a half-written file

    months = sorted({m for _, m, *_ in rows})
    thick = sum(1 for r in rows if r[3] >= MIN_SALES)
    print(
        f"[market-index] wrote {out} — {len(rows)} county-months, "
        f"{len(series)} counties, {months[0]}..{months[-1]} "
        f"(window {WINDOW_MONTHS}mo); {thick} rows meet the n>={MIN_SALES} "
        f"floor index_ratio requires"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
