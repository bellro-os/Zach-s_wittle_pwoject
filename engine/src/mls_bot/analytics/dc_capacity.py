"""Loaders for the new DC capacity signals.

Consumed by `scripts/enrich_all_parcels_dc_v3.py` to attach per-parcel
capacity-aware fields. All loaders degrade gracefully when source JSONLs
are missing or empty (return empty dict / zero).

Sources (populated by `scripts/fetch_capacity_signals.py`):
    data/pjm_queue.jsonl
    data/eia_generators_va.jsonl
    data/va_water_withdrawals.jsonl
    data/va_vpdes_volumes.jsonl
    data/va_fcc_fiber.jsonl
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np


# ---------- substation-name canonicalization -------------------------------

_SUB_TOKENS_TO_DROP = re.compile(
    r"\b(SUBSTATION|SUB|SWITCHING|STATION|TAP|JCT|JUNCTION|TIE)\b",
    re.IGNORECASE,
)


def canon_sub_name(name: str | None) -> str:
    """Normalize substation names so 'Mosby' / 'MOSBY SUB' / 'Mosby Substation' merge."""
    s = (name or "").upper()
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = _SUB_TOKENS_TO_DROP.sub("", s)
    s = re.sub(r"\b\d+\s*KV\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------- PJM queue ------------------------------------------------------

def load_pjm_queue_by_sub(path: Path = Path("data/pjm_queue.jsonl")) -> dict[str, dict]:
    """Return {canonical_substation_name: {'queue_mw': float, 'count': int}}.

    Aggregates pending PJM interconnection requests per substation as a proxy
    for corridor stress. High aggregate MW means the substation already has
    a queue of generation/load contesting its capacity.
    """
    out: dict[str, dict] = defaultdict(lambda: {"queue_mw": 0.0, "count": 0})
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            sub = canon_sub_name(r.get("poi_substation"))
            if not sub:
                continue
            mw = r.get("mw")
            if mw:
                out[sub]["queue_mw"] += float(mw)
            out[sub]["count"] += 1
    return dict(out)


# ---------- EIA generators -> regional supply pressure ---------------------

# Heuristic VA-county to PJM sub-zone mapping. Approximate; refine when EIA
# data + zone boundary data is available.
_DOM_ZONE_COUNTIES = {
    # Northern Virginia (DOM zone, supply-constrained for new DC load)
    "ARLINGTON", "FAIRFAX", "FAIRFAX_CITY", "LOUDOUN", "PRINCE_WILLIAM",
    "STAFFORD", "FAUQUIER", "MANASSAS", "FALLS_CHURCH", "ALEXANDRIA",
    # Richmond + Tidewater + central VA (DOM zone, mostly balanced)
    "RICHMOND", "HENRICO", "CHESTERFIELD", "HANOVER", "GOOCHLAND",
    "POWHATAN", "AMELIA", "DINWIDDIE", "PRINCE_GEORGE", "PETERSBURG",
    "SURRY", "ISLE_OF_WIGHT", "SUFFOLK", "VIRGINIA_BEACH", "CHESAPEAKE",
    "NORFOLK", "PORTSMOUTH", "HAMPTON", "NEWPORT_NEWS", "YORK",
    "JAMES_CITY", "WILLIAMSBURG", "CHARLES_CITY", "NEW_KENT",
    "GLOUCESTER", "MATHEWS", "MIDDLESEX", "ESSEX", "KING_AND_QUEEN",
    "KING_WILLIAM", "LANCASTER", "NORTHUMBERLAND", "RICHMOND_COUNTY",
    "WESTMORELAND", "KING_GEORGE", "SPOTSYLVANIA", "FREDERICKSBURG",
    "CAROLINE", "ORANGE", "MADISON", "GREENE", "ALBEMARLE",
    "CHARLOTTESVILLE", "FLUVANNA", "LOUISA", "BUCKINGHAM", "CUMBERLAND",
    "NOTTOWAY", "LUNENBURG", "MECKLENBURG", "BRUNSWICK", "GREENSVILLE",
    "EMPORIA", "SOUTHAMPTON", "FRANKLIN_CITY", "CHARLOTTE",
    "PRINCE_EDWARD", "APPOMATTOX", "AMHERST", "NELSON", "HALIFAX",
    "PITTSYLVANIA", "DANVILLE", "HENRY", "MARTINSVILLE", "PATRICK",
}
_APCO_ZONE_COUNTIES = {
    # Western/Southwestern VA (APCo zone, surplus generation post-coal-retirement)
    "AUGUSTA", "STAUNTON", "WAYNESBORO", "ROCKINGHAM", "HARRISONBURG",
    "SHENANDOAH", "PAGE", "WARREN", "FREDERICK", "WINCHESTER", "CLARKE",
    "ROCKBRIDGE", "LEXINGTON", "BUENA_VISTA", "BATH", "HIGHLAND",
    "ALLEGHANY", "COVINGTON", "BOTETOURT", "ROANOKE_COUNTY", "ROANOKE_CITY",
    "ROANOKE", "SALEM", "VINTON", "CRAIG", "BEDFORD", "LYNCHBURG",
    "CAMPBELL", "FRANKLIN", "FLOYD", "MONTGOMERY", "BLACKSBURG",
    "CHRISTIANSBURG", "RADFORD", "RADFORD_CITY", "GILES", "PULASKI",
    "BLAND", "WYTHE", "CARROLL", "GRAYSON", "GALAX", "SMYTH",
    "WASHINGTON", "BRISTOL", "RUSSELL", "TAZEWELL", "BUCHANAN",
    "DICKENSON", "WISE", "NORTON", "LEE", "SCOTT",
}


def regional_supply_pressure(county: str,
                              eia_path: Path = Path("data/eia_generators_va.jsonl")
                              ) -> str:
    """Return one of: surplus | balanced | constrained.

    Default heuristic when EIA data is empty:
      - DOM zone, NoVA core: constrained (NoVA data-center growth saturates supply)
      - DOM zone, central + Tidewater: balanced
      - APCo zone: surplus (post-coal-retirement, slow demand growth)
    When EIA data IS loaded, refine by net operating MW per county.
    """
    c = (county or "").upper().replace(" ", "_")
    nova_core = {"LOUDOUN", "PRINCE_WILLIAM", "FAIRFAX", "ARLINGTON",
                  "FAUQUIER", "STAFFORD"}
    if c in nova_core:
        return "constrained"
    if c in _APCO_ZONE_COUNTIES:
        return "surplus"
    if c in _DOM_ZONE_COUNTIES:
        return "balanced"
    return "balanced"


def supply_pressure_points(label: str, weight: float) -> float:
    """Translate a supply-pressure label into soft-score points."""
    return {
        "constrained": 0.0,
        "balanced":    weight * 0.5,
        "surplus":     weight,
    }.get(label, weight * 0.5)


# ---------- water withdrawals ----------------------------------------------

def load_water_points() -> tuple[np.ndarray, np.ndarray]:
    """Return (xy_array, mgd_array) for permitted water withdrawals.

    xy is np.array shape (n, 2) as (lat, lng). mgd is shape (n,) of permitted
    daily million-gallons. Use with BallTree for nearest-neighbor sums.
    """
    path = Path("data/va_water_withdrawals.jsonl")
    if not path.exists():
        return np.zeros((0, 2)), np.zeros((0,))
    pts = []
    mgds = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lat, lng = r.get("lat"), r.get("lng")
            mgd = r.get("permitted_mgd")
            if lat is None or lng is None or mgd is None:
                continue
            try:
                pts.append([float(lat), float(lng)])
                mgds.append(float(mgd))
            except (TypeError, ValueError):
                continue
    if not pts:
        return np.zeros((0, 2)), np.zeros((0,))
    return np.array(pts), np.array(mgds)


# ---------- VPDES wastewater -----------------------------------------------

def load_vpdes_points() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (xy, permitted_mgd, residual_mgd)."""
    path = Path("data/va_vpdes_volumes.jsonl")
    if not path.exists():
        return np.zeros((0, 2)), np.zeros((0,)), np.zeros((0,))
    pts = []
    perm = []
    resid = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lat, lng = r.get("lat"), r.get("lng")
            p = r.get("permitted_mgd")
            res = r.get("residual_mgd")
            if lat is None or lng is None or (p is None and res is None):
                continue
            try:
                pts.append([float(lat), float(lng)])
                perm.append(float(p) if p is not None else 0.0)
                resid.append(float(res) if res is not None else 0.0)
            except (TypeError, ValueError):
                continue
    if not pts:
        return np.zeros((0, 2)), np.zeros((0,)), np.zeros((0,))
    return np.array(pts), np.array(perm), np.array(resid)


# ---------- FCC fiber ------------------------------------------------------

def load_fiber_points() -> tuple[np.ndarray, list[str]]:
    """Return (xy, providers). Providers is a parallel list of provider strings."""
    path = Path("data/va_fcc_fiber.jsonl")
    if not path.exists():
        return np.zeros((0, 2)), []
    pts = []
    provs = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            lat, lng = r.get("lat"), r.get("lng")
            prov = r.get("provider")
            if lat is None or lng is None or not prov:
                continue
            try:
                pts.append([float(lat), float(lng)])
                provs.append(str(prov).strip().upper())
            except (TypeError, ValueError):
                continue
    if not pts:
        return np.zeros((0, 2)), []
    return np.array(pts), provs
