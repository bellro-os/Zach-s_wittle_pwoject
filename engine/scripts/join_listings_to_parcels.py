"""Join MLS listings to county parcel data via parcel_id.

Strategy:
1. Build an in-memory index of all parcel JSONLs under data/<county>_parcels*.jsonl.
   For each parcel, also index normalized variants (zero-padded, stripped, etc.)
   to handle the format mismatch between the MLS feed and county records.
2. For each MLS listing in data/mls/listings.jsonl, look up by parcel_id
   trying variants in order. Attach county-side fields (assessed values, owner,
   sfla, year_built, slope, in_floodplain).
3. Write data/mls/listings_with_parcels.jsonl and report match rate per county.

Run:
    PYTHONPATH=src python scripts/join_listings_to_parcels.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


PARCEL_FIELDS_TO_ATTACH = [
    "owner1",
    "owner2",
    "site_addr1",
    "mail_addr1",
    "mail_addr2",
    "assessed_total",
    "assessed_land",
    "assessed_bldg",
    "last_sale_date",
    "last_sale_price",
    "year_built",
    "sfla",
    "acres",
    "zoning",
    "subd_name",
    "lat",
    "lng",
    "slope_mean_pct",
    "pct_under_10pct_slope",
]

# Use the latest enrichment variant per county (slope > geo > raw).
PARCEL_FILE_PRIORITY = ("_slope.jsonl", "_geo.jsonl", ".jsonl")


def _alnum(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s or "").upper()


def _variants(pid: str) -> list[str]:
    """Return all reasonable lookup variants for a parcel id."""
    if not pid:
        return []
    pid = pid.strip().upper()
    out = {pid}
    out.add(_alnum(pid))
    # Numeric: try zero-padding to common widths
    if pid.isdigit():
        for w in (4, 5, 6, 7, 8, 10, 15):
            if len(pid) <= w:
                out.add(pid.zfill(w))
        # And stripped of leading zeros
        out.add(pid.lstrip("0") or "0")
    # Alphanumeric clean: also try with leading-zero trim
    clean = _alnum(pid)
    if clean and clean.isdigit():
        out.add(clean.lstrip("0") or "0")
        for w in (4, 5, 6, 7):
            if len(clean) <= w:
                out.add(clean.zfill(w))
    return [v for v in out if v]


def _select_parcel_files(data_dir: Path) -> list[Path]:
    """Pick the most-enriched parcel file per county-stem."""
    by_stem: dict[str, Path] = {}
    all_files = sorted(data_dir.glob("*_parcels*.jsonl")) + sorted(data_dir.glob("blacksburg_parcels*.jsonl"))
    seen = set()
    for f in all_files:
        if f in seen: continue
        seen.add(f)
        # Compute stem: drop the suffix variant
        name = f.name
        stem = name
        for suf in PARCEL_FILE_PRIORITY:
            if name.endswith(suf):
                stem = name[: -len(suf)]
                break
        # Pick the highest-priority variant for each stem
        existing = by_stem.get(stem)
        if not existing:
            by_stem[stem] = f
            continue
        # Prefer slope > geo > raw
        def rank(p: Path) -> int:
            n = p.name
            if n.endswith("_slope.jsonl"): return 0
            if n.endswith("_geo.jsonl"): return 1
            return 2
        if rank(f) < rank(existing):
            by_stem[stem] = f
    return list(by_stem.values())


def build_parcel_index(data_dir: Path) -> tuple[dict[str, dict], Counter]:
    """Returns (index keyed by canonical+variants, counter of rows per file)."""
    idx: dict[str, dict] = {}
    file_counts: Counter = Counter()
    files = _select_parcel_files(data_dir)
    print(f"loading {len(files)} parcel files:")
    for f in files:
        n = 0
        with f.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                pid = (r.get("parcel_id") or "").strip()
                if not pid:
                    continue
                # Slim row (only the fields we want to attach + jurisdiction)
                slim = {"_parcel_source": f.name, "_parcel_id_raw": pid}
                for k in PARCEL_FIELDS_TO_ATTACH + ["jurisdiction"]:
                    if k in r:
                        slim[k] = r[k]
                # Index by every variant — first writer wins to keep the highest-priority file
                for v in _variants(pid):
                    if v not in idx:
                        idx[v] = slim
                n += 1
        file_counts[f.name] = n
        print(f"  {f.name:55s}  {n:>7} rows")
    print(f"index size: {len(idx)} keys")
    return idx, file_counts


def _county_from_listing(r: dict) -> str:
    return (r.get("county") or "").strip().upper() or "?"


def join(
    listings_path: Path,
    parcel_dir: Path,
    out_path: Path,
    out_csv_path: Path,
) -> dict:
    idx, _file_counts = build_parcel_index(parcel_dir)

    matched = 0
    unmatched = 0
    by_county: dict[str, dict[str, int]] = defaultdict(lambda: {"matched": 0, "unmatched": 0})
    by_class: dict[str, dict[str, int]] = defaultdict(lambda: {"matched": 0, "unmatched": 0})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_csv_path.parent.mkdir(parents=True, exist_ok=True)

    csv_fields: list[str] | None = None
    with listings_path.open("r", encoding="utf-8") as src, \
         out_path.open("w", encoding="utf-8") as dst, \
         out_csv_path.open("w", newline="", encoding="utf-8-sig") as csv_dst:
        for line in src:
            r = json.loads(line)
            pid = (r.get("parcel_id") or "").strip()
            hit = None
            for v in _variants(pid):
                hit = idx.get(v)
                if hit:
                    break
            county = _county_from_listing(r)
            cls = r.get("_class") or "?"
            if hit:
                matched += 1
                by_county[county]["matched"] += 1
                by_class[cls]["matched"] += 1
                # Attach with parcel_ prefix to avoid collision
                for k in PARCEL_FIELDS_TO_ATTACH:
                    if k in hit:
                        r[f"parcel_{k}"] = hit[k]
                r["_parcel_match"] = "parcel_id"
                r["_parcel_source"] = hit.get("_parcel_source")
                r["_parcel_id_raw"] = hit.get("_parcel_id_raw")
            else:
                unmatched += 1
                by_county[county]["unmatched"] += 1
                by_class[cls]["unmatched"] += 1
                r["_parcel_match"] = "unmatched"
            dst.write(json.dumps(r, default=str) + "\n")

            # Flat CSV — drop _raw and dict-typed keys
            flat = {k: v for k, v in r.items() if k != "_raw" and not isinstance(v, (dict, list, tuple, set))}
            if csv_fields is None:
                csv_fields = sorted(flat.keys())
                w = csv.DictWriter(csv_dst, fieldnames=csv_fields, extrasaction="ignore")
                w.writeheader()
            else:
                w = csv.DictWriter(csv_dst, fieldnames=csv_fields, extrasaction="ignore")
            w.writerow(flat)

    print(f"\n=== match results ===")
    total = matched + unmatched
    rate = (matched / total * 100) if total else 0
    print(f"  total: {total}  matched: {matched} ({rate:.1f}%)  unmatched: {unmatched}")
    print(f"\nby class:")
    for cls in sorted(by_class):
        m, u = by_class[cls]["matched"], by_class[cls]["unmatched"]
        t = m + u
        r = m / t * 100 if t else 0
        print(f"  {cls:6s}  total {t:>7}  matched {m:>7} ({r:>5.1f}%)")
    print(f"\nby county (top 15 by total):")
    counties_ranked = sorted(by_county.items(), key=lambda kv: -(kv[1]["matched"] + kv[1]["unmatched"]))
    for c, d in counties_ranked[:15]:
        m, u = d["matched"], d["unmatched"]
        t = m + u
        r = m / t * 100 if t else 0
        print(f"  {c:25s}  total {t:>7}  matched {m:>7} ({r:>5.1f}%)")
    return {
        "total": total,
        "matched": matched,
        "unmatched": unmatched,
        "match_rate": round(rate, 2),
        "by_county": dict(by_county),
        "by_class": dict(by_class),
    }


def main() -> int:
    listings = Path("data/mls/listings.jsonl")
    if not listings.exists():
        print(f"!! {listings} missing — run scripts/rets_pull_all.py first")
        return 1
    summary = join(
        listings_path=listings,
        parcel_dir=Path("data"),
        out_path=Path("data/mls/listings_with_parcels.jsonl"),
        out_csv_path=Path("outputs/mls_analytics/listings_with_parcels.csv"),
    )
    Path("data/mls/join_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
