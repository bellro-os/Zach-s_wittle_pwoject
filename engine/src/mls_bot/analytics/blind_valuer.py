"""Layer 2 — blind AI comparable read (the certified Haiku ensemble anchor).

An independent, price-blind valuation of the subject from the engine's OWN
selected comps: the model sees subject facts + comp facts/remarks (with every
$-amount and list/price/status phrase stripped) and returns one number. The
production ensemble is ``final mid = mean(engine unrounded mid, blind)`` —
certified 2026-07 on a held-out 1000-subject pool (engine-only 13.24% median
APE -> ensemble 11.54%; see Compbird docs/). Ported from the certification
harness (scratchpad ``packet_ladder.py`` E3 arm + ``cert_seed45.py``); the
leave-one-out machinery (as-of freezing, subject-sale exclusion, address-prefix
guards) is deliberately NOT ported — production comps come from the engine's
normal ``pick_comps`` selection, which already excludes the subject.

Env-gated: everything here is inert unless ``CMA_BLIND_ENSEMBLE=1`` is set in
the process environment (compbird's engine env only — Ratifyly leaves it unset
and its output stays byte-identical). The gate lives in the callers
(``build_cma._apply_blind_ensemble``); this module additionally degrades to
``None`` whenever no ``ANTHROPIC_API_KEY`` is configured.

ONE ANCHOR PER SUBJECT (the one-number invariant): the blind valuation is
computed once per subject signature — a hash of exactly the subject facts the
model sees — from the engine's untuned comp picks, then cached in-process AND
on disk (``data/cma_blind_cache.json``, same pattern as ``cma_hygiene``).
Every later valuation of that subject (profile, preview including user-tuned
recomputes, generate) folds the SAME cached anchor, so tuned recomputes never
pay a second LLM call and /profile == /preview == /generate holds. The comp-set
hash, model, prompt version and as-of date are recorded on each cache entry for
audit; the lookup key is (subject signature, model, prompt version) so a
hygiene-on and a hygiene-off caller of the same subject share one anchor.
Failures (timeout / parse) are cached IN-PROCESS ONLY as ``None`` so a whole
worker session stays consistently engine-only for that subject rather than
flip-flopping, while a later worker restart may retry.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .llm import call_messages, llm_available

# Blind-valuer model — the certified recipe's model. Env-overridable so a
# backtest can A/B a different model without a code change.
BLIND_MODEL = os.environ.get("CMA_BLIND_MODEL", "claude-haiku-4-5-20251001").strip() \
    or "claude-haiku-4-5-20251001"

# Part of the cache key — bump whenever the prompt or packet schema changes so
# stale anchors are never replayed. "1" = the certified E3 packet recipe.
PROMPT_VERSION = "1"

_CACHE_VERSION = 1

# Hard wall-clock budget for the LLM call (seconds). A blind read must never
# block a valuation — on timeout the caller silently (but logged) falls back
# to engine-only.
def _timeout() -> float:
    try:
        return float(os.environ.get("CMA_BLIND_TIMEOUT", "8") or "8")
    except ValueError:
        return 8.0


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MLS_LOOKUP_PARQUET = _PROJECT_ROOT / "data" / "mls_lookup.parquet"
_CACHE_PATH = Path(os.environ.get("CMA_BLIND_CACHE", "").strip()
                   or (_PROJECT_ROOT / "data" / "cma_blind_cache.json"))

# In-process anchor cache: key -> int (success) | None (failed this session —
# kept so one worker session never flip-flops between blind and engine-only).
_MEM: dict[str, Optional[int]] = {}


def _log(msg: str) -> None:
    print(f"[blind] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# $-amount + list/price/status stripping (leak rule) — ported verbatim from the
# certification harness (packet_ladder.strip_price).
# ---------------------------------------------------------------------------

_DOLLAR_RX = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s*[kKmM]?")
# price-ish bare numerics: "450k", "mid 300s", "low 400's", "upper 200s"
_NUMK_RX = re.compile(r"(?i)\b\d{2,4}\s*k\b|\b\d+00'?s\b|\b(?:low|mid|upper|high)\s+\$?\d+")
_KW_RX = re.compile(
    r"(?i)\b(list(?:ed|ing)?\s+(?:price|at|for)|list\s*price|asking|priced?\b|"
    r"under\s+contract|contingen\w*|pending|back\s+on\s+(?:the\s+)?market|"
    r"sold\s+(?:for|at)|apprais\w*|reduc(?:ed|tion)\w*|offer\s+deadline|"
    r"closing\s+cost\w*|(?:below|above|under|over)\s+(?:market|assess\w*)|"
    r"assessed?\s+value|price\s+(?:drop|improvement|change))\b")


def strip_price(text: str) -> str:
    """Remove whole sentences containing $-amounts or list/price/status phrases,
    then mask any residual $-amounts / price-ish numerics."""
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?;])\s+", str(text))
    kept = [p for p in parts
            if not (_DOLLAR_RX.search(p) or _KW_RX.search(p) or _NUMK_RX.search(p))]
    out = " ".join(kept)
    out = _DOLLAR_RX.sub("[amt]", out)
    out = _NUMK_RX.sub("[amt]", out)
    return re.sub(r"\s+", " ", out).strip()


# ---------------------------------------------------------------------------
# Prompt (ported verbatim from the certified harness arm)
# ---------------------------------------------------------------------------

PROMPT = """You are an expert residential comparable-sales analyst. Estimate the market value of the SUBJECT property as of {as_of}, using ONLY the recent nearby sales provided. Select the 4-6 most comparable sales, adjust for differences (size, lot, beds/baths, distance, sale date), and produce a value opinion.

