"""CSV-backed persistence + lead-queue computation for the dashboard.

All writes are append-only. All reads pull the latest CSV state. No database,
no ORM, no caching — at 50 calls/day scale this is fine.

Data sources (read):
  outputs/mls_analytics/leads/seller_scores.csv      — ranked prospects (8k+)
  outputs/mls_analytics/leads/expired_watchlist.csv  — relist targets
  outputs/mls_analytics/leads/neighbor_outreach.csv  — neighbor of recent sale
  data/outreach_log.csv                               — mail / letter history

Data sources (write):
  data/dashboard/calls.csv                            — phone outcomes
  data/dashboard/doorknocks.csv                       — door knock outcomes
  data/dashboard/clients.csv                          — client roster
  data/dashboard/deals.csv                            — deal pipeline
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


# ---------- Paths ----------------------------------------------------------

ROOT = Path(__file__).resolve().parents[3]
SELLER_SCORES = ROOT / "outputs" / "mls_analytics" / "leads" / "seller_scores.csv"
EXPIRED_WATCHLIST = ROOT / "outputs" / "mls_analytics" / "leads" / "expired_watchlist.csv"
OUTREACH_LOG = ROOT / "data" / "outreach_log.csv"

DASH_DIR = ROOT / "data" / "dashboard"
CALLS_CSV = DASH_DIR / "calls.csv"
DOORS_CSV = DASH_DIR / "doorknocks.csv"
CLIENTS_CSV = DASH_DIR / "clients.csv"
DEALS_CSV = DASH_DIR / "deals.csv"

CALL_HEADERS = ["timestamp", "parcel_id", "county", "owner", "site_addr",
                "outcome", "notes", "next_followup"]
DOOR_HEADERS = ["timestamp", "parcel_id", "county", "owner", "site_addr",
                "outcome", "notes"]
CLIENT_HEADERS = ["client_id", "created", "name", "phone", "email", "source",
                  "anniversary", "notes"]
DEAL_HEADERS = ["deal_id", "created", "client_id", "stage", "side",
                "property", "list_price", "expected_close",
                "est_commission_pct", "notes"]


# ---------- Outcomes (drive suppression logic) -----------------------------

OUTCOME_FOLLOWUP_DAYS = {
    "interested":     1,    # follow up immediately tomorrow
    "talk_later":     14,
    "left_voicemail":  7,
    "no_answer":       3,
    "callback":        2,
    "meeting_scheduled": 1,
    "left_flyer":     21,   # door-knock equivalent of voicemail
    "nobody_home":     7,   # door-knock equivalent of no_answer
    "not_interested":  365,  # suppress for a year
    "bad_number":   36500,   # ~never
    "dnc":          36500,
    "wrong_owner":  36500,
}

HOT_OUTCOMES = {"interested", "meeting_scheduled", "callback"}
DEAD_OUTCOMES = {"not_interested", "bad_number", "dnc", "wrong_owner"}


# ---------- Initialization -------------------------------------------------

def _init_csv(path: Path, headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(headers)


def ensure_files() -> None:
    _init_csv(CALLS_CSV, CALL_HEADERS)
    _init_csv(DOORS_CSV, DOOR_HEADERS)
    _init_csv(CLIENTS_CSV, CLIENT_HEADERS)
    _init_csv(DEALS_CSV, DEAL_HEADERS)


# ---------- Generic readers ------------------------------------------------

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_calls() -> list[dict]:
    return _read_csv(CALLS_CSV)


def read_doorknocks() -> list[dict]:
    return _read_csv(DOORS_CSV)


def read_clients() -> list[dict]:
    return _read_csv(CLIENTS_CSV)


def read_deals() -> list[dict]:
    return _read_csv(DEALS_CSV)


def read_outreach_log() -> list[dict]:
    return _read_csv(OUTREACH_LOG)


# ---------- Writers --------------------------------------------------------

def log_call(*, parcel_id: str, county: str, owner: str, site_addr: str,
             outcome: str, notes: str = "",
             custom_followup_days: int | None = None) -> dict:
    """Append a call row. Returns the row dict for any chained UI rendering."""
    ensure_files()
    days = custom_followup_days if custom_followup_days is not None \
        else OUTCOME_FOLLOWUP_DAYS.get(outcome, 30)
    fu = (date.today() + timedelta(days=days)).isoformat() if days < 36000 else ""
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "parcel_id": parcel_id,
        "county": (county or "").upper().strip(),
        "owner": owner,
        "site_addr": site_addr,
        "outcome": outcome,
        "notes": notes,
        "next_followup": fu,
    }
    with CALLS_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CALL_HEADERS).writerow(row)
    return row


def log_doorknock(*, parcel_id: str, county: str, owner: str, site_addr: str,
                  outcome: str, notes: str = "") -> dict:
    ensure_files()
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "parcel_id": parcel_id,
        "county": (county or "").upper().strip(),
        "owner": owner,
        "site_addr": site_addr,
        "outcome": outcome,
        "notes": notes,
    }
    with DOORS_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=DOOR_HEADERS).writerow(row)
    return row


def add_client(*, name: str, phone: str = "", email: str = "",
               source: str = "", anniversary: str = "",
               notes: str = "") -> str:
    """Append a new client. Returns the generated client_id."""
    ensure_files()
    existing = read_clients()
    next_id = f"C{len(existing) + 1:04d}"
    row = {
        "client_id": next_id,
        "created": date.today().isoformat(),
        "name": name.strip(),
        "phone": phone.strip(),
        "email": email.strip(),
        "source": source.strip(),
        "anniversary": anniversary.strip(),
        "notes": notes.strip(),
    }
    with CLIENTS_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CLIENT_HEADERS).writerow(row)
    return next_id


def add_deal(*, client_id: str, stage: str, side: str, property: str,
             list_price: float, expected_close: str = "",
             est_commission_pct: float = 3.0, notes: str = "") -> str:
    ensure_files()
    existing = read_deals()
    next_id = f"D{len(existing) + 1:04d}"
    row = {
        "deal_id": next_id,
        "created": date.today().isoformat(),
        "client_id": client_id,
        "stage": stage,
        "side": side,
        "property": property,
        "list_price": str(list_price) if list_price else "",
        "expected_close": expected_close,
        "est_commission_pct": str(est_commission_pct),
        "notes": notes,
    }
    with DEALS_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=DEAL_HEADERS).writerow(row)
    return next_id


def update_deal_stage(deal_id: str, new_stage: str, notes: str = "") -> bool:
    """Append-only stage change: writes a new row with the same deal_id.
    Lookup logic in `latest_deals()` picks the most-recent row per deal_id."""
    ensure_files()
    deals = read_deals()
    existing = next((d for d in reversed(deals) if d.get("deal_id") == deal_id), None)
    if not existing:
        return False
    row = dict(existing)
    row["stage"] = new_stage
    row["created"] = date.today().isoformat()
    if notes:
        row["notes"] = notes
    with DEALS_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=DEAL_HEADERS).writerow(row)
    return True


def latest_deals() -> list[dict]:
    """Latest row per deal_id (since stage changes are append-only)."""
    seen: dict[str, dict] = {}
    for d in read_deals():
        seen[d.get("deal_id") or ""] = d
    seen.pop("", None)
    return list(seen.values())


# ---------- Suppression --------------------------------------------------

def suppressed_parcels(within_days: int = 60) -> dict[tuple[str, str], dict]:
    """Return {(parcel_id, county_upper): last_touch_row} for parcels that
    should be hidden from any outreach queue.

    A parcel is suppressed if any of:
      - logged in calls.csv OR doorknocks.csv within `within_days`
      - last outcome was a DEAD_OUTCOME (permanent)
      - has a next_followup date in the future
      - touched via outreach_log.csv within window (legacy letters)
    """
    today = date.today()
    out: dict[tuple[str, str], dict] = {}
    for row in read_calls() + read_doorknocks():
        pid = (row.get("parcel_id") or "").strip()
        if not pid:
            continue
        county = (row.get("county") or "").upper().strip()
        key = (pid, county)
        outcome = (row.get("outcome") or "").lower()
        try:
            ts = datetime.fromisoformat(row.get("timestamp", "")[:19]).date()
        except Exception:
            ts = today
        if outcome in DEAD_OUTCOMES:
            out[key] = row
            continue
        if (today - ts).days <= within_days:
            out[key] = row
            continue
        fu = row.get("next_followup", "")
        if fu:
            try:
                fu_date = date.fromisoformat(fu[:10])
                if fu_date > today:
                    out[key] = row
            except Exception:
                pass
    # Also pull from outreach_log.csv (legacy mail/letter touches)
    for row in read_outreach_log():
        pid = (row.get("parcel_id") or "").strip()
        if not pid or pid.startswith("#"):
            continue
        county = (row.get("county") or "").upper().strip()
        try:
            ts = date.fromisoformat((row.get("contact_date") or "")[:10])
        except Exception:
            continue
        if (today - ts).days <= within_days:
            out.setdefault((pid, county), row)
    return out


def hot_prospects(within_days: int = 30) -> list[dict]:
    """Calls whose outcome is interested/meeting/callback within window."""
    today = date.today()
    cutoff = today - timedelta(days=within_days)
    out = []
    for row in read_calls():
        outcome = (row.get("outcome") or "").lower()
        if outcome not in HOT_OUTCOMES:
            continue
        try:
            ts = datetime.fromisoformat(row.get("timestamp", "")[:19]).date()
        except Exception:
            continue
        if ts >= cutoff:
            out.append(row)
    out.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return out


def followups_due(within_days: int = 3) -> list[dict]:
    """Calls with a next_followup ≤ today + N days, returned chronological."""
    today = date.today()
    horizon = today + timedelta(days=within_days)
    out = []
    # Track latest call per parcel to avoid duplicate follow-ups
    latest_call: dict[tuple[str, str], dict] = {}
    for row in read_calls():
        key = ((row.get("parcel_id") or "").strip(),
               (row.get("county") or "").upper().strip())
        latest_call[key] = row
    for row in latest_call.values():
        fu = row.get("next_followup", "")
        if not fu:
            continue
        try:
            fu_date = date.fromisoformat(fu[:10])
        except Exception:
            continue
        if fu_date <= horizon:
            out.append({**row, "_followup_date": fu_date.isoformat()})
    out.sort(key=lambda r: r["_followup_date"])
    return out


# ---------- Call queue (the heart of phase 1) -----------------------------

_SIGNAL_LABELS = {
    "tenure": "tenure",
    "equity": "equity",
    "estate_pattern": "estate / trust pattern",
    "absentee": "absentee owner",
    "oos_mail": "out-of-state mail",
    "expired": "expired listing",
    "investor_dispose": "investor sell window",
    "hot_subdivision": "hot subdivision",
    "vintage_estate": "vintage estate home",
    "multi_prop": "multi-property",
    "intra_family_recent": "recent intra-family transfer",
    "intra_family_pattern": "intra-family pattern",
    "mail_addr_changed_18mo": "recent mail-address change",
    "tax_delinquent": "tax delinquent",
}

_NEG_SIGNAL_LABELS = {
    "rate_locked": "rate-lock penalty",
    "recent_purchase": "recent purchase",
}

_POS_PRIORITY = [
    "tax_delinquent", "mail_addr_changed_18mo",
    "intra_family_recent", "estate_pattern", "expired",
    "investor_dispose", "intra_family_pattern", "tenure",
    "equity", "multi_prop", "absentee", "hot_subdivision",
    "oos_mail", "vintage_estate",
]


def _signal_keys_from(signals_pos: str) -> set[str]:
    """Extract the structural keys from a signals_pos string like
    'tenure:7.5y(+23);estate_pattern(+30);absentee(+10)'."""
    keys = set()
    for chunk in (signals_pos or "").split(";"):
        m = re.match(r"\s*([a-z_]+)", chunk.lower())
        if m:
            keys.add(m.group(1))
    return keys


def _parse_signal_chunk(chunk: str) -> dict | None:
    """Parse one entry like 'estate_pattern(+30)', 'tenure:7.5y(+23)',
    or 'rate_locked:-2.1%(-12)'. Returns {key, modifier, points, label}."""
    chunk = (chunk or "").strip()
    if not chunk:
        return None
    m = re.match(r"([a-z_]+)(?::([^()]+))?\(([+-]?\d+)\)", chunk)
    if not m:
        return None
    key = m.group(1)
    modifier = (m.group(2) or "").strip()
    points = int(m.group(3))
    label = _SIGNAL_LABELS.get(key) or _NEG_SIGNAL_LABELS.get(key) or key.replace("_", " ")
    # Enrich label with modifier where it improves readability
    if key == "tenure" and modifier:
        m2 = re.match(r"([\d.]+)y", modifier)
        if m2:
            label = f"{m2.group(1)}y tenure"
    elif key == "equity" and modifier:
        m2 = re.match(r"\$?([\d,]+)", modifier)
        if m2:
            label = f"${m2.group(1)} equity"
    elif key == "expired" and modifier:
        label = f"expired {modifier[:7]}"
    elif key == "multi_prop" and modifier:
        m2 = re.match(r"(\d+)parc", modifier)
        if m2:
            label = f"owns {m2.group(1)} parcels"
    elif key == "rate_locked" and modifier:
        label = f"rate-lock {modifier}"
    return {"key": key, "modifier": modifier, "points": points, "label": label}


def _parse_signals(s: str) -> list[dict]:
    """Parse a semicolon-delimited signals string into a list of dicts."""
    return [c for c in (_parse_signal_chunk(x) for x in (s or "").split(";")) if c]


def _top_signals(signals_pos: str, n: int = 3) -> list[dict]:
    """Pick the N most-meaningful signals (priority order). Returns list of
    {key, label, points, modifier} dicts."""
    parsed = _parse_signals(signals_pos)
    by_key = {p["key"]: p for p in parsed}
    chosen = []
    for k in _POS_PRIORITY:
        if k in by_key:
            chosen.append(by_key[k])
            if len(chosen) >= n:
                break
    return chosen


def _last_contact_summary(parcel_id: str, county_upper: str,
                          calls_index: dict, knocks_index: dict,
                          outreach_index: dict) -> dict:
    """Structured last-contact info for the queue table.

    Returns {label, days_since, channel, outcome}. Most recent touch wins.
    `days_since` is None if never contacted (label='Never')."""
    today = date.today()
    best_days = None
    best_channel = None
    best_outcome = ""
    for ch, idx in [("call", calls_index), ("knock", knocks_index)]:
        row = idx.get((parcel_id, county_upper))
        if not row:
            continue
        try:
            ts = datetime.fromisoformat(row.get("timestamp", "")[:19]).date()
        except Exception:
            continue
        days = (today - ts).days
        if best_days is None or days < best_days:
            best_days = days
            best_channel = ch
            best_outcome = (row.get("outcome") or "").lower()
    o = outreach_index.get((parcel_id, county_upper))
    if o:
        try:
            ts = date.fromisoformat((o.get("contact_date") or "")[:10])
            days = (today - ts).days
            if best_days is None or days < best_days:
                best_days = days
                best_channel = "letter"
                best_outcome = (o.get("channel") or "letter").lower()
        except Exception:
            pass
    if best_days is None:
        return {"label": "Never", "days_since": None, "channel": None, "outcome": ""}
    icon = {"call": "📞", "knock": "🚪", "letter": "✉"}.get(best_channel, "·")
    return {
        "label": f"{icon} {best_outcome} {best_days}d ago",
        "days_since": best_days,
        "channel": best_channel,
        "outcome": best_outcome,
    }


def _safe_float(v) -> float:
    try:
        return float(v) if v not in ("", None, "None") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v) -> int:
    try:
        return int(float(v)) if v not in ("", None, "None") else 0
    except (TypeError, ValueError):
        return 0


def call_queue(
    *,
    min_score: int = 50,
    counties: list[str] | None = None,
    owner_types: list[str] | None = None,   # ["person", "entity"]
    signal_must_have: list[str] | None = None,
    lead_types: list[str] | None = None,
    suppress_within_days: int = 60,
    sort_by: str = "score",
    max_rows: int = 100,
    skip_flippers: bool = True,
) -> list[dict]:
    """Compute the today's-call queue from seller_scores + suppression."""
    if not SELLER_SCORES.exists():
        return []
    suppressed = suppressed_parcels(within_days=suppress_within_days)
    calls_index = {((r.get("parcel_id") or "").strip(),
                    (r.get("county") or "").upper().strip()): r
                   for r in read_calls()}
    knocks_index = {((r.get("parcel_id") or "").strip(),
                     (r.get("county") or "").upper().strip()): r
                    for r in read_doorknocks()}
    outreach_index = {((r.get("parcel_id") or "").strip(),
                       (r.get("county") or "").upper().strip()): r
                      for r in read_outreach_log()}

    counties_set = {c.upper() for c in (counties or [])}
    owner_types_set = {t.lower() for t in (owner_types or [])}
    sigmust = {s.lower() for s in (signal_must_have or [])}
    lead_types_set = {t.lower() for t in (lead_types or [])}

    rows = []
    with SELLER_SCORES.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            score = _safe_int(r.get("score"))
            if score < min_score:
                continue
            if skip_flippers and str(r.get("is_flipper_pattern", "")).lower() == "true":
                continue
            county_u = (r.get("county") or "").upper().strip()
            if counties_set and county_u not in counties_set:
                continue
            owner_type = (r.get("owner_type") or "person").lower()
            if owner_types_set and owner_type not in owner_types_set:
                continue
            lt = (r.get("lead_type") or "unclassified").lower()
            if lead_types_set and lt not in lead_types_set:
                continue
            sig_keys = _signal_keys_from(r.get("signals_pos", ""))
            if sigmust and not sigmust.issubset(sig_keys):
                continue
            pid = (r.get("parcel_id") or "").strip()
            if (pid, county_u) in suppressed:
                continue
            try:
                tenure = float(r.get("tenure_years") or 0)
            except ValueError:
                tenure = 0
            try:
                equity = float(r.get("estimated_equity") or 0)
            except ValueError:
                equity = 0
            row = {
                "score": score,
                "lead_type": lt,
                "parcel_id": pid,
                "county": county_u,
                "owner": r.get("owner", ""),
                "owner_type": owner_type,
                "site_addr": r.get("site_addr", ""),
                "mail_addr": r.get("mail_addr", ""),
                "year_built": r.get("year_built", ""),
                "bedrooms": r.get("bedrooms", ""),
                "tenure_years": tenure,
                "estimated_equity": equity,
                "subdivision": r.get("subdivision", ""),
                "top_signals": _top_signals(r.get("signals_pos", "")),
                "signals_raw": r.get("signals_pos", ""),
                "signals_neg_raw": r.get("signals_neg", ""),
                "has_neg": bool((r.get("signals_neg") or "").strip()),
                "scc_lookup_url": r.get("scc_lookup_url", ""),
                "whitepages_url": r.get("whitepages_url", ""),
                "true_people_url": r.get("true_people_url", ""),
                "last_contact": _last_contact_summary(
                    pid, county_u, calls_index, knocks_index, outreach_index
                ),
            }
            row["channel_hint"] = channel_hint(row)
            rows.append(row)

    # Sort
    sort_keys = {
        "score":  lambda r: -r["score"],
        "tenure": lambda r: -r["tenure_years"],
        "equity": lambda r: -r["estimated_equity"],
        "county": lambda r: (r["county"], -r["score"]),
        "subdivision": lambda r: (r["subdivision"] or "~~~", -r["score"]),
    }
    rows.sort(key=sort_keys.get(sort_by, sort_keys["score"]))
    return rows[:max_rows]


