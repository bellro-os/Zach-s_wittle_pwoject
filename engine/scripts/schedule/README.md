# Scheduled MLS Bot + parcel tasks

Windows Task Scheduler entries automate the data-freshness pipeline.

## Install

```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule\install_schedules.ps1
```

Creates four user-scope (no-admin) tasks:

| Task | When | Command | Typical runtime |
|---|---|---|---|
| **MLS Bot Hourly** | **every hour** | `python tasks.py mls-hourly` | ~2–4 min |
| MLS Bot Daily  | every day 06:30   | `python tasks.py mls-daily`  | ~3–5 min |
| MLS Bot Weekly | Sunday 04:00      | `python tasks.py mls-weekly` | ~5–8 min |
| VA Parcels Daily Refresh | every day 05:00 | `refresh.py --all --max-age-days 14` (in `../va-parcels-pipeline`) | ~1–10 min |

Logs accumulate under `logs\` (one file per task).

## What runs

**Hourly** = incremental RETS delta pull → merge county deeds → enrich →
**rebuild `mls_lookup.parquet`** (the file the CMA/valuation engine queries).
The freshness loop: comps stay ≤1 h stale without the cost of the full daily run.

> Why the rebuild matters: the incremental pull upserts
> `data/mls/listings.jsonl`, but the CMA reads `data/mls_lookup.parquet`, and
> `_pick_listings_jsonl` prefers `listings_plus_deeds.jsonl` — so fresh listings
> only reach the parquet after merge-deeds regenerates that file. The rebuild was
> previously not wired into any schedule (the parquet went days stale). Hourly and
> Daily now both run merge → enrich → rebuild.

**Daily** = the hourly chain + every analytics CSV → the 4 lead lists → digest
HTML → 7-day alerts.

**Weekly** = refresh the agent/office directory + retrain the DOM model.

**VA Parcels Daily Refresh** = cheap change-detection across every registered
county parcel source (ArcGIS max-edit-timestamp / row-count vs. stored state);
re-pulls only sources that changed, or any older than `--max-age-days`. County
CAMA/GIS data changes daily-to-monthly, so a daily *check* — not hourly polling
of 70+ county servers — is the correct, polite cadence; the data refreshes as
fast as counties publish it. State: `outputs/refresh_state.json`; freshness:
`outputs/refresh_heartbeat.json`.

## Operate

```powershell
# Run on demand
Start-ScheduledTask -TaskName "MLS Bot Daily"

# Show next-run / last-result
Get-ScheduledTask -TaskName "MLS Bot*" | Get-ScheduledTaskInfo

# Uninstall
Unregister-ScheduledTask -TaskName "MLS Bot Daily"  -Confirm:$false
Unregister-ScheduledTask -TaskName "MLS Bot Weekly" -Confirm:$false
```

## Failure handling

- Settings include `RestartCount=2 / RestartInterval=10min` — transient RETS
  hiccups will retry twice automatically.
- `ExecutionTimeLimit=2h` — if an incremental pull hangs, the task is killed
  and the next morning's run starts clean.
- `StartWhenAvailable=true` — if the laptop was off at 06:30, the task fires
  the next time the machine is awake.