SUBJECT (value this property):
{subject}

RECENT NEARBY SALES (all closed before {as_of}; distances from subject):
{comps}

Respond with STRICT JSON only, no other text:
{{"estimate": <int dollars>, "low": <int>, "high": <int>, "comps_used": [<addresses>]}}"""


# ---------------------------------------------------------------------------
# Packet rendering
# ---------------------------------------------------------------------------

def _f(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


# Subject facts the model sees — identical key set to the certified E3 subject
# line (base + E0 enrichment). None/absent values are omitted, never fabricated.
_SUBJECT_KEYS = ("address", "city", "sqft", "acres", "bedrooms", "full_baths",
                 "year_built", "half_baths", "subdivision", "property_subtype",
                 "appearance")


def subject_packet(subject: dict[str, Any],
                   remarks: Optional[str] = None) -> dict[str, Any]:
    d = {k: subject[k] for k in _SUBJECT_KEYS if subject.get(k) is not None}
    if remarks:
        d["remarks"] = remarks  # already stripped + truncated
    return d


def _fetch_packet_fields(listing_ids: list[str]) -> dict[str, dict[str, Any]]:
    """public_remarks + total_fin_sqft per listing_id from the slim parquet."""
    ids = [str(i) for i in listing_ids if i]
    if not ids or not _MLS_LOOKUP_PARQUET.exists():
        return {}
    try:
        import duckdb
        con = duckdb.connect(":memory:")
        quoted = ",".join("'" + i.replace("'", "''") + "'" for i in ids)
        rows = con.execute(
            f"SELECT CAST(listing_id AS VARCHAR), public_remarks, "
            f"TRY_CAST(total_fin_sqft AS DOUBLE) "
            f"FROM read_parquet('{_MLS_LOOKUP_PARQUET.as_posix()}') "
            f"WHERE CAST(listing_id AS VARCHAR) IN ({quoted})"
        ).fetchall()
        con.close()
    except Exception:
        return {}
    return {str(lid): {"public_remarks": pub or "", "total_fin_sqft": tfs}
            for lid, pub, tfs in rows}


def render_comp(c: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """One comp row of the blind packet, from an engine (pick_comps) comp dict.

    Field set = the certified E3 recipe's production subset: address, sold
    price/date, sqft, acres, beds, baths, year_built, distance, subtype,
    subdivision, appearance, dom, sold-to-orig-list ratio, total_fin_sqft,
    price-stripped remarks. Every NULL omitted. Returns None for comps the
    blind read must not see: pendings / no realized sold price (their only
    price signal is a list price — a leak the recipe strips).
    """
    sp = _f(c.get("sold_price"))
    if not sp or sp <= 0 or c.get("_pending"):
        return None
    out: dict[str, Any] = {"address": c.get("address"), "sold_price": int(sp)}
    cd = str(c.get("close_date") or "")[:10]
    if cd:
        out["sold_date"] = cd
    sf = _f(c.get("sqft"))
    if sf:
        out["sqft"] = int(sf)
    ac = _f(c.get("acres"))
    if ac:
        out["acres"] = round(ac, 2)
    beds = _f(c.get("bedrooms"))
    if beds:
        out["beds"] = int(beds)
    baths = _f(c.get("full_baths"))
    if baths:
        out["baths"] = float(baths)
    yb = _f(c.get("year_built"))
    if yb:
        out["year_built"] = int(yb)
    dist = _f(c.get("_distance_mi"))
    if dist is not None:
        out["distance_mi"] = round(dist, 2)
    if c.get("property_subtype"):
        out["subtype"] = str(c["property_subtype"])
    if c.get("subdivision") and str(c["subdivision"]).strip():
        out["subdivision"] = str(c["subdivision"]).strip()
    if c.get("appearance"):
        out["appearance"] = str(c["appearance"])[:60]
    dom = _f(c.get("dom"))
    if dom is not None:
        out["dom"] = int(dom)
    olp = _f(c.get("original_list_price")) or _f(c.get("list_price"))
    if olp and olp > 0:
        out["sold_to_orig_list"] = round(sp / olp, 2)
    extra = extra or {}
    tfs = _f(extra.get("total_fin_sqft"))
    if tfs:
        out["total_fin_sqft"] = int(tfs)
    rem = strip_price(extra.get("public_remarks") or "")[:250]
    if rem:
        out["remarks"] = rem
    return out


def build_packet(subject: dict[str, Any],
                 comps: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(subject packet, comp packet rows) for the blind prompt."""
    lids = [str(c.get("listing_id") or "") for c in comps]
    slid = str(subject.get("listing_id") or "")
    fields = _fetch_packet_fields([slid] + lids if slid else lids)

    subj_rem = ""
    if slid:
        # Subjects are often off-market in production — no listing row / no
        # remarks is fine, the packet simply omits them (degrade gracefully).
        subj_rem = strip_price(
            (fields.get(slid) or {}).get("public_remarks") or "")[:400]
        if "$" in subj_rem:
            # Production analogue of the harness leak-guard assert: a $ that
            # somehow survived the strip disqualifies the remarks, not the run.
            _log("subject remarks dropped ($ survived strip)")
            subj_rem = ""

    comp_rows = []
    for c, lid in zip(comps, lids):
        row = render_comp(c, fields.get(lid))
        if row is not None:
            comp_rows.append(row)
    return subject_packet(subject, subj_rem or None), comp_rows


