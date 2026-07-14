"""Owner-name canonicalization + multi-property detection across NRV counties.

Builds two outputs:

  data/owner_canonical.jsonl      one row per (county, parcel_id), with owner1
                                  and owner2 mapped to canonical_owner_id values

  outputs/mls_analytics/owner_portfolios.csv   per canonical_owner_id, the
                                  count of NRV parcels held + the parcel list

The canonicalization is deliberately conservative:
  - county-recorder formatting is normalized (uppercase, strip punctuation,
    collapse whitespace)
  - role suffixes are stripped (TRUSTEE, TRS, ETUX, ETAL, LIFE ESTATE, etc.)
  - JR / SR / II / III are stripped — same person across decades
  - entities (LLC, INC, TRUST, etc.) are detected and tagged
  - "ESTATE OF SMITH" and "SMITH ESTATE" both canonicalize to "SMITH ESTATE"
    (they're the same legal entity for our purposes)
  - persons normalize to "LASTNAME FIRSTNAME" (middle initial dropped)

What we explicitly do NOT do at v1:
  - merge spouses into a household id (we keep owner1 and owner2 separate
    so an analyst can still see the actual co-ownership)
  - phonetic matching (would create too many false-positive collisions)
  - cross-county owner_id stability beyond the normalization rules
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


PARCEL_FILES_NRV = [
    ("MONTGOMERY", "data/montgomery_county_parcels.jsonl"),
    ("PULASKI",    "data/pulaski_county_parcels.jsonl"),
    ("FLOYD",      "data/floyd_county_parcels.jsonl"),
    ("GILES",      "data/giles_county_parcels.jsonl"),
    ("RADFORD",    "data/radford_city_parcels.jsonl"),
]

# Other NRV-adjacent files that might contain absentee owners we care about.
# These are pulled in for the cross-county multi-property scan but kept
# in a separate bucket so users can filter to NRV-only.
PARCEL_FILES_EXTENDED = [
    ("ROANOKE_COUNTY", "data/roanoke_county_parcels.jsonl"),
    ("BOTETOURT",      "data/botetourt_county_parcels.jsonl"),
    ("FRANKLIN",       "data/franklin_county_parcels.jsonl"),
    ("BEDFORD",        "data/bedford_county_parcels.jsonl"),
    ("CARROLL",        "data/carroll_county_parcels.jsonl"),
    ("WYTHE",          "data/wythe_county_parcels.jsonl"),
    ("HENRY",          "data/henry_county_parcels.jsonl"),
]

OUT_JSONL = Path("data/owner_canonical.jsonl")
OUT_PORTFOLIOS = Path("outputs/mls_analytics/owner_portfolios.csv")


# Role / suffix tokens we strip BEFORE deciding entity-vs-person
_ROLE_SUFFIXES = re.compile(
    r"\b("
    r"TRUSTEES?|TRS|TR|TTE|TTEE|"
    r"ETUX|ETUS|ET\s*UX|ETAL|ET\s*AL|"
    r"LIFE\s+ESTATE|LIFE\s+TENANT|"
    r"JR|SR|II+|IV|V|"
    r"REVOCABLE|IRREVOCABLE|LIVING|FAMILY|"
    r"DEC[D]?|DECEASED"
    r")\b\.?",
    re.IGNORECASE,
)

_ENTITY_PATTERN = re.compile(
    r"\b("
    r"LLC|L\.L\.C\.|INC\b|CORP(?:ORATION)?|COMPANY|CO\b|"
    r"LP\b|LLP\b|LTD|LIMITED|"
    r"PARTNERSHIP|HOLDINGS|PROPERTIES|MANAGEMENT|MGMT|"
    r"REALTY|INVEST|CAPITAL|GROUP\b|"
    r"VENTURES|ASSOCIATES|DEVELOPMENT|"
    r"BUILDERS|CONSTRUCTION|BUILDING|"
    r"CHURCH|MINISTRIES|TEMPLE|MOSQUE|SYNAGOGUE|"
    r"FOUNDATION|FOUNDATIONS|"
    r"CEMETERY|HOA\b|HOMEOWNERS|"
    r"COUNTY|TOWN|CITY|STATE|COMMONWEALTH|UNITED\s+STATES|U\.?S\.?A\.?|FEDERAL|"
    r"COMMISSION|AUTHORITY|DEPARTMENT|AGENCY|BOARD\s+OF|"
    r"SCHOOL|SCHOOLS|"
    r"BANK\b|CREDIT\s+UNION|"
    r"VPI\b|VIRGINIA\s+TECH|UNIVERSITY|COLLEGE"
    r")\b",
    re.IGNORECASE,
)

_TRUST_PATTERN = re.compile(r"\bTRUST\b", re.IGNORECASE)
_ESTATE_PATTERN = re.compile(r"\b(ESTATE\s+OF\s+|HEIRS\s+OF\s+|.+\s+ESTATE\b|.+\s+HEIRS\b)", re.IGNORECASE)

# "C/O FAMILY NAME" pattern — the C/O part is a mail-recipient designation,
# not the legal owner. We try to extract the principal name from after it.
_CO_PATTERN = re.compile(r"^\s*C\s*/\s*O\s+", re.IGNORECASE)


def _basic_normalize(name: str) -> str:
    """Uppercase, strip non-alphanumeric (preserve & and -), collapse whitespace."""
    s = (name or "").upper()
    s = s.replace("&", " AND ")
    # Strip "C/O ..." prefix BEFORE removing the slash
    s = re.sub(r"^\s*C\s*/\s*O\s+", "", s)
    s = re.sub(r"[^A-Z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _classify(name: str) -> str:
    """Return 'entity' | 'estate' | 'trust' | 'person'."""
    if not name:
        return "person"
    if _ENTITY_PATTERN.search(name):
        return "entity"
    if _ESTATE_PATTERN.search(name):
        return "estate"
    if _TRUST_PATTERN.search(name):
        return "trust"
    return "person"


def canonicalize(name: str | None) -> tuple[str, str] | None:
    """Return (canonical_id, owner_type) or None for empty/junk strings.

    canonical_id is the deduplication key (use this to count multi-property).
    owner_type ∈ {entity, estate, trust, person}.
    """
    if not name:
        return None
    s = _basic_normalize(name)
    if not s or len(s) < 3:
        return None
    # Drop "C/O " prefix
    s = _CO_PATTERN.sub("", s)
    # Junk strings to ignore
    if s in ("UNKNOWN", "OWNER UNKNOWN", "VARIOUS", "MULTIPLE", "CEMETERY",
              "TENANTS", "TENANT", "TENANTS IN COMMON", "JOINT TENANTS",
              "OCCUPANT", "RESIDENT", "PROPERTY OWNER", "CURRENT OWNER"):
        return None

    classification = _classify(s)

    # Strip role suffixes for the canonical key (but remember if we saw them)
    cleaned = _ROLE_SUFFIXES.sub("", s)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(" -.,;")

    # Estate/Heirs unification: "ESTATE OF SMITH" / "SMITH ESTATE" / "SMITH HEIRS"
    # all canonicalize to "<LASTNAME> ESTATE" so they bucket together.
    if classification == "estate":
        m1 = re.match(r"^ESTATE\s+OF\s+(.+)$", cleaned)
        m2 = re.match(r"^HEIRS\s+OF\s+(.+)$", cleaned)
        m3 = re.match(r"^(.+)\s+(?:ESTATE|HEIRS)$", cleaned)
        principal = (m1 or m2 or m3).group(1).strip() if (m1 or m2 or m3) else cleaned
        # Use just the lastname token from principal for the bucket
        last = principal.split()[0] if principal else cleaned
        return (f"EST:{last}", "estate")

    if classification == "entity":
        # Entities canonicalize to the cleaned name (already de-suffixed of roles).
        # Drop trailing entity tokens too so "FRALIN SP LLC" and "FRALIN SP" merge.
        # But keep the entity tag visible.
        ent = re.sub(r"\b(LLC|L\.L\.C\.|INC|CORP(?:ORATION)?|LP|LLP|LTD|LIMITED)\b\.?",
                     "", cleaned).strip()
        ent = re.sub(r"\s+", " ", ent)
        if not ent or len(ent) < 2:
            return None
        return (f"ENT:{ent}", "entity")

    if classification == "trust":
        # Drop "TRUST" word to merge variants ("SMITH FAMILY TRUST" / "SMITH TRUST")
        t = re.sub(r"\bTRUST\b", "", cleaned).strip()
        t = re.sub(r"\s+", " ", t)
        # If we ended up with nothing (e.g. "LIVING TRUST" with no family name),
        # this is junk — every parcel of this shape would otherwise collapse together.
        if not t or len(t) < 2:
            return None
        return (f"TRU:{t}", "trust")

    # Person: keep first two name tokens (LASTNAME FIRSTNAME), drop middle / suffix
    tokens = [tok for tok in cleaned.split() if tok and len(tok) > 1]
    if len(tokens) < 2:
        return (f"PER:{cleaned}", "person") if cleaned else None
    return (f"PER:{tokens[0]} {tokens[1]}", "person")


def build_canonical(parcel_files: list[tuple[str, str]] | None = None,
                    *, include_extended: bool = False) -> dict:
    """Read all NRV parcel JSONL files, emit canonical mappings.

    Returns a summary dict and writes:
      data/owner_canonical.jsonl
      outputs/mls_analytics/owner_portfolios.csv
    """
    if parcel_files is None:
        parcel_files = list(PARCEL_FILES_NRV)
        if include_extended:
            parcel_files += PARCEL_FILES_EXTENDED

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    OUT_PORTFOLIOS.parent.mkdir(parents=True, exist_ok=True)

    portfolios: dict[str, dict] = defaultdict(lambda: {
        "canonical_owner_id": None,
        "owner_type": None,
        "sample_owner_string": None,
        "parcel_ids": [],   # list of (county, parcel_id, owner_position)
        "counties": set(),
        "n_parcels": 0,
    })

    n_total = 0
    n_canon = 0
    with OUT_JSONL.open("w", encoding="utf-8") as out:
        for county, path in parcel_files:
            p = Path(path)
            if not p.exists():
                print(f"  [owner_dedup] skip {county}: {path} not found")
                continue
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    n_total += 1
                    parcel_id = (r.get("parcel_id") or "").strip()
                    if not parcel_id:
                        continue
                    o1 = canonicalize(r.get("owner1"))
                    o2 = canonicalize(r.get("owner2"))
                    rec = {
                        "county": county,
                        "parcel_id": parcel_id,
                        "owner1_raw": r.get("owner1"),
                        "owner1_canonical_id": o1[0] if o1 else None,
                        "owner1_type": o1[1] if o1 else None,
                        "owner2_raw": r.get("owner2"),
                        "owner2_canonical_id": o2[0] if o2 else None,
                        "owner2_type": o2[1] if o2 else None,
                    }
                    out.write(json.dumps(rec) + "\n")
                    if o1:
                        n_canon += 1
                        e = portfolios[o1[0]]
                        e["canonical_owner_id"] = o1[0]
                        e["owner_type"] = o1[1]
                        if not e["sample_owner_string"]:
                            e["sample_owner_string"] = r.get("owner1")
                        e["parcel_ids"].append((county, parcel_id, 1))
                        e["counties"].add(county)
                        e["n_parcels"] += 1
                    if o2:
                        e = portfolios[o2[0]]
                        e["canonical_owner_id"] = o2[0]
                        e["owner_type"] = o2[1]
                        if not e["sample_owner_string"]:
                            e["sample_owner_string"] = r.get("owner2")
                        e["parcel_ids"].append((county, parcel_id, 2))
                        e["counties"].add(county)
                        e["n_parcels"] += 1

    # Portfolio CSV: one row per canonical_owner_id WITH MULTIPLE PARCELS
    rows = [
        {
            "canonical_owner_id": v["canonical_owner_id"],
            "owner_type": v["owner_type"],
            "sample_owner_string": v["sample_owner_string"],
            "n_parcels": v["n_parcels"],
            "n_counties": len(v["counties"]),
            "counties": ";".join(sorted(v["counties"])),
            "parcel_ids": ";".join(f"{c}/{pid}" for (c, pid, _) in v["parcel_ids"][:50]),
            "parcel_overflow": max(0, v["n_parcels"] - 50),
        }
        for v in portfolios.values() if v["n_parcels"] >= 2
    ]
    rows.sort(key=lambda x: (-x["n_parcels"], x["canonical_owner_id"]))

    if rows:
        with OUT_PORTFOLIOS.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
    else:
        OUT_PORTFOLIOS.write_text("canonical_owner_id\n", encoding="utf-8-sig")

    return {
        "total_parcels_scanned": n_total,
        "owners_canonicalized": n_canon,
        "distinct_canonical_owners": len(portfolios),
        "owners_with_multiple_parcels": len(rows),
        "owner_canonical_jsonl": str(OUT_JSONL),
        "owner_portfolios_csv": str(OUT_PORTFOLIOS),
    }


def lookup_multi_property_count() -> dict[str, int]:
    """Convenience reader: returns {canonical_owner_id: n_parcels} for all
    owners with >=2 parcels. Used by seller_scoring.py."""
    out: dict[str, int] = {}
    if not OUT_PORTFOLIOS.exists():
        return out
    with OUT_PORTFOLIOS.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                out[r["canonical_owner_id"]] = int(r.get("n_parcels") or 0)
            except (TypeError, ValueError):
                pass
    return out
