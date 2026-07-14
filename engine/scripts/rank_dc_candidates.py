"""Run DC_SUITABILITY across all 24 county slope-enriched JSONLs.

Combines results into a single ranked CSV — rank 1 is highest score statewide.
Also writes per-county top-10 mini CSVs for easy review.

Usage:
    python scripts/rank_dc_candidates.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from mls_bot.leadgen import REGISTRY, write_leads_csv


COUNTIES = [
    "montgomery", "roanoke", "franklin", "floyd", "giles", "carroll",
    "washington", "bland", "lee", "wise", "wythe", "patrick",
    "tazewell", "pulaski", "henry", "craig", "smyth", "buchanan",
    "halifax", "mecklenburg", "brunswick", "lunenburg", "charlotte",
    "pittsylvania",
]


def _load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    root = Path(__file__).parent.parent
    out_dir = root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    per_county_dir = out_dir / "dc_candidates_per_county"
    per_county_dir.mkdir(exist_ok=True)

    detector = REGISTRY["DC_SUITABILITY"]
    config = {"jurisdiction": "ALL"}

    all_leads = []
    t0 = time.time()
    for county in COUNTIES:
        in_path = root / f"data/{county}_county_parcels_slope.jsonl"
        if not in_path.exists():
            print(f"  -- {county:14s} missing {in_path.name}")
            continue
        rows = _load_rows(in_path)
        leads = detector(rows, config)
        if not leads:
            print(f"  -- {county:14s} 0 candidates")
            continue
        # Write per-county top-25 CSV
        write_leads_csv(per_county_dir / f"{county}_top25.csv", leads[:25])
        all_leads.extend(leads)
        print(f"  OK {county:14s} {len(leads):>5} candidates "
              f"(top score {leads[0].score})")

    if not all_leads:
        print("no candidates statewide")
        return 1

    all_leads.sort(key=lambda l: -float(l.detail.get("score_dc") or 0))

    master_csv = out_dir / "dc_candidates_statewide.csv"
    write_leads_csv(master_csv, all_leads)
    top100_csv = out_dir / "dc_candidates_top100.csv"
    write_leads_csv(top100_csv, all_leads[:100])

    print()
    print(f"  Total candidates: {len(all_leads):,}")
    print(f"  Statewide CSV:    {master_csv}")
    print(f"  Top-100 CSV:      {top100_csv}")
    print(f"  Per-county dir:   {per_county_dir}")
    print(f"  Duration:         {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