# ---------------------------------------------------------------------------
# Single-subject blind call
# ---------------------------------------------------------------------------

def blind_value(subject: dict[str, Any], comps: list[dict[str, Any]],
                *, as_of: str, model: Optional[str] = None) -> Optional[int]:
    """One blind Haiku valuation from the packet. None on any failure.

    Faithful to the certified call: user-only prompt (no system), model
    default temperature (none sent), max_tokens 1500, ``estimate`` parsed from
    the first-to-last brace span. The only production addition is the hard
    ``CMA_BLIND_TIMEOUT`` (default 8s) wall so a slow call can't block a
    valuation.
    """
    if not llm_available():
        return None
    subj, comp_rows = build_packet(subject, comps)
    if len(comp_rows) < 2:
        _log(f"packet too thin ({len(comp_rows)} usable comps) — skipping blind read")
        return None
    msg = PROMPT.format(as_of=as_of, subject=json.dumps(subj),
                        comps="\n".join(json.dumps(r) for r in comp_rows))
    text = call_messages(system="", user=msg, max_tokens=1500,
                         model=(model or BLIND_MODEL), temperature=None,
                         timeout=_timeout())
    if not text:
        return None
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        est = json.loads(m.group(0)).get("estimate") if m else None
        est = float(est) if est else None
        return int(round(est)) if est and est > 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cache (hygiene-cache pattern: versioned JSON blob, tolerant I/O)
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, Any]:
    try:
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"_v": _CACHE_VERSION}
    if not isinstance(data, dict) or data.get("_v") != _CACHE_VERSION:
        return {"_v": _CACHE_VERSION}
    return data


