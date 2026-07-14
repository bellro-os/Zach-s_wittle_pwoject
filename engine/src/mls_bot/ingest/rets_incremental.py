"""Incremental RETS pull — fetches only listings updated since the last run.

Uses `L_UpdateDate >= last_pull_timestamp` so we only pull rows that changed.
Detects status / price transitions vs. the prior listings.jsonl and appends
those to listings_history.jsonl (append-only, one row per observed change).

Storage layout maintained:
    data/mls/listings.jsonl              — current snapshot (upserted by listing_id)
    data/mls/listings_history.jsonl      — append-only state transitions
    data/mls/pulls_log.jsonl             — pull metadata (last-run anchor)

Strategy:
1. Read the last successful pull's `ended_at` from pulls_log.jsonl. Subtract
   1 hour as a safety overlap (idempotent: dupes are deduped by listing_id +
   change-detection).
2. For each class, run SEARCH with `(L_UpdateDate=ANCHOR+)`.
3. Map updated rows to canonical schema using the field map.
4. Diff against the existing listings.jsonl by listing_id:
   - New listing_id → write to history with kind='new'.
   - Status changed → history kind='status_change'.
   - List price changed → history kind='price_change' (with delta).
   - Sold price changed → history kind='sold_price_set'.
5. Rewrite listings.jsonl with upserted state. Append history rows.
6. Append a new pull-log entry.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .rets_pull import open_session, load_field_map, map_row, CLASSES


SAFETY_OVERLAP_HOURS = 1


def _last_anchor(pulls_log: Path) -> datetime:
    """Return the latest `ended_at` from pulls_log, minus the safety overlap.
    If no log exists, return epoch (forces a full pull semantics, but caller
    should use rets_pull.pull_all for the initial backfill instead)."""
    if not pulls_log.exists():
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    last_end = None
    with pulls_log.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                t = e.get("ended_at")
                if t:
                    last_end = t
            except Exception:
                continue
    if not last_end:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    if isinstance(last_end, str):
        last_end = datetime.fromisoformat(last_end)
    if last_end.tzinfo is None:
        last_end = last_end.replace(tzinfo=timezone.utc)
    return last_end - timedelta(hours=SAFETY_OVERLAP_HOURS)


def _dmql_anchor(anchor: datetime) -> str:
    # RETS DMQL date format: YYYY-MM-DDTHH:MM:SS+ for "≥ this time".
    return anchor.strftime("%Y-%m-%dT%H:%M:%S+")


def _index_listings(listings_path: Path) -> dict[str, dict]:
    if not listings_path.exists():
        return {}
    idx: dict[str, dict] = {}
    with listings_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lid = r.get("listing_id")
            if lid:
                idx[lid] = r
    return idx


def _detect_changes(prev: dict | None, curr: dict, observed_at: str) -> list[dict]:
    """Return a list of history events between prev and curr. May be 0..N events."""
    out: list[dict] = []
    base = {
        "listing_id": curr.get("listing_id"),
        "_class": curr.get("_class"),
        "observed_at": observed_at,
        "city": curr.get("city"),
        "address": curr.get("address"),
    }
    if prev is None:
        out.append({**base, "kind": "new",
                    "status": curr.get("status_category"),
                    "list_price": curr.get("list_price")})
        return out
    if prev.get("status_category") != curr.get("status_category"):
        out.append({**base, "kind": "status_change",
                    "from_status": prev.get("status_category"),
                    "to_status": curr.get("status_category"),
                    "list_price": curr.get("list_price")})
    try:
        p_old = float(prev.get("list_price") or 0)
        p_new = float(curr.get("list_price") or 0)
    except (TypeError, ValueError):
        p_old = p_new = 0
    if p_old != p_new and p_old > 0 and p_new > 0:
        delta = p_new - p_old
        pct = round(delta / p_old * 100, 2) if p_old else None
        out.append({**base, "kind": "price_change",
                    "from_price": p_old, "to_price": p_new,
                    "delta": delta, "delta_pct": pct})
    if not prev.get("sold_price") and curr.get("sold_price"):
        out.append({**base, "kind": "sold_price_set",
                    "sold_price": curr.get("sold_price"),
                    "close_date": curr.get("close_date")})
    return out


def pull_incremental(
    field_map_path: str | Path = "outputs/rets_metadata/field_map.json",
    listings_path: str | Path = "data/mls/listings.jsonl",
    history_path: str | Path = "data/mls/listings_history.jsonl",
    pulls_log_path: str | Path = "data/mls/pulls_log.jsonl",
    *,
    classes: Iterable[str] = CLASSES,
    force_anchor: datetime | None = None,
) -> dict:
    listings_path = Path(listings_path)
    history_path = Path(history_path)
    pulls_log_path = Path(pulls_log_path)
    field_map = load_field_map(field_map_path)

    anchor = force_anchor or _last_anchor(pulls_log_path)
    anchor_dmql = _dmql_anchor(anchor)
    print(f"anchor: {anchor.isoformat()} (dmql: {anchor_dmql})")

    print(f"loading existing snapshot from {listings_path} ...")
    prev_index = _index_listings(listings_path)
    print(f"  {len(prev_index):,} existing listings")

    started = time.time()
    started_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    history_rows: list[dict] = []
    upserts: dict[str, dict] = {}

    sess = open_session()
    try:
        from rets import Session  # noqa: F401  (used implicitly via sess)
        for cid in classes:
            t0 = time.time()
            print(f"  {cid} ...")
            n = 0
            try:
                results = sess.search(
                    resource="Property",
                    resource_class=cid,
                    dmql_query=f"(L_UpdateDate={anchor_dmql})",
                    limit=9_999_999,
                    standard_names=0,
                    auto_offset=True,
                )
                for raw in results:
                    lid = raw.get("L_ListingID")
                    if not lid:
                        continue
                    canonical = map_row(raw, cid, field_map)
                    upserts[lid] = canonical
                    history_rows.extend(_detect_changes(prev_index.get(lid), canonical, started_iso))
                    n += 1
            except Exception as e:
                msg = str(e).lower()
                if "no records" in msg:
                    n = 0
                else:
                    print(f"    [warn] {cid}: {e}")
            counts[cid] = n
            print(f"    {cid}: {n} rows in {time.time()-t0:.1f}s")
    finally:
        try:
            sess.logout()
        except Exception:
            pass

    # Apply upserts: rewrite listings.jsonl with prev_index + upserts merged.
    if upserts:
        print(f"applying {len(upserts)} upserts...")
        merged = dict(prev_index)
        merged.update(upserts)
        listings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = listings_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in merged.values():
                f.write(json.dumps(r, default=str) + "\n")
        tmp.replace(listings_path)

    # Append history rows
    if history_rows:
        print(f"appending {len(history_rows)} history events...")
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            for h in history_rows:
                f.write(json.dumps(h, default=str) + "\n")

    summary = {
        "started_at": started_iso,
        "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_s": round(time.time() - started, 1),
        "anchor": anchor.isoformat(),
        "counts": counts,
        "total_updates": sum(counts.values()),
        "upserts_applied": len(upserts),
        "history_events": len(history_rows),
        "kind": "incremental",
    }
    pulls_log_path.parent.mkdir(parents=True, exist_ok=True)
    with pulls_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, default=str) + "\n")
    return summary