# ---------- Channel hint, score breakdown, doorknock queue ----------------

def channel_hint(row: dict) -> dict:
    """Decide whether a row leans 'call' or 'knock' based on signal mix.
    Returns {channel: 'call'|'knock'|'either', reason: str}."""
    raw = row.get("signals_raw") or row.get("signals_pos", "")
    sig_keys = _signal_keys_from(raw)
    owner_type = (row.get("owner_type") or "").lower()
    mail = (row.get("mail_addr") or "").strip().upper()
    site = (row.get("site_addr") or "").strip().upper()
    is_absentee = ("absentee" in sig_keys) or (bool(mail) and bool(site) and mail != site)
    is_oos = "oos_mail" in sig_keys
    is_entity = owner_type in ("entity", "trust", "estate")
    has_expired = "expired" in sig_keys
    has_mail_changed = "mail_addr_changed_18mo" in sig_keys
    call_pts = sum([is_absentee, is_oos, is_entity, has_expired, has_mail_changed])

    is_person = owner_type == "person"
    try:
        tenure = float(row.get("tenure_years") or 0)
    except (TypeError, ValueError):
        tenure = 0.0
    is_occupied = bool(mail) and bool(site) and mail == site
    is_long_tenure = tenure >= 5
    is_vintage = "vintage_estate" in sig_keys
    knock_pts = sum([is_occupied, is_person, is_long_tenure, is_vintage])

    call_reasons, knock_reasons = [], []
    if is_absentee: call_reasons.append("absentee")
    if is_oos: call_reasons.append("out-of-state mail")
    if is_entity: call_reasons.append("entity/trust owner")
    if has_expired: call_reasons.append("expired listing")
    if has_mail_changed: call_reasons.append("recent mail change")
    if is_occupied: knock_reasons.append("owner-occupied")
    if is_person: knock_reasons.append("person owner")
    if is_long_tenure: knock_reasons.append(f"{tenure:.0f}y tenure")
    if is_vintage: knock_reasons.append("vintage")

    if call_pts >= 2 and call_pts > knock_pts:
        return {"channel": "call", "reason": ", ".join(call_reasons) or "phone-favorable"}
    if knock_pts >= 3 and knock_pts > call_pts:
        return {"channel": "knock", "reason": ", ".join(knock_reasons) or "door-favorable"}
    return {"channel": "either", "reason": "mixed — either channel works"}


