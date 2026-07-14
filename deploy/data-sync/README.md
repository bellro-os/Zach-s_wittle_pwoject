# Hourly data sync — pipeline machine → Railway, via object storage

The app's freshness stamp says **"MLS data · refreshed hourly"**
(`src/components/compbird/studio/data-freshness.tsx`). This kit is what makes
that claim TRUE on Railway. There is **no SSH** into a Railway service and
volumes are **not shareable across services**, so the pipeline is
push → bucket → pull:

```
Windows pipeline box                 Cloudflare R2 (S3 API)        Railway "engine" service
────────────────────                 ──────────────────────        ────────────────────────
"MLS Bot Hourly" task                <prefix>/objects/<rel>.<sha16>  entrypoint.sh (PID 1)
 └─ python tasks.py mls-hourly        (immutable, content-addressed) ├─ boot: pull_and_swap.sh  ← self-seeds an empty volume
 └─ scripts/push_prod_data.ps1  ──▶  <prefix>/manifest.json          ├─ worker/cma_worker.py (:8765)
     (hash-skip unchanged files)      (uploaded LAST = finalize)     └─ loop: pull_and_swap.sh every SYNC_INTERVAL_MIN
                                                                          1. GET manifest, diff vs applied state
                                                                          2. download changed → tmp IN the volume, sha256-verify
                                                                          3. VALIDATE (duckdb / sqlite / json / pickle probes)
                                                                          4. os.replace() = atomic rename into place
                                                                          5. write DATA_DIR/.freshness (manifest timestamp)
```

Why the puller can never see a partial push: objects are uploaded to
**content-addressed keys** (a new hash = a new key, never an overwrite of a
live object; each S3 PUT is atomic), and the single `manifest.json` — the only
key a puller reads first — is uploaded **after** every object it references.
Every download is re-verified against the manifest's sha256 before anything is
validated, and nothing is renamed into place until **the whole batch**
validates. The worker only ever reads the old file or the new one.

Both halves are new files only — nothing in the live `MLS Bot Hourly` task or
the engine repo's existing code was modified. Wiring the push into the
schedule is a manual, documented step (below). *(This kit replaces the
VPS-era `swap_data.sh` SSH design — superseded by the Railway launch decision.)*

## What ships (and why)

The authoritative list lives in **one** place: `MLS Bot/scripts/push_prod_data.ps1`
(`$Manifest`), with per-file `source:line` reader evidence in its header
(verified against the engine source 2026-07-14). The puller consumes the
pushed `manifest.json` — including each file's validation `kind` — so the two
sides cannot drift.

| File | What it is | Size | Validation |
|---|---|---|---|
| `data/mls_lookup.parquet` | THE hourly comp pool — the freshness claim | ~7 MB | duckdb probe, ≥1000 rows |
| `data/market_index.parquet` | county $/sqft index (AVM debias, prior-sale anchors) | ~10 KB | duckdb probe |
| `data/supplemental_listings.parquet` | compbird's public-records pool (`CMA_LISTINGS_PARQUET`) | ~13 MB | duckdb probe |
| `data/parcel_lookup.parquet` | parcel attributes (subject resolution) | ~87 MB | duckdb probe, ≥1000 rows |
| `data/search_index.sqlite` | address typeahead FTS — read by the **Next app**, see caveat below | ~1.1 GB | sqlite probe |
| `data/cma_regions.json` | per-region dialed CMA knobs | ~2 KB | json probe |
| `outputs/mls_analytics/avm_model/*.joblib` | AVM regressor + meta | ~2 MB | non-empty + pickle magic |
| `outputs/mls_analytics/dom_model/*.joblib` | DOM quantile models (optional) | ~5 MB | non-empty + pickle magic |
| `outputs/mls_analytics/price_cut_model/*.joblib` | price-cut model (optional) | ~1.5 MB | non-empty + pickle magic |

Everything is SHA256-checked against the last successful push
(`MLS Bot/logs/push_prod_data.state.json`), so an unchanged file costs
nothing. Model joblibs effectively ship only on retrain.

