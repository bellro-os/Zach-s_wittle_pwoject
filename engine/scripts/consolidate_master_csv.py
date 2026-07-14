"""Merge the three preset-specific v3 CSVs into one master CSV.

Each row is a unique parcel keyed on (county, parcel_id). All shared
parcel/distance/site columns appear once. Score and pass/fail columns
appear once per preset:

  score_piedmont, passed_piedmont, failed_piedmont
  score_appalachian, passed_appalachian, failed_appalachian
  score_hyperscale, passed_hyperscale, failed_hyperscale

Output: outputs/all_parcels_dc_master.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


PRESETS = ("piedmont", "appalachian", "hyperscale")

# Per-row fields that don't depend on the preset (everything except score
# and the pass/fail flags).
SHARED_FIELDS = [
    "county", "parcel_id", "jurisdiction", "site",
    "owner", "owner2", "owner_type", "mail_addr1", "mail_addr2",
    "zoning", "subd_name", "year_built",
    "assessed_total", "assessed_land", "assessed_bldg",
    "last_sale_date", "last_sale_price",
    "acres", "lat", "lng",
    "slope_mean_pct", "slope_max_pct",
    "pct_under_5pct_slope", "pct_under_10pct_slope", "pct_under_15pct_slope",
    "miles_to_sub_min_volt", "min_volt_at_nearest_sub_kv",
    "miles_to_any_sub", "any_sub_voltage_kv",
    "miles_to_wwtp", "miles_to_nearest_residential",
    "miles_to_major_highway", "miles_to_existing_dc",
    "in_opportunity_zone", "in_floodplain",
    "primary_utility", "queue_tier", "tax_tier_score",
]


def main() -> int:
    root = Path(__file__).parent.parent
    out_path = root / "outputs" / "all_parcels_dc_master.csv"

    merged: dict[tuple[str, str], dict] = {}

    for preset in PRESETS:
        in_path = root / "outputs" / f"all_parcels_dc_metrics_{preset}_v3.csv"
        if not in_path.exists():
            print(f"  warning: {in_path.name} missing, skipping {preset}")
            continue
        print(f"  reading {in_path.name}...")
        n = 0
        with in_path.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row.get("county") or "", row.get("parcel_id") or "")
                if key not in merged:
                    base = {k: row.get(k, "") for k in SHARED_FIELDS}
                    for p in PRESETS:
                        base[f"score_{p}"] = ""
                        base[f"passed_{p}"] = ""
                        base[f"failed_{p}"] = ""
                    merged[key] = base
                merged[key][f"score_{preset}"] = row.get("score_dc", "")
                merged[key][f"passed_{preset}"] = row.get("passed_hard_filters", "")
                merged[key][f"failed_{preset}"] = row.get("failed_reasons", "")
                n += 1
        print(f"    merged {n:,} rows  (total unique: {len(merged):,})")

    if not merged:
        print("no data merged — aborting")
        return 1

    # Best score across presets (for default sort)
    for r in merged.values():
        scores = []
        for p in PRESETS:
            try:
                scores.append(float(r.get(f"score_{p}") or 0))
            except (TypeError, ValueError):
                pass
        r["best_score"] = round(max(scores), 1) if scores else 0
        # Which presets pass?
        passes = [p for p in PRESETS if r.get(f"passed_{p}") == "Y"]
        r["passes_any"] = "Y" if passes else "N"
        r["presets_passed"] = "+".join(passes) if passes else ""

    fieldnames = (
        SHARED_FIELDS
        + ["best_score", "passes_any", "presets_passed"]
        + [f"score_{p}" for p in PRESETS]
        + [f"passed_{p}" for p in PRESETS]
        + [f"failed_{p}" for p in PRESETS]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(
        merged.values(),
        key=lambda r: (-(r.get("best_score") or 0), r.get("county", ""), r.get("parcel_id", "")),
    )
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(sorted_rows)

    print(f"\n  wrote {len(sorted_rows):,} rows to {out_path}")
    print(f"  passes any preset: {sum(1 for r in sorted_rows if r['passes_any'] == 'Y'):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