def seller_score_row(parcel_id: str, county: str = "") -> dict | None:
    """Fetch one parcel's full row from seller_scores.csv."""
    if not SELLER_SCORES.exists() or not parcel_id:
        return None
    cu = (county or "").upper().strip()
    with SELLER_SCORES.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("parcel_id") or "").strip() != parcel_id:
                continue
            if cu and (r.get("county") or "").upper().strip() != cu:
                continue
            return r
    return None


def score_breakdown(row: dict) -> dict:
    """Full positive/negative signal breakdown + hidden columns for the
    inline row-expansion panel. Accepts either a raw seller_scores row
    (signals_pos/_neg keys) or a call_queue row (signals_raw/_neg_raw)."""
    pos_raw = row.get("signals_pos") or row.get("signals_raw") or ""
    neg_raw = row.get("signals_neg") or row.get("signals_neg_raw") or ""
    pos = _parse_signals(pos_raw)
    neg = _parse_signals(neg_raw)
    pos.sort(key=lambda p: _POS_PRIORITY.index(p["key"])
             if p["key"] in _POS_PRIORITY else 99)
    return {
        "positive": pos,
        "negative": neg,
        "hidden": {
            "last_sale_date": row.get("last_sale_date", ""),
            "last_sale_price": _safe_float(row.get("last_sale_price")),
            "assessed_total": _safe_float(row.get("assessed_total")),
            "rate_at_purchase": row.get("rate_at_purchase", ""),
            "rate_delta_now": row.get("rate_delta_now", ""),
            "is_flipper_pattern":
                str(row.get("is_flipper_pattern", "")).lower() == "true",
            "canonical_owner_id": row.get("canonical_owner_id", ""),
            "mail_addr": row.get("mail_addr", ""),
            "site_addr": row.get("site_addr", ""),
        },
    }