**Heavy-file rate limit:** `search_index.sqlite` is rebuilt hourly and a
SQLite rebuild changes bytes even when content barely moved — raw hash-compare
would upload ~1.1 GB *every hour* from the home connection. It is marked
*heavy* and ships at most every `-HeavyMinIntervalHours` (default 20 → ~daily);
the manifest carries the previous (still-live) object forward in between.
Comps freshness is unaffected (`mls_lookup.parquet` ships hourly); the only
cost is that brand-new addresses can take up to a day to appear in *typeahead*.
`-HeavyMinIntervalHours 0` ships it whenever it changes.

**Deliberately NOT shipped** (engine-owned runtime caches — pushing would
clobber live state): `data/cma_blind_cache.json`, `data/cma_hygiene_cache.json`.

## One-time R2 setup

1. Cloudflare dashboard → R2 → **Create bucket** (e.g. `compbird-engine-data`;
   location: Eastern North America). No public access. Egress is free.
2. R2 → **Manage API tokens** → *Create API token* → **Object Read & Write**,
   scoped to that one bucket. Copy the **Access Key ID** / **Secret Access
   Key** and the account's S3 endpoint `https://<accountid>.r2.cloudflarestorage.com`.
3. That's the whole server side — no compute, no lifecycle rules needed (the
   push script garbage-collects superseded objects itself).

## Configure the pipeline box (Windows)

Set machine env vars once (System → Environment Variables) — the same names
the engine service uses on Railway:

| Env var | Value |
|---|---|
| `R2_ENDPOINT` | `https://<accountid>.r2.cloudflarestorage.com` |
| `R2_BUCKET` | `compbird-engine-data` |
| `R2_KEY` | access key id |
| `R2_SECRET` | secret access key |
| `R2_PREFIX` | *(optional)* default `engine-data` |