def _save_cache(cache: dict[str, Any]) -> None:
    cache["_v"] = _CACHE_VERSION
    try:
        _CACHE_PATH.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    except Exception:
        pass


def subject_signature(subject: dict[str, Any]) -> str:
    """Hash of exactly the subject facts the model sees (+ parcel id).

    Deliberately excludes remarks so the signature needs no I/O — a subject
    fact edit (override) changes the signature and earns a fresh anchor; a
    comp-pool refresh does not.
    """
    ident = {k: subject.get(k) for k in _SUBJECT_KEYS}
    ident["parcel_id"] = str(subject.get("parcel_id") or "")
    raw = json.dumps(ident, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _anchor_key(sig: str, model: str) -> str:
    return hashlib.sha256(
        f"{sig}|{model}|{PROMPT_VERSION}".encode("utf-8")).hexdigest()


def _comp_set_hash(comps: list[dict[str, Any]]) -> str:
    ids = sorted(str(c.get("listing_id") or c.get("address") or "") for c in comps)
    return hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:16]


def get_blind_anchor(subject: dict[str, Any],
                     untuned_comps: Optional[list[dict[str, Any]]] = None,
                     *, fetch_untuned: Optional[Callable[[], list[dict[str, Any]]]] = None,
                     as_of: str) -> Optional[int]:
    """The subject's cached blind anchor, computing it once if needed.

    ``untuned_comps`` — the engine's untuned comp picks when the caller's own
    request IS untuned; tuned recomputes pass None and (on the rare cold path)
    supply ``fetch_untuned`` to derive the untuned picks, so the anchor is
    always computed at the certified posture regardless of user tuning.
    """
    if not llm_available():
        return None
    sig = subject_signature(subject)
    key = _anchor_key(sig, BLIND_MODEL)

    if key in _MEM:
        v = _MEM[key]
        _log(f"cache hit (memory): anchor={v} for {subject.get('address')}")
        return v
    disk = _load_cache()
    ent = disk.get(key)
    if isinstance(ent, dict) and isinstance(ent.get("blind"), (int, float)):
        v = int(ent["blind"])
        _MEM[key] = v
        _log(f"cache hit (disk): anchor={v} for {subject.get('address')}")
        return v

    comps = untuned_comps
    if comps is None and fetch_untuned is not None:
        try:
            comps = fetch_untuned()
        except Exception as e:
            _log(f"untuned comp fetch failed ({type(e).__name__}: {e}) — engine-only")
            comps = None
    if not comps:
        # Nothing to build a packet from; do NOT poison the session cache —
        # a later untuned call with comps in hand may still compute the anchor.
        return None

    t0 = time.perf_counter()
    try:
        v = blind_value(subject, comps, as_of=as_of)
    except Exception as e:  # the blind read must never break a valuation
        _log(f"blind call raised {type(e).__name__}: {e} — engine-only")
        v = None
    took = time.perf_counter() - t0
    _MEM[key] = v  # None too: one worker session stays consistent per subject
    if v is None:
        _log(f"blind read unavailable for {subject.get('address')} "
             f"({took:.1f}s) — engine-only (logged, session-cached)")
        return None
    disk[key] = {
        "blind": v,
        "sig": sig,
        "comp_hash": _comp_set_hash(comps),
        "model": BLIND_MODEL,
        "pv": PROMPT_VERSION,
        "as_of": as_of,
        "n_comps": len(comps),
    }
    _save_cache(disk)
    _log(f"computed anchor={v} for {subject.get('address')} "
         f"in {took:.1f}s (packet from {len(comps)} untuned comps)")
    return v


__all__ = ["get_blind_anchor", "blind_value", "build_packet", "strip_price",
           "subject_signature", "BLIND_MODEL", "PROMPT_VERSION"]
