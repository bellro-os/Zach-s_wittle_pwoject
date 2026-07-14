"""Probate / estate signals on the parcel side.

Surfaces parcels likely to liquidate due to a death-of-owner event. Three
signal types, scored 1 point each (cumulative):

  name_pattern     — owner name contains "ESTATE", "HEIRS", "TRUSTEE",
                     "LIFE ESTATE", "DEC'D" / "DECEASED"
  zero_dollar_xfer — last_sale_price <= $1000 (gift / death-of-grantor pass)
                     within last 5 years
  vintage_hold     — year_built < 1960 AND assessed_total > $200k
                     (long-held vintage estate, more likely to need cash-out)

Output: outputs/mls_analytics/leads/probate_signals.csv
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .db import connect


LEADS_DIR = Path("outputs/mls_analytics/leads")

# Reuse the parcel files we already trust for NRV deeds
PARCEL_FILES = (
    "data/montgomery_county_parcels_slope.jsonl",
    "data/blacksburg_parcels.jsonl",
    "data/pulaski_county_parcels.jsonl",
    "data/floyd_county_parcels_slope.jsonl",
    "data/giles_county_parcels_slope.jsonl",
    "data/radford_city_parcels.jsonl",
    "data/roanoke_county_parcels_slope.jsonl",
    "data/carroll_county_parcels_slope.jsonl",
    "data/wythe_county_parcels_slope.jsonl",
)

NAME_PATTERN = re.compile(
    r"\b(ESTATE\s+OF|ESTATE\s+\b|HEIRS?\s+OF|TRUSTEE|"
    r"LIFE\s+ESTATE|LIFE\s+TENANT|"
    r"DEC['’]?D|DECEASED|"
    r"REVOCABLE\s+TRUST|LIVING\s+TRUST|FAMILY\s+TRUST)\b",
    re.IGNORECASE,
)


def _name_match(name: str | None) -> str | None:
    if not name:
        return None
    m = NAME_PATTERN.search(name)
    if m:
        return m.group(0).upper()
    return None


def _safe_float(v) -> float | None:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _scc_search_url(name: str) -> str:
    if not name:
        return ""
    import urllib.parse as _p
    return f"https://cis.scc.virginia.gov/EntitySearch/EntitySearchByName?searchName={_p.quote(name.strip())}"


def write_probate_signals_csv(out_path: Path = LEADS_DIR / "probate_signals.csv",
                                year_min_zero_xfer: int = 2019) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    today_year = datetime.now().year

    by_parcel: dict[tuple[str, str], dict] = {}
    for fname in PARCEL_FILES:
        p = Path(fname)
        if not p.exists():
            continue
        for line in p.open("r", encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue

            owner = (r.get("owner1") or "").strip()
            county = (r.get("county") or
                      fname.split("/")[-1].replace("_parcels_slope.jsonl", "")
                                          .replace("_parcels.jsonl", "").upper())
            pid = (r.get("parcel_id") or "").strip()
            assessed = _safe_float(r.get("assessed_total")) or 0
            try:
                yr = int(r.get("year_built") or 0)
            except (TypeError, ValueError):
                yr = 0

            # Required strong signals: only name_pattern or zero_xfer qualify.
            signals: list[str] = []
            name_hit = _name_match(owner)
            if name_hit:
                signals.append(f"name:{name_hit}")

            last_date = (r.get("last_sale_date") or "")[:10]
            last_price = _safe_float(r.get("last_sale_price"))
            if (last_date and last_price is not None and last_price <= 1000
                    and last_date >= f"{year_min_zero_xfer}-01-01"):
                signals.append(f"zero_xfer:{last_date}@${last_price:.0f}")

            if not signals:
                continue  # require at least one strong signal

            # Tie-breaker: vintage estate flag (boosts score, doesn't qualify alone)
            if yr and yr < 1960 and assessed >= 200000:
                signals.append(f"vintage:{yr}|${int(assessed):,}")

            key = (pid, county)
            row = {
                "score": len(signals),
                "owner": owner,
                "owner2": (r.get("owner2") or "").strip(),
                "county": county,
                "parcel_id": pid,
                "site_addr": (r.get("site_addr1") or "").strip(),
                "mail_addr": (r.get("mail_addr1") or "").strip(),
                "year_built": yr or "",
                "assessed_total": int(assessed) if assessed else "",
                "last_sale_date": last_date,
                "last_sale_price": int(last_price) if last_price is not None else "",
                "signals": ";".join(signals),
                "scc_lookup_url": _scc_search_url(owner),
            }
            existing = by_parcel.get(key)
            if not existing or row["score"] > existing["score"]:
                by_parcel[key] = row

    rows_out = sorted(by_parcel.values(), key=lambda x: (-x["score"], -(x["assessed_total"] or 0)))
    if not rows_out:
        out_path.write_text("score,owner,county,parcel_id,signals\n", encoding="utf-8-sig")
        return 0

    import csv
    fields = list(rows_out[0].keys())
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    return len(rows_out)