Sanity-check the SigV4 signer (no config or network needed), then push by hand:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\zach\Desktop\MLS Bot\scripts\push_prod_data.ps1" -SelfTest
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\zach\Desktop\MLS Bot\scripts\push_prod_data.ps1"
```

Exit 0 + `=== push OK ===` in `MLS Bot\logs\push_prod_data.log` (rotating,
1 MB × 3) means every object landed AND the manifest was finalized. The first
push uploads ~1.2 GB (the index dominates); a typical hourly push is ~7 MB.

## Schedule it — add the push as the final step of "MLS Bot Hourly"

> **Do NOT edit the live task blindly.** The instructions below are the exact
> change; apply manually when ready. The current task action (verified
> 2026-07-14, hourly trigger `PT1H`) is:
>
> `cmd.exe /d /c set PYTHONPATH=src && cd /d "C:\Users\zach\Desktop\MLS Bot" && "C:\Python313\python.exe" tasks.py mls-hourly >> "C:\Users\zach\Desktop\MLS Bot\logs\MLS_Bot_Hourly.log" 2>&1`

Append the push after the refresh (cmd `&&` = the push only runs when the
refresh succeeded, so a failed refresh never publishes stale/partial data):

```powershell
# Elevated PowerShell. Re-registers the SAME task with the push appended.
$args = '/d /c set PYTHONPATH=src && cd /d "C:\Users\zach\Desktop\MLS Bot" && "C:\Python313\python.exe" tasks.py mls-hourly >> "C:\Users\zach\Desktop\MLS Bot\logs\MLS_Bot_Hourly.log" 2>&1 && powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\zach\Desktop\MLS Bot\scripts\push_prod_data.ps1" >> "C:\Users\zach\Desktop\MLS Bot\logs\MLS_Bot_Hourly.log" 2>&1'
$t = Get-ScheduledTask -TaskName 'MLS Bot Hourly'
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $args
Set-ScheduledTask -TaskName 'MLS Bot Hourly' -Action $action -Trigger $t.Triggers -Settings $t.Settings
```

The push exits non-zero on any failure, but under cmd `&&`-chaining the task's
"last run result" reflects the last command — the real red/green signal is the
engine-side freshness marker (below) plus `logs/push_prod_data.log`. To make a
push failure show as its own red task, schedule it separately instead:

```powershell
schtasks /Create /TN "Compbird data push (hourly)" /SC HOURLY /ST 00:20 /F /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\Users\zach\Desktop\MLS Bot\scripts\push_prod_data.ps1\""
```

(`:20` offset: the refresh at `:00` takes several minutes; hashes are read at
push time, so a mid-write hour simply ships on the NEXT push.) Tick **"Run
task as soon as possible after a scheduled start is missed"** either way.
Hash state updates only after a successful finalize, so any failure re-ships
the same files next hour — the pipeline self-heals.

## Configure the Railway engine service

The seam (already wired by the deploy kit): `Dockerfile.engine` copies this
directory into the image and boots `deploy/entrypoint.engine.sh`, which
symlinks the service's ONE volume into the repo-relative paths the engine
resolves (`$RAILWAY_VOLUME_MOUNT_PATH/{data,outputs,cache}` →
`/app/{data,outputs,cache}`), then **execs `deploy/data-sync/entrypoint.sh`**
(this kit) as the supervisor. Contract honored here: exec-able, **no args**,
all config via env, starts the worker itself (`python -X utf8
worker/cma_worker.py`), never exits while the worker runs, propagates its
exit code. `pull_and_swap.sh` must sit next to `entrypoint.sh`. Because the
symlinks put data AND outputs on the volume, the puller's tmp dirs
(`…/.sync-tmp` inside each root) are on the same filesystem as the live files
— the rename stays atomic.

Service env:

| Env var | Value |
|---|---|
| `R2_ENDPOINT` / `R2_BUCKET` / `R2_KEY` / `R2_SECRET` (+ optional `R2_PREFIX`) | same as the Windows box |
| `DATA_DIR` / `OUTPUTS_DIR` | leave at defaults (`/app/data`, `/app/outputs`) — the volume symlinks handle placement |
| `SYNC_INTERVAL_MIN` | default `15` |
| `CMA_WORKER_HOST` | defaulted to `::` here — Railway's private mesh is IPv6-only; the worker binds AF_INET6 when the host contains `:`. Do NOT set `0.0.0.0` (IPv4-only = unreachable over `engine.railway.internal`). |
| `CMA_BLIND_CACHE` / `CMA_HYGIENE_CACHE` | defaulted by `entrypoint.engine.sh` to `$VOL/cache/…` so anchors survive redeploys AND data swaps; the puller never ships or clobbers them |
| `CLEAR_BLIND_CACHE_ON_SWAP` | default `0` — see tradeoffs below |
| `REQUIRE_SEED` | default `0`; set `1` to crash-loop until the first push lands |
| plus the six production flags + `ANTHROPIC_API_KEY` + `CMA_WORKER_TOKEN` | (deploy kit's table) |

**First deploy order:** run the Windows push once (bucket populated) → deploy
the engine → entrypoint's boot pull self-seeds the empty volume → worker warms
on real data. Deploying the engine first also works (worker starts dataless,
`REQUIRE_SEED=0`), and heals within `SYNC_INTERVAL_MIN` of the first push.

## Freshness verification

Three checks, most authoritative first:

1. **The marker (the ops contract):** `DATA_DIR/.freshness` — line 1 is the
   applied manifest's `generated_utc`; rewritten every successful cycle (a
   no-op cycle bumps mtime = "loop alive"). Detail in
   `DATA_DIR/.sync/last_success.json` / `last_failure.json`.
   ```bash
   railway ssh --service engine -- cat /app/data/.freshness
   # 2026-07-14T16:20:11Z
   ```
2. **The stamp's actual data source — newest comp `close_date`.** The studio
   stamp (`src/lib/compbird/freshness.ts`) surfaces the newest comparable's
   close date from the profile payload. One curl from inside the private
   network (comps are redacted for anonymous PUBLIC calls, not at the worker):
   ```bash
   railway ssh --service engine -- python3 -c "import json,urllib.request; r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8765/profile',data=json.dumps({'parcelId':'230322'}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+__import__('os').environ.get('CMA_WORKER_TOKEN','')})); p=json.load(r); print(max((c.get('close_date') or '') for c in p.get('comps',[])))"
   ```
   That date should track the newest close in the local
   `MLS Bot/data/mls_lookup.parquet` after a push.
3. **Public spot-check:** `https://compbird.com` studio as a logged-in Pro
   user — the stamp reads "evidence current to <newest close>". The anonymous
   `/api/compbird/profile` redacts comps, and `meta.as_of` is generated at
   request time — NOT a freshness signal; use checks 1–2 for ops.

