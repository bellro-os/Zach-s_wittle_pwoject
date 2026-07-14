#!/usr/bin/env python3
"""Data-freshness STATUS + ALERT for the Ratified data pipeline.

The freshness pipeline can go silently stale (it did once: the CMA parquet was
4 days old while listings kept updating). This script checks every freshness
signal, prints a status table, writes a machine-readable status JSON, and
EXITS NON-ZERO if anything is STALE so a scheduler log surfaces the problem.

Signals checked
---------------
1. MLS parquet         mtime of data/mls_lookup.parquet            (stale > --mls-max-age-hours, default 3h)
2. MLS incremental pull last line of data/mls/pulls_log.jsonl      -> ended_at (fallback anchor) (stale > mls max age)
3. MLS listings        mtime of data/mls/listings.jsonl           (stale > mls max age)
4. County parcels      last_tick in va-parcels-pipeline/outputs/refresh_heartbeat.json
                       (stale > --parcel-max-age-hours, default 36h; MISSING = warn-only, not a hard fail)
5. Parcel CSV (info)   mtime of va-parcels-pipeline/outputs/va_parcels_statewide.csv (context only, never fails)

Exit codes
----------
0  all signals OK (a MISSING parcel heartbeat is a warning, still 0, with a note)
1  at least one signal is STALE

Recommended Windows Task Scheduler usage
----------------------------------------
Run hourly, a few minutes AFTER the MLS hourly job. If this exits 1, the
Task Scheduler "Last Run Result" / $LASTEXITCODE is non-zero and the log shows
which feed is stale.

    schtasks /Create /TN "Ratified Freshness Check" /SC HOURLY /MO 1 /ST 00:10 ^
      /TR "cmd /c \"cd /d \"C:\\Users\\zach\\Desktop\\MLS Bot\" && python scripts\\freshness_check.py >> logs\\freshness_check.log 2>&1\"" ^
      /RL HIGHEST /F

PowerShell equivalent for checking the result after a manual run:

    python "C:\\Users\\zach\\Desktop\\MLS Bot\\scripts\\freshness_check.py"; $LASTEXITCODE

Stdlib only (os.path.getmtime + json + datetime); pandas/duckdb intentionally
unused to stay dependency-light.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# --- Paths (absolute, so the script works regardless of cwd) ----------------
MLS_ROOT = r"C:\Users\zach\Desktop\MLS Bot"
PARCELS_ROOT = r"C:\Users\zach\Desktop\va-parcels-pipeline"

MLS_PARQUET = os.path.join(MLS_ROOT, "data", "mls_lookup.parquet")
PULLS_LOG = os.path.join(MLS_ROOT, "data", "mls", "pulls_log.jsonl")
LISTINGS = os.path.join(MLS_ROOT, "data", "mls", "listings.jsonl")
PARCEL_HEARTBEAT = os.path.join(PARCELS_ROOT, "outputs", "refresh_heartbeat.json")
PARCEL_CSV = os.path.join(PARCELS_ROOT, "outputs", "va_parcels_statewide.csv")

# Status constants
OK = "OK"
STALE = "STALE"
MISSING = "MISSING"
INFO = "INFO"  # context-only signal, never fails the run


def human_age(seconds: float | None) -> str:
    """Render an age in seconds as a compact human string."""
    if seconds is None:
        return "-"
    if seconds < 0:
        seconds = 0
    s = int(seconds)
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    if not days and not hours:
        parts.append(f"{secs}s")
    return " ".join(parts)


def parse_iso_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (with or without offset) to an aware UTC datetime."""
    text = value.strip()
    # Python's fromisoformat handles offsets like +00:00; normalize a trailing Z.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        # Assume UTC for naive timestamps rather than guessing local zone.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_from_mtime(path: str, now_epoch: float) -> float | None:
    """Age in seconds from a file's mtime, or None if missing."""
    if not os.path.exists(path):
        return None
    return now_epoch - os.path.getmtime(path)


def last_jsonl_line(path: str) -> dict | None:
    """Return the last non-empty JSON object from a .jsonl file, or None."""
    if not os.path.exists(path):
        return None
    last = None
    # Read in text mode; files here are small-to-moderate. Iterate to grab the
    # final non-blank line without loading huge files into a single string.
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                last = stripped
    if last is None:
        return None
    try:
        return json.loads(last)
    except json.JSONDecodeError:
        return None


