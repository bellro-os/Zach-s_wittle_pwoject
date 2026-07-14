"""Run compute_parcel_slope.py across all 24 county geo files in parallel."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


COUNTIES = [
    "montgomery", "roanoke", "franklin", "floyd", "giles", "carroll",
    "washington", "bland", "lee", "wise", "wythe", "patrick",
    "tazewell", "pulaski", "henry", "craig", "smyth", "buchanan",
    "halifax", "mecklenburg", "brunswick", "lunenburg", "charlotte",
    "pittsylvania",
]


def run_one(county: str, root: Path) -> tuple[str, int, str]:
    in_path = root / f"data/{county}_county_parcels_geo.jsonl"
    out_path = root / f"data/{county}_county_parcels_slope.jsonl"
    if not in_path.exists():
        return county, -1, f"missing input: {in_path}"
    cmd = [
        sys.executable,
        str(root / "scripts" / "compute_parcel_slope.py"),
        "--in", str(in_path),
        "--out", str(out_path),
        "--dem-dir", str(root / "data" / "dem"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    return county, proc.returncode, (proc.stdout or proc.stderr).strip().splitlines()[-1] if proc.stdout or proc.stderr else ""


def main() -> int:
    root = Path(__file__).parent.parent
    t0 = time.time()
    workers = 6  # multiple counties in parallel; each opens the same DEM tiles read-only
    print(f"computing slope for {len(COUNTIES)} counties with {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(run_one, c, root): c for c in COUNTIES}
        for fut in as_completed(futures):
            county, rc, msg = fut.result()
            mark = "OK" if rc == 0 else f"!!{rc}"
            print(f"  {mark} {county:15s} {msg}")
    print(f"\nTotal: {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
