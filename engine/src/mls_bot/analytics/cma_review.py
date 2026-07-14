"""Layer 3 — adversarial comp-set review.

A final sanity gate: given the subject, the chosen comp set, and the
triangulated value, one LLM call critiques the set the way a reviewing
appraiser would — "is this comp obviously wrong? what's missing? is the
value defensible?" — and returns a short structured critique surfaced in the
dashboard preview.

It does NOT change the number or the comps; it flags. Degrades to ``None``
when no API key is configured.
"""
from __future__ import annotations

from typing import Any, Optional

from .llm import call_json, llm_available


_SYSTEM = (
    "You are a senior appraiser doing a final review of a junior's CMA. You "
    "are skeptical and concise. You flag comps that don't belong, gaps in the "
    "set, and whether the headline value is defensible. You never fabricate "
    "data. Return strict JSON only."
)


def review_cma(subject: dict[str, Any], comps: list[dict[str, Any]],
               valuation: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return a critique dict or ``None`` if the LLM is unavailable.

    Critique keys: ``overall`` (str), ``confidence`` ("high"|"medium"|"low"),
    ``weak_comps`` (list of {address, why}), ``missing`` (list of str),
    ``value_check`` (str)."""
    if not llm_available() or not comps:
        return None

    sf = subject.get("sqft")
    lines = [
        f"SUBJECT: {subject.get('address')} — {sf} sqft, "
        f"{subject.get('bedrooms')}bd/{subject.get('full_baths')}ba, "
        f"built {subject.get('year_built')}, {subject.get('subdivision')} subdivision, "
        f"{subject.get('acres')} acres, {subject.get('county')} County.",
        "",
        f"TRIANGULATED VALUE: ${valuation.get('mid')} "
        f"(range ${valuation.get('low')}-${valuation.get('high')}, "
        f"method divergence {valuation.get('divergence_pct')}%).",
        "",
        "COMP SET:",
    ]
    for i, c in enumerate(comps, 1):
        ppsf = None
        if c.get("sqft") and c.get("sold_price") and c["sqft"]:
            ppsf = round(float(c["sold_price"]) / float(c["sqft"]))
        dist = c.get("distance_mi") if "distance_mi" in c else c.get("_distance_mi")
        lines.append(
            f"  [{i}] {c.get('address')} ({c.get('subdivision')}) — "
            f"sold {str(c.get('close_date'))[:10]} ${c.get('sold_price')} / "
            f"{c.get('sqft')} sqft = ${ppsf}/sqft, "
            f"{round(dist,1) if isinstance(dist,(int,float)) else '?'} mi away, "
            f"cohort {c.get('cohort') or c.get('_cohort')}."
        )
    lines.append(
        "\nReturn a JSON object with: "
        '"overall" (one-sentence verdict), '
        '"confidence" ("high"|"medium"|"low"), '
        '"weak_comps" (array of {"address": str, "why": str} for comps that '
        "don't belong — empty array if all are fine), "
        '"missing" (array of strings — what kind of comp or signal is absent), '
        '"value_check" (one sentence on whether the headline value is defensible). '
        "Return ONLY the JSON object."
    )
    user = "\n".join(lines)

    result = call_json(system=_SYSTEM, user=user, max_tokens=900)
    if not isinstance(result, dict):
        return None
    # Normalize shape defensively.
    return {
        "overall": str(result.get("overall") or ""),
        "confidence": str(result.get("confidence") or "medium"),
        "weak_comps": result.get("weak_comps") if isinstance(result.get("weak_comps"), list) else [],
        "missing": result.get("missing") if isinstance(result.get("missing"), list) else [],
        "value_check": str(result.get("value_check") or ""),
    }


__all__ = ["review_cma"]
