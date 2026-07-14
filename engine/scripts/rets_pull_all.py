"""Full backfill driver — pulls every listing the NRV MLS RETS feed exposes.

Run:
    PYTHONPATH=src python scripts/rets_pull_all.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from mls_bot.ingest.rets_pull import pull_all


def main() -> int:
    field_map = Path("outputs/rets_metadata/field_map.json")
    if not field_map.exists():
        print(f"!! field map missing — run scripts/build_field_map.py first")
        return 1

    summary = pull_all(
        field_map_path=field_map,
        out_listings=Path("data/mls/listings.jsonl"),
        out_pulls_log=Path("data/mls/pulls_log.jsonl"),
    )
    print()
    print("=== summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
