"""Outreach tracker — single CSV the user maintains.

You log who you've contacted, when, and the outcome. The seller-scoring
output then suppresses already-contacted prospects so the daily refresh
doesn't keep showing you names you just called.

File: data/outreach_log.csv (you edit this)

Format:
    parcel_id,county,owner,contact_date,channel,outcome,notes,follow_up_date

Scoring suppression rule (default):
  - Skip parcel if any contact_date >= today - 90 days, UNLESS outcome
    is "interested"/"hot" (then keep at top with bonus)
  - Add `outreach_status` column to seller_scores.csv: never_contacted /
    contacted_X_days_ago / interested / cold

Hot prospects ("interested" / "hot" outcomes) get +15 score boost so they
stay at the top of your call queue.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path


OUTREACH_LOG = Path("data/outreach_log.csv")


OUTREACH_HEADERS = [
    "parcel_id", "county", "owner", "contact_date", "channel",
    "outcome", "notes", "follow_up_date", "campaign",
]


# Outcome buckets used by campaign_performance()
WIN_OUTCOMES = {"listing_signed", "signed", "won", "listing_won"}
RESPONSE_OUTCOMES = {
    "interested", "hot", "warm", "callback", "meeting_scheduled",
    "listing_signed", "signed", "won", "listing_won",
    "not_interested", "no", "decline",
}
LOSS_OUTCOMES = {"not_interested", "cold", "do_not_call", "dnc",
                  "no", "decline"}


def _migrate_log_schema(path: Path) -> None:
    """If the log lacks the `campaign` column, add it (preserves all rows)."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return
        if "campaign" in header:
            return
        rows = list(reader)
    new_header = list(header) + ["campaign"]
    new_len = len(new_header)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(new_header)
        for r in rows:
            r = list(r)
            if len(r) < new_len:
                r += [""] * (new_len - len(r))
            elif len(r) > new_len:
                r = r[:new_len]
            w.writerow(r)