## Staleness alerting hook

Alert when **the `.freshness` timestamp is older than 2 hours** (pushes are
hourly, pulls every 15 min; >2 h means the Windows box stopped pushing OR the
engine stopped applying — one signal covers both ends), or when
`.sync/last_failure.json` is newer than `last_success.json`. Wire it however
ops-monitoring lands: a Railway cron service running
`test $(( $(date +%s) - $(date -d "$(head -1 /app/data/.freshness)" +%s) )) -lt 7200`
inside the engine container, or an external monitor hitting a future
app-exposed freshness endpoint. (The marker is volume-local; the Next app
cannot read the engine's volume on Railway.)

## Blind-anchor cache — the honest story

`cma_blind_cache.json` (path env `CMA_BLIND_CACHE`, `blind_valuer.py:70`)
caches the LLM blind valuation **per (subject signature, model, prompt
version)**. Anchors do **not** auto-invalidate when the comp pool refreshes —
**by design** (the one-number invariant: profile == preview == generate, and
tuned recomputes never pay a second LLM call). Consequence: a subject valued
last week keeps folding last week's blind anchor into its ensemble after
today's swap.

`CLEAR_BLIND_CACHE_ON_SWAP=1` clears it whenever a pool parquet swaps.
**Default OFF.** Turning it on:

- ✚ anchors re-read fresh comp evidence on each subject's next valuation
- − every subject's next valuation pays a new Haiku call (cost + latency)
- − a subject's number can shift between visits with no user action
- − the running worker keeps its in-process anchor memo (`_MEM`,
  `blind_valuer.py:75`) until restarted, so a disk clear alone is partial

The hygiene cache (`cma_hygiene_cache.json`) is content-hash-keyed — pool
refreshes miss it naturally; it is never touched.

## Search index on Railway — the cross-service caveat

`data/search_index.sqlite` is read by the **app** service (better-sqlite3,
`src/lib/cma/search-index.ts:74-75`, path env `SEARCH_INDEX_PATH`), and Railway
volumes are per-service — the app cannot see the engine's copy. Without it,
studio typeahead breaks (the Python spawn fallback doesn't exist in the app
image). The deploy kit must pick one:

1. **Recommended:** run this same `pull_and_swap.sh` as a loop in the app
   container (needs `python3` + `bash` in the app image; ~30 MB) with
   `SYNC_INCLUDE=data/search_index.sqlite`, `DATA_DIR=/data`
   (the app's volume), `SEARCH_INDEX_PATH=/data/search_index.sqlite`. The
   sqlite probe is stdlib — no duckdb needed for this file set.
2. Bake a periodic app redeploy that re-downloads the index at boot.

Reopen caveat either way: the app opens the index **once** and caches the
handle — and caches *failure* too (`search-index.ts:81` memoizes `null`), so
the index must be present **before** the app boots, and the app must be
restarted/redeployed to pick up a swapped index (it ships ~daily on the heavy
tier; a scheduled daily restart after the nightly ship matches the proven
pattern).

## Local dry run (no bucket, no network — this is the verification harness)

```powershell
# Windows side: -LocalTarget writes the exact bucket layout to a directory.
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\zach\Desktop\MLS Bot\scripts\push_prod_data.ps1" `
  -LocalTarget "C:\temp\compbird-sync-test\bucket"
# 1st run: uploads everything -> objects/... + manifest.json
# 2nd run: every file logs "[skip] unchanged (hash match)"; manifest re-finalized

# Pull side (git-bash), into a scratch "volume":
DATA_DIR=/c/temp/compbird-sync-test/vol/data \
OUTPUTS_DIR=/c/temp/compbird-sync-test/vol/outputs \
bash deploy/data-sync/pull_and_swap.sh --local-source "/c/temp/compbird-sync-test/bucket"
# 1st run: downloads, probes, swaps all files; writes vol/data/.freshness
# 2nd run: "up to date … marker refreshed"
# corrupt an objects/ parquet (garbage bytes) -> the cycle FAILS, nothing swaps
```

The push state file keys per target, so local dry runs never affect what ships
to production.
