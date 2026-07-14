"""One-time backfill of data/mls/listings_history.jsonl.

The history log only contains events observed since the first incremental
run. To bootstrap, we synthesize 'price_change' history rows for every
listing where original_list_price != list_price — using list_date as the
observed_at since we don't know when the cut happened.

Also synthesizes 'sold_price_set' for every closed listing using close_date.
And 'status_change' (initial: → final) for every listing using status_changed_at.

This won't add fidelity (we don't know the intermediate steps), but it gives
the analytics modules a non-empty history to work with for cohort summaries.

Run:
    PYTHONPATH=src python scripts/backfill_history.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


LISTINGS = Path("data/mls/listings.jsonl")
HISTORY = Path("data/mls/listings_history.jsonl")


def _safe_float(v) -> float | None:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    if not LISTINGS.exists():
        print(f"!! {LISTINGS} missing")
        return 1
    HISTORY.parent.mkdir(parents=True, exist_ok=True)

    n_price = n_sold = n_status = 0
    observed_at_synth = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat(timespec="seconds")

    with LISTINGS.open("r", encoding="utf-8") as src, \
         HISTORY.open("a", encoding="utf-8") as dst:
        for line in src:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lid = r.get("listing_id")
            if not lid:
                continue
            base = {
                "listing_id": lid,
                "_class": r.get("_class"),
                "city": r.get("city"),
                "address": r.get("address"),
                "_synthetic": True,
            }

            # price_change — original vs final list price
            orig = _safe_float(r.get("original_list_price"))
            final_ = _safe_float(r.get("list_price"))
            if orig and final_ and orig != final_ and orig > 0:
                delta = final_ - orig
                pct = round(delta / orig * 100, 2)
                row = {
                    **base,
                    "kind": "price_change",
                    "from_price": orig,
                    "to_price": final_,
                    "delta": delta,
                    "delta_pct": pct,
                    "observed_at": str(r.get("status_changed_at") or r.get("close_date") or r.get("off_market_date") or observed_at_synth),
                }
                dst.write(json.dumps(row, default=str) + "\n")
                n_price += 1

            # sold_price_set — for any closed listing
            sold_price = _safe_float(r.get("sold_price"))
            close_date = r.get("close_date")
            if sold_price and close_date:
                row = {
                    **base,
                    "kind": "sold_price_set",
                    "sold_price": sold_price,
                    "close_date": close_date,
                    "observed_at": str(close_date),
                }
                dst.write(json.dumps(row, default=str) + "\n")
                n_sold += 1

            # status_change — initial Active → final status (synthetic)
            final_status = r.get("status_category")
            if final_status and final_status != "Active":
                row = {
                    **base,
                    "kind": "status_change",
                    "from_status": "Active",
                    "to_status": final_status,
                    "list_price": final_,
                    "observed_at": str(r.get("status_changed_at") or r.get("off_market_date") or r.get("close_date") or observed_at_synth),
                }
                dst.write(json.dumps(row, default=str) + "\n")
                n_status += 1

    print(f"appended to {HISTORY}:")
    print(f"  price_change events:   {n_price:,}")
    print(f"  sold_price_set events: {n_sold:,}")
    print(f"  status_change events:  {n_status:,}")
    print(f"  total: {n_price + n_sold + n_status:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
