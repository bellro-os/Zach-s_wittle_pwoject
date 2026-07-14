"""Top-50 capacity-aware DC site CSV.

Reads the v3 metrics CSVs (one per preset) and emits a single ranked CSV
prioritizing parcels with measurable utility-capacity headroom.

Run after `scripts/enrich_all_parcels_dc_v3.py` so the new Tier-13 columns
are populated.

Output: outputs/dc_capacity_top50_<preset>.csv
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).parent.parent
METRICS_DIR = ROOT / "outputs"


def _f(v) -> float:
    try:
        return float(v) if v not in (None, "", "None") else 0.0
    except (TypeError, ValueError):
        return 0.0


def build_top50(preset: str, n: int = 50) -> Path:
    src = METRICS_DIR / f"all_parcels_dc_metrics_{preset}_v3.csv"
    if not src.exists():
        print(f"  [skip] {src} not found")
        return src
    rows = []
    with src.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("passed_hard_filters") != "Y":
                continue
            cap = _f(r.get("nearest_sub_capacity_proxy"))
            queue = _f(r.get("nearest_sub_pjm_queue_mw"))
            water = _f(r.get("water_mgd_within_5mi"))
            wwtp_resid = _f(r.get("wwtp_residual_mgd"))
            fiber = _f(r.get("fiber_carrier_count"))
            score = _f(r.get("score_dc"))
            # Composite capacity score: heavily weighted on substation tier,
            # subtract queue stress, add the four utility headroom signals.
            cap_score = (
                cap * 0.05
                - min(queue, 3000) * 0.02
                + min(water, 50) * 0.5
                + min(wwtp_resid, 10) * 1.0
                + min(fiber, 5) * 2.0
                + score * 0.5     # keep the existing score as a baseline
            )
            r["_cap_score"] = round(cap_score, 1)
            rows.append(r)
    rows.sort(key=lambda x: -x["_cap_score"])
    rows = rows[:n]

    out_path = METRICS_DIR / f"dc_capacity_top50_{preset}.csv"
    if not rows:
        out_path.write_text("preset,empty\n", encoding="utf-8-sig")
        print(f"  [{preset}] no rows passed hard filters; empty output")
        return out_path

    # Pick the most-relevant columns for the top-50 view
    pick = [
        "_cap_score",
        "score_dc",
        "county", "site", "owner", "parcel_id", "acres",
        "miles_to_any_sub", "any_sub_voltage_kv",
        "nearest_sub_lines", "nearest_sub_capacity_proxy",
        "nearest_sub_pjm_queue_mw", "regional_supply_pressure",
        "water_mgd_within_5mi", "wwtp_residual_mgd",
        "fiber_carrier_count",
        "miles_to_interstate", "miles_to_existing_dc",
        "primary_utility", "queue_tier",
        "in_opportunity_zone",
    ]
    fields = [k for k in pick if k in rows[0]]

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  [{preset}] wrote {len(rows)} top sites -> {out_path}")
    return out_path


def main() -> int:
    print("=== Top-50 capacity-aware DC sites ===")
    for preset in ("piedmont", "appalachian", "hyperscale"):
        build_top50(preset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
