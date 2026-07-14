"""Parcel-source registry — one entry per VA county we can pull from.

Each `ParcelSource` bundles the ArcGIS REST URL, the list of fields to
request, and a `to_canonical(raw)` function that produces a row in our
common schema (matching what `dump_sample` has always written for
Montgomery). Detectors run against that canonical schema and don't know
or care which county the data came from.

Canonical row schema (fields may be None when a county doesn't expose
that attribute):
    parcel_id, tax_map_id, jurisdiction, county,
    site_addr1, site_addr2, mail_addr1, mail_addr2,
    owner1, owner2,
    assessed_total, assessed_land, assessed_bldg,
    last_sale_date, last_sale_price,
    acres, year_built, bedrooms, full_baths, half_baths,
    sfla, stories, zoning, subd_name, neighborhood,
    deedbook, deedpage
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _num(v: Any) -> float | None:
    s = _clean(v)
    if s is None:
        return None
    try:
        return float(s.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _int(v: Any) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _sale_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.utcfromtimestamp(v / 1000).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = _clean(v)
    if not s:
        return None
    # Strip ISO 8601 time component if present (e.g. "2005-10-13T04:00:00Z")
    if "T" in s:
        s = s.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%m%d%Y", "%d-%b-%y", "%d-%b-%Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            if d.year > date.today().year:
                d = d.replace(year=d.year - 100)
            return d
        except ValueError:
            continue
    return None


@dataclass
class ParcelSource:
    county: str                # e.g. "MONTGOMERY"
    url: str                   # endpoint URL (layer URL for arcgis_rest; /wfs base for geoserver_wfs)
    out_fields: str            # comma-separated field list for arcgis_rest (ignored for WFS)
    to_canonical: Callable[[dict], dict]
    parcel_id_field: str = "PARCEL_ID"  # source's field name for the parcel id
    jurisdiction_filter_field: str | None = None  # server-side jurisdiction filter
    object_id_field: str = "OBJECTID"
    # WFS-specific (only set for kind="geoserver_wfs")
    kind: str = "arcgis_rest"  # "arcgis_rest" | "geoserver_wfs"
    wfs_typename: str | None = None


# ---------------------------------------------------------------------------
# Montgomery — the original, preserved 1:1 so existing JSONL stays identical.

_MONTGOMERY_FIELDS = ",".join([
    "OBJECTID", "PARCEL_ID", "TAX_MAP_ID", "OWNER1", "OWNER2",
    "SITE_ADD1", "SITE_ADD2", "MAIL_ADD1", "MAIL_ADD2",
    "ACRES", "NACRES", "LEGAL1", "LEGAL2",
    "SUBD_NAME", "SUBD_LOT", "SUBD_BLK",
    "DEEDBOOK", "DEEDPAGE",
    "ZONING", "NEIGHBORHD",
    "LAND_VALUE", "BLDG_VALUE", "TOTAL_VALU",
    "NLAND_VALU", "NBLDG_VALU", "NTOTAL_VAL",
    "SALE_DATE", "SALE_PRICE", "NSALE_PRIC",
    "STORIES", "YEARBLT", "ROOMS", "BEDROOMS",
    "FULLBATHS", "HALFBATHS", "SFLA",
    "JURISDICTI",
])


def _montgomery_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("PARCEL_ID")),
        "tax_map_id": p.get("TAX_MAP_ID"),
        "jurisdiction": p.get("JURISDICTI"),
        "county": "MONTGOMERY",
        "site_addr1": p.get("SITE_ADD1"),
        "site_addr2": p.get("SITE_ADD2"),
        "mail_addr1": p.get("MAIL_ADD1"),
        "mail_addr2": p.get("MAIL_ADD2"),
        "owner1": p.get("OWNER1"),
        "owner2": p.get("OWNER2"),
        "assessed_total": p.get("NTOTAL_VAL") or _num(p.get("TOTAL_VALU")),
        "assessed_land":  p.get("NLAND_VALU") or _num(p.get("LAND_VALUE")),
        "assessed_bldg":  p.get("NBLDG_VALU") or _num(p.get("BLDG_VALUE")),
        "last_sale_date": _sale_date(p.get("SALE_DATE")),
        "last_sale_price": p.get("NSALE_PRIC") or _num(p.get("SALE_PRICE")),
        "acres": p.get("NACRES") or _num(p.get("ACRES")),
        "year_built": _int(p.get("YEARBLT")),
        "bedrooms": _int(p.get("BEDROOMS")),
        "full_baths": _int(p.get("FULLBATHS")),
        "half_baths": _int(p.get("HALFBATHS")),
        "sfla": _int(p.get("SFLA")),
        "stories": _num(p.get("STORIES")),
        "zoning": p.get("ZONING"),
        "subd_name": p.get("SUBD_NAME"),
        "neighborhood": p.get("NEIGHBORHD"),
        "deedbook": p.get("DEEDBOOK"),
        "deedpage": p.get("DEEDPAGE"),
    }


# ---------------------------------------------------------------------------
# Scott — "PVAOwnership" layer from the regional GSCplanning server.

_SCOTT_FIELDS = ",".join([
    "OBJECTID", "MapNumber", "Name1", "Name2", "MailAddress", "CityStateZip",
    "Class", "YearBuilt", "DeedBook", "DeedPage",
    "SalePrice", "SaleDate", "Prev_Owner", "TaxDist", "Acre_PVA",
    "Description", "fcv", "res_land", "farm_land", "com_land", "sqft",
])


def _scott_row(p: dict) -> dict:
    mail = _clean(p.get("MailAddress"))
    city_state_zip = _clean(p.get("CityStateZip"))
    return {
        "parcel_id": _clean(p.get("MapNumber")),
        "tax_map_id": p.get("MapNumber"),
        "jurisdiction": None,
        "county": "SCOTT",
        "site_addr1": None,                   # Scott doesn't publish site address
        "site_addr2": None,
        "mail_addr1": mail,
        "mail_addr2": city_state_zip,
        "owner1": p.get("Name1"),
        "owner2": p.get("Name2"),
        "assessed_total": _num(p.get("fcv")),  # Fair Cash Value
        "assessed_land": _num(p.get("res_land")) or _num(p.get("farm_land")),
        "assessed_bldg": None,
        "last_sale_date": _sale_date(p.get("SaleDate")),
        "last_sale_price": _num(p.get("SalePrice")),
        "acres": _num(p.get("Acre_PVA")),
        "year_built": _int(p.get("YearBuilt")),
        "bedrooms": None,
        "full_baths": None,
        "half_baths": None,
        "sfla": _int(p.get("sqft")),
        "stories": None,
        "zoning": p.get("TaxDist"),
        "subd_name": None,
        "neighborhood": None,
        "deedbook": p.get("DeedBook"),
        "deedpage": p.get("DeedPage"),
    }


# ---------------------------------------------------------------------------
# Roanoke County — 343-field "Parcel Report" layer. We pull the highest-value
# subset; `SalePrice1/SaleDateYMD1` are the most recent transaction.

_ROANOKE_COUNTY_FIELDS = ",".join([
    "OBJECTID", "ParcelID", "GPIN", "Calc_Acreage", "Subdivision", "Jurisdiction",
    "Owner1_LastAndFirst", "Owner2_LastAndFirst",
    "MailingAddressLine1", "MailingAddressLine2", "MailingAddressLine3",
    "LocationAddressForDisplay", "LocationAddressNumber", "LocationStreetName",
    "SalePrice1", "SaleDateYMD1",
    "SumAllCardsTotalValue", "SumAllCardsLandOnlyValue", "SumAllCardsBuildingOnlyValue",
    "SumAllCardsTotalMarketValue",
    "YearBuilt", "Zone01_Description",
    "Deed_AC_LT_NBR", "ND_Deed_AC_LT_NBR",
])


def _roanoke_county_row(p: dict) -> dict:
    mail1 = _clean(p.get("MailingAddressLine1"))
    mail2_parts = [
        _clean(p.get("MailingAddressLine2")) or "",
        _clean(p.get("MailingAddressLine3")) or "",
    ]
    mail2 = " ".join(part for part in mail2_parts if part) or None
    site = _clean(p.get("LocationAddressForDisplay"))
    return {
        "parcel_id": _clean(p.get("ParcelID")) or _clean(p.get("GPIN")),
        "tax_map_id": p.get("GPIN"),
        "jurisdiction": p.get("Jurisdiction"),
        "county": "ROANOKE_COUNTY",
        "site_addr1": site,
        "site_addr2": None,
        "mail_addr1": mail1,
        "mail_addr2": mail2,
        "owner1": p.get("Owner1_LastAndFirst"),
        "owner2": p.get("Owner2_LastAndFirst"),
        "assessed_total": _num(p.get("SumAllCardsTotalValue")),
        "assessed_land":  _num(p.get("SumAllCardsLandOnlyValue")),
        "assessed_bldg":  _num(p.get("SumAllCardsBuildingOnlyValue")),
        "last_sale_date": _sale_date(p.get("SaleDateYMD1")),
        "last_sale_price": _num(p.get("SalePrice1")),
        "acres": _num(p.get("Calc_Acreage")),
        "year_built": _int(p.get("YearBuilt")),
        "bedrooms": None,
        "full_baths": None,
        "half_baths": None,
        "sfla": None,
        "stories": None,
        "zoning": p.get("Zone01_Description"),
        "subd_name": p.get("Subdivision"),
        "neighborhood": None,
        "deedbook": None,
        "deedpage": None,
    }


# ---------------------------------------------------------------------------
# Botetourt County — webgis.net VA hosted, MapServer/23 Parcels layer.
# Has Owner1/2, Sale1Amt + Sale1D, yrbuilt, SqFT, LandVal1, TotVal1, mail addr.

_BOTETOURT_FIELDS = ",".join([
    "OBJECTID", "LRSNum", "TaxAcct", "LINK", "RPC",
    "Owner1", "Owner2", "Grantor1",
    "MailAddr", "MailCity", "MailStat", "MailZip",
    "Legal1", "LegalAc", "Doc3Ref", "instnum1", "instnum2",
    "LandVal1", "TotVal1", "Sale1D", "Sale1Amt",
    "yrbuilt", "SqFT", "NumImp",
])


def _botetourt_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("LINK")) or _clean(p.get("TaxAcct")),
        "tax_map_id": p.get("LINK") or p.get("TaxAcct"),
        "jurisdiction": "BOTETOURT",
        "county": "BOTETOURT",
        "site_addr1": None,
        "site_addr2": None,
        "mail_addr1": _clean(p.get("MailAddr")),
        "mail_addr2": _split_addr2([p.get("MailCity"), p.get("MailStat"), p.get("MailZip")]),
        "owner1": _clean(p.get("Owner1")),
        "owner2": _clean(p.get("Owner2")),
        "assessed_total": _num(p.get("TotVal1")),
        "assessed_land": _num(p.get("LandVal1")),
        "assessed_bldg": None,
        "last_sale_date": _sale_date(p.get("Sale1D")),
        "last_sale_price": _num(p.get("Sale1Amt")),
        "acres": _num(p.get("LegalAc")),
        "year_built": _int(p.get("yrbuilt")),
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": _num(p.get("SqFT")),
        "stories": None,
        "zoning": None,
        "subd_name": None,
        "neighborhood": _clean(p.get("Legal1")),
        "deedbook": _clean(p.get("Doc3Ref")), "deedpage": None,
    }


# ---------------------------------------------------------------------------
# Bedford County — webgis.bedfordcountyva.gov OpenData/OpenDataProperty/0.
# Up to 3 sales per parcel (Sale1/Sale2/Sale3) — bonus depth vs other counties.

_BEDFORD_FIELDS = ",".join([
    "OBJECTID", "PIN", "GPIN", "PPIN", "LRSN", "RPC", "MapLink", "LINK", "ACCOUNT",
    "Owner1", "Owner2", "Grantor1",
    "LocAddr", "MailAddr", "MailCity", "MailStat", "MailZip",
    "Legal1", "LegalAc", "PCDesc",
    "Sale1D", "Sale1Amt", "Sale2D", "Sale2Amt", "Sale3D", "Sale3Amt",
])


def _bedford_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("PIN")) or _clean(p.get("MapLink")),
        "tax_map_id": p.get("MapLink") or p.get("PIN"),
        "jurisdiction": "BEDFORD",
        "county": "BEDFORD",
        "site_addr1": _clean(p.get("LocAddr")),
        "site_addr2": None,
        "mail_addr1": _clean(p.get("MailAddr")),
        "mail_addr2": _split_addr2([p.get("MailCity"), p.get("MailStat"), p.get("MailZip")]),
        "owner1": _clean(p.get("Owner1")),
        "owner2": _clean(p.get("Owner2")),
        "assessed_total": None,
        "assessed_land": None,
        "assessed_bldg": None,
        "last_sale_date": _sale_date(p.get("Sale1D")),
        "last_sale_price": _num(_clean(p.get("Sale1Amt"))),
        "prior_sale_date": _sale_date(p.get("Sale2D")),
        "prior_sale_price": _num(_clean(p.get("Sale2Amt"))),
        "third_sale_date": _sale_date(p.get("Sale3D")),
        "third_sale_price": _num(_clean(p.get("Sale3Amt"))),
        "acres": _num(_clean(p.get("LegalAc"))),
        "year_built": None,
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": _clean(p.get("PCDesc")),
        "subd_name": None,
        "neighborhood": _clean(p.get("Legal1")),
        "deedbook": None, "deedpage": None,
    }


# ---------------------------------------------------------------------------
# Radford City (independent) — Realestate/MapServer/2 Tax_Lots layer.
# 5,324 parcels. Has owner, assessed value, dwelling sqft, lat/lng, deed
# reference. Sale price field exists but is virtually empty (1 of 5,324).

_RADFORD_FIELDS = ",".join([
    "OBJECTID", "PIN", "TAX_ACCOUNT", "ALT_PIN", "TAX_CATEGORY",
    "PROPERTY_ADDRESS", "PROPERTY_CITY", "PROPERTY_ZIP",
    "OWNER", "OWNER_ALT", "OWNER_STREET", "OWNER_CITY", "OWNER_STATE", "OWNER_ZIP",
    "TOTAL_VALUE", "LAND_VALUE", "DWELLING_VALUE",
    "DWELLING_SIZE", "LAND_SIZE", "ZONE", "WARD",
    "RECORDED", "INSTRUMENT_ID", "BOOK", "PAGE", "DEED_REF", "PLAT_REF",
    "latitude_y", "longitude_x", "PROPERTY_CARD_LINK",
])


def _radford_row(p: dict) -> dict:
    site = _clean(p.get("PROPERTY_ADDRESS"))
    return {
        "parcel_id": _clean(p.get("PIN")) or _clean(p.get("TAX_ACCOUNT")),
        "tax_map_id": p.get("PIN"),
        "jurisdiction": "RADFORD",
        "county": "RADFORD",
        "site_addr1": site,
        "site_addr2": _split_addr2([p.get("PROPERTY_CITY"), p.get("PROPERTY_ZIP")]),
        "mail_addr1": _clean(p.get("OWNER_STREET")),
        "mail_addr2": _split_addr2([p.get("OWNER_CITY"), p.get("OWNER_STATE"), p.get("OWNER_ZIP")]),
        "owner1": _clean(p.get("OWNER")),
        "owner2": _clean(p.get("OWNER_ALT")),
        "assessed_total": _num(p.get("TOTAL_VALUE")),
        "assessed_land":  _num(p.get("LAND_VALUE")),
        "assessed_bldg":  _num(p.get("DWELLING_VALUE")),
        "last_sale_date": _sale_date(p.get("RECORDED")),
        "last_sale_price": None,  # SALE_AMOUNT field exists but is empty
        "acres": _num(p.get("LAND_SIZE")),
        "year_built": None,
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": _num(p.get("DWELLING_SIZE")),
        "stories": None,
        "zoning": _clean(p.get("ZONE")),
        "subd_name": None,
        "neighborhood": _clean(p.get("WARD")),
        "deedbook": _clean(p.get("BOOK")), "deedpage": _clean(p.get("PAGE")),
        "lat": _num(p.get("latitude_y")),
        "lng": _num(p.get("longitude_x")),
    }


# ---------------------------------------------------------------------------
# Franklin — "Updated Web Parcels". Owner + assessment present; no sale data.

_FRANKLIN_FIELDS = ",".join([
    "OBJECTID", "PIN", "Parcel_No", "Parcel_Ext", "Subdivision", "Parent_PIN",
    "zoning", "owner_name", "owner_address", "owner_city", "owner_state",
    "owner_zip", "owner_zip_ext", "deed_book", "deed_page", "FULLADDR",
    "acreage", "land_value", "improvement_value", "total_assessed_value",
    "land_use_value",
])


def _franklin_row(p: dict) -> dict:
    city = _clean(p.get("owner_city")) or ""
    state = _clean(p.get("owner_state")) or ""
    zipc = _clean(p.get("owner_zip")) or ""
    ext = _clean(p.get("owner_zip_ext")) or ""
    if ext:
        zipc = f"{zipc}-{ext}" if zipc else ext
    mail2 = ", ".join(part for part in [city, " ".join(x for x in [state, zipc] if x)] if part)
    return {
        "parcel_id": _clean(p.get("PIN")) or _clean(p.get("Parcel_No")),
        "tax_map_id": p.get("Parcel_No"),
        "jurisdiction": None,
        "county": "FRANKLIN",
        "site_addr1": _clean(p.get("FULLADDR")),
        "site_addr2": None,
        "mail_addr1": _clean(p.get("owner_address")),
        "mail_addr2": mail2 or None,
        "owner1": p.get("owner_name"),
        "owner2": None,
        "assessed_total": _num(p.get("total_assessed_value")),
        "assessed_land":  _num(p.get("land_value")),
        "assessed_bldg":  _num(p.get("improvement_value")),
        "last_sale_date": None,
        "last_sale_price": None,
        "acres": _num(p.get("acreage")),
        "year_built": None,
        "bedrooms": None,
        "full_baths": None,
        "half_baths": None,
        "sfla": None,
        "stories": None,
        "zoning": p.get("zoning"),
        "subd_name": p.get("Subdivision"),
        "neighborhood": None,
        "deedbook": p.get("deed_book"),
        "deedpage": p.get("deed_page"),
    }


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# iGIS / InteractiveGIS counties — all served via GeoServer WFS at
# https://<sub>.interactivegis.com/geoserver/<sub>/wfs.
# Field schemas vary per county; a separate to_canonical function per source.

def _split_addr2(parts: list) -> str | None:
    bits: list[str] = []
    for p in parts:
        if p is None:
            continue
        s = str(p).strip()
        if s:
            bits.append(s)
    return ", ".join(bits) if bits else None


def _floyd_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("parc_id")) or _clean(p.get("mapnumber")),
        "tax_map_id": p.get("mapnumber"),
        "jurisdiction": None,
        "county": "FLOYD",
        "site_addr1": None,  # iGIS Floyd publishes only mailing address
        "site_addr2": None,
        "mail_addr1": p.get("address"),
        "mail_addr2": _split_addr2([p.get("address2"), p.get("zip")]),
        "owner1": p.get("accountname"),
        "owner2": p.get("accountname2"),
        "assessed_total": _num(p.get("totalassessment")),
        "assessed_land": _num(p.get("currentlandvalue")),
        "assessed_bldg": _num(p.get("totalimprovementsvalue")),
        "last_sale_date": _sale_date(p.get("saledate")),
        "last_sale_price": _num(p.get("saleprice")),
        "acres": _num(p.get("totalacres")),
        "year_built": None,
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("stateclass"),
        "subd_name": None,
        "neighborhood": p.get("description"),
        "deedbook": p.get("deedbook"),
        "deedpage": p.get("deedpage"),
    }


def _giles_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("map")) or _clean(p.get("account")),
        "tax_map_id": p.get("map"),
        "jurisdiction": None,
        "county": "GILES",
        "site_addr1": None,
        "site_addr2": None,
        "mail_addr1": p.get("address1"),
        "mail_addr2": _split_addr2([p.get("address2"), p.get("city"), p.get("state"), p.get("zip")]),
        "owner1": p.get("owner1"),
        "owner2": p.get("owner2"),
        "assessed_total": (_num(p.get("land_value")) or 0) + (_num(p.get("imp_value")) or 0) or None,
        "assessed_land": _num(p.get("land_value")),
        "assessed_bldg": _num(p.get("imp_value")),
        "last_sale_date": _sale_date(p.get("sale_date")),
        "last_sale_price": _num(p.get("sale_price")),
        "acres": _num(p.get("acreage")),
        "year_built": None,
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("zone"),
        "subd_name": None,
        "neighborhood": _clean(p.get("desc1")),
        "deedbook": p.get("deed_book"),
        "deedpage": p.get("deed_page"),
    }


def _carroll_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("pin_for_0s")) or _clean(p.get("pin_origin")) or _clean(p.get("parc_id")),
        "tax_map_id": p.get("pin_origin") or p.get("pin_for_0s"),
        "jurisdiction": None,
        "county": "CARROLL",
        "site_addr1": _clean(p.get("prop_addr")),
        "site_addr2": None,
        "mail_addr1": p.get("address1"),
        "mail_addr2": p.get("address2"),
        "owner1": p.get("ownername1"),
        "owner2": p.get("ownername2"),
        "assessed_total": _num(p.get("totalvalue")),
        "assessed_land": _num(p.get("landvalue")),
        "assessed_bldg": _num(p.get("bldgvalue")),
        "last_sale_date": _sale_date(p.get("saledate")),
        "last_sale_price": _num(p.get("saleprice")),
        "acres": _num(p.get("parcelsize")),
        "year_built": None,
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": None,
        "subd_name": None,
        "neighborhood": None,
        "deedbook": p.get("deedbook"),
        "deedpage": None,
    }


def _washington_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("parcel_no")) or _clean(p.get("parcel_no_1")),
        "tax_map_id": p.get("parcel_no"),
        "jurisdiction": None,
        "county": "WASHINGTON",
        "site_addr1": None,
        "site_addr2": None,
        "mail_addr1": p.get("address_1"),
        "mail_addr2": p.get("address_2"),
        "owner1": p.get("name"),
        "owner2": p.get("name2"),
        "assessed_total": _num(p.get("tot_val")),
        "assessed_land": _num(p.get("land_value")),
        "assessed_bldg": _num(p.get("imp_value")),
        "last_sale_date": _sale_date(p.get("sale_date")),
        "last_sale_price": _num(p.get("sale_amnt")),
        "acres": _num(p.get("acreage")),
        "year_built": _int(p.get("year_blt")),
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": None,
        "subd_name": None,
        "neighborhood": None,
        "deedbook": p.get("deed_book"),
        "deedpage": p.get("deed_page"),
    }


def _bland_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("smapnum")) or _clean(p.get("mmap")),
        "tax_map_id": p.get("mmap"),
        "jurisdiction": None,
        "county": "BLAND",
        "site_addr1": _split_addr2([str(p.get("mhse") or ""), p.get("mstrt")]) or None,
        "site_addr2": _split_addr2([p.get("mprcit"), p.get("mprsta"), p.get("mprzp1")]),
        "mail_addr1": p.get("madd1"),
        "mail_addr2": _split_addr2([p.get("mcity"), p.get("mstate"), p.get("mzip5")]),
        "owner1": p.get("mlnam"),
        "owner2": None,
        "assessed_total": _num(p.get("mtotpr")),
        "assessed_land": _num(p.get("mtotld")),
        "assessed_bldg": _num(p.get("mimprv")),
        "last_sale_date": None,  # only year (myrsld), no precise date
        "last_sale_price": None,
        "acres": _num(p.get("macre1")),
        "year_built": _int(p.get("myrblt")),
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("mzone"),
        "subd_name": None,
        "neighborhood": p.get("mdesc1"),
        "deedbook": p.get("mdbook"),
        "deedpage": None,
    }


def _lee_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("pin")) or _clean(p.get("gpin")),
        "tax_map_id": p.get("pin"),
        "jurisdiction": None,
        "county": "LEE",
        "site_addr1": p.get("address_1"),
        "site_addr2": _split_addr2([p.get("address_2"), p.get("address_3")]),
        "mail_addr1": p.get("owner_home"),
        "mail_addr2": None,
        "owner1": p.get("owner_name"),
        "owner2": p.get("owner_na_1"),
        "assessed_total": _num(p.get("market_val")),
        "assessed_land": _num(p.get("land_value")),
        "assessed_bldg": None,
        "last_sale_date": None,  # Lee uses sales_code/avg_price_, no clean sale date
        "last_sale_price": None,
        "acres": _num(p.get("acres")),
        "year_built": _int(p.get("yr_built")),
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("zone"),
        "subd_name": None,
        "neighborhood": None,
        "deedbook": p.get("deed_book"),
        "deedpage": p.get("deed_page"),
    }


def _wythe_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("smapnum")) or _clean(p.get("prop_id")) or _clean(p.get("tax_join")),
        "tax_map_id": p.get("smapnum"),
        "jurisdiction": None, "county": "WYTHE",
        "site_addr1": _clean(p.get("site_addr")),
        "site_addr2": _split_addr2([p.get("site_city"), p.get("site_zip")]),
        "mail_addr1": p.get("own_addr1"),
        "mail_addr2": _split_addr2([p.get("own_city"), p.get("own_state"), p.get("own_zip")]),
        "owner1": p.get("owner1"),
        "owner2": p.get("owner2"),
        "assessed_total": _num(p.get("total_val")),
        "assessed_land": _num(p.get("land_val")),
        "assessed_bldg": _num(p.get("bldg_val")),
        "last_sale_date": _sale_date(p.get("ls_date")),
        "last_sale_price": _num(p.get("ls_price")),
        "acres": _num(p.get("lot_size")),
        "year_built": _int(p.get("year_built")),
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": _int(p.get("res_area")) or _int(p.get("bld_area")),
        "stories": _num(p.get("stories")),
        "zoning": p.get("use_code"),
        "subd_name": None,
        "neighborhood": p.get("style"),
        "deedbook": p.get("ls_book"), "deedpage": None,
    }


def _tazewell_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("gislink")) or _clean(p.get("parcels_id")) or _clean(p.get("remap")),
        "tax_map_id": p.get("tax_map_") or p.get("remap"),
        "jurisdiction": None, "county": "TAZEWELL",
        "site_addr1": _clean(p.get("property_l")),
        "site_addr2": None,
        "mail_addr1": _clean(p.get("owner_addr")),  # Tazewell ships full address as one string
        "mail_addr2": None,
        "owner1": p.get("owner_full"),
        "owner2": None,
        "assessed_total": _num(p.get("assessed_v")),
        "assessed_land": _num(p.get("land_value")),
        "assessed_bldg": None,
        "last_sale_date": None, "last_sale_price": None,
        "acres": _num(p.get("land_acres")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": None, "subd_name": None,
        "neighborhood": _clean(p.get("legal_desc")),
        "deedbook": None, "deedpage": None,
    }


def _pulaski_row(p: dict) -> dict:
    # WFS DescribeFeatureType showed: considerat=sale price, pxfer_date=sale date,
    # deed_type, grantor, current_im=improvements, current_la=land.
    # NOTE: current_ye is the assessment effective DATE (YYYYMMDD), not the value;
    # true total = improvements + land.
    imp = _num(p.get("current_im"))
    land = _num(p.get("current_la"))
    total = (imp or 0) + (land or 0) if (imp or land) else None
    return {
        "parcel_id": _clean(p.get("parcel_id")) or _clean(p.get("parc_lbl")) or _clean(p.get("dxf_text")),
        "tax_map_id": p.get("parc_lbl") or p.get("parcel_id"),
        "jurisdiction": None, "county": "PULASKI",
        "site_addr1": _clean(p.get("prop_stree")),
        "site_addr2": _split_addr2([p.get("prop_city"), p.get("prop_zip")]),
        "mail_addr1": p.get("own_street"),
        "mail_addr2": _split_addr2([p.get("own_city"), p.get("own_state"), p.get("own_zip")]),
        "owner1": p.get("owner1"),
        "owner2": p.get("owner2"),
        "assessed_total": total,
        "assessed_land": land,
        "assessed_bldg": imp,
        "last_sale_date": _sale_date(p.get("pxfer_date")),
        "last_sale_price": _num(p.get("considerat")),
        "deed_type": _clean(p.get("deed_type")),
        "grantor": _clean(p.get("grantor")),
        "acres": _num(p.get("legal_acre")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": None,
        "subd_name": p.get("area_name"),
        "neighborhood": _clean(p.get("neigh_name")) or _clean(p.get("leg_descri")),
        "deedbook": p.get("deed_book"), "deedpage": p.get("deed_page"),
    }


def _henry_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("acctnumb")) or _clean(p.get("map_numb")),
        "tax_map_id": p.get("map_numb"),
        "jurisdiction": None, "county": "HENRY",
        "site_addr1": _clean(p.get("propaddr")),
        "site_addr2": None,
        "mail_addr1": p.get("ownradr1"),
        "mail_addr2": _split_addr2([p.get("ownrcyst"), p.get("ownrzipc")]),
        "owner1": p.get("ownrname"),
        "owner2": p.get("prv1name"),
        "assessed_total": _num(p.get("totlmval")) or _num(p.get("totlival")),
        "assessed_land": _num(p.get("totllval")),
        "assessed_bldg": None,
        "last_sale_date": _sale_date(p.get("ownrdate")),
        "last_sale_price": _num(p.get("ownrcons")),
        "acres": _num(p.get("totlacre")),
        "year_built": _int(p.get("yearbilt")),
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("zonetype"),
        "subd_name": None,
        "neighborhood": _clean(p.get("legldesc")),
        "deedbook": p.get("ownrdeed"), "deedpage": None,
    }


def _wise_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("parcel_id")) or _clean(p.get("map_number")),
        "tax_map_id": p.get("map_number"),
        "jurisdiction": None,
        "county": "WISE",
        "site_addr1": _clean(p.get("situsaddre")),
        "site_addr2": None,
        "mail_addr1": p.get("address"),
        "mail_addr2": _split_addr2([p.get("address2"), p.get("city"), p.get("state"), p.get("zip")]),
        "owner1": p.get("primaryown"),
        "owner2": p.get("secondaryo"),
        "assessed_total": _num(p.get("totalasses")),
        "assessed_land": _num(p.get("land")),
        "assessed_bldg": None,
        "last_sale_date": None,
        "last_sale_price": None,
        "acres": _num(p.get("acreage")),
        "year_built": None,
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("taxdistric"),
        "subd_name": None,
        "neighborhood": p.get("descriptio"),
        "deedbook": None,
        "deedpage": None,
    }


# ---------------------------------------------------------------------------
# WebGIS.net (Hurt & Proffitt) — ArcGIS REST under /arcgis/rest/services/VA/<name>/MapServer/<layer>

_CRAIG_FIELDS = ",".join([
    "OBJECTID","HPAcctNo","HPLabel","REComment","OwnerName1","OwnerName2",
    "OwnerAddress1","OwnerAddress2","OwnerCity","OwnerState","OwnerZip",
    "zoning","UID","parcel_id","tax_bill_id","PropertyStreet","PropertyCity",
    "PropertyState","PropertyZip","platbook","platpage","tax_legal_acreage",
    "legal_acreage","legal_sqft","Legal_1","Legal_2",
])


def _craig_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("parcel_id")) or _clean(p.get("HPAcctNo")),
        "tax_map_id": p.get("HPLabel") or p.get("tax_bill_id"),
        "jurisdiction": None, "county": "CRAIG",
        "site_addr1": _split_addr2([p.get("PropertyStreet")]),
        "site_addr2": _split_addr2([p.get("PropertyCity"), p.get("PropertyState"), p.get("PropertyZip")]),
        "mail_addr1": p.get("OwnerAddress1"),
        "mail_addr2": _split_addr2([p.get("OwnerAddress2"), p.get("OwnerCity"), p.get("OwnerState"), p.get("OwnerZip")]),
        "owner1": p.get("OwnerName1"),
        "owner2": p.get("OwnerName2"),
        "assessed_total": None, "assessed_land": None, "assessed_bldg": None,
        "last_sale_date": None, "last_sale_price": None,
        "acres": _num(p.get("legal_acreage")) or _num(p.get("tax_legal_acreage")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": _int(p.get("legal_sqft")), "stories": None,
        "zoning": p.get("zoning"), "subd_name": None,
        "neighborhood": _clean(p.get("Legal_1")),
        "deedbook": p.get("platbook"), "deedpage": p.get("platpage"),
    }


_SMYTH_FIELDS = ",".join([
    "OBJECTID","ID","ACCOUNT","Year_Built","Name","Owner_Address","Owner_City",
    "Owner_State","Owner_Zip","Street_Number","Street_Name","City","State","Zip",
    "Acreage","District","Description","Sale_Date","Deed_Book","Deed_Page",
    "GIS_PIN","Imp_Value","Land_Value","Total_Property_Value",
])


def _smyth_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("GIS_PIN")) or _clean(p.get("ID")) or _clean(p.get("ACCOUNT")),
        "tax_map_id": p.get("GIS_PIN") or p.get("ID"),
        "jurisdiction": None, "county": "SMYTH",
        "site_addr1": _split_addr2([str(p.get("Street_Number") or ""), p.get("Street_Name")]),
        "site_addr2": _split_addr2([p.get("City"), p.get("State"), p.get("Zip")]),
        "mail_addr1": p.get("Owner_Address"),
        "mail_addr2": _split_addr2([p.get("Owner_City"), p.get("Owner_State"), p.get("Owner_Zip")]),
        "owner1": p.get("Name"),
        "owner2": None,
        "assessed_total": _num(p.get("Total_Property_Value")),
        "assessed_land": _num(p.get("Land_Value")),
        "assessed_bldg": _num(p.get("Imp_Value")),
        "last_sale_date": _sale_date(p.get("Sale_Date")),
        "last_sale_price": None,  # Smyth has no sale price field
        "acres": _num(p.get("Acreage")),
        "year_built": _int(p.get("Year_Built")),
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": None, "subd_name": None,
        "neighborhood": _clean(p.get("Description")),
        "deedbook": p.get("Deed_Book"), "deedpage": p.get("Deed_Page"),
    }


_BUCHANAN_FIELDS = ",".join([
    "OBJECTID","ACCOUNT","REMAP","GPIN","OWNER","ADDRESS1","ADDRESS2","ADDRESS3",
    "ZIPCODE1","DISTRICT","DESCRIPT1","DESCRIPT2","DESCRIPT3",
    "LAND_VALUE","IMP_VALUE","PLAT_BOOK","DEED_BOOK","DEED_PAGE","ACRES","PROPADR",
])


def _buchanan_row(p: dict) -> dict:
    addr2_bits = [p.get("ADDRESS2"), p.get("ADDRESS3"), p.get("ZIPCODE1")]
    return {
        "parcel_id": _clean(p.get("GPIN")) or _clean(p.get("ACCOUNT")) or _clean(p.get("REMAP")),
        "tax_map_id": p.get("REMAP") or p.get("GPIN"),
        "jurisdiction": None, "county": "BUCHANAN",
        "site_addr1": _clean(p.get("PROPADR")),
        "site_addr2": None,
        "mail_addr1": p.get("ADDRESS1"),
        "mail_addr2": _split_addr2(addr2_bits),
        "owner1": p.get("OWNER"),
        "owner2": None,
        "assessed_total": (_num(p.get("LAND_VALUE")) or 0) + (_num(p.get("IMP_VALUE")) or 0) or None,
        "assessed_land": _num(p.get("LAND_VALUE")),
        "assessed_bldg": _num(p.get("IMP_VALUE")),
        "last_sale_date": None, "last_sale_price": None,
        "acres": _num(p.get("ACRES")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": None, "subd_name": None,
        "neighborhood": _clean(p.get("DESCRIPT1")),
        "deedbook": p.get("DEED_BOOK"), "deedpage": p.get("DEED_PAGE"),
    }


# Charlotte County via geodecisions.com — partial (no sale data)
_CHARLOTTE_FIELDS = ",".join([
    "OBJECTID","CAMA_LINK","PIN_TYPE","record","ownerid","acres","OwnerName",
    "address1","address2","city","state","zipCode","landvalue","class",
    "deedbookpage","district","description",
])


def _charlotte_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("CAMA_LINK")) or _clean(str(p.get("record") or "")),
        "tax_map_id": p.get("CAMA_LINK"),
        "jurisdiction": None, "county": "CHARLOTTE",
        "site_addr1": None, "site_addr2": None,
        "mail_addr1": p.get("address1"),
        "mail_addr2": _split_addr2([p.get("address2"), p.get("city"), p.get("state"), p.get("zipCode")]),
        "owner1": p.get("OwnerName") or p.get("ownerid"),
        "owner2": None,
        "assessed_total": None,
        "assessed_land": _num(p.get("landvalue")),
        "assessed_bldg": None,
        "last_sale_date": None, "last_sale_price": None,
        "acres": _num(p.get("acres")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("class"),
        "subd_name": None,
        "neighborhood": _clean(p.get("description")),
        "deedbook": p.get("deedbookpage"), "deedpage": None,
    }


_PITTSYLVANIA_FIELDS = ",".join([
    "OBJECTID","GPIN","APIN","ID","ASSESSED_G","ACCOUNT_NAME1","ACCOUNT_NAME2",
    "ACCOUNT_ADDR1","ACCOUNT_CSZ","PROPERTYADDRESS","PC_PROPERTY_DESC",
    "PC_ASSESSED_ACREAGE","TOTAL_ACREAGE","DEED_DATE","PC_CURR_OWNER_BK_PG",
    "PC_ZONE_CODE","BLDG_YR_BUILT","MA_BLDG_AREA","SECT_FULL_BATHS",
    "TOTAL_LAND_VALUE","TOTAL_BLDG_VALUE","TOTAL_MKT_VALUE","TOTAL_NET_VALUE",
    "PC_CLASS_CODE","PARCEL_CLASS_DESC","PC_TOWNSHIP",
])


def _pittsylvania_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("GPIN")) or _clean(p.get("ID")),
        "tax_map_id": p.get("GPIN"),
        "jurisdiction": p.get("PC_TOWNSHIP"), "county": "PITTSYLVANIA",
        "site_addr1": _clean(p.get("PROPERTYADDRESS")),
        "site_addr2": None,
        "mail_addr1": p.get("ACCOUNT_ADDR1"),
        "mail_addr2": p.get("ACCOUNT_CSZ"),
        "owner1": p.get("ACCOUNT_NAME1"),
        "owner2": p.get("ACCOUNT_NAME2"),
        "assessed_total": _num(p.get("TOTAL_NET_VALUE")) or _num(p.get("TOTAL_MKT_VALUE")),
        "assessed_land": _num(p.get("TOTAL_LAND_VALUE")),
        "assessed_bldg": _num(p.get("TOTAL_BLDG_VALUE")),
        "last_sale_date": _sale_date(p.get("DEED_DATE")),
        "last_sale_price": None,
        "acres": _num(p.get("TOTAL_ACREAGE")) or _num(p.get("PC_ASSESSED_ACREAGE")),
        "year_built": _int(p.get("BLDG_YR_BUILT")),
        "bedrooms": None,
        "full_baths": _int(p.get("SECT_FULL_BATHS")),
        "half_baths": None,
        "sfla": _int(p.get("MA_BLDG_AREA")),
        "stories": None,
        "zoning": p.get("PC_ZONE_CODE"),
        "subd_name": None,
        "neighborhood": _clean(p.get("PARCEL_CLASS_DESC")) or _clean(p.get("PC_PROPERTY_DESC")),
        "deedbook": p.get("PC_CURR_OWNER_BK_PG"), "deedpage": None,
    }


_HALIFAX_FIELDS = ",".join([
    "OBJECTID","PRN","MAP","OWNER_CURRENT","Co_Owner_Current",
    "Address_Line_1_Current","Address_Line_2_Current","City_State_Zip_Current",
    "PARCEL_LOCATION_NUMBER","PARCEL_LOCATION_STREET","ALTERNATE_PARCEL_ID",
    "LEGAL_DESCRIP","DISTRICT","SALE_DATE_1","SALE_PRICE_1",
    "AS_LAND_VAL_1","AS_BLDG_VAL_1","AS_TOTAL_APR_VAL_1","AS_TOTAL_ASSESS_VAL_1",
    "CITY","STATE","ZIP",
])


def _halifax_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(str(p.get("PRN") or "")) or _clean(p.get("ALTERNATE_PARCEL_ID")),
        "tax_map_id": p.get("MAP") or p.get("ALTERNATE_PARCEL_ID"),
        "jurisdiction": None, "county": "HALIFAX",
        "site_addr1": _split_addr2([str(p.get("PARCEL_LOCATION_NUMBER") or ""), p.get("PARCEL_LOCATION_STREET")]),
        "site_addr2": _split_addr2([p.get("CITY"), p.get("STATE"), p.get("ZIP")]),
        "mail_addr1": p.get("Address_Line_1_Current"),
        "mail_addr2": _split_addr2([p.get("Address_Line_2_Current"), p.get("City_State_Zip_Current")]),
        "owner1": p.get("OWNER_CURRENT"),
        "owner2": p.get("Co_Owner_Current"),
        "assessed_total": _num(p.get("AS_TOTAL_ASSESS_VAL_1")) or _num(p.get("AS_TOTAL_APR_VAL_1")),
        "assessed_land": _num(p.get("AS_LAND_VAL_1")),
        "assessed_bldg": _num(p.get("AS_BLDG_VAL_1")),
        "last_sale_date": _sale_date(p.get("SALE_DATE_1")),
        "last_sale_price": _num(p.get("SALE_PRICE_1")),
        "acres": None, "year_built": None,
        "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": None, "subd_name": None,
        "neighborhood": _clean(p.get("LEGAL_DESCRIP")),
        "deedbook": None, "deedpage": None,
    }


# ---------------------------------------------------------------------------
# Timmons / SouthsideGIS — ArcGIS Online hosted services under Timmons' org

_MECK_FIELDS = ",".join([
    "OBJECTID","PRN","ParcelNumber","PIN","AccountName","CareOf","BusinessName",
    "Legal1","Legal2","Zoning","ZoningCode","StateClass","StateClassCode",
    "Subdivision","Neighborhood","TransferDate","SalesCode","Consideration",
    "InstrumentNumber","TotalAcres","CrtLand","CrtLandUse","CrtMainStructures",
    "CrtOtherStructures","CrtTotal","Deed","Plat",
])


def _meck_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(str(p.get("PRN") or "")) or _clean(p.get("PIN")) or _clean(p.get("ParcelNumber")),
        "tax_map_id": p.get("ParcelNumber") or p.get("PIN"),
        "jurisdiction": None, "county": "MECKLENBURG",
        "site_addr1": None, "site_addr2": None,
        "mail_addr1": None, "mail_addr2": None,
        "owner1": p.get("AccountName"),
        "owner2": p.get("CareOf"),
        "assessed_total": _num(p.get("CrtTotal")),
        "assessed_land": _num(p.get("CrtLand")),
        "assessed_bldg": _num(p.get("CrtMainStructures")),
        "last_sale_date": _sale_date(p.get("TransferDate")),
        "last_sale_price": _num(p.get("Consideration")),
        "acres": _num(p.get("TotalAcres")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("Zoning"),
        "subd_name": p.get("Subdivision"),
        "neighborhood": p.get("Neighborhood"),
        "deedbook": p.get("Deed"), "deedpage": p.get("Plat"),
    }


_BRUN_FIELDS = ",".join([
    "OBJECTID","MapParcelID","NAME","ADDRESS_1","CITY_STATE","ZIP","ACRES",
    "LAND","IMP","TOTAL","CL","DESCRIPTION_1","DESCRIPTION_2","DESCRIPTION_3",
    "DB","PG","INSTR_","CONSID","DATE","HSE__","PHYS__ADDRESS","DISTR",
])


def _brunswick_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("MapParcelID")),
        "tax_map_id": p.get("MapParcelID"),
        "jurisdiction": None, "county": "BRUNSWICK",
        "site_addr1": _split_addr2([str(p.get("HSE__") or ""), p.get("PHYS__ADDRESS")]),
        "site_addr2": None,
        "mail_addr1": p.get("ADDRESS_1"),
        "mail_addr2": _split_addr2([p.get("CITY_STATE"), p.get("ZIP")]),
        "owner1": p.get("NAME"),
        "owner2": None,
        "assessed_total": _num(p.get("TOTAL")),
        "assessed_land": _num(p.get("LAND")),
        "assessed_bldg": _num(p.get("IMP")),
        "last_sale_date": _sale_date(p.get("DATE")),
        "last_sale_price": _num(p.get("CONSID")),
        "acres": _num(p.get("ACRES")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("CL"),
        "subd_name": None,
        "neighborhood": _clean(p.get("DESCRIPTION_1")),
        "deedbook": p.get("DB"), "deedpage": p.get("PG"),
    }


_LUNENBURG_FIELDS = ",".join([
    "OBJECTID","ParcelID","Map_Number","GPIN","Zoning","Account_Name","Care_Of",
    "Account_Address","Account_City","Account_State","Account_Zip",
    "Legal_Description1","State_Class","State_Class_Code","Subdivision",
    "Neighborhood","Deed","Plat","Total_Acres","Tract_Size","Crt_Land",
    "Crt_Other_Structures","Crt_Total","Big_Map_Num","Situs_Full_Address",
])


def _lunenburg_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("Map_Number")) or _clean(p.get("ParcelID")) or _clean(p.get("GPIN")),
        "tax_map_id": p.get("Map_Number") or p.get("Big_Map_Num"),
        "jurisdiction": None, "county": "LUNENBURG",
        "site_addr1": _clean(p.get("Situs_Full_Address")),
        "site_addr2": None,
        "mail_addr1": p.get("Account_Address"),
        "mail_addr2": _split_addr2([p.get("Account_City"), p.get("Account_State"), p.get("Account_Zip")]),
        "owner1": p.get("Account_Name"),
        "owner2": p.get("Care_Of"),
        "assessed_total": _num(p.get("Crt_Total")),
        "assessed_land": _num(p.get("Crt_Land")),
        "assessed_bldg": _num(p.get("Crt_Other_Structures")),
        "last_sale_date": None, "last_sale_price": None,
        "acres": _num(p.get("Total_Acres")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("Zoning"),
        "subd_name": p.get("Subdivision"),
        "neighborhood": p.get("Neighborhood"),
        "deedbook": p.get("Deed"), "deedpage": p.get("Plat"),
    }


def _patrick_row(p: dict) -> dict:
    return {
        "parcel_id": _clean(p.get("smapnum")) or _clean(p.get("acct")),
        "tax_map_id": p.get("smapnum"),
        "jurisdiction": None, "county": "PATRICK",
        "site_addr1": _split_addr2([str(p.get("e911_st_no") or ""), p.get("e911_str_1")]),
        "site_addr2": None,
        "mail_addr1": p.get("address_1"),
        "mail_addr2": _split_addr2([p.get("city"), p.get("state"), p.get("zip")]),
        "owner1": p.get("owner_name"),
        "owner2": p.get("coowner_na"),
        "assessed_total": _num(p.get("total_valu")),
        "assessed_land": _num(p.get("land_value")),
        "assessed_bldg": _num(p.get("imp_val")),
        "last_sale_date": None, "last_sale_price": None,
        "acres": _num(p.get("acres")),
        "year_built": None, "bedrooms": None, "full_baths": None, "half_baths": None,
        "sfla": None, "stories": None,
        "zoning": p.get("class"),
        "subd_name": None,
        "neighborhood": _clean(p.get("property_d")),
        "deedbook": None, "deedpage": p.get("property_1"),
    }


def _arcgis_rest(county: str, url: str, fields: str, mapper: Callable[[dict], dict], pid_field: str) -> ParcelSource:
    return ParcelSource(
        county=county, url=url, out_fields=fields,
        to_canonical=mapper, parcel_id_field=pid_field,
    )


def _wfs(county: str, sub: str, typename: str, parcel_id_field: str, mapper: Callable[[dict], dict]) -> ParcelSource:
    return ParcelSource(
        county=county,
        url=f"https://{sub}.interactivegis.com/geoserver/{sub}/wfs",
        out_fields="*",  # WFS returns all attributes
        to_canonical=mapper,
        parcel_id_field=parcel_id_field,
        kind="geoserver_wfs",
        wfs_typename=typename,
    )


SOURCES: dict[str, ParcelSource] = {
    "MONTGOMERY": ParcelSource(
        county="MONTGOMERY",
        url="https://maps.montva.com/server/rest/services/Land/Parcels_Public/MapServer/1",
        out_fields=_MONTGOMERY_FIELDS,
        to_canonical=_montgomery_row,
        parcel_id_field="PARCEL_ID",
        jurisdiction_filter_field="JURISDICTI",
    ),
    "ROANOKE_COUNTY": ParcelSource(
        county="ROANOKE_COUNTY",
        url="https://arcgis.roanokecountyva.gov/arcgisweb/rest/services/OneView/OneClick/MapServer/1",
        out_fields=_ROANOKE_COUNTY_FIELDS,
        to_canonical=_roanoke_county_row,
        parcel_id_field="ParcelID",
        jurisdiction_filter_field="Jurisdiction",
    ),
    "FRANKLIN": ParcelSource(
        county="FRANKLIN",
        url="https://gis.franklincountyva.gov/arcgis/rest/services/PublicServices/UpdatedWebParcels/MapServer/0",
        out_fields=_FRANKLIN_FIELDS,
        to_canonical=_franklin_row,
        parcel_id_field="PIN",
    ),
    "RADFORD": ParcelSource(
        county="RADFORD",
        url="https://gisportal2.radford.va.us/arcgis/rest/services/Realestate/MapServer/2",
        out_fields=_RADFORD_FIELDS,
        to_canonical=_radford_row,
        parcel_id_field="PIN",
    ),
    "BOTETOURT": ParcelSource(
        county="BOTETOURT",
        url="https://www.webgis.net/arcgis/rest/services/VA/BotetourtCo_WebGIS/MapServer/23",
        out_fields=_BOTETOURT_FIELDS,
        to_canonical=_botetourt_row,
        parcel_id_field="LINK",
    ),
    "BEDFORD": ParcelSource(
        county="BEDFORD",
        url="https://webgis.bedfordcountyva.gov/arcgis/rest/services/OpenData/OpenDataProperty/MapServer/0",
        out_fields=_BEDFORD_FIELDS,
        to_canonical=_bedford_row,
        parcel_id_field="PIN",
    ),
    # iGIS / GeoServer WFS sources
    "FLOYD":      _wfs("FLOYD",      "floydcova",   "floydcova:geo_parcels",   "parc_id",   _floyd_row),
    "GILES":      _wfs("GILES",      "gilescova",   "gilescova:parcels_shp",   "map",       _giles_row),
    "CARROLL":    _wfs("CARROLL",    "carrollcova", "carrollcova:parcels",     "parc_id",   _carroll_row),
    "WASHINGTON": _wfs("WASHINGTON", "washcova",    "washcova:parcels",        "parcel_no", _washington_row),
    "BLAND":      _wfs("BLAND",      "blandcova",   "blandcova:parcels",       "smapnum",   _bland_row),
    "LEE":        _wfs("LEE",        "leecova",     "leecova:parcels",         "pin",       _lee_row),
    "WISE":       _wfs("WISE",       "wisecova",    "wisecova:parcels",        "parcel_id", _wise_row),
    "WYTHE":      _wfs("WYTHE",      "wythecova",   "wythecova:parcels",       "smapnum",   _wythe_row),
    "TAZEWELL":   _wfs("TAZEWELL",   "tazewellcova","tazewellcova:parcels",    "gislink",   _tazewell_row),
    "PULASKI":    _wfs("PULASKI",    "pulaskicova", "pulaskicova:parcels",     "parcel_id", _pulaski_row),
    "HENRY":      _wfs("HENRY",      "henrycova",   "henrycova:parcels",       "acctnumb",  _henry_row),
    # WebGIS.net (Hurt & Proffitt) — ArcGIS REST
    "CRAIG":    _arcgis_rest("CRAIG",
        "https://www.webgis.net/arcgis/rest/services/VA/Craig_WebGIS/MapServer/9",
        _CRAIG_FIELDS, _craig_row, "parcel_id"),
    "SMYTH":    _arcgis_rest("SMYTH",
        "https://www.webgis.net/arcgis/rest/services/VA/SmythCo_WebGIS/MapServer/17",
        _SMYTH_FIELDS, _smyth_row, "GIS_PIN"),
    "BUCHANAN": _arcgis_rest("BUCHANAN",
        "https://www.webgis.net/arcgis/rest/services/VA/Buchanan/MapServer/11",
        _BUCHANAN_FIELDS, _buchanan_row, "GPIN"),
    "HALIFAX":  _arcgis_rest("HALIFAX",
        "https://www.webgis.net/arcgis/rest/services/VA/HalifaxCo_WebGIS/MapServer/11",
        _HALIFAX_FIELDS, _halifax_row, "PRN"),
    # Timmons / SouthsideGIS
    "MECKLENBURG": _arcgis_rest("MECKLENBURG",
        "https://services.arcgis.com/O8ZpeBC0xLM5nL34/arcgis/rest/services/MeckParcels_TammyTest20221101/FeatureServer/0",
        _MECK_FIELDS, _meck_row, "PRN"),
    "BRUNSWICK": _arcgis_rest("BRUNSWICK",
        "https://services.arcgis.com/O8ZpeBC0xLM5nL34/arcgis/rest/services/GIS_TaxParcel_Brun_Latest/FeatureServer/0",
        _BRUN_FIELDS, _brunswick_row, "MapParcelID"),
    "LUNENBURG": _arcgis_rest("LUNENBURG",
        "https://services.arcgis.com/O8ZpeBC0xLM5nL34/arcgis/rest/services/LunenburgParcels/FeatureServer/0",
        _LUNENBURG_FIELDS, _lunenburg_row, "Map_Number"),
    # Patrick is on iGIS (patcova subdomain), WFS-based like the other iGIS counties
    "PATRICK":  _wfs("PATRICK",   "patcova",   "patcova:parcels",   "smapnum",  _patrick_row),
    "CHARLOTTE": _arcgis_rest("CHARLOTTE",
        "https://parcelviewer.geodecisions.com/arcgis/rest/services/Charlotte_CivQuest/Charlotte_CivQuest/FeatureServer/7",
        _CHARLOTTE_FIELDS, _charlotte_row, "CAMA_LINK"),
    "PITTSYLVANIA": _arcgis_rest("PITTSYLVANIA",
        "https://services2.arcgis.com/mTpBDvIjv8OhMDVd/arcgis/rest/services/Tax_Parcels/FeatureServer/100",
        _PITTSYLVANIA_FIELDS, _pittsylvania_row, "GPIN"),
}


def get(county: str) -> ParcelSource:
    key = county.upper()
    if key not in SOURCES:
        raise KeyError(f"Unknown county {county!r}. Known: {sorted(SOURCES)}")
    return SOURCES[key]
