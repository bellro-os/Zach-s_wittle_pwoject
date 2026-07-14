"""Layer 1 — AI comp-hygiene reviewer.

The deterministic scorer ranks comps on structured fields (sqft, acres,
distance, recency). It is blind to the free-text MLS remarks, which is where
non-arms-length deals, condition outliers, and wrong-property-type comps hide.
This module reads the shortlisted comps' remarks in ONE batched LLM call and
returns structured hygiene verdicts that the deterministic engine folds back
in (drop bad comps, flag condition outliers). The LLM never sets a price.

Empirically (see the accuracy test on 509 Jefferson) this is the one place an
LLM measurably improved the comp set — it caught a 2-bed "Other"-type property
the numeric scorer ranked #1.

Degrades cleanly: if no ``ANTHROPIC_API_KEY`` is set, :func:`review_comps`
returns ``{}`` and the caller proceeds with the deterministic comp set
unchanged.

Caching: a closed comp's remarks never change, so each comp's verdict is
cached in ``data/cma_hygiene_cache.json``. The key hashes everything the
verdict depends on — listing_id, model, prompt version, subject signature,
and the subject's own remarks — so a model swap or prompt change never
replays stale verdicts. After a few runs most comps are pre-analyzed and the
marginal cost approaches zero.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import duckdb

from .llm import call_json, llm_available

_LOG = logging.getLogger(__name__)

# Comp-hygiene reviewer model. Overridable via env so the backtest / optimizer
# can A/B a stronger model without a code change. Defaults to the shipped model.
HYGIENE_MODEL = os.environ.get("CMA_HYGIENE_MODEL", "claude-haiku-4-5-20251001").strip() \
    or "claude-haiku-4-5-20251001"

# Part of the cache key — bump whenever the prompt or verdict schema changes
# so stale-prompt verdicts are never replayed. "2" = AGENT REMARKS line
# dropped (column is 100%-NULL upstream) + subject-remarks condition line.
PROMPT_VERSION = "2"

# Cache file format version. Pre-versioned files predate the model/prompt
# aware key and may hold index-misassigned verdicts — they are discarded on
# load, never migrated.
_CACHE_VERSION = 2

# Parse-time clamp on the model's per-comp $/sqft condition adjustment,
# mirroring the deterministic path's ±15 (cached historical verdicts had
# reached |70|).
_PPSF_ADJ_LIMIT = 15.0

# Times a batch came back with a different verdict count than comps sent
# (observable by backtests / monitoring; reset on module reload).
MISMATCH_COUNT = 0

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MLS_LOOKUP_PARQUET = _PROJECT_ROOT / "data" / "mls_lookup.parquet"
# Cache path is overridable via env so a backtest can isolate its cache from
# the shipped shared location.
_CACHE_PATH = Path(os.environ.get("CMA_HYGIENE_CACHE", "").strip()
                   or (_PROJECT_ROOT / "data" / "cma_hygiene_cache.json"))


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"_v": _CACHE_VERSION}
    if not isinstance(data, dict) or data.get("_v") != _CACHE_VERSION:
        # Old/unknown format — start fresh rather than migrate possibly
        # poisoned entries (pre-v2 keys were model-blind and zip-mapped).
        return {"_v": _CACHE_VERSION}
    return data


def _save_cache(cache: dict[str, Any]) -> None:
    cache["_v"] = _CACHE_VERSION
    try:
        _CACHE_PATH.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    except Exception:
        pass


def _cache_key(listing_id: str, model: str, subject_sig: str,
               remarks_hash: str = "") -> str:
    # A verdict depends on the comp, the subject it is compared to, the model
    # that produced it, the prompt version, and the subject's own remarks (if
    # fed in). Hash them all so none can silently alias another's verdict.
    raw = "|".join([str(listing_id), str(model), PROMPT_VERSION,
                    subject_sig, remarks_hash])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Remarks fetch
# ---------------------------------------------------------------------------

def _fetch_remarks(listing_ids: list[str]) -> dict[str, dict[str, str]]:
    """Pull public/agent remarks for the given listing_ids from the slim parquet."""
    ids = [str(i) for i in listing_ids if i]
    if not ids or not _MLS_LOOKUP_PARQUET.exists():
        return {}
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW l AS SELECT * FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}')"
    )
    quoted = ",".join("'" + i.replace("'", "''") + "'" for i in ids)
    try:
        rows = con.execute(
            f"SELECT CAST(listing_id AS VARCHAR) AS lid, public_remarks, agent_remarks "
            f"FROM l WHERE CAST(listing_id AS VARCHAR) IN ({quoted})"
        ).fetchall()
    except Exception:
        return {}
    out: dict[str, dict[str, str]] = {}
    for lid, pub, agt in rows:
        out[str(lid)] = {
            "public_remarks": (pub or "")[:700],
            "agent_remarks": (agt or "")[:400],
        }
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a meticulous residential real-estate appraiser. You read MLS "
    "remarks for comparable sales and judge, for each, whether it is a clean "
    "arms-length transaction, what condition tier it is, whether its property "
    "type actually matches the subject, and how its price-per-sqft should be "
    "adjusted to normalize CONDITION to the subject. You never invent facts "
    "not supported by the remarks. You return strict JSON only."
)


def _subject_signature(subject: dict[str, Any]) -> str:
    sf = subject.get("sqft") or "?"
    sub = str(subject.get("subdivision") or "").strip()[:20]
    return f"{sf}-{sub}"


def _mask_prices(txt: str) -> str:
    """Mask $-amounts so subject remarks can't leak price into the review."""
    return re.sub(r"\$\s?[\d][\d,\.kK]*", "$***", txt or "")


