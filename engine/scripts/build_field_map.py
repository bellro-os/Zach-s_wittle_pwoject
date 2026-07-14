"""Build a per-class RETS field map from the metadata dumps.

Reads outputs/rets_metadata/property_*_fields.json (one per class) and produces
outputs/rets_metadata/field_map.json: a dict keyed by class name (RE_1, MF_2,
LD_3, CM_4, FM_5, RN_6), each value being a {canonical_field_name: rets_system_name}
mapping for the fields the ingest cares about.

Common L_* fields (listing core, status, dates, prices, address, agent) are
identical across all classes. Per-class LM_* / LR_* fields differ — bedrooms
is LM_Int1_6 in RE_1 but a different ID in MF_2, etc. The fields are matched
by their LongName (or StandardName when available), which is stable across
classes.

If a canonical field has no match in a given class (e.g. bedrooms in LD_3 /
CM_4), it's omitted — the ingest will write null for that column.

Run once:
    PYTHONPATH=src python scripts/build_field_map.py
"""

from __future__ import annotations

import json
from pathlib import Path


META_DIR = Path("outputs/rets_metadata")
OUT_PATH = META_DIR / "field_map.json"

CLASSES = ["RE_1", "MF_2", "LD_3", "CM_4", "FM_5", "RN_6"]

# Common fields — these L_* fields exist in every class with the same SystemName.
COMMON_FIELDS = {
    "listing_id":           "L_ListingID",
    "mls_number":           "L_PrimaryListingDisplayId",
    "parcel_id":            "LM_Char50_3",
    "status_category":      "L_StatusCatID",
    "status_detail":        "L_StatusID",
    "status_changed_at":    "L_StatusDate",
    "list_date":            "L_ListingDate",
    "expiration_date":      "L_ExpirationDate",
    "close_date":           "L_ClosingDate",
    "off_market_date":      "L_OffMarketDate",
    "list_price":           "L_AskingPrice",
    "original_list_price":  "L_OriginalPrice",
    "sold_price":           "L_SoldPrice",
    "feed_dom":             "L_DOM",
    "feed_cdom":            "L_CDOM",
    "how_sold":             "L_HowSold",
    "property_subtype":     "L_Type_",
    "address":              "L_Address",
    "address_number":       "L_AddressNumber",
    "address_direction":    "L_AddressDirection",
    "address_street":       "L_AddressStreet",
    "city":                 "L_City",
    "state":                "L_State",
    "subdivision":          "LM_Char50_4",
    "zoning":               "LM_char10_80",
    "county":               "LM_char10_67",
    "acres":                "L_NumAcres",
    "list_agent":           "L_ListAgent1",
    "list_office":          "L_ListOffice1",
    "list_office_name":     "LO1_OrganizationName",
    "latitude":             "LMD_MP_Latitude",
    "longitude":            "LMD_MP_Longitude",
    "update_timestamp":     "L_UpdateDate",
}

# Per-class fields — looked up by LongName so we get the right LM_*/LR_* per class.
# (canonical_name, list_of_long_names_to_try)  — first match wins.
# RES uses "Above Grade SqFt Fin"; MF/FM use "apx fin sqft"; CM uses "apx fin sqft"
# but ALSO has split fields (warehouse/office/lease/sale); RN uses "apx total fin sqft".
PER_CLASS_LOOKUPS = [
    ("sqft",            ["Above Grade SqFt Fin", "Apx Total Fin SqFt", "Apx Fin SqFt",
                         "Total Square Feet", "Apx Total SqFt", "Apx Above Grade SqFt",
                         "Square Feet"]),
    ("sqft_office",     ["Apx Office SqFt"]),                          # CM only
    ("sqft_warehouse",  ["Apx Warehouse SqFt"]),                       # CM only
    ("sqft_lease",      ["BuildingInformationSqFtLease"]),             # CM only
    ("sqft_sale",       ["BuildingInformationSqFtSale"]),              # CM only
    ("units",           ["Units", "Total Units", "Number Of Units"]),  # MF only
    ("bedrooms",        ["Bedrooms", "Total Bedrooms", "Number of Bedrooms"]),
    ("full_baths",      ["Full Baths", "Total Full Baths"]),
    ("half_baths",      ["Half Baths", "Total Half Baths"]),
    ("year_built",      ["Year Built"]),
    ("public_remarks",  ["Public Remarks", "Public Description"]),
    ("agent_remarks",   ["Agent Remarks", "Private Remarks"]),
    ("hoa_dues",        ["HOA: HOA Annual Dues", "HOA Annual Dues", "HOA Dues"]),
    ("high_school",     ["High School"]),
    ("middle_school",   ["Middle School"]),
    ("elementary",      ["Elementary School"]),
    ("levels",          ["Levels", "Stories"]),
    ("garage",          ["Garage/Carport"]),
    ("basement",        ["Basement"]),
    ("fireplaces",      ["Fireplace", "Total Fireplaces"]),
    ("price_per_sqft",  ["Price Per SQFT"]),
    ("zip",             ["Zip", "Zip Code", "Postal Code"]),
]


def _find_by_long_name(rows: list[dict], long_names: list[str]) -> str | None:
    by_long = {(r.get("LongName") or "").strip().lower(): r.get("SystemName") for r in rows}
    for ln in long_names:
        sn = by_long.get(ln.strip().lower())
        if sn:
            return sn
    return None


def main() -> int:
    out: dict[str, dict[str, str]] = {}
    for cid in CLASSES:
        path = META_DIR / f"property_{cid}_fields.json"
        if not path.exists():
            print(f"[skip] {path} not found")
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        # SystemName index for verifying COMMON fields actually exist
        sys_names = {(r.get("SystemName") or "") for r in rows}
        m: dict[str, str] = {}
        # Common fields — only include if the SystemName exists in this class
        for canon, sn in COMMON_FIELDS.items():
            if sn in sys_names:
                m[canon] = sn
        # Per-class fields — resolved by LongName
        for canon, long_names in PER_CLASS_LOOKUPS:
            sn = _find_by_long_name(rows, long_names)
            if sn:
                m[canon] = sn
        out[cid] = m
        print(f"{cid}: {len(m)} canonical fields mapped")

    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_PATH}")

    # Per-class divergence report — what's missing per class
    print("\nPer-canonical coverage:")
    all_canon: set[str] = set(COMMON_FIELDS) | {c for c, _ in PER_CLASS_LOOKUPS}
    print(f"  {'canonical':22s}  " + "  ".join(c.ljust(5) for c in CLASSES))
    for canon in sorted(all_canon):
        flags = ["Y" if canon in out.get(cid, {}) else "-" for cid in CLASSES]
        print(f"  {canon:22s}  " + "      ".join(flags))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
