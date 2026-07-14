"""Condition + property-type extraction from listing public_remarks.

Lightweight regex/keyword scoring. Outputs:
  condition_score  — int in [0..5], where 0=as-is/distressed, 5=fully renovated
  condition_flags  — list of matched signals (e.g. ['new_kitchen', 'turnkey'])
  is_manufactured  — True/False; flagged from "manufactured", "doublewide", etc.
  is_distressed    — True/False; flagged from "as-is", "estate sale", etc.

This is NOT a sentiment model — it's a tag dictionary tuned for VA agent slang.
Calibrated on a quick scan of NRV listings; extend the lexicons as needed.
"""

from __future__ import annotations

import re


# Each pattern adds (or subtracts) the given weight to the score.
# Score is then clipped to [0..5] with base 2.5.
_PATTERNS: list[tuple[str, str, float]] = [
    # +positive signals
    ("renovated",          r"\b(fully\s+renovated|completely\s+renovated|renovated\s+throughout|just\s+renovated|recent(ly)?\s+renovated)\b", +1.5),
    ("renovation_partial", r"\b(renovat(ed|ion))\b", +0.7),
    ("turnkey",            r"\b(turn[-\s]?key|move[-\s]?in\s+ready)\b", +1.0),
    ("new_kitchen",        r"\b(new\s+kitchen|brand[-\s]new\s+kitchen|fully\s+updated\s+kitchen|kitchen\s+remodel|remodeled\s+kitchen)\b", +0.8),
    ("new_bath",           r"\b(new\s+bath|remodeled\s+bath|bath(room)?\s+remodel|new(ly)?\s+updated\s+bath)\b", +0.6),
    ("new_roof",           r"\b(new\s+roof|roof\s+replaced|recent(ly)?\s+replaced\s+roof)\b", +0.6),
    ("new_hvac",           r"\b(new\s+(hvac|furnace|heat\s+pump|a\.?c\.?)|hvac\s+replaced)\b", +0.4),
    ("new_floors",         r"\b(new\s+floor(ing|s)|hardwood(\s+floors)?\s+throughout|new\s+lvp|new\s+vinyl\s+plank)\b", +0.4),
    ("freshly_painted",    r"\b(fresh(ly)?\s+paint(ed)?|new\s+paint(\s+throughout)?)\b", +0.3),
    ("luxury",             r"\b(luxury|designer|custom\s+built|architect[-\s]designed|estate\s+home)\b", +0.5),
    ("upgrade",            r"\b(upgrade(d|s)|update(d|s))\b", +0.3),
    ("granite_quartz",     r"\b(granite|quartz)\s+counter(top)?s?\b", +0.3),
    ("stainless",          r"\bstainless(\s+steel)?\s+(appliance|appl)\b", +0.2),
    ("well_maintained",    r"\b(well[-\s]maintained|meticulous(ly\s+maintained)?|pride\s+of\s+ownership|lovingly\s+cared)\b", +0.5),
    ("smart_home",         r"\b(smart\s+home|nest|ring|smart\s+thermostat)\b", +0.2),
    ("energy_efficient",   r"\b(energy[-\s]efficient|solar\s+panels?|geothermal)\b", +0.3),

    # -negative signals (distress / fixer)
    ("as_is",              r"\b(sold\s+as[-\s]is|as[-\s]is\s+condition|as\s+is(\s+where\s+is)?)\b", -2.0),
    ("needs_tlc",          r"\b(needs?\s+tlc|some\s+tlc|tender\s+loving\s+care)\b", -1.5),
    ("fixer",              r"\b(fixer[-\s]upper|fixer\s+special|investor\s+special|handyman\s+special|diy[-\s]special)\b", -1.8),
    ("needs_work",         r"\b(needs\s+work|need(s|ed)\s+repair|some\s+repair(s)?|requires\s+repairs?)\b", -1.2),
    ("estate_sale",        r"\b(estate\s+sale|estate\s+of|heirs?\s+selling|probate\s+sale)\b", -0.5),
    ("foreclosure",        r"\b(foreclosure|foreclosed|reo\b|bank[-\s]owned|short\s+sale)\b", -1.0),
    ("dated",              r"\b(dated|original\s+(kitchen|bath|condition)|bring\s+your\s+vision|tons?\s+of\s+potential)\b", -0.5),
    ("deferred_maint",     r"\b(deferred\s+maintenance|cosmetic\s+repair(s)?\s+needed)\b", -0.8),
    ("priced_to_sell",     r"\b(priced\s+to\s+sell|priced\s+(below|under)\s+(market|appraisal|tax))\b", -0.3),
    ("cash_only",          r"\b(cash\s+only|cash\s+offer(s)?\s+only)\b", -1.0),
]

_MANUFACTURED_PATTERN = re.compile(
    r"\b(manufactured(\s+home)?|mobile\s+home|"
    r"single[-\s]?wide|double[-\s]?wide|triple[-\s]?wide|"
    r"modular(\s+home)?|hud\s+(home|tag))\b",
    re.IGNORECASE,
)

_DISTRESSED_PATTERN = re.compile(
    r"\b(sold\s+as[-\s]is|as[-\s]is\s+condition|fixer[-\s]upper|"
    r"investor\s+special|handyman\s+special|"
    r"foreclosure|reo\b|bank[-\s]owned|short\s+sale|"
    r"cash\s+only|estate\s+sale|probate\s+sale)\b",
    re.IGNORECASE,
)


def score_remarks(text: str | None) -> dict:
    """Return condition extraction for a single listing's remarks string."""
    if not text or not isinstance(text, str):
        return {
            "condition_score": None,
            "condition_flags": [],
            "is_manufactured": False,
            "is_distressed": False,
        }
    base = 2.5  # neutral baseline
    delta = 0.0
    flags: list[str] = []
    for name, pattern, weight in _PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            flags.append(name)
            delta += weight
    score = max(0.0, min(5.0, base + delta))
    return {
        "condition_score": round(score, 2),
        "condition_flags": flags,
        "is_manufactured": bool(_MANUFACTURED_PATTERN.search(text)),
        "is_distressed": bool(_DISTRESSED_PATTERN.search(text)),
    }


def label(score: float | None) -> str:
    if score is None:
        return "(no remarks)"
    if score >= 4.5: return "fully renovated"
    if score >= 3.5: return "well-updated"
    if score >= 2.5: return "average / well-maintained"
    if score >= 1.5: return "dated / needs cosmetic"
    return "distressed / needs work"