def init_log_if_missing(path: Path = OUTREACH_LOG) -> None:
    _migrate_log_schema(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(OUTREACH_HEADERS)
        # Add a sample row commented-style for first-time users
        w.writerow([
            "# example: parcel_id from seller_scores.csv",
            "MONTGOMERY", "JANE DOE TRUSTEE", "2026-05-01",
            "phone", "left_voicemail", "spoke to neighbor; out of town",
            "2026-05-15", "mail_merge_2026Q2"
        ])


def load_outreach(path: Path = OUTREACH_LOG) -> dict:
    """Return {(parcel_id, county): list_of_contact_dicts}."""
    if not path.exists():
        return {}
    out: dict = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = (row.get("parcel_id") or "").strip()
            if pid.startswith("#") or not pid:
                continue
            county = (row.get("county") or "").strip().upper()
            out.setdefault((pid, county), []).append(row)
    return out


def annotate_scores_csv(scores_csv: Path | str = "outputs/mls_analytics/leads/seller_scores.csv",
                       outreach_path: Path = OUTREACH_LOG,
                       *, suppress_days: int = 90) -> int:
    """Read the scores CSV, annotate each row with outreach status, suppress
    or boost based on contact history. Rewrites the CSV in place."""
    scores_csv = Path(scores_csv)
    if not scores_csv.exists():
        return 0
    init_log_if_missing(outreach_path)
    contacts = load_outreach(outreach_path)
    today = date.today()

    rows: list[dict] = []
    with scores_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        return 0

    n_suppressed = 0
    n_hot = 0
    out_rows: list[dict] = []
    for r in rows:
        pid = (r.get("parcel_id") or "").strip()
        county = (r.get("county") or "").strip().upper()
        history = contacts.get((pid, county)) or []

        outreach_status = "never_contacted"
        score_adjust = 0
        last_contact = None
        last_outcome = ""
        for h in history:
            cd = (h.get("contact_date") or "").strip()
            try:
                d = date.fromisoformat(cd[:10])
                if last_contact is None or d > last_contact:
                    last_contact = d
                    last_outcome = (h.get("outcome") or "").strip().lower()
            except Exception:
                continue

        if last_contact:
            days_ago = (today - last_contact).days
            if last_outcome in ("interested", "hot", "warm"):
                outreach_status = f"hot:{last_outcome}"
                score_adjust = 15
                n_hot += 1
            elif last_outcome in ("not_interested", "cold", "do_not_call", "dnc"):
                outreach_status = "cold"
                score_adjust = -50  # heavily suppress
                n_suppressed += 1
            elif days_ago < suppress_days:
                outreach_status = f"contacted_{days_ago}d_ago"
                score_adjust = -50  # suppress recent contacts
                n_suppressed += 1
            else:
                outreach_status = f"contacted_{days_ago}d_ago"
                score_adjust = -5

        r["outreach_status"] = outreach_status
        r["last_contact_date"] = str(last_contact) if last_contact else ""
        r["last_outcome"] = last_outcome
        try:
            r["score"] = round(float(r.get("score", 0)) + score_adjust)
        except (TypeError, ValueError):
            pass
        out_rows.append(r)

    out_rows.sort(key=lambda x: -float(x.get("score", 0) or 0))
    fields = list(out_rows[0].keys())
    with scores_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    print(f"  outreach annotation: {len(out_rows)} prospects | hot:{n_hot} | suppressed:{n_suppressed}")
    return len(out_rows)


def campaign_performance(
    out_csv: Path | str = "outputs/mls_analytics/campaign_performance.csv",
    outreach_path: Path = OUTREACH_LOG,
    *,
    scores_csv: Path | str = "outputs/mls_analytics/leads/seller_scores.csv",
) -> int:
    """Aggregate outreach log by campaign. Returns campaign count written.

    Per-campaign metrics:
      letters_sent     — distinct (parcel,county) pairs in campaign
      contacts         — total log rows
      responses        — rows whose outcome implies a real response
      listings_won     — rows whose outcome is in WIN_OUTCOMES
      losses           — rows in LOSS_OUTCOMES
      win_rate         — listings_won / letters_sent (decimal)
      response_rate    — responses / letters_sent
      dollar_volume_won — sum(list_price) across won parcels (uses
                          seller_scores.csv last_sale_price as a proxy
                          when the won listing isn't yet in MLS)
      first_contact / last_contact — date range of contacts in this campaign
    """
    out_csv = Path(out_csv)
    if not outreach_path.exists():
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        out_csv.write_text("campaign,letters_sent\n", encoding="utf-8-sig")
        return 0
    _migrate_log_schema(outreach_path)

    # Load seller_scores for $-volume proxy
    scores_lookup: dict[tuple[str, str], dict] = {}
    sp = Path(scores_csv)
    if sp.exists():
        with sp.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                pid = (r.get("parcel_id") or "").strip()
                county = (r.get("county") or "").strip().upper()
                if pid:
                    scores_lookup[(pid, county)] = r

    rows: list[dict] = []
    with outreach_path.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            pid = (r.get("parcel_id") or "").strip()
            if pid.startswith("#") or not pid:
                continue
            rows.append(r)

    by_camp: dict[str, list[dict]] = {}
    for r in rows:
        camp = (r.get("campaign") or "(none)").strip() or "(none)"
        by_camp.setdefault(camp, []).append(r)

    out_rows: list[dict] = []
    for camp, contacts in sorted(by_camp.items()):
        parcels: set[tuple[str, str]] = set()
        responses = 0
        wins = 0
        losses = 0
        won_volume = 0.0
        first_dt: date | None = None
        last_dt: date | None = None
        for c in contacts:
            pid = (c.get("parcel_id") or "").strip()
            county = (c.get("county") or "").strip().upper()
            parcels.add((pid, county))
            outcome = (c.get("outcome") or "").strip().lower()
            if outcome in RESPONSE_OUTCOMES:
                responses += 1
            if outcome in WIN_OUTCOMES:
                wins += 1
                sr = scores_lookup.get((pid, county)) or {}
                try:
                    lp = float(sr.get("last_sale_price") or 0)
                    won_volume += lp
                except (TypeError, ValueError):
                    pass
            if outcome in LOSS_OUTCOMES:
                losses += 1
            cd = (c.get("contact_date") or "").strip()
            try:
                d = date.fromisoformat(cd[:10])
                if first_dt is None or d < first_dt:
                    first_dt = d
                if last_dt is None or d > last_dt:
                    last_dt = d
            except Exception:
                pass

        n_letters = len(parcels)
        out_rows.append({
            "campaign": camp,
            "letters_sent": n_letters,
            "contacts": len(contacts),
            "responses": responses,
            "listings_won": wins,
            "losses": losses,
            "win_rate": round(wins / n_letters, 4) if n_letters else 0,
            "response_rate": round(responses / n_letters, 4) if n_letters else 0,
            "dollar_volume_won": int(won_volume) if won_volume else "",
            "first_contact": first_dt.isoformat() if first_dt else "",
            "last_contact": last_dt.isoformat() if last_dt else "",
        })

    out_rows.sort(key=lambda x: -x["letters_sent"])

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    if not out_rows:
        out_csv.write_text("campaign,letters_sent\n", encoding="utf-8-sig")
        return 0
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    return len(out_rows)
