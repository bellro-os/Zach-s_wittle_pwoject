"""Merge county deed sales (last_sale_date / last_sale_price from CAMA) into MLS data.

The Paragon RETS feed only retains ~3 years of closed sales. County assessors
record every deeded transfer for decades — but only the most recent sale is
exposed via the parcel JSONLs. We merge that one-sale-per-parcel into MLS data
to get pre-2023 sold prices.

Two outputs:
  data/mls/listings_plus_deeds.jsonl     — every MLS row + deed_* columns
  data/mls/deed_sales_nrv.jsonl          — every NRV parcel with an arms-length sale,
                                            keyed by parcel_id (no MLS dependency)
  outputs/mls_analytics/nrv_deed_sales.csv — flat CSV of the deed sales

Filtering: arms-length-likely == last_sale_price > $5,000 AND last_sale_date present.
The price floor catches gift / quitclaim / intra-family transfers (typically $0/$1/$10).
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Reuse the variant/index helpers from join_listings_to_parcels — same mechanics.
sys.path.insert(0, str(Path(__file__).parent))
from join_listings_to_parcels import _variants, _select_parcel_files  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mls_bot.leadgen.helpers import is_owner_occupied  # noqa: E402


NRV_PARCEL_FILES = (
    # Core NRV
    "montgomery_county_parcels_slope.jsonl",
    "blacksburg_parcels.jsonl",
    "pulaski_county_parcels.jsonl",   # raw — slope variant pre-dates the price-mapping fix
    "floyd_county_parcels_slope.jsonl",
    "giles_county_parcels_slope.jsonl",
    "radford_city_parcels.jsonl",     # added 2026-05-06; no price recovery (SALE_AMOUNT empty)
    # NRV-adjacent (have working prices and meaningful MLS listing volume)
    "roanoke_county_parcels_slope.jsonl",
    "carroll_county_parcels_slope.jsonl",
    "wythe_county_parcels_slope.jsonl",
    # Tier 8 expansion: SE/E NRV
    "botetourt_county_parcels.jsonl",
    "bedford_county_parcels.jsonl",   # 50k parcels with up to 3 sales each
)

ARMS_LENGTH_PRICE_FLOOR = 5_000


def _norm_county(s: str | None) -> str:
    return (s or "").strip().upper().replace(" COUNTY", "").replace(" CO.", "").strip()


def _safe_float(v) -> float | None:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_deed_index(parcel_dir: Path) -> tuple[dict[str, dict], list[dict], dict]:
    """Build (variant_index, deed_only_rows, county_stats).

    variant_index: every variant of every NRV parcel with an arms-length sale
    deed_only_rows: one row per NRV parcel with arms-length sale (for export)
    county_stats: per-county totals
    """
    idx: dict[str, dict] = {}
    deed_rows: list[dict] = []
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "with_date": 0, "with_price": 0})

    for fname in NRV_PARCEL_FILES:
        p = parcel_dir / fname
        if not p.exists():
            print(f"[skip] {fname} not found")
            continue
        county_label = fname.replace("_parcels_slope.jsonl", "").replace("_parcels.jsonl", "").upper()
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                stats[county_label]["total"] += 1
                pid = (r.get("parcel_id") or "").strip()
                sd = r.get("last_sale_date")
                sp = _safe_float(r.get("last_sale_price"))
                has_date = bool(sd)
                has_price = sp is not None and sp > ARMS_LENGTH_PRICE_FLOOR
                if has_date:
                    stats[county_label]["with_date"] += 1
                if has_price:
                    stats[county_label]["with_price"] += 1
                if not pid or not has_date:
                    continue
                deed = {
                    "parcel_id": pid,
                    "_parcel_source": fname,
                    "deed_county": county_label,
                    "deed_last_sale_date": sd,
                    "deed_last_sale_price": sp,
                    "deed_arms_length": has_price,
                    "owner1": r.get("owner1"),
                    "site_addr1": r.get("site_addr1"),
                    "mail_addr1": r.get("mail_addr1"),
                    "owner_occupied": is_owner_occupied(r),
                    "jurisdiction": r.get("jurisdiction"),
                    "year_built": r.get("year_built"),
                    "sfla": r.get("sfla"),
                    "acres": r.get("acres"),
                    "assessed_total": r.get("assessed_total"),
                    "lat": r.get("lat"),
                    "lng": r.get("lng"),
                }
                # Index every variant; first writer wins (highest-priority file is loaded first
                # via _select_parcel_files in NRV_PARCEL_FILES order — slope > raw)
                for v in _variants(pid):
                    if v not in idx:
                        idx[v] = deed
                if has_price:
                    deed_rows.append(deed)
    return idx, deed_rows, stats


def merge(listings_path: Path, parcel_dir: Path, out_listings: Path,
          out_deeds: Path, out_deeds_csv: Path) -> dict:
    print(f"building deed index from NRV parcels...")
    idx, deed_rows, stats = build_deed_index(parcel_dir)

    print()
    print(f"per-county audit:")
    print(f"  {'county':30s}  {'total':>8s}  {'w/date':>8s}  {'w/price':>8s}  {'price%':>7s}")
    for c, d in sorted(stats.items()):
        rate = (d["with_price"] / d["total"] * 100) if d["total"] else 0
        print(f"  {c:30s}  {d['total']:>8,}  {d['with_date']:>8,}  {d['with_price']:>8,}  {rate:>6.1f}%")
    print(f"  index size: {len(idx):,} variant keys; deed rows (w/price): {len(deed_rows):,}")

    # Stream MLS listings, attach deed columns
    matched_w_price = 0
    matched_date_only = 0
    unmatched = 0
    by_county = Counter()

    out_listings.parent.mkdir(parents=True, exist_ok=True)
    out_deeds.parent.mkdir(parents=True, exist_ok=True)
    out_deeds_csv.parent.mkdir(parents=True, exist_ok=True)

    with listings_path.open("r", encoding="utf-8") as src, \
         out_listings.open("w", encoding="utf-8") as dst:
        for line in src:
            r = json.loads(line)
            pid = (r.get("parcel_id") or "").strip()
            hit = None
            for v in _variants(pid):
                hit = idx.get(v)
                if hit:
                    break
            if hit:
                r["deed_last_sale_date"] = hit.get("deed_last_sale_date")
                r["deed_last_sale_price"] = hit.get("deed_last_sale_price")
                r["deed_county"] = hit.get("deed_county")
                r["deed_arms_length"] = hit.get("deed_arms_length")
                r["parcel_owner_occupied"] = hit.get("owner_occupied")
                r["parcel_owner1"] = hit.get("owner1")
                r["parcel_assessed_total"] = hit.get("assessed_total")
                if hit.get("deed_last_sale_price"):
                    matched_w_price += 1
                else:
                    matched_date_only += 1
                by_county[hit.get("deed_county") or "?"] += 1
            else:
                r["deed_last_sale_date"] = None
                r["deed_last_sale_price"] = None
                r["deed_county"] = None
                r["deed_arms_length"] = None
                r["parcel_owner_occupied"] = None
                r["parcel_owner1"] = None
                r["parcel_assessed_total"] = None
                unmatched += 1
            dst.write(json.dumps(r, default=str) + "\n")

    # Write standalone deed-only file + CSV
    with out_deeds.open("w", encoding="utf-8") as f:
        for d in deed_rows:
            f.write(json.dumps(d, default=str) + "\n")
    if deed_rows:
        cols = list(deed_rows[0].keys())
        with out_deeds_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for d in deed_rows:
                w.writerow(d)

    total = matched_w_price + matched_date_only + unmatched
    print()
    print(f"=== MLS listings merged with deed data ===")
    print(f"  total listings:   {total:,}")
    print(f"  matched w/price:  {matched_w_price:,} ({matched_w_price/total*100:.1f}%)")
    print(f"  matched date only:{matched_date_only:,} ({matched_date_only/total*100:.1f}%)")
    print(f"  unmatched:        {unmatched:,} ({unmatched/total*100:.1f}%)")
    print()
    print(f"matched listings by county (top 10):")
    for c, n in by_county.most_common(10):
        print(f"  {c:25s}  {n:,}")
    print()
    print(f"wrote {out_listings}")
    print(f"wrote {out_deeds}")
    print(f"wrote {out_deeds_csv}")

    return {
        "total_listings": total,
        "matched_w_price": matched_w_price,
        "matched_date_only": matched_date_only,
        "unmatched": unmatched,
        "deed_rows": len(deed_rows),
        "by_county": dict(by_county),
        "audit": {k: dict(v) for k, v in stats.items()},
    }


def main() -> int:
    listings = Path("data/mls/listings.jsonl")
    if not listings.exists():
        print(f"!! {listings} missing — run RETS pull first")
        return 1
    summary = merge(
        listings_path=listings,
        parcel_dir=Path("data"),
        out_listings=Path("data/mls/listings_plus_deeds.jsonl"),
        out_deeds=Path("data/mls/deed_sales_nrv.jsonl"),
        out_deeds_csv=Path("outputs/mls_analytics/nrv_deed_sales.csv"),
    )
    Path("data/mls/deed_merge_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
