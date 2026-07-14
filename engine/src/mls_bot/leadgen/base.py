"""Lead dataclass + registry for category detectors.

Each detector is a module under mls_bot.leadgen that calls @register("NAME")
on a function with the signature Detector = Callable[[list[dict], dict], list[Lead]].
Rows are parsed assessor JSONL dicts; config is a free-form dict of knobs
passed from the CLI (e.g. {"jurisdiction": "BLACKSBURG", "tenure_min": 3}).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Lead:
    category: str
    key: str                     # unique identifier within this category
    score: int                   # 0-100
    parcels: list[dict] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


Detector = Callable[[list[dict], dict], list[Lead]]
REGISTRY: dict[str, Detector] = {}


def register(name: str) -> Callable[[Detector], Detector]:
    def deco(fn: Detector) -> Detector:
        REGISTRY[name] = fn
        return fn
    return deco


_CSV_EXCLUDED_DETAIL_KEYS = {"summary", "parcels_preview"}


def write_leads_csv(path: str, leads: list[Lead]) -> int:
    """Write leads to CSV. Flat-fields only — dicts/lists in detail are skipped.

    Returns the number of rows written (excluding the header).
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    detail_keys: list[str] = []
    seen: set[str] = set()
    for lead in leads:
        for k, v in lead.detail.items():
            if k in _CSV_EXCLUDED_DETAIL_KEYS or k in seen:
                continue
            if isinstance(v, (dict, list, tuple, set)):
                continue
            detail_keys.append(k)
            seen.add(k)

    fieldnames = ["category", "score", "key"] + detail_keys
    try:
        f = out.open("w", newline="", encoding="utf-8-sig")
    except PermissionError as e:
        raise RuntimeError(
            f"cannot write {out}: the file is locked. "
            f"close it in Excel / your editor and re-run. ({e})"
        ) from e
    with f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for lead in leads:
            row: dict[str, object] = {
                "category": lead.category,
                "score": lead.score,
                "key": lead.key,
            }
            for k in detail_keys:
                row[k] = lead.detail.get(k, "")
            w.writerow(row)
    return len(leads)


def print_leads(category: str, leads: list[Lead]) -> None:
    print(f"\n=== {category} — {len(leads)} leads ===\n")
    if not leads:
        print("(no matches — try loosening filters)")
        return

    print(f"{'#':>3}  {'score':>5}  {'cnt':>4}  summary / key")
    print("-" * 100)
    for i, lead in enumerate(leads, 1):
        summary = lead.detail.get("summary") or lead.key
        print(f"{i:>3}  {lead.score:>5}  {len(lead.parcels):>4}  {summary}")

    print()
    print(f"--- details ({len(leads)}) ---\n")
    for i, lead in enumerate(leads, 1):
        print(f"{i}. {lead.detail.get('summary') or lead.key}")
        for k, v in lead.detail.items():
            if k in ("summary", "parcels_preview"):
                continue
            print(f"   {k}: {v}")
        for line in lead.detail.get("parcels_preview", []):
            print(f"   - {line}")
        print()
