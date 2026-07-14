"""Thin wrappers around profile helpers so detectors read cleanly.

All primitives live in mls_bot.profile; this module exists to localize imports
and give detectors a stable interface (so a future refactor of profile.py
doesn't ripple through every category).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..profile import (
    _BAD_MAIL_KEYS,
    _norm_addr,
    _norm_mail,
    _parse_date,
    classify_owner,
)


def is_person(row: dict) -> bool:
    return classify_owner(row.get("owner1")) == "person"


def is_entity(row: dict) -> bool:
    return classify_owner(row.get("owner1")) == "entity"


def is_govt(row: dict) -> bool:
    return classify_owner(row.get("owner1")) == "govt_or_institution"


def mail_key(row: dict) -> str:
    return _norm_mail(row.get("mail_addr1"), row.get("mail_addr2"))


def site_key(row: dict) -> str:
    return _norm_addr(row.get("site_addr1"))


def is_owner_occupied(row: dict) -> bool | None:
    """True if the owner's street matches the property street.

    Compares addr1 to addr1 only — the assessor feed stores city/state/zip in
    addr2 for mail but not for site, so comparing the full mail_key to
    site_key would always return False.
    """
    site = _norm_addr(row.get("site_addr1"))
    mail = _norm_addr(row.get("mail_addr1"))
    if not site or not mail:
        return None
    return site == mail


def tenure_years(row: dict, today: date | None = None) -> int | None:
    sd = _parse_date(row.get("last_sale_date"))
    if not sd:
        return None
    t = (today or date.today()) - sd
    return t.days // 365


def parse_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def filter_jurisdiction(rows: list[dict], jurisdiction: str | None) -> list[dict]:
    if not jurisdiction or jurisdiction.upper() == "ALL":
        return rows
    j = jurisdiction.upper()
    return [r for r in rows if (r.get("jurisdiction") or "").upper() == j]


__all__ = [
    "_BAD_MAIL_KEYS",
    "_norm_addr",
    "_norm_mail",
    "_parse_date",
    "classify_owner",
    "is_person",
    "is_entity",
    "is_govt",
    "mail_key",
    "site_key",
    "is_owner_occupied",
    "tenure_years",
    "parse_float",
    "filter_jurisdiction",
]
