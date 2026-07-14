"""Apply condition extraction across all MLS listings.

Reads each row from data/mls/listings_plus_deeds.jsonl, runs the regex
scorer in mls_bot.analytics.condition, and stamps four columns:

    condition_score   — float 0..5
    condition_flags   — comma-separated list of matched signals
    is_manufactured   — bool
    is_distressed     — bool

Idempotent. Run after the flood enrichment.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mls_bot.analytics.condition import score_remarks  # noqa: E402


LISTINGS_PATH = Path("data/mls/listings_plus_deeds.jsonl")


def main() -> int:
    if not LISTINGS_PATH.exists():
        print(f"!! {LISTINGS_PATH} missing")
        return 1

    started = time.time()
    n_total = n_remarks = n_manuf = n_distress = 0
    score_buckets = {"distressed (0-1)": 0, "needs cosmetic (1-2.5)": 0,
                     "average (2.5-3.5)": 0, "updated (3.5-4.5)": 0, "renovated (4.5+)": 0}
    tmp = LISTINGS_PATH.with_suffix(".jsonl.tmp")
    with LISTINGS_PATH.open("r", encoding="utf-8") as src, \
         tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            try:
                r = json.loads(line)
            except Exception:
                dst.write(line)
                continue
            n_total += 1
            remarks = r.get("public_remarks") or ""
            extra = (r.get("agent_remarks") or "") if isinstance(r.get("agent_remarks"), str) else ""
            full = (remarks + " " + extra).strip()
            cls = score_remarks(full)
            r["condition_score"] = cls["condition_score"]
            r["condition_flags"] = ",".join(cls["condition_flags"]) if cls["condition_flags"] else ""
            r["is_manufactured"] = cls["is_manufactured"]
            r["is_distressed"] = cls["is_distressed"]
            if cls["condition_score"] is not None:
                n_remarks += 1
                s = cls["condition_score"]
                if s < 1: score_buckets["distressed (0-1)"] += 1
                elif s < 2.5: score_buckets["needs cosmetic (1-2.5)"] += 1
                elif s < 3.5: score_buckets["average (2.5-3.5)"] += 1
                elif s < 4.5: score_buckets["updated (3.5-4.5)"] += 1
                else: score_buckets["renovated (4.5+)"] += 1
            if cls["is_manufactured"]:
                n_manuf += 1
            if cls["is_distressed"]:
                n_distress += 1
            dst.write(json.dumps(r, default=str) + "\n")

    tmp.replace(LISTINGS_PATH)
    print(f"=== condition enrichment complete ===")
    print(f"  total listings: {n_total:,}")
    print(f"  with remarks: {n_remarks:,} ({n_remarks/n_total*100:.1f}%)")
    print(f"  manufactured flag: {n_manuf:,}")
    print(f"  distressed flag:   {n_distress:,}")
    print(f"  score distribution:")
    for k, v in score_buckets.items():
        print(f"    {k:>26s}: {v:,}")
    print(f"  elapsed: {time.time()-started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
