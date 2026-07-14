"""RETS Media pull — fetches photo URLs for listings.

We use ObjectType=Photo with location=1 so we get back URLs (not binaries).
Photos stay hosted on Paragon's CDN; we just store the URL list per listing.

Output: data/mls/listings_media.jsonl
  one row per listing with photos:
    {"listing_id": "...", "_class": "RE_1", "n_photos": 41,
     "photos": [{"object_id": 1, "url": "...", "description": "..."}, ...]}

For analytics we typically only care about Active + Pending listings — closed
sales' photos are stale/gone and not useful for live CMAs. Default scope is
status_category in (Active, Pending). Pass `statuses=...` to broaden.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

from .rets_pull import open_session


DEFAULT_STATUSES = ("Active", "Pending")


def _photos_for(sess, listing_id: str) -> list[dict]:
    try:
        objs = list(sess.get_object(
            resource="Property",
            object_type="Photo",
            content_ids=str(listing_id),
            object_ids="*",
            location=1,
        ))
    except Exception as e:
        return [{"_error": str(e)}]
    out = []
    for o in objs:
        if isinstance(o, dict):
            out.append({
                "object_id": o.get("object_id"),
                "url": o.get("location"),
                "description": o.get("content_description"),
                "sub_description": o.get("content_sub_description"),
            })
    return out


def pull_media(
    listings_path: Path | str = "data/mls/listings.jsonl",
    out_path: Path | str = "data/mls/listings_media.jsonl",
    *,
    statuses: Iterable[str] = DEFAULT_STATUSES,
    progress_every: int = 100,
    sleep_s: float = 0.0,
) -> dict:
    listings_path = Path(listings_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    target_ids: list[tuple[str, str]] = []
    statuses_set = set(statuses)
    with listings_path.open("r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("status_category") not in statuses_set:
                continue
            lid = r.get("listing_id")
            cls = r.get("_class")
            if lid:
                target_ids.append((lid, cls))

    print(f"target listings (statuses={list(statuses_set)}): {len(target_ids)}")

    sess = open_session()
    total_photos = 0
    listings_with_photos = 0
    listings_no_photos = 0
    started = time.time()
    try:
        with out_path.open("w", encoding="utf-8") as f:
            for i, (lid, cls) in enumerate(target_ids, 1):
                photos = _photos_for(sess, lid)
                # Filter out error sentinels
                real = [p for p in photos if "_error" not in p]
                row = {
                    "listing_id": lid,
                    "_class": cls,
                    "n_photos": len(real),
                    "photos": real,
                }
                if real:
                    listings_with_photos += 1
                    total_photos += len(real)
                else:
                    listings_no_photos += 1
                f.write(json.dumps(row, default=str) + "\n")
                if i % progress_every == 0:
                    rate = i / (time.time() - started + 1)
                    eta = (len(target_ids) - i) / rate
                    print(f"  {i}/{len(target_ids)}  ({rate:.1f}/s, eta {eta/60:.1f} min)")
                if sleep_s:
                    time.sleep(sleep_s)
    finally:
        try:
            sess.logout()
        except Exception:
            pass

    summary = {
        "elapsed_s": round(time.time() - started, 1),
        "target_listings": len(target_ids),
        "listings_with_photos": listings_with_photos,
        "listings_no_photos": listings_no_photos,
        "total_photos": total_photos,
        "out_path": str(out_path),
    }
    return summary
