"""Per-region CMA calibration store.

The engine's tuning knobs (sqft basis factor, land rates, distance scale) have
always been GLOBAL — one value for every market. This module adds a small,
versioned, human-diffable store (``data/cma_regions.json``) holding per-region
deviations from the global defaults, with a resolution ladder:

    fips5  ->  cbsa:<code>  ->  state:<XX>  ->  global

Only deviations are stored (a region entry carries just the knobs it overrides),
so national scale is a few hundred entries, not thousands.

DEFAULT-SAFE FOR RATIFYLY: nothing in the engine consults this module unless the
caller opts in (the scrape/dial-in tooling). When the JSON file is absent or a
region resolves to nothing, ``knobs_for`` returns the global defaults, which are
exactly today's hard-coded engine constants.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _PROJECT_ROOT / "data" / "cma_regions.json"

# Global defaults == the engine's current constants. sqft_factor documents the
# SUPPLEMENTAL pool's build-time scaling (0.76 was the Montgomery cross-basis
# fit); in fully scrape-based (same-basis) runs the honest default is 1.0 and
# the dial-in loop measures the truth per region.
GLOBAL_DEFAULTS: dict[str, Any] = {
    "sqft_factor": 0.76,
    "land_rate_lo": 5000.0,
    "land_rate_hi": 6500.0,
    "dist_scale": 5.0,
}

_cache: dict[str, Any] | None = None
_cache_path: str | None = None


def _load(path: Optional[str] = None) -> dict[str, Any]:
    global _cache, _cache_path
    p = str(path or os.environ.get("CMA_REGIONS_JSON") or _DEFAULT_PATH)
    if _cache is not None and _cache_path == p:
        return _cache
    data: dict[str, Any] = {"version": 1, "global": {}, "regions": {}}
    try:
        with open(p, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass  # absent/corrupt file -> pure defaults (default-safe)
    _cache, _cache_path = data, p
    return data


def invalidate_cache() -> None:
    global _cache
    _cache = None


def _norm_county(name: str) -> str:
    """Normalize a county/jurisdiction display name for matching:
    'Montgomery County' / 'MONTGOMERY' / 'montgomery co.' -> 'montgomery'."""
    s = re.sub(r"[^a-z ]", "", (name or "").lower())
    s = re.sub(r"\b(county|city|co|of)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def region_keys_for(subject: dict[str, Any]) -> list[str]:
    """Precedence-ordered candidate keys for a subject: explicit fips5, then a
    normalized county-name key, then cbsa/state, then nothing (-> global)."""
    keys: list[str] = []
    fips5 = str(subject.get("fips5") or "").strip()
    if len(fips5) == 5 and fips5.isdigit():
        keys.append(fips5)
    county = _norm_county(str(subject.get("county") or ""))
    state = str(subject.get("state") or "VA").strip().upper()[:2]
    if county:
        keys.append(f"county:{state.lower()}:{county}")
    cbsa = str(subject.get("cbsa") or "").strip()
    if cbsa:
        keys.append(f"cbsa:{cbsa}")
    if state:
        keys.append(f"state:{state}")
    return keys


def knobs_for(subject: dict[str, Any], path: Optional[str] = None) -> dict[str, Any]:
    """Effective knob dict for a subject: the most specific matching region's
    entries merged over the file's ``global`` block merged over GLOBAL_DEFAULTS.
    Never raises; never returns non-knob metadata (``_meta`` etc. stripped)."""
    data = _load(path)
    out = dict(GLOBAL_DEFAULTS)
    for k, v in (data.get("global") or {}).items():
        if not k.startswith("_"):
            out[k] = v
    regions = data.get("regions") or {}
    for key in region_keys_for(subject):
        entry = regions.get(key)
        if isinstance(entry, dict):
            for k, v in entry.items():
                if not k.startswith("_"):
                    out[k] = v
            break  # most specific wins; no cascading across siblings
    return out


def write_region(key: str, knobs: dict[str, Any], meta: dict[str, Any],
                 path: Optional[str] = None) -> None:
    """Insert/update one region entry (knobs + ``_meta``) atomically."""
    p = Path(str(path or os.environ.get("CMA_REGIONS_JSON") or _DEFAULT_PATH))
    data = dict(_load(str(p)))
    regions = dict(data.get("regions") or {})
    regions[key] = {**{k: v for k, v in knobs.items() if not k.startswith("_")},
                    "_meta": meta}
    data["regions"] = regions
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    invalidate_cache()
