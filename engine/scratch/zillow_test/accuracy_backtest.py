"""ACCURACY backtest: MLS-only pool vs Zillow-only pool, head-to-head, on the
SAME ground-truth subjects.

Ground truth = a known recent SOLD price (from the production MLS parquet).
For EACH subject we predict its value TWICE, with the subject EXCLUDED from the
pool both times:

  (A) MLS-only pool   — the EXACT production temporal-leave-one-out path. We do
      NOT reimplement it: we import scripts/backtest_cma.py and call its
      _score_one with the production _make_asof_listings_conn factory. This is
      byte-identical to `python scripts/backtest_cma.py`.

  (B) Zillow-only pool — same _score_one, but cma_compset._fast_listings_connection
      is pointed at the ISOLATED Zillow parquet (scratch/zillow_test/), as-of
      filtered to close_date < as-of. Because the same physical property has a
      DIFFERENT parcel_id in Zillow (Z<zpid>) than in MLS, parcel self-exclusion
      can't catch the subject's own Zillow row, so we ALSO spatially exclude any
      Zillow row within ~25 m of the subject's lat/lng (its own sale) at the SQL
      source — belt-and-suspenders leave-one-out.

NOTHING is unioned: each arm sees exactly one pool. NO production file or data is
modified. The MLS arm runs production code with the production patch factory;
the Zillow arm swaps ONLY the in-process _fast_listings_connection reference
inside a try/finally that restores it.

Two studies:
  STUDY 1 (ACCURACY, dense-both): N Montgomery-County sold subjects, valued via
    both pools; report median |APE|, MAPE, PPE10, PPE20, interval coverage, n —
    side by side.
  STUDY 2 (COVERAGE, statewide): a sample of subjects spread over many VA
    counties; for each, does MLS-only return a usable valuation vs Zillow-only,
    and is it LOCAL (nearest comp within ~15 mi)? Quantifies the geographic gap.

Run from C:/Users/zach/Desktop/MLS Bot:
    python scratch/zillow_test/accuracy_backtest.py --n 50 --months 18
    python scratch/zillow_test/accuracy_backtest.py --coverage --cov-n 12
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from statistics import median
from typing import Any, Optional

ROOT = Path("C:/Users/zach/Desktop/MLS Bot")
for p in (ROOT / "scripts", ROOT / "src"):
    sp = str(p)
    if sp in sys.path:
        sys.path.remove(sp)
    sys.path.insert(0, sp)
import os
os.chdir(ROOT)

import duckdb  # noqa: E402

# Import the PRODUCTION backtest harness as a module and reuse its machinery.
import backtest_cma as bt  # noqa: E402  (scripts/backtest_cma.py)
import build_cma as _bc  # noqa: E402
import mls_bot.analytics.cma_compset as _cc  # noqa: E402
import mls_bot.analytics.dom_model as _dm  # noqa: E402
from build_cma import _estimate_value, _num  # noqa: E402
from mls_bot.analytics.cma_compset import pick_comps  # noqa: E402

MLS_PARQUET = (ROOT / "data" / "mls_lookup.parquet").as_posix()
ZIL_PARQUET = (ROOT / "scratch" / "zillow_test" / "zillow_listings.parquet").as_posix()

# Spatial self-exclusion radius for the Zillow arm (degrees). ~0.00025 deg ~= 28 m
# at VA latitude — tight enough to drop ONLY the subject's own sale, not a
# legitimate next-door comp.
SELF_DEG = 0.00025

# A comp is "local" if its nearest comp is within this many miles of the subject.
LOCAL_MI = 15.0


def _haversine_mi(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return None
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 3958.7613 * 2 * asin(sqrt(a))


# ---------------------------------------------------------------------------
# Zillow as-of listings connection (mirrors bt._make_asof_listings_conn, but on
# the Zillow parquet, with SPATIAL self-exclusion because Zillow parcel_ids
# don't match MLS parcel_ids).
# ---------------------------------------------------------------------------
def _make_zillow_asof_conn(asof: date, subj_lat: Optional[float],
                           subj_lng: Optional[float], subj_addr: str):
    if isinstance(asof, datetime):
        asof = asof.date()
    asof_s = asof.isoformat()
    # Spatial self-exclusion: drop any Zillow row within SELF_DEG of the subject
    # (its own sold record). Also drop by normalized street address as a second
    # belt — Zillow addresses are "123 Main St, City, VA 24060".
    geo_clause = ""
    if subj_lat is not None and subj_lng is not None:
        geo_clause = (
            f"AND NOT (ABS(latitude - {float(subj_lat)}) < {SELF_DEG} "
            f"AND ABS(longitude - {float(subj_lng)}) < {SELF_DEG}) "
        )
    addr_key = (subj_addr or "").split(",")[0].strip().upper().replace("'", "''")
    addr_clause = ""
    if addr_key:
        addr_clause = f"AND UPPER(TRIM(address)) NOT LIKE '{addr_key}%' "

    def _factory():
        con = duckdb.connect(":memory:")
        con.execute(
            f"""
            CREATE VIEW listings AS
            SELECT * FROM read_parquet('{ZIL_PARQUET}')
            WHERE COALESCE(
                    TRY_CAST(close_date AS DATE),
                    TRY_CAST(status_changed_at AS DATE)
                  ) < DATE '{asof_s}'
            {geo_clause}
            {addr_clause}
            """
        )
        return con

    return _factory


# ---------------------------------------------------------------------------
# Score one subject through ONE pool. Reuses the production leakage controls
# from backtest_cma for the time anchors + subject construction.
# ---------------------------------------------------------------------------
def _score_pool(row: dict[str, Any], *, pool: str, months_back: int,
                n_comps: int, typical_dom: int) -> dict[str, Any]:
    """pool = 'mls' (production factory) or 'zillow' (Zillow factory).

    Everything else — frozen date, _today_date anchor, dom_model date, subject
    construction, prior-sale root, post-hoc leak assertions, valuation — is the
    production backtest path (bt._score_one logic), so the MLS arm is identical
    to `python scripts/backtest_cma.py`.
    """
    sold = _num(row.get("sold_price"))
    if not sold or sold <= 0:
        return {"skipped": "no_sold_price"}
    subject_pid = str(row.get("parcel_id") or "").strip()
    if subject_pid.upper() in bt._PLACEHOLDER_PARCELS and pool == "mls":
        return {"skipped": "placeholder_parcel"}

    close_d = bt._as_date(row.get("close_date"))
    list_d = bt._as_date(row.get("list_date"))
    if list_d is not None:
        asof = list_d
    elif close_d is not None:
        asof = close_d - timedelta(days=typical_dom)
    else:
        return {"skipped": "no_asof_date"}
    if close_d is not None and list_d is not None and (close_d - list_d).days > bt._RELIST_CAP_DAYS:
        asof = close_d - timedelta(days=typical_dom)
    if close_d is not None and asof >= close_d:
        asof = close_d - timedelta(days=max(1, typical_dom))

    subj = bt._build_subject(row)
    has_geo = subj.get("latitude") is not None and subj.get("longitude") is not None
    s_lat = _num(subj.get("latitude"))
    s_lng = _num(subj.get("longitude"))

    frozen = bt._make_frozen_date(asof)
    orig_cc_date = _cc.date
    orig_today = _bc._today_date
    orig_conn = _cc._fast_listings_connection
    orig_dm_date = _dm.date

    _cc.date = frozen
    _bc._today_date = lambda: asof
    _dm.date = frozen
    if pool == "mls":
        _cc._fast_listings_connection = bt._make_asof_listings_conn(asof, subject_pid)
    else:
        _cc._fast_listings_connection = _make_zillow_asof_conn(
            asof, s_lat, s_lng, str(row.get("address") or "")
        )

    try:
        with bt._AsOfPriorSaleRoot(asof):
            comps = pick_comps(subj, n=n_comps, months_back=months_back)
            if not comps:
                return {"skipped": "empty_comp_pool", "asof": asof.isoformat()}
            # Leak guard: future + self. For the MLS arm use parcel id; for the
            # Zillow arm use the spatial check (parcel ids differ).
            nearest = None
            for c in comps:
                cd = bt._as_date(c.get("close_date")) or bt._as_date(c.get("status_changed_at"))
                if cd is not None and cd >= asof:
                    return {"skipped": "leak_future_comp", "asof": asof.isoformat()}
                if pool == "mls":
                    cpid = str(c.get("parcel_id") or "").strip().upper()
                    if subject_pid and cpid == subject_pid.upper():
                        return {"skipped": "leak_self_comp", "asof": asof.isoformat()}
                d = _haversine_mi(s_lat, s_lng, c.get("latitude"), c.get("longitude"))
                if d is not None and (nearest is None or d < nearest):
                    nearest = d
            val = _estimate_value(subj, comps)
    finally:
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

    return {
        "skipped": None,
        "address": row.get("address"),
        "county": str(row.get("county") or "") or "(unknown)",
        "sold_price": sold,
        "predicted_mid": mid,
        "predicted_low": low,
        "predicted_high": high,
        "ape": abs(mid - sold) / sold,
        "signed_error_pct": (mid - sold) / sold,
        "covered": bool(low and high and low <= sold <= high),
        "comp_count": len(comps),
        "nearest_comp_mi": round(nearest, 2) if nearest is not None else None,
        "is_local": (nearest is not None and nearest <= LOCAL_MI),
        "has_geo": has_geo,
        "asof": asof.isoformat(),
    }


# ---------------------------------------------------------------------------
# Subject selection
# ---------------------------------------------------------------------------
def _pick_montgomery_sales(months: int, n: int, asof_run: date,
                           min_price: float) -> list[dict[str, Any]]:
    """Dense-both ground truth: Montgomery RE_1 closed sales with sold price,
    geocoded, recent. These exist in BOTH pools so the head-to-head is fair."""
    con = duckdb.connect(":memory:")
    cutoff = (asof_run - timedelta(days=int(months * 30.4))).isoformat()
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
        FROM read_parquet('{MLS_PARQUET}')
        WHERE status_category='Closed' AND _class='RE_1'
          AND UPPER(county) LIKE '%MONTGOMERY%'
          AND TRY_CAST(sold_price AS DOUBLE) >= {float(min_price)}
          AND TRY_CAST(sqft AS DOUBLE) > 0
          AND TRY_CAST(sold_price AS DOUBLE) >= 30 * TRY_CAST(sqft AS DOUBLE)
          AND latitude IS NOT NULL AND longitude IS NOT NULL
          AND close_date IS NOT NULL
          AND close_date >= DATE '{cutoff}'
          AND close_date < DATE '{asof_run.isoformat()}'
        ORDER BY close_date DESC, listing_id
    """
    rows = con.execute(sql).fetchdf().to_dict(orient="records")
    con.close()
    # Even spread across the window: take every k-th so subjects aren't all from
    # the last few weeks (which would starve the as-of pools differently).
    if n and len(rows) > n:
        step = len(rows) / n
        rows = [rows[int(i * step)] for i in range(n)]
    return rows


