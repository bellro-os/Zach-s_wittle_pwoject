"""Deed-pattern signals derived from existing parcel data.

Multi-decade Circuit Court scraping is a separate, high-effort workstream.
This module instead derives 80% of the deed-pattern value from data already
in `data/<county>_parcels.jsonl` + `data/owner_canonical.jsonl`:

  intra_family_transfer_recent_24mo    last_sale_price near zero AND date < 24mo
  quitclaim_or_gift_recent_24mo        same — we treat $0 / $1 / sub-$5k transfers
                                       as a heuristic for non-arms-length transfer
  acquisition_within_24mo              tenure < 2 years on this parcel
  flipper_pattern (entity-level)       canonical_owner_id holds 3+ parcels each
                                       acquired within the last 5 years

Outputs:
  data/parcel_deed_signals.jsonl       (per parcel)
  outputs/mls_analytics/leads/flipper_owners.csv  (per canonical_owner_id)

These are read by seller_scoring.py to add the new weighted signals.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .owner_dedup import canonicalize, PARCEL_FILES_NRV


OUT_PARCEL_SIGNALS = Path("data/parcel_deed_signals.jsonl")
OUT_FLIPPERS = Path("outputs/mls_analytics/leads/flipper_owners.csv")

# Thresholds
NON_ARMS_LENGTH_PRICE_MAX = 5_000.0   # $0 / $1 / nominal — almost always intra-family
RECENT_TRANSFER_DAYS = 24 * 30         # 24 months
FLIPPER_LOOKBACK_DAYS = 5 * 365        # 5 years
FLIPPER_MIN_PARCELS = 3                # 3+ recent acquisitions = flipper pattern


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _parse_price(v) -> float | None:
    try:
        x = float(v)
        return x if x >= 0 else None
    except (ValueError, TypeError):
        return None


def build_signals(parcel_files: list[tuple[str, str]] | None = None) -> dict:
    """Compute parcel-level + owner-level deed signals."""
    if parcel_files is None:
        parcel_files = PARCEL_FILES_NRV
    today = date.today()
    cutoff_24mo = today.toordinal() - RECENT_TRANSFER_DAYS
    cutoff_5y = today.toordinal() - FLIPPER_LOOKBACK_DAYS

    OUT_PARCEL_SIGNALS.parent.mkdir(parents=True, exist_ok=True)
    OUT_FLIPPERS.parent.mkdir(parents=True, exist_ok=True)

    # Per-canonical-owner: list of (county, parcel_id, sale_date_ordinal, price)
    owner_acquisitions: dict[str, list[tuple]] = defaultdict(list)

    n_total = 0
    n_signaled = 0
    with OUT_PARCEL_SIGNALS.open("w", encoding="utf-8") as out:
        for county, src in parcel_files:
            sp = Path(src)
            if not sp.exists():
                print(f"  [deed_signals] skip {county}: {src} not found")
                continue
            with sp.open("r", encoding="utf-8") as f:
                for line in f:
                    n_total += 1
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    parcel_id = (r.get("parcel_id") or "").strip()
                    if not parcel_id:
                        continue
                    sd = _parse_date(r.get("last_sale_date"))
                    sp_v = _parse_price(r.get("last_sale_price"))
                    sd_ord = sd.toordinal() if sd else None

                    intra_family = (
                        sp_v is not None and sp_v <= NON_ARMS_LENGTH_PRICE_MAX
                        and sd_ord is not None and sd_ord >= cutoff_24mo
                    )
                    acquired_24mo = sd_ord is not None and sd_ord >= cutoff_24mo

                    sig = {
                        "county": county,
                        "parcel_id": parcel_id,
                        "intra_family_transfer_recent_24mo": bool(intra_family),
                        "acquisition_within_24mo": bool(acquired_24mo),
                        "tenure_years_since_last_sale": (
                            round((today - sd).days / 365.25, 1) if sd else None
                        ),
                    }
                    if any([sig["intra_family_transfer_recent_24mo"],
                            sig["acquisition_within_24mo"]]):
                        n_signaled += 1
                    out.write(json.dumps(sig) + "\n")

                    # Track for flipper detection
                    if sd_ord and sd_ord >= cutoff_5y:
                        canon = canonicalize(r.get("owner1"))
                        if canon and canon[1] == "entity":
                            owner_acquisitions[canon[0]].append(
                                (county, parcel_id, sd_ord, sp_v)
                            )

    # Flipper detection: entities with 3+ recent acquisitions
    flippers = []
    for owner_id, acqs in owner_acquisitions.items():
        if len(acqs) >= FLIPPER_MIN_PARCELS:
            acqs_sorted = sorted(acqs, key=lambda x: -x[2])
            most_recent = date.fromordinal(acqs_sorted[0][2])
            flippers.append({
                "canonical_owner_id": owner_id,
                "n_acquisitions_5yr": len(acqs),
                "most_recent_acquisition": most_recent.isoformat(),
                "counties": ";".join(sorted(set(a[0] for a in acqs))),
                "median_acquisition_price": (
                    sorted(a[3] for a in acqs if a[3] is not None)
                    [len([a for a in acqs if a[3] is not None]) // 2]
                    if any(a[3] is not None for a in acqs) else None
                ),
                "sample_parcels": ";".join(
                    f"{a[0]}/{a[1]}" for a in acqs_sorted[:10]
                ),
            })
    flippers.sort(key=lambda x: -x["n_acquisitions_5yr"])

    if flippers:
        with OUT_FLIPPERS.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(flippers[0].keys()))
            w.writeheader()
            for fp in flippers:
                w.writerow(fp)
    else:
        OUT_FLIPPERS.write_text("canonical_owner_id\n", encoding="utf-8-sig")

    return {
        "parcels_scanned": n_total,
        "parcels_with_signals": n_signaled,
        "flipper_owners_detected": len(flippers),
        "parcel_signals_jsonl": str(OUT_PARCEL_SIGNALS),
        "flippers_csv": str(OUT_FLIPPERS),
    }


def load_parcel_signals() -> dict[tuple[str, str], dict]:
    """Reader for seller_scoring: returns {(county, parcel_id): signals}."""
    out: dict[tuple[str, str], dict] = {}
    if not OUT_PARCEL_SIGNALS.exists():
        return out
    with OUT_PARCEL_SIGNALS.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            out[(r.get("county"), r.get("parcel_id"))] = r
    return out


def load_flipper_owner_ids() -> set[str]:
    """Reader for seller_scoring: returns set of canonical_owner_ids flagged as flippers."""
    out: set[str] = set()
    if not OUT_FLIPPERS.exists():
        return out
    with OUT_FLIPPERS.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            cid = (r.get("canonical_owner_id") or "").strip()
            if cid:
                out.add(cid)
    return out
