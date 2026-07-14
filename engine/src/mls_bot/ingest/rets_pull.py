"""RETS pull for the NRV MLS (Paragon-hosted).

Writes canonical listing rows to JSONL on disk. Replaces the Postgres-targeted
RETS path stubbed in mls.py. Self-contained — depends only on the `rets`
package, dotenv, and our field map JSON.

Public entry points:
    pull_class(class_id, ...)           -> yields canonical row dicts
    pull_all(field_map_path, out_path)  -> pulls all 6 classes, writes JSONL

Output schema: see scripts/build_field_map.py for canonical column names.
A `_raw` column preserves the unmapped RETS row for future re-mapping.
A `_class` column records which Property class the row came from.
A `_pulled_at` column is an ISO timestamp from the local clock.

Status lookup is auto-resolved by the rets library (returns 'Active' / 'Closed'
/ 'Pending' / 'Expired/Cancelled' / 'Withdrawn' / 'Rented/Leased' instead of
the integer ID).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from dotenv import load_dotenv
from rets import Session


# Status integer IDs (from the Status lookup):
#   1=Active 2=Closed 3=Pending 4=Expired/Cancelled 5=Withdrawn 6=Rented/Leased
STATUS_IDS = (1, 2, 3, 4, 5, 6)

CLASSES = ("RE_1", "MF_2", "LD_3", "CM_4", "FM_5", "RN_6")

# Year ranges where rural/inactive years would be empty anyway, but we err
# on the safe side — the LD_3 sample showed listings going back to 1999.
DEFAULT_YEAR_START = 1995
DEFAULT_YEAR_END = datetime.now().year


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce(v: object) -> object:
    """Normalize empty strings to None; preserve rest as-is."""
    if v is None or v == "":
        return None
    return v


def open_session() -> Session:
    load_dotenv()
    sess = Session(
        login_url=os.environ["MLS_RETS_LOGIN_URL"],
        username=os.environ["MLS_RETS_USERNAME"],
        password=os.environ["MLS_RETS_PASSWORD"],
        user_agent=os.environ.get("MLS_RETS_USER_AGENT") or "mls-bot/0.1",
        user_agent_password=os.environ.get("MLS_RETS_UA_PASSWORD") or None,
    )
    sess.login()
    return sess


def load_field_map(path: str | Path) -> dict[str, dict[str, str]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def map_row(raw: dict, class_id: str, field_map: dict[str, dict[str, str]]) -> dict:
    """Apply the per-class canonical map. Unknown fields go into `_raw`."""
    cmap = field_map.get(class_id, {})
    out: dict[str, object] = {"_class": class_id, "_pulled_at": _iso()}
    mapped_sys_names = set(cmap.values())
    for canon, sys_name in cmap.items():
        out[canon] = _coerce(raw.get(sys_name))
    # Preserve everything not in the canonical map for forensic / re-map use.
    extras = {k: v for k, v in raw.items() if k not in mapped_sys_names and v not in (None, "")}
    out["_raw"] = extras
    return out


def _search_chunk(
    sess: Session,
    class_id: str,
    dmql_query: str,
    *,
    limit: int = 9_999_999,
) -> Iterator[dict]:
    """Run a single DMQL search; yield raw rows. Library handles offset paging."""
    results = sess.search(
        resource="Property",
        resource_class=class_id,
        dmql_query=dmql_query,
        limit=limit,
        standard_names=0,
        auto_offset=True,
    )
    for row in results:
        yield row


def pull_class(
    sess: Session,
    class_id: str,
    field_map: dict[str, dict[str, str]],
    *,
    progress_every: int = 1000,
) -> Iterator[dict]:
    """Pull every listing in `class_id`. Yields canonical rows.

    The library's auto_offset paginates through the server-side row cap
    automatically, so a single (L_ListingID=0+) catch-all is sufficient.
    """
    seen_ids: set[str] = set()
    total = 0
    try:
        rows = _search_chunk(sess, class_id, "(L_ListingID=0+)")
        for raw in rows:
            lid = raw.get("L_ListingID")
            if not lid or lid in seen_ids:
                continue
            seen_ids.add(lid)
            total += 1
            yield map_row(raw, class_id, field_map)
            if total % progress_every == 0:
                print(f"    {class_id}: {total} rows")
    except Exception as e:
        msg = str(e).lower()
        if "no records" not in msg:
            print(f"  [warn] {class_id}: {e}")


def pull_all(
    field_map_path: str | Path,
    out_listings: str | Path,
    out_pulls_log: str | Path,
    *,
    classes: Iterable[str] = CLASSES,
) -> dict:
    """Run a full backfill across the given classes; write listings JSONL.

    Returns a summary dict (also appended to out_pulls_log).
    """
    field_map = load_field_map(field_map_path)
    out_listings = Path(out_listings)
    out_listings.parent.mkdir(parents=True, exist_ok=True)
    out_pulls_log = Path(out_pulls_log)
    out_pulls_log.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    started_iso = _iso()
    counts: dict[str, int] = {}

    sess = open_session()
    try:
        with out_listings.open("w", encoding="utf-8") as f:
            for cid in classes:
                t0 = time.time()
                print(f"\n=== {cid} ===")
                n = 0
                for row in pull_class(sess, cid, field_map):
                    f.write(json.dumps(row, default=str) + "\n")
                    n += 1
                counts[cid] = n
                print(f"  {cid} done: {n} rows in {time.time()-t0:.1f}s")
    finally:
        try:
            sess.logout()
        except Exception:
            pass

    summary = {
        "started_at": started_iso,
        "ended_at": _iso(),
        "elapsed_s": round(time.time() - started, 1),
        "counts": counts,
        "total": sum(counts.values()),
        "out_listings": str(out_listings),
    }
    with out_pulls_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, default=str) + "\n")
    return summary