def _pick_statewide_sales(n_counties: int, per_county: int, months: int,
                          asof_run: date, min_price: float) -> list[dict[str, Any]]:
    """Coverage study: spread subjects across many VA counties. We pick the
    most recent geocoded RE_1 sale(s) per county for a wide sample of counties."""
    con = duckdb.connect(":memory:")
    cutoff = (asof_run - timedelta(days=int(months * 30.4))).isoformat()
    # Choose counties: a deterministic wide spread (alphabetical) so the sample
    # spans NoVA, Tidewater, SW, Piedmont — not just the dense feed core.
    counties = con.execute(f"""
        SELECT county, count(*) c
        FROM read_parquet('{MLS_PARQUET}')
        WHERE status_category='Closed' AND _class='RE_1'
          AND TRY_CAST(sold_price AS DOUBLE) >= {float(min_price)}
          AND latitude IS NOT NULL AND county IS NOT NULL AND TRIM(county) <> ''
          AND close_date >= DATE '{cutoff}'
        GROUP BY 1 HAVING count(*) >= 1 ORDER BY county
    """).fetchdf()["county"].tolist()
    # Sample n_counties evenly across the alphabetical list for geographic spread.
    if len(counties) > n_counties:
        step = len(counties) / n_counties
        counties = [counties[int(i * step)] for i in range(n_counties)]
    rows: list[dict[str, Any]] = []
    for cty in counties:
        cty_e = cty.replace("'", "''")
        r = con.execute(f"""
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
            FROM read_parquet('{MLS_PARQUET}')
            WHERE status_category='Closed' AND _class='RE_1'
              AND county = '{cty_e}'
              AND TRY_CAST(sold_price AS DOUBLE) >= {float(min_price)}
              AND TRY_CAST(sqft AS DOUBLE) > 0
              AND latitude IS NOT NULL AND longitude IS NOT NULL
              AND close_date IS NOT NULL AND close_date < DATE '{asof_run.isoformat()}'
            ORDER BY close_date DESC LIMIT {per_county}
        """).fetchdf().to_dict(orient="records")
        rows.extend(r)
    con.close()
    return rows


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    apes = [r["ape"] for r in rows]
    return {
        "n": n,
        "median_ape_pct": round(median(apes) * 100, 2),
        "mape_pct": round(sum(apes) / n * 100, 2),
        "ppe10_pct": round(sum(1 for r in rows if r["ape"] <= 0.10) / n * 100, 1),
        "ppe20_pct": round(sum(1 for r in rows if r["ape"] <= 0.20) / n * 100, 1),
        "coverage_pct": round(sum(1 for r in rows if r["covered"]) / n * 100, 1),
        "median_signed_pct": round(median([r["signed_error_pct"] for r in rows]) * 100, 2),
    }