def doorknock_queue(
    *,
    min_score: int = 50,
    counties: list[str] | None = None,
    subdivisions: list[str] | None = None,
    signal_must_have: list[str] | None = None,
    lead_types: list[str] | None = None,
    suppress_within_days: int = 60,
    max_rows: int = 200,
) -> list[dict]:
    """Door-knock variant: owner-occupied + person owners + tenure≥3yr,
    sorted by subdivision then score desc within each subdivision."""
    rows = call_queue(
        min_score=min_score,
        counties=counties,
        owner_types=["person"],
        signal_must_have=signal_must_have,
        lead_types=lead_types,
        suppress_within_days=suppress_within_days,
        sort_by="score",
        max_rows=max_rows * 4,
        skip_flippers=True,
    )
    subs_set = {s.lower() for s in (subdivisions or [])}
    out = []
    for r in rows:
        mail = (r.get("mail_addr") or "").strip().upper()
        site = (r.get("site_addr") or "").strip().upper()
        if not (mail and site and mail == site):
            continue
        if r.get("tenure_years", 0) < 3:
            continue
        if subs_set and (r.get("subdivision") or "").lower() not in subs_set:
            continue
        out.append(r)
    out.sort(key=lambda r: (r.get("subdivision") or "~~~", -r["score"]))
    return out[:max_rows]


