"""Conversation openers tailored to each lead type.

When the agent expands the "Why?" panel on a row, the top of the panel
shows a one-line opener formatted with the row's actual data. The intent
is to *anchor* the call — instead of "I notice you've owned the house a
while", say "I noticed you reduced from $425k to $375k before pulling
the listing — was pricing the issue?"

Templates are Python f-string-style with {placeholders}. Values come from
the queue-row dict (call_queue() output in data_layer.py). When a value
is missing, the template falls back to a generic opener for that type.
"""

from __future__ import annotations

import re


# Maps lead_type → list of (regex on signal key to extract data, template).
# We fall back to the bare template if no signal-specific data is needed.

def _signal_value(signals_raw: str, key: str) -> str:
    """Pull the modifier from a signals_pos chunk like 'tenure:7.5y(+23)' →
    '7.5y'. Returns empty string if not present."""
    if not signals_raw:
        return ""
    for chunk in signals_raw.split(";"):
        m = re.match(rf"\s*{re.escape(key)}(?::([^()]+))?\(", chunk)
        if m:
            return (m.group(1) or "").strip()
    return ""


def _money(v) -> str:
    try:
        n = int(float(v))
        return f"${n:,}"
    except (TypeError, ValueError):
        return ""


_OPENERS: dict[str, str] = {
    "price_cut_motivated": (
        "I noticed you reduced your asking price by {pct_cut} before pulling "
        "the {address} listing — was pricing the issue, or has the timing shifted?"
    ),
    "serial_relister": (
        "Your home at {address} has been on the market {n_listings} times. "
        "What do you think kept it from selling — pricing, marketing, or condition?"
    ),
    "recent_forced_sale_alumni": (
        "I noticed you recently wrapped up a long sale process — those can "
        "drag. I wondered if {address} is on your radar at all, and whether "
        "it'd help to think through timing or strategy on it before listing."
    ),
    "tax_delinquent_person": (
        "I help homeowners navigate property-tax issues without losing equity. "
        "Has the situation at {address} given you any thought about your options?"
    ),
    "distressed_condition": (
        "Your last listing at {address} mentioned it needed some work. "
        "Are you still hoping to sell, or has the timing shifted? I have buyers "
        "looking for projects."
    ),
    "neighbor_of_recent_expired": (
        "Your neighbor's home at the nearby parcel just came off market. "
        "Buyers are still active in {subdivision} — would now be the time "
        "to talk about {address}?"
    ),
    "empty_nester_pattern": (
        "You've been at {address} {tenure_yrs} years — has the right-size "
        "question come up? I help long-time owners think through what's next."
    ),

    # Fallback types — for prospects whose dominant signal is an existing one
    "estate": (
        "I'm reaching out about {address}. I work with families navigating "
        "estate-related property decisions and wanted to introduce myself "
        "before there's any urgency."
    ),
    "expired_recent": (
        "I saw {address} came off the market recently. I wanted to ask what "
        "you'd want to see happen differently if you went back on."
    ),
    "mail_changed": (
        "I'm calling about {address}. I noticed your mailing address changed "
        "recently — is the {address} property still home, or have plans changed?"
    ),
    "intra_family": (
        "I work with families who have inherited or transferred property and "
        "wanted to introduce myself in case {address} comes up in conversation."
    ),
    "absentee_investor": (
        "I'm reaching out about {address}. I work with property investors in "
        "the area — curious if you've thought about timing on this one."
    ),
    "long_tenure": (
        "You've been at {address} {tenure_yrs} years — I help long-time "
        "homeowners think through what's next when timing might be right."
    ),
    "unclassified": (
        "I'm reaching out about {address}. I work with homeowners in the area "
        "and wanted to introduce myself."
    ),
}


def opener_for(row: dict) -> str:
    """Return a conversation opener tailored to the row's lead_type,
    formatted with row-specific values."""
    lead_type = (row.get("lead_type") or "unclassified").strip() or "unclassified"
    template = _OPENERS.get(lead_type, _OPENERS["unclassified"])
    raw_signals = row.get("signals_raw") or row.get("signals_pos") or ""

    # Pre-extract reusable values
    address = (row.get("site_addr") or "").strip().title() or "your home"
    subdivision = (row.get("subdivision") or "").strip().title() or "your area"

    tenure_yrs = row.get("tenure_years") or 0
    try:
        tenure_int = int(float(tenure_yrs))
    except (TypeError, ValueError):
        tenure_int = 0

    pct_cut_modifier = _signal_value(raw_signals, "price_cut_motivated")
    pct_cut = pct_cut_modifier or "a meaningful amount"
    serial_modifier = _signal_value(raw_signals, "serial_relister")
    # serial modifier looks like "5x"
    n_listings = serial_modifier.rstrip("x") if serial_modifier else "several"

    try:
        return template.format(
            address=address,
            subdivision=subdivision,
            tenure_yrs=tenure_int or "many",
            pct_cut=pct_cut,
            n_listings=n_listings,
        )
    except (KeyError, IndexError):
        # Defensive fallback if a placeholder is missing
        return _OPENERS["unclassified"].format(address=address)


def label_for(lead_type: str) -> str:
    """Human-readable label used in the lead-type chip + filter UI."""
    return {
        "price_cut_motivated":          "Price-cut motivated",
        "serial_relister":              "Serial re-lister",
        "recent_forced_sale_alumni":    "Forced-sale alumni",
        "tax_delinquent_person":        "Tax-delinquent",
        "distressed_condition":         "Distressed condition",
        "neighbor_of_recent_expired":   "Neighbor of expired",
        "empty_nester_pattern":         "Empty-nester",
        "estate":                       "Estate / trust",
        "expired_recent":               "Recently expired",
        "mail_changed":                 "Mail address changed",
        "intra_family":                 "Intra-family transfer",
        "absentee_investor":            "Absentee investor",
        "long_tenure":                  "Long-tenure owner",
        "unclassified":                 "Unclassified",
    }.get(lead_type, lead_type.replace("_", " ").title())


# Semantic color tones for the chip palette (maps to CSS classes in
# dashboard.css). Person-callable types get warmer/stronger colors;
# fallback types get cool neutrals.
def chip_class_for(lead_type: str) -> str:
    return {
        "price_cut_motivated":          "chip-warn",
        "serial_relister":              "chip-danger",
        "recent_forced_sale_alumni":    "chip-warn",
        "tax_delinquent_person":        "chip-danger",
        "distressed_condition":         "chip-warn",
        "neighbor_of_recent_expired":   "chip-success",
        "empty_nester_pattern":         "chip-info",
        "estate":                       "chip-neutral",
        "expired_recent":               "chip-info",
        "mail_changed":                 "chip-neutral",
        "intra_family":                 "chip-neutral",
        "absentee_investor":            "chip-neutral",
        "long_tenure":                  "chip-neutral",
        "unclassified":                 "chip-neutral",
    }.get(lead_type, "chip-neutral")


ALL_LEAD_TYPES = [
    "price_cut_motivated", "serial_relister", "recent_forced_sale_alumni",
    "tax_delinquent_person", "distressed_condition",
    "neighbor_of_recent_expired", "empty_nester_pattern",
    "estate", "expired_recent", "mail_changed", "intra_family",
    "absentee_investor", "long_tenure", "unclassified",
]