def make_signal(name, path, age_seconds, threshold_seconds, status, note=""):
    return {
        "name": name,
        "path": path,
        "age_seconds": None if age_seconds is None else round(age_seconds, 1),
        "age_human": human_age(age_seconds),
        "threshold_seconds": threshold_seconds,
        "status": status,
        "note": note,
    }


def check_mtime_signal(name, path, threshold_seconds, now_epoch):
    age = age_from_mtime(path, now_epoch)
    if age is None:
        return make_signal(name, path, None, threshold_seconds, MISSING, "file not found")
    status = STALE if age > threshold_seconds else OK
    return make_signal(name, path, age, threshold_seconds, status)


def check_pulls_log(path, threshold_seconds, now_utc):
    rec = last_jsonl_line(path)
    if rec is None:
        if not os.path.exists(path):
            return make_signal("mls_pull_recency", path, None, threshold_seconds, MISSING, "pulls_log not found")
        return make_signal("mls_pull_recency", path, None, threshold_seconds, MISSING, "no parseable last line")
    # Prefer ended_at (when the pull finished); fall back to anchor.
    ts_field = None
    raw = None
    for field in ("ended_at", "anchor", "started_at"):
        if rec.get(field):
            ts_field = field
            raw = rec[field]
            break
    if raw is None:
        return make_signal("mls_pull_recency", path, None, threshold_seconds, MISSING,
                           "no timestamp field in last line")
    try:
        dt = parse_iso_utc(raw)
    except (ValueError, TypeError):
        return make_signal("mls_pull_recency", path, None, threshold_seconds, MISSING,
                           f"unparseable {ts_field}: {raw!r}")
    age = (now_utc - dt).total_seconds()
    status = STALE if age > threshold_seconds else OK
    return make_signal("mls_pull_recency", path, age, threshold_seconds, status,
                       f"from {ts_field}={raw}")


def check_parcel_heartbeat(path, threshold_seconds, now_utc):
    if not os.path.exists(path):
        # Never run -> warn-only, NOT a hard fail.
        return make_signal("county_parcel_refresh", path, None, threshold_seconds, MISSING,
                           "heartbeat never written (warn-only, does not fail the run)")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return make_signal("county_parcel_refresh", path, None, threshold_seconds, MISSING,
                           f"unreadable heartbeat: {exc}")
    raw = data.get("last_tick") or data.get("ended_at") or data.get("timestamp")
    if not raw:
        return make_signal("county_parcel_refresh", path, None, threshold_seconds, MISSING,
                           "no last_tick in heartbeat")
    try:
        dt = parse_iso_utc(raw)
    except (ValueError, TypeError):
        return make_signal("county_parcel_refresh", path, None, threshold_seconds, MISSING,
                           f"unparseable last_tick: {raw!r}")
    age = (now_utc - dt).total_seconds()
    status = STALE if age > threshold_seconds else OK
    return make_signal("county_parcel_refresh", path, age, threshold_seconds, status,
                       f"last_tick={raw}")


def check_csv_info(path, now_epoch):
    age = age_from_mtime(path, now_epoch)
    if age is None:
        return make_signal("parcel_csv_context", path, None, None, MISSING, "context-only; file not found")
    return make_signal("parcel_csv_context", path, age, None, INFO, "context-only; never fails the run")


