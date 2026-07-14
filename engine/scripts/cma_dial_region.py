"""Per-region dial-in for the SCRAPE-ONLY comp pipeline.

Self-scored, held-out calibration (locked design decision: ground truth = the
region's own recently-sold scraped sales, each valued with its own sale hidden):

  1. Build a throwaway pool from the scraped source at factor 1.0 (raw basis),
     carrying `sqft_raw` so any candidate factor is applied IN-MEMORY.
  2. Draw N seeded-random recently-sold subjects in the region (subjects use
     RAW sfla — the physical truth; the factor is a COMP-side basis knob).
  3. For each candidate sqft factor: value every subject leave-one-out
     (comp pool filtered to sales strictly before the subject's own sale,
     subject's own parcel excluded), score vs the actual sold price.
  4. Pick the factor bias-first (|median signed error| minimal, median |APE|
     as tiebreak), apply the acceptance gate, and --promote the winner into
     data/cma_regions.json.

Acceptance gate (a region is "dialed in"): N >= 40 scored subjects,
|median signed error| <= 1.5%, median |APE| <= 12%.

Engine safety: runs with CMA_SKIP_AVM=1 and a patched listings connection —
the published pools, env, and the MLS default path are untouched.

  python -X utf8 scripts/cma_dial_region.py --county "Montgomery County" --state VA
      [--fips5 51121] [--months-window 6] [--max-subjects 120]
      [--factors 0.76,0.9,1.0,1.1] [--seed 42] [--promote]

NOTE (same-basis cancellation): with subjects on raw sfla and comps scaled by
f, $/sqft-style estimates scale ~1/f — so in fully scrape-based mode the
bias-zero factor is expected near 1.0. This harness MEASURES that instead of
assuming it; the published cross-basis pool (0.76, MLS-basis subjects) is a
different regime and stays as-is.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_ROOT / "src"))

os.environ.setdefault("CMA_SKIP_AVM", "1")  # scrape profile: comp methods only

import duckdb  # noqa: E402

from mls_bot.analytics import cma_compset  # noqa: E402
from mls_bot.analytics.cma_regions import write_region  # noqa: E402
import build_cma  # noqa: E402


def _build_temp_pool(tmpdir: str) -> Path:
    """Build a raw-basis (factor 1.0) pool with sqft_raw into a temp path."""
    out = Path(tmpdir) / "dial_pool.parquet"
    env = dict(os.environ)
    env["SUPPLEMENTAL_SQFT_FACTOR"] = "1.0"
    env["SUPPLEMENTAL_OUT_PARQUET"] = str(out)
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(_SCRIPTS / "build_supplemental_pool.py")],
        env=env, capture_output=True, text=True, cwd=str(_ROOT),
    )
    if r.returncode != 0 or not out.exists():
        raise SystemExit(f"pool build failed:\n{r.stdout}\n{r.stderr}")
    return out


def _pick_subjects(pool: Path, county_like: str, state: str, months_window: int,
                   max_subjects: int, seed: int) -> list[dict]:
    """Seeded-random recently-sold subjects in the region (raw-basis facts)."""
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT address, city, county, parcel_id, sqft_raw, acres, bedrooms,
               full_baths, latitude, longitude, sold_price, close_date
        FROM read_parquet('{pool.as_posix()}')
        WHERE upper(state) = ?
          AND lower(county) LIKE ?
          AND close_date >= (current_date - INTERVAL {int(months_window)} MONTH)
          AND sold_price >= 80000
          AND sqft_raw > 200 AND bedrooms > 0
          AND latitude IS NOT NULL AND longitude IS NOT NULL
        """,
        [state.upper(), f"%{county_like.lower().replace(' county','').strip()}%"],
    ).fetchall()
    con.close()
    rng = random.Random(seed)
    rng.shuffle(rows)
    subs = []
    for (addr, city, county, pid, sqft_raw, acres, beds, baths, lat, lng,
         sold, close) in rows[:max_subjects]:
        subs.append({
            "address": addr, "city": city, "county": county, "parcel_id": pid,
            "sqft": float(sqft_raw), "acres": float(acres) if acres else None,
            "bedrooms": float(beds) if beds else None,
            "full_baths": float(baths) if baths else None,
            "latitude": float(lat), "longitude": float(lng),
            "_class": "RE_1",
            "_actual_sold": float(sold), "_sold_date": str(close),
        })
    return subs


class _PatchedPool:
    """Patch cma_compset's listings connection: the temp pool with sqft derived
    from sqft_raw at the candidate factor, filtered leave-one-out per subject
    (only sales strictly BEFORE the subject's own sale; own parcel excluded)."""

    def __init__(self, pool: Path):
        self.pool = pool
        self.factor = 1.0
        self.as_of: str = "9999-12-31"
        self.exclude_pid: str = ""
        self._orig = None

    def _connection(self):
        con = duckdb.connect(":memory:")
        con.execute(
            f"""
            CREATE VIEW listings AS
            SELECT * REPLACE (CAST(round(sqft_raw * {self.factor}) AS INTEGER) AS sqft)
            FROM read_parquet('{self.pool.as_posix()}')
            WHERE close_date < DATE '{self.as_of}'
              AND parcel_id <> '{self.exclude_pid}'
            """
        )
        return con

    def __enter__(self):
        self._orig = cma_compset._fast_listings_connection
        cma_compset._fast_listings_connection = lambda: self._connection()
        return self

    def __exit__(self, *a):
        cma_compset._fast_listings_connection = self._orig