def run_accuracy(n: int, months: int, min_price: float, asof_run: date,
                 n_comps: int, months_back: int):
    typical_dom = bt._typical_dom()
    subjects = _pick_montgomery_sales(months, n, asof_run, min_price)
    print(f"\n{'='*84}\nSTUDY 1 — ACCURACY (Montgomery County, dense-both)\n{'='*84}")
    print(f"subjects drawn: {len(subjects)}  | months={months}  min_price=${min_price:,.0f}  "
          f"n_comps={n_comps}  months_back={months_back}  typical_dom={typical_dom}")
    print("Each subject valued TWICE (subject excluded both times); ground truth = its sold price.\n")

    mls_rows, zil_rows, paired = [], [], []
    mls_skip, zil_skip = {}, {}
    for i, row in enumerate(subjects, 1):
        m = _score_pool(row, pool="mls", months_back=months_back,
                        n_comps=n_comps, typical_dom=typical_dom)
        z = _score_pool(row, pool="zillow", months_back=months_back,
                        n_comps=n_comps, typical_dom=typical_dom)
        if m.get("skipped"):
            mls_skip[m["skipped"]] = mls_skip.get(m["skipped"], 0) + 1
        else:
            mls_rows.append(m)
        if z.get("skipped"):
            zil_skip[z["skipped"]] = zil_skip.get(z["skipped"], 0) + 1
        else:
            zil_rows.append(z)
        if not m.get("skipped") and not z.get("skipped"):
            paired.append((row, m, z))
        if i % 10 == 0:
            print(f"  ... {i}/{len(subjects)} done "
                  f"(MLS scored {len(mls_rows)}, ZIL scored {len(zil_rows)})")

    mls_m = _metrics(mls_rows)
    zil_m = _metrics(zil_rows)
    # Paired metrics: only subjects where BOTH arms produced a valuation (fairest
    # apples-to-apples comparison on the identical subject set).
    pm = _metrics([m for _, m, _ in paired])
    pz = _metrics([z for _, _, z in paired])

    print(f"\nmls skipped: {mls_skip}")
    print(f"zil skipped: {zil_skip}")

    def _tbl(title, a, b):
        print(f"\n{title}")
        print(f"  {'metric':<22}{'MLS-only':>14}{'Zillow-only':>14}")
        keys = [("n", "n", ""), ("median_ape_pct", "median |APE|", "%"),
                ("mape_pct", "MAPE", "%"), ("ppe10_pct", "PPE10", "%"),
                ("ppe20_pct", "PPE20", "%"), ("coverage_pct", "interval coverage", "%"),
                ("median_signed_pct", "median signed err", "%")]
        for key, lab, suf in keys:
            av = a.get(key, "-"); bv = b.get(key, "-")
            print(f"  {lab:<22}{str(av)+suf:>14}{str(bv)+suf:>14}")

    _tbl("ALL-SCORED (each arm's own scored set)", mls_m, zil_m)
    _tbl(f"PAIRED (both arms scored, n={len(paired)} identical subjects)", pm, pz)
    return {"mls": mls_m, "zil": zil_m, "paired_mls": pm, "paired_zil": pz,
            "n_paired": len(paired)}