def subdivision_groups(rows: list[dict]) -> list[dict]:
    """Group rows by subdivision for the door-knock view.
    Returns list of {name, count, avg_score, top_score, rows}."""
    by_sub: dict[str, list[dict]] = {}
    for r in rows:
        s = (r.get("subdivision") or "").strip() or "(no subdivision)"
        by_sub.setdefault(s, []).append(r)
    out = []
    for name, group in by_sub.items():
        avg = sum(r["score"] for r in group) / max(len(group), 1)
        out.append({
            "name": name,
            "count": len(group),
            "avg_score": round(avg, 1),
            "top_score": max(r["score"] for r in group),
            "rows": group,
        })
    out.sort(key=lambda g: (-g["count"], -g["avg_score"]))
    return out


def lead_type_counts(*, min_score: int = 40) -> dict[str, int]:
    """Count prospects per lead_type across the full seller_scores.csv
    (no suppression). For the stats banner."""
    if not SELLER_SCORES.exists():
        return {}
    counts: dict[str, int] = {}
    with SELLER_SCORES.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                if int(float(r.get("score") or 0)) < min_score:
                    continue
            except (TypeError, ValueError):
                continue
            lt = (r.get("lead_type") or "unclassified").strip() or "unclassified"
            counts[lt] = counts.get(lt, 0) + 1
    return counts