def print_table(signals, overall, json_path, exit_code):
    name_w = max(len(s["name"]) for s in signals)
    name_w = max(name_w, len("SIGNAL"))
    age_w = max(max(len(s["age_human"]) for s in signals), len("AGE"))
    thr_w = len("THRESHOLD")

    def thr_str(s):
        ts = s["threshold_seconds"]
        return "-" if ts is None else human_age(ts)

    age_w = max(age_w, max(len(thr_str(s)) for s in signals), len("AGE"))
    thr_w = max(thr_w, max(len(thr_str(s)) for s in signals))

    print("=" * (name_w + age_w + thr_w + 24))
    print(f"  Ratified data-freshness check  ({datetime.now(timezone.utc).isoformat()})")
    print("=" * (name_w + age_w + thr_w + 24))
    header = f"  {'SIGNAL':<{name_w}}  {'AGE':>{age_w}}  {'THRESHOLD':>{thr_w}}  STATUS"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for s in signals:
        flag = {OK: "OK   ", STALE: "STALE", MISSING: "MISS ", INFO: "INFO "}.get(s["status"], s["status"])
        print(f"  {s['name']:<{name_w}}  {s['age_human']:>{age_w}}  {thr_str(s):>{thr_w}}  {flag}")
        if s.get("note"):
            print(f"  {'':<{name_w}}  -> {s['note']}")
    print("  " + "-" * (len(header) - 2))
    print(f"  OVERALL: {overall.upper()}   exit={exit_code}")
    print(f"  status JSON: {json_path}")
    print("=" * (name_w + age_w + thr_w + 24))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check Ratified pipeline data freshness; exit 1 if any signal is stale.")
    parser.add_argument("--mls-max-age-hours", type=float, default=3.0,
                        help="Max age (hours) for MLS signals before STALE (default: 3).")
    parser.add_argument("--parcel-max-age-hours", type=float, default=36.0,
                        help="Max age (hours) for the county parcel refresh before STALE (default: 36).")
    parser.add_argument("--json-out", default=os.path.join("outputs", "freshness_status.json"),
                        help="Path to write the machine-readable status JSON "
                             "(default: outputs/freshness_status.json).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress the stdout table (still writes JSON and sets the exit code).")
    args = parser.parse_args(argv)

    now_utc = datetime.now(timezone.utc)
    now_epoch = time.time()

    mls_threshold = args.mls_max_age_hours * 3600.0
    parcel_threshold = args.parcel_max_age_hours * 3600.0

    signals = [
        check_mtime_signal("mls_parquet", MLS_PARQUET, mls_threshold, now_epoch),
        check_pulls_log(PULLS_LOG, mls_threshold, now_utc),
        check_mtime_signal("mls_listings", LISTINGS, mls_threshold, now_epoch),
        check_parcel_heartbeat(PARCEL_HEARTBEAT, parcel_threshold, now_utc),
        check_csv_info(PARCEL_CSV, now_epoch),
    ]

    # A STALE signal fails the run. A MISSING parcel heartbeat is warn-only.
    # A MISSING *MLS* signal is treated as a hard failure (the feed should exist).
    mls_missing = [s for s in signals
                   if s["status"] == MISSING and s["name"].startswith("mls")]
    any_stale = any(s["status"] == STALE for s in signals)
    fail = any_stale or bool(mls_missing)
    overall = "stale" if fail else "ok"
    exit_code = 1 if fail else 0

    # Resolve the JSON path relative to the MLS root if a relative path was given,
    # so scheduler runs from any cwd land the file in the expected place.
    json_path = args.json_out
    if not os.path.isabs(json_path):
        json_path = os.path.join(MLS_ROOT, json_path)
    os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)

    payload = {
        "checked_at": now_utc.isoformat(),
        "overall": overall,
        "exit_code": exit_code,
        "thresholds": {
            "mls_max_age_hours": args.mls_max_age_hours,
            "parcel_max_age_hours": args.parcel_max_age_hours,
        },
        "signals": [
            {
                "name": s["name"],
                "path": s["path"],
                "age_seconds": s["age_seconds"],
                "age_human": s["age_human"],
                "threshold_seconds": s["threshold_seconds"],
                "status": s["status"],
                "note": s.get("note", ""),
            }
            for s in signals
        ],
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    if not args.quiet:
        print_table(signals, overall, json_path, exit_code)
        warn_missing = [s for s in signals
                        if s["status"] == MISSING and not s["name"].startswith("mls")]
        for s in warn_missing:
            print(f"  WARNING: {s['name']} is MISSING ({s.get('note','')}) -- warn-only, run still passes.")
        if fail:
            bad = [s["name"] for s in signals if s["status"] == STALE] + [s["name"] for s in mls_missing]
            print(f"  ALERT: stale/missing feed(s): {', '.join(bad)}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
