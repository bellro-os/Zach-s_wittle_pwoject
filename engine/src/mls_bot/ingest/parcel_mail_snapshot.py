"""Periodic snapshot of parcel mailing addresses.

Each run captures `(county, parcel_id, owner1, owner1_canonical_id,
mail_addr_normalized, snapshot_date)` to a per-month JSONL under
`data/snapshots/parcel_mail_<YYYY-MM>.jsonl`. Re-running in the same month
overwrites that month's snapshot.

The diff helper compares two snapshots and returns the set of parcels whose
mailing address changed. The `mail_addr_changed_within_18mo` seller-score
signal is built from this diff history.

First run is the baseline — no diffs are produced. Run monthly via Task
Scheduler (or whenever `mls-daily` runs, idempotently overwriting the
current month). 18 months of monthly snapshots is the steady-state target.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from ..analytics.owner_dedup import canonicalize


SNAPSHOT_DIR = Path("data/snapshots")

PARCEL_FILES_NRV = [
    ("MONTGOMERY", "data/montgomery_county_parcels.jsonl"),
    ("PULASKI",    "data/pulaski_county_parcels.jsonl"),
    ("FLOYD",      "data/floyd_county_parcels.jsonl"),
    ("GILES",      "data/giles_county_parcels.jsonl"),
    ("RADFORD",    "data/radford_city_parcels.jsonl"),
]


def _normalize_mail(addr1: str | None, addr2: str | None) -> str:
    """Collapse formatting variation so cosmetic re-keying isn't read as a move."""
    s = " ".join(x.strip() for x in (addr1 or "", addr2 or "") if (x or "").strip())
    s = s.upper()
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"\b(STREET|STR\.?)\b", "ST", s)
    s = re.sub(r"\b(AVENUE|AVE\.?)\b", "AVE", s)
    s = re.sub(r"\b(ROAD|RD\.?)\b", "RD", s)
    s = re.sub(r"\b(DRIVE|DR\.?)\b", "DR", s)
    s = re.sub(r"\b(BOULEVARD|BLVD\.?)\b", "BLVD", s)
    s = re.sub(r"\b(LANE|LN\.?)\b", "LN", s)
    s = re.sub(r"\b(CIRCLE|CIR\.?)\b", "CIR", s)
    s = re.sub(r"\b(COURT|CT\.?)\b", "CT", s)
    s = re.sub(r"\b(PLACE|PL\.?)\b", "PL", s)
    s = re.sub(r"\bAPARTMENT\b|\bAPT\b", "APT", s)
    s = re.sub(r"\bSUITE\b|\bSTE\b", "STE", s)
    s = re.sub(r"\b(NORTH|N\.?)\b", "N", s)
    s = re.sub(r"\b(SOUTH|S\.?)\b", "S", s)
    s = re.sub(r"\b(EAST|E\.?)\b", "E", s)
    s = re.sub(r"\b(WEST|W\.?)\b", "W", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def take_snapshot(*, snapshot_date: date | None = None,
                  parcel_files: list[tuple[str, str]] | None = None) -> dict:
    """Capture the current mailing-address state. Returns summary dict.

    Idempotent within a calendar month — re-runs overwrite that month's file.
    """
    if snapshot_date is None:
        snapshot_date = date.today()
    if parcel_files is None:
        parcel_files = PARCEL_FILES_NRV
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SNAPSHOT_DIR / f"parcel_mail_{snapshot_date.strftime('%Y-%m')}.jsonl"

    n_total = 0
    n_written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for county, src in parcel_files:
            sp = Path(src)
            if not sp.exists():
                print(f"  [mail_snapshot] skip {county}: {src} not found")
                continue
            with sp.open("r", encoding="utf-8") as g:
                for line in g:
                    n_total += 1
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    parcel_id = (r.get("parcel_id") or "").strip()
                    if not parcel_id:
                        continue
                    norm = _normalize_mail(r.get("mail_addr1"), r.get("mail_addr2"))
                    if not norm:
                        continue
                    canon = canonicalize(r.get("owner1"))
                    f.write(json.dumps({
                        "county": county,
                        "parcel_id": parcel_id,
                        "owner1": r.get("owner1"),
                        "owner1_canonical_id": canon[0] if canon else None,
                        "mail_norm": norm,
                        "snapshot_date": snapshot_date.isoformat(),
                    }) + "\n")
                    n_written += 1
    return {
        "snapshot_date": snapshot_date.isoformat(),
        "out_path": str(out_path),
        "rows_scanned": n_total,
        "rows_captured": n_written,
    }


def list_snapshots() -> list[Path]:
    """Return chronologically-sorted list of snapshot files on disk."""
    if not SNAPSHOT_DIR.exists():
        return []
    return sorted(SNAPSHOT_DIR.glob("parcel_mail_*.jsonl"))


def _load_snapshot(path: Path) -> dict[tuple[str, str], dict]:
    """Return {(county, parcel_id): row}."""
    out: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            out[(r.get("county"), r.get("parcel_id"))] = r
    return out


def diff_against_baseline(*, baseline_age_months: int = 18) -> dict:
    """Compare the latest snapshot against the oldest one within the lookback window.

    Returns:
      {
        'baseline': <path>,
        'latest':   <path>,
        'changed':  [(county, parcel_id, old_mail, new_mail, owner1), ...],
        'changed_n': int,
      }

    Used by seller_scoring to populate `mail_addr_changed_within_18mo`.
    """
    snaps = list_snapshots()
    if len(snaps) < 2:
        return {"changed": [], "changed_n": 0,
                 "msg": f"need 2+ snapshots; have {len(snaps)} — take more over time"}

    latest = snaps[-1]
    # Find the oldest snapshot within the lookback window
    today = date.today()
    cutoff = date(today.year, today.month, 1)
    months_back = baseline_age_months
    target_year = cutoff.year - (months_back // 12)
    target_month = cutoff.month - (months_back % 12)
    while target_month <= 0:
        target_month += 12
        target_year -= 1
    cutoff_str = f"{target_year:04d}-{target_month:02d}"
    baseline = next((s for s in snaps if s.stem.endswith(cutoff_str) or
                     s.stem.split("_")[-1] >= cutoff_str), snaps[0])
    if baseline == latest:
        return {"changed": [], "changed_n": 0,
                 "msg": "no older snapshot available within window"}

    base = _load_snapshot(baseline)
    cur = _load_snapshot(latest)
    changed: list[tuple] = []
    for key, c_row in cur.items():
        b_row = base.get(key)
        if not b_row:
            continue   # new parcel — not "changed"
        if b_row.get("mail_norm") != c_row.get("mail_norm"):
            changed.append((
                key[0], key[1],
                b_row.get("mail_norm"),
                c_row.get("mail_norm"),
                c_row.get("owner1"),
            ))
    return {
        "baseline": str(baseline),
        "latest": str(latest),
        "changed": changed,
        "changed_n": len(changed),
    }


def changed_parcel_ids(*, baseline_age_months: int = 18) -> set[tuple[str, str]]:
    """Convenience set of (county, parcel_id) for the seller-score signal."""
    d = diff_against_baseline(baseline_age_months=baseline_age_months)
    return {(c, p) for (c, p, *_rest) in d.get("changed") or []}