def _norm_addr(s: Any) -> str:
    """Normalize an address for fuzzy verdict matching: upper, alnum, 25 chars."""
    t = re.sub(r"[^A-Z0-9 ]+", " ", str(s or "").upper())
    return re.sub(r"\s+", " ", t).strip()[:25]


def _match_by_address(to_review: list[dict[str, Any]],
                      result: list[Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Recover (comp, verdict) pairs via the model's returned addresses.

    Used when the verdict count doesn't match the comp count (an omission
    would shift every later verdict under zip-by-index). Only unambiguous
    matches are returned; unmatched comps get NO verdict and are not cached.
    """
    by_addr: dict[str, list[dict[str, Any]]] = {}
    for v in result:
        if isinstance(v, dict):
            by_addr.setdefault(_norm_addr(v.get("address")), []).append(v)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for c in to_review:
        na = _norm_addr(c.get("address"))
        candidates = by_addr.get(na) or []
        if na and len(candidates) == 1:
            pairs.append((c, candidates[0]))
    return pairs


def review_comps(subject: dict[str, Any], comps: list[dict[str, Any]],
                 *, model: Optional[str] = None,
                 subject_remarks: Optional[dict[str, Any]] = None,
                 ) -> dict[str, dict[str, Any]]:
    """Return a hygiene verdict per comp address.

    Each verdict: ``{keep, arms_length, property_type_match, condition_tier,
    ppsf_adjustment_pct, reason}``. Returns ``{}`` when the LLM is unavailable
    or no remarks could be fetched — the caller then uses the comps as-is.

    ``subject_remarks`` (optional, ``{"public_remarks": ..., "agent_remarks":
    ...}``) feeds the subject's OWN listing remarks into the prompt so
    condition adjustments are relative to the subject's actual condition
    instead of the stock "average-to-updated" assumption. $-amounts are
    masked so no price leaks into the review.
    """
    if not llm_available() or not comps:
        return {}

    eff_model = (model or HYGIENE_MODEL).strip()
    subject_sig = _subject_signature(subject)

    subj_pub = subj_agt = ""
    if isinstance(subject_remarks, str):
        # Tolerate a bare string (footgun: it used to silently no-op).
        subject_remarks = {"public_remarks": subject_remarks}
    if isinstance(subject_remarks, dict):
        subj_pub = _mask_prices(str(subject_remarks.get("public_remarks") or ""))
        subj_agt = _mask_prices(str(subject_remarks.get("agent_remarks") or ""))
    if subj_pub or subj_agt:
        remarks_hash = hashlib.sha256(
            f"{subj_pub}\x1f{subj_agt}".encode("utf-8")).hexdigest()[:16]
        cond_line = ("The subject's own listing remarks (USE THESE to set the "
                     "subject's condition): "
                     + " ".join(p for p in (subj_pub, subj_agt) if p))
    else:
        remarks_hash = ""
        cond_line = ("Treat the subject as average-to-updated condition "
                     "unless told otherwise.")

    cache = _load_cache()

    # Resolve verdicts from cache where possible; collect the rest for one call.
    verdicts: dict[str, dict[str, Any]] = {}
    to_review: list[dict[str, Any]] = []
    for c in comps:
        lid = str(c.get("listing_id") or "")
        addr = str(c.get("address") or "")
        if lid:
            ck = _cache_key(lid, eff_model, subject_sig, remarks_hash)
            if ck in cache:
                verdicts[addr] = cache[ck]
                continue
        to_review.append(c)

    if not to_review:
        return verdicts

    remarks = _fetch_remarks([str(c.get("listing_id") or "") for c in to_review])

    # Build the batched prompt.
    sf_subj = subject.get("sqft")
    lines = [
        f"SUBJECT: {subject.get('address')} — {sf_subj} sqft, "
        f"{subject.get('bedrooms')}bd/{subject.get('full_baths')}ba, "
        f"built {subject.get('year_built')}, {subject.get('subdivision')} subdivision, "
        f"{subject.get('acres')} acres. {cond_line}",
        "",
        "COMPARABLES TO REVIEW:",
    ]
    for i, c in enumerate(to_review, 1):
        lid = str(c.get("listing_id") or "")
        rem = remarks.get(lid, {})
        ppsf = None
        if c.get("sqft") and c.get("sold_price") and c["sqft"]:
            ppsf = round(float(c["sold_price"]) / float(c["sqft"]))
        # agent_remarks is 100%-NULL upstream, so only public remarks are
        # rendered (the AGENT line printed "(none)" on every call).
        lines.append(
            f"\n[{i}] {c.get('address')} ({c.get('subdivision')}) — "
            f"sold {str(c.get('close_date'))[:10]} ${c.get('sold_price')} / "
            f"{c.get('sqft')} sqft = ${ppsf}/sqft, "
            f"{c.get('bedrooms')}bd/{c.get('full_baths')}ba, built {c.get('year_built')}, "
            f"sold/list {c.get('original_list_price') and round(float(c.get('sold_price'))/float(c.get('original_list_price')),3)}.\n"
            f"    PUBLIC REMARKS: {rem.get('public_remarks') or '(none)'}"
        )
    lines.append(
        "\n\nReturn a JSON array, one object per comparable, in the same order, "
        "each with EXACTLY these keys: "
        '{"address": str, "keep": bool (false if it is not a valid comp for this subject), '
        '"arms_length": bool, "property_type_match": bool (false if e.g. townhouse/condo/land '
        'when subject is a single-family house), '
        '"condition_tier": one of "distressed"|"dated"|"average"|"updated"|"fully_renovated"|"luxury", '
        '"ppsf_adjustment_pct": number (negative if the comp is nicer than the subject so its '
        '$/sqft should be discounted; positive if inferior), '
        '"reason": str (one sentence citing a remark phrase)}. '
        "Return ONLY the JSON array."
    )
    user = "\n".join(lines)

    result = call_json(system=_SYSTEM, user=user, max_tokens=2000,
                       model=eff_model)
    if result is None:
        # One retry on request/JSON-parse failure before degrading.
        result = call_json(system=_SYSTEM, user=user, max_tokens=2000,
                           model=eff_model)
    if not isinstance(result, list):
        # LLM failed or returned garbage — degrade to the cached subset.
        return verdicts

    if len(result) == len(to_review):
        pairs = list(zip(to_review, result))
    else:
        # An omitted/extra item would shift every later verdict under
        # zip-by-index — recover what we can by the model's returned address.
        global MISMATCH_COUNT
        MISMATCH_COUNT += 1
        pairs = _match_by_address(to_review, result)
        _LOG.warning(
            "hygiene verdict count mismatch (sent %d comps, got %d verdicts): "
            "recovered %d by address, rest left unverdicted and uncached "
            "(mismatch #%d)",
            len(to_review), len(result), len(pairs), MISMATCH_COUNT)

    wrote = False
    for c, verdict in pairs:
        if not isinstance(verdict, dict):
            continue
        addr = str(c.get("address") or "")
        adj = _safe_num(verdict.get("ppsf_adjustment_pct"), 0.0)
        clean = {
            "keep": bool(verdict.get("keep", True)),
            "arms_length": bool(verdict.get("arms_length", True)),
            "property_type_match": bool(verdict.get("property_type_match", True)),
            "condition_tier": str(verdict.get("condition_tier") or "average"),
            # Clamp at ingest for parity with the deterministic ±15 path.
            "ppsf_adjustment_pct": max(-_PPSF_ADJ_LIMIT, min(_PPSF_ADJ_LIMIT, adj)),
            "reason": str(verdict.get("reason") or ""),
        }
        verdicts[addr] = clean
        lid = str(c.get("listing_id") or "")
        if lid:
            cache[_cache_key(lid, eff_model, subject_sig, remarks_hash)] = clean
            wrote = True

    if wrote:
        _save_cache(cache)
    return verdicts


def _safe_num(v, default: float) -> float:
    try:
        f = float(v)
        return f if f == f else default  # reject NaN
    except (TypeError, ValueError):
        return default


def apply_hygiene(comps: list[dict[str, Any]],
                  verdicts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate comps with hygiene verdicts and drop the ones flagged unusable.

    Adds ``_hygiene`` to each surviving comp. Comps flagged ``keep=false`` or
    ``property_type_match=false`` or ``arms_length=false`` are removed. When a
    comp has no verdict (LLM unavailable), it passes through unchanged.
    """
    if not verdicts:
        return comps
    out: list[dict[str, Any]] = []
    for c in comps:
        addr = str(c.get("address") or "")
        v = verdicts.get(addr)
        if v is None:
            out.append(c)
            continue
        if not v.get("keep", True) or not v.get("property_type_match", True) \
                or not v.get("arms_length", True):
            # Dropped — record why on a sidecar list the caller can surface.
            c["_hygiene_dropped"] = v.get("reason") or "flagged by hygiene review"
            continue
        c2 = dict(c)
        c2["_hygiene"] = v
        out.append(c2)
    return out


__all__ = ["review_comps", "apply_hygiene", "_fetch_remarks", "PROMPT_VERSION"]