def run_coverage(n_counties: int, per_county: int, months: int, min_price: float,
                 asof_run: date, n_comps: int, months_back: int):
    typical_dom = bt._typical_dom()
    subjects = _pick_statewide_sales(n_counties, per_county, months, asof_run, min_price)
    print(f"\n{'='*84}\nSTUDY 2 — COVERAGE (statewide, many VA counties)\n{'='*84}")
    print(f"subjects: {len(subjects)} across {len({s['county'] for s in subjects})} counties  "
          f"(LOCAL = nearest comp within {LOCAL_MI:.0f} mi)\n")
    print(f"  {'county':<22}{'subject':<34}{'MLS':>16}{'ZIL':>16}")
    counts = {"mls_usable": 0, "mls_local": 0, "zil_usable": 0, "zil_local": 0,
              "mls_only": 0, "zil_only": 0, "both": 0, "neither": 0,
              "mls_local_only": 0, "zil_local_only": 0}
    details = []
    for row in subjects:
        m = _score_pool(row, pool="mls", months_back=months_back,
                        n_comps=n_comps, typical_dom=typical_dom)
        z = _score_pool(row, pool="zillow", months_back=months_back,
                        n_comps=n_comps, typical_dom=typical_dom)
        m_ok = not m.get("skipped")
        z_ok = not z.get("skipped")
        m_local = m_ok and m.get("is_local")
        z_local = z_ok and z.get("is_local")
        counts["mls_usable"] += int(m_ok)
        counts["zil_usable"] += int(z_ok)
        counts["mls_local"] += int(m_local)
        counts["zil_local"] += int(z_local)
        if m_ok and not z_ok:
            counts["mls_only"] += 1
        elif z_ok and not m_ok:
            counts["zil_only"] += 1
        elif m_ok and z_ok:
            counts["both"] += 1
        else:
            counts["neither"] += 1
        if m_local and not z_local:
            counts["mls_local_only"] += 1
        if z_local and not m_local:
            counts["zil_local_only"] += 1

        def _fmt(r, ok):
            if not ok:
                return "NONE"
            nm = r.get("nearest_comp_mi")
            loc = "L" if r.get("is_local") else "FAR"
            return f"{loc}@{nm}mi"
        addr = (row.get("address") or "")[:32]
        print(f"  {str(row.get('county'))[:20]:<22}{addr:<34}"
              f"{_fmt(m, m_ok):>16}{_fmt(z, z_ok):>16}")
        details.append({"county": row.get("county"), "address": row.get("address"),
                        "mls_ok": m_ok, "zil_ok": z_ok,
                        "mls_local": m_local, "zil_local": z_local,
                        "mls_nearest_mi": m.get("nearest_comp_mi"),
                        "zil_nearest_mi": z.get("nearest_comp_mi")})

    nT = len(subjects)
    print(f"\n  {'-'*60}")
    print(f"  total subjects: {nT}")
    print(f"  MLS-only usable valuation : {counts['mls_usable']}/{nT} "
          f"({counts['mls_usable']/nT*100:.0f}%)   of which LOCAL (<{LOCAL_MI:.0f}mi): "
          f"{counts['mls_local']}/{nT} ({counts['mls_local']/nT*100:.0f}%)")
    print(f"  Zillow-only usable valuation: {counts['zil_usable']}/{nT} "
          f"({counts['zil_usable']/nT*100:.0f}%)   of which LOCAL (<{LOCAL_MI:.0f}mi): "
          f"{counts['zil_local']}/{nT} ({counts['zil_local']/nT*100:.0f}%)")
    print(f"  both usable: {counts['both']}   MLS-only: {counts['mls_only']}   "
          f"Zillow-only: {counts['zil_only']}   neither: {counts['neither']}")
    print(f"  LOCAL where the OTHER is not local: "
          f"Zillow-local-only={counts['zil_local_only']}  MLS-local-only={counts['mls_local_only']}")
    return counts, details


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="Montgomery subjects (Study 1).")
    ap.add_argument("--months", type=int, default=18)
    ap.add_argument("--min-price", type=float, default=80_000.0)
    ap.add_argument("--n-comps", type=int, default=6)
    ap.add_argument("--months-back", type=int, default=18)
    ap.add_argument("--as-of-run", type=str, default="2026-06-30")
    ap.add_argument("--coverage", action="store_true", help="Also run Study 2.")
    ap.add_argument("--cov-counties", type=int, default=24)
    ap.add_argument("--cov-per-county", type=int, default=1)
    ap.add_argument("--only-coverage", action="store_true")
    args = ap.parse_args()
    asof_run = bt._as_date(args.as_of_run) or date.today()

    if not args.only_coverage:
        run_accuracy(args.n, args.months, args.min_price, asof_run,
                     args.n_comps, args.months_back)
    if args.coverage or args.only_coverage:
        run_coverage(args.cov_counties, args.cov_per_county, args.months,
                     args.min_price, asof_run, args.n_comps, args.months_back)


if __name__ == "__main__":
    main()