def _score(subjects: list[dict], pool: Path, factor: float) -> dict:
    apes, signed, comp_ns, nearest = [], [], [], []
    failed = 0
    with _PatchedPool(pool) as pp:
        pp.factor = factor
        for s in subjects:
            pp.as_of = s["_sold_date"]
            pp.exclude_pid = s["parcel_id"]
            subj = {k: v for k, v in s.items() if not k.startswith("_")}
            try:
                comps = build_cma.prepare_comps(subj, n_comps=6, months_back=18,
                                                ai_hygiene=False)
                if not comps:
                    failed += 1
                    continue
                est = build_cma._estimate_value(subj, comps).mid
            except Exception:
                failed += 1
                continue
            if not est or est <= 0:
                failed += 1
                continue
            actual = s["_actual_sold"]
            err = (est - actual) / actual
            apes.append(abs(err))
            signed.append(err)
            comp_ns.append(len(comps))
            dists = [c.get("_distance_mi") for c in comps
                     if isinstance(c.get("_distance_mi"), (int, float))]
            if dists:
                nearest.append(min(dists))
    n = len(apes)
    if n == 0:
        return {"factor": factor, "n": 0, "failed": failed}
    return {
        "factor": factor,
        "n": n,
        "failed": failed,
        "median_ape_pct": round(statistics.median(apes) * 100, 2),
        "signed_bias_pct": round(statistics.median(signed) * 100, 2),
        "ppe10_pct": round(100 * sum(1 for a in apes if a <= 0.10) / n, 1),
        "ppe20_pct": round(100 * sum(1 for a in apes if a <= 0.20) / n, 1),
        "median_comps": statistics.median(comp_ns),
        "median_nearest_mi": round(statistics.median(nearest), 2) if nearest else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--county", required=True, help='e.g. "Montgomery County"')
    ap.add_argument("--state", default="VA")
    ap.add_argument("--fips5", default=None, help="optional fips5 key for the store")
    ap.add_argument("--months-window", type=int, default=6,
                    help="subjects sold within the last N months (small keeps the "
                         "as-of/time-adjustment error negligible)")
    ap.add_argument("--max-subjects", type=int, default=120)
    ap.add_argument("--factors", default="0.76,0.90,1.00,1.10",
                    help="comma list of comp-side sqft factors to sweep")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--promote", action="store_true",
                    help="write the winning knobs into data/cma_regions.json")
    args = ap.parse_args()

    factors = [float(x) for x in args.factors.split(",") if x.strip()]

    with tempfile.TemporaryDirectory() as td:
        print(f"[dial] building raw-basis temp pool …")
        pool = _build_temp_pool(td)
        subjects = _pick_subjects(pool, args.county, args.state,
                                  args.months_window, args.max_subjects, args.seed)
        print(f"[dial] region={args.county}, {args.state} | subjects={len(subjects)} "
              f"(sold in last {args.months_window} mo, seed {args.seed})")
        if len(subjects) < 40:
            print(f"[dial] REFUSED: {len(subjects)} subjects < 40 floor — region "
                  f"inherits parent/global knobs.")
            return 2

        results = []
        for f in factors:
            r = _score(subjects, pool, f)
            results.append(r)
            print(f"[dial]   f={f:<5} n={r.get('n')} medAPE={r.get('median_ape_pct')}% "
                  f"bias={r.get('signed_bias_pct')}% ppe10={r.get('ppe10_pct')}% "
                  f"nearest={r.get('median_nearest_mi')}mi")

        scored = [r for r in results if r.get("n", 0) >= 40]
        if not scored:
            print("[dial] no factor produced >=40 scored subjects — aborting.")
            return 2
        best = min(scored, key=lambda r: (abs(r["signed_bias_pct"]), r["median_ape_pct"]))
        gate = (abs(best["signed_bias_pct"]) <= 1.5 and best["median_ape_pct"] <= 12.0)
        print(f"\n[dial] WINNER f={best['factor']}  medAPE={best['median_ape_pct']}%  "
              f"bias={best['signed_bias_pct']}%  ppe10={best['ppe10_pct']}%  "
              f"gate={'PASS — dialed in' if gate else 'FAIL — provisional'}")

        key = args.fips5 or f"county:{args.state.lower()}:{args.county.lower().replace(' county','').strip()}"
        meta = {
            "calibrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": "scrape_only_self_scored",
            "n": best["n"],
            "median_ape_pct": best["median_ape_pct"],
            "signed_bias_pct": best["signed_bias_pct"],
            "ppe10_pct": best["ppe10_pct"],
            "ppe20_pct": best["ppe20_pct"],
            "dialed_in": bool(gate),
            "months_window": args.months_window,
            "seed": args.seed,
            "sweep": results,
        }
        if args.promote:
            write_region(key, {"sqft_factor": best["factor"]}, meta)
            print(f"[dial] PROMOTED → data/cma_regions.json ['{key}'] "
                  f"(sqft_factor={best['factor']}, dialed_in={gate})")
        else:
            print(f"[dial] dry-run (no --promote). Would write ['{key}']:")
            print(json.dumps({"sqft_factor": best["factor"], "_meta": meta}, indent=2)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