def known_subdivisions(limit: int = 200) -> list[str]:
    """Distinct subdivisions in seller_scores.csv, sorted by frequency."""
    if not SELLER_SCORES.exists():
        return []
    counts: dict[str, int] = {}
    with SELLER_SCORES.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            s = (r.get("subdivision") or "").strip()
            if s:
                counts[s] = counts.get(s, 0) + 1
    return [s for s, _ in sorted(counts.items(), key=lambda x: -x[1])[:limit]]


# ---------- Quick stats for top banner ------------------------------------

def quick_stats() -> dict:
    """Counts for the home-page banner."""
    today = date.today()
    calls = read_calls()
    deals = latest_deals()

    def calls_since(d: date) -> int:
        return sum(1 for c in calls
                   if c.get("timestamp", "")[:10] >= d.isoformat())

    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    pipe_dollars = 0.0
    active_deals = 0
    for d in deals:
        stage = (d.get("stage") or "").lower()
        if stage in ("closed", "lost", "dead", ""):
            continue
        active_deals += 1
        try:
            pipe_dollars += float(d.get("list_price") or 0)
        except (TypeError, ValueError):
            pass

    return {
        "calls_today": calls_since(today),
        "calls_week":  calls_since(week_start),
        "calls_month": calls_since(month_start),
        "active_deals": active_deals,
        "pipeline_dollars": pipe_dollars,
        "hot_count": len(hot_prospects(within_days=30)),
        "followups_due_count": len(followups_due(within_days=3)),
    }


# ---------- County autocomplete data --------------------------------------

def known_counties() -> list[str]:
    """Distinct counties in seller_scores.csv for filter dropdown."""
    if not SELLER_SCORES.exists():
        return []
    s: set[str] = set()
    with SELLER_SCORES.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            c = (r.get("county") or "").strip().upper()
            if c:
                s.add(c)
    return sorted(s)
