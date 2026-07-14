# Compbird ops on Railway — backups, uptime, error alerting

Ops kit for the **Railway** launch (two services: `app` = Dockerfile.app,
`engine` = Dockerfile.engine; one persistent volume each; engine private on
`http://engine.railway.internal:8765`). This REPLACES the VPS/cron kit that
used to live here — Railway has no host cron, no docker CLI on a box you own,
and no host paths, so periodic work runs INSIDE the containers and alerting
goes out over webhooks.

| File | What | Runs where |
|---|---|---|
| `litestream.yml` | continuous SQLite replication of the app DB to R2 (~1s behind live) | app container, supervises `node server.js` |
| `restore.sh` | integrity-checked restore from the replica + row-count report (`--counts` mode for drills) | app container (`compbird-restore`) or any box with litestream |
| `freshness-check.sh` | MLS-data freshness watchdog: marker age -> webhook w/ cooldown + optional dead-man ping | engine container, called by the data-sync pull loop |
| `fallback-backup.sh` | nightly `sqlite .backup` fallback (local rotation + optional R2 upload) — only if Litestream is off | app container loop |
| `ops.env.example` | which env vars to set on which Railway service | reference only |

## What Railway gives you natively vs what this kit adds

| Railway handles | This kit adds |
|---|---|
| TLS, domains, proxy | outside-in uptime probing (UptimeRobot et al. on `/api/health`) |
| restart on crash; deploy gated by healthcheck | paging when the app is up but WRONG (stale data, dead engine) |
| deploy-status webhooks (FAILED / CRASHED) | webhook alerts with cooldown from inside the loops |
| build + runtime logs, metrics dashboards | continuous off-provider DB backup (R2) + a REHEARSED restore |
| volume snapshots (service → volume → Backups) | dead-man liveness for the private engine without exposing it |

What Railway does **not** do: probe your HTTP endpoint on a schedule and page
you, notice that `mls_lookup.parquet` stopped refreshing, or back up a SQLite
file transactionally (volume snapshots are not WAL-aware; they are the
secondary, not the primary). That is exactly the gap the pieces below fill.

---

## 1. Backups — Litestream (primary)

The app DB (`DATABASE_URL=file:/data/compbird.db`, Railway volume mounted at
`/data`) is replicated continuously to Cloudflare R2 by Litestream running as
the container's top process: `litestream replicate -exec "node server.js"`
streams every WAL frame and exits when node exits. Worst-case data loss is
seconds, vs a day for nightly dumps.

**R2 setup (one-time):** create bucket `compbird-backups`; R2 → Manage API
Tokens → create a token scoped to ONLY that bucket, Object Read & Write; note
the account id from the R2 overview page.

**Railway app-service variables** (see `ops.env.example`):

```
LITESTREAM_DB_PATH=/data/compbird.db          # MUST match DATABASE_URL's file: path
LITESTREAM_REPLICA_URL=s3://compbird-backups/compbird/db?endpoint=<ACCOUNT_ID>.r2.cloudflarestorage.com&region=auto
LITESTREAM_ACCESS_KEY_ID=...
LITESTREAM_SECRET_ACCESS_KEY=...
```

### Blocks for the deploy agent to adopt (this kit does not edit your files)

`deploy/Dockerfile.app`, in the **runner** stage, before `USER node`
(the tarball layout — a bare `litestream` member — is verified against the
v0.5.14 release asset):

```dockerfile
# ── Litestream: continuous SQLite backup to R2 (deploy/ops/README.md) ────────
ARG LITESTREAM_VERSION=0.5.14
ADD https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-x86_64.tar.gz /tmp/litestream.tar.gz
RUN tar -xzf /tmp/litestream.tar.gz -C /usr/local/bin litestream && rm /tmp/litestream.tar.gz
COPY deploy/ops/litestream.yml /etc/litestream.yml
COPY deploy/ops/restore.sh /usr/local/bin/compbird-restore
RUN sed -i 's/\r$//' /usr/local/bin/compbird-restore && chmod +x /usr/local/bin/compbird-restore
```

`docker-entrypoint.sh` — replace the final `exec node server.js` with (order
matters: restore-if-missing must run BEFORE `prisma db push`, or the push
creates an empty DB and the restore no-ops forever):

```sh
: "${LITESTREAM_DB_PATH:=/data/compbird.db}"; export LITESTREAM_DB_PATH

if [ -n "${LITESTREAM_REPLICA_URL:-}" ]; then
  # Fresh volume (disaster recovery / volume swap): pull the newest backup.
  # No-ops when the DB already exists or the replica is empty (first launch).
  litestream restore -if-db-not-exists -if-replica-exists \
    -config /etc/litestream.yml "$LITESTREAM_DB_PATH"
fi

echo "-> Syncing database schema (prisma db push)..."
CHECKPOINT_DISABLE=1 node node_modules/prisma/build/index.js db push \
  --skip-generate --schema prisma/schema.prisma

export NODE_OPTIONS="--max-old-space-size=1024"
if [ -n "${LITESTREAM_REPLICA_URL:-}" ]; then
  echo "-> Starting compbird under litestream replication..."
  exec litestream replicate -config /etc/litestream.yml -exec "node server.js"
else
  echo "WARN: LITESTREAM_REPLICA_URL unset - running WITHOUT continuous DB backup"
  exec node server.js
fi
```

Notes:
- Litestream v0.5 adds two empty bookkeeping tables (`_litestream_lock`,
  `_litestream_seq`) to the DB. Harmless; you will see them in `--counts`.
- `litestream.yml` is deliberately minimal: the v0.5 YAML loader silently
  IGNORES unknown keys (verified — a bogus key parses clean), so every extra
  knob is a typo risk with no error to catch it.
- The engine's multi-GB parquets are NOT backed up this way — they are
  re-pushed hourly from the Windows box (the data-sync loop IS their backup).

### Blind-anchor cache (ask of the data-sync agent — their loop, one line)

`$DATA_DIR/cma_blind_cache.json` exists only on the engine volume; losing it
re-pays one Claude call per previously-valued subject. After each successful
pull cycle, push it back out with the same client you pull with:

```sh
<r2-client> cp "$DATA_DIR/cma_blind_cache.json" s3://compbird-backups/compbird/cache/cma_blind_cache.json
```

## 2. Backups — fallback (documented, second line)

If Litestream is ever off: `fallback-backup.sh` takes a WAL-safe
`sqlite .backup` snapshot, integrity-checks it, gzips + rotates 7 locally on
the volume, and uploads to R2 via `curl --aws-sigv4` (falls back to `aws`/`mc`;
node+better-sqlite3 covers the snapshot itself if sqlite3 CLI is absent).
Railway has no cron, so it runs from a loop in the entrypoint:

```sh
( while :; do fallback-backup.sh || echo "fallback-backup FAILED"; sleep 86400; done ) &
```

Tooling: node:20-slim ships neither `sqlite3` nor `curl`. For R2 uploads add
`curl` to the apt-get line in Dockerfile.app (snapshots themselves work
without it via the node fallback, but stay volume-local). Independently:
enable Railway's native **volume backups** (app service → volume → Backups →
daily) as the zero-effort second copy — just remember they are point-in-time
volume snapshots, not transactional DB backups; Litestream stays primary.

## 3. Restore + the drill

**Production restore (Railway):**

```sh
railway ssh --service app
compbird-restore -o /data/restored.db      # restore newest backup to a side path
# point-in-time instead:  LITESTREAM_RESTORE_ARGS="-timestamp 2026-07-14T04:00:00Z" compbird-restore -o /data/restored.db
FORCE=1 compbird-restore                    # or restore straight over the live path:
                                            # moves live db -> .pre-restore.<ts>, clears -wal/-shm
exit
railway redeploy --service app              # reopen the DB + resume replication
```

Two caveats, both by design:
- restoring over the live path while node is running risks a torn write —
  prefer the side-path + `FORCE=1` swap immediately followed by `redeploy`
  (seconds of 5xx), or do it during a quiet window;
- after any restore, point `LITESTREAM_REPLICA_URL` at a FRESH prefix (e.g.
  `.../compbird/db-2`) so the old backup lineage is preserved intact and the
  restored DB starts a clean one.

Disaster recovery (volume lost entirely): create a new volume, redeploy — the
entrypoint's `restore -if-db-not-exists` pulls the newest backup before
`prisma db push` runs. That path is exercised by the drill's restore step
(same command, same config mechanics).

### Restore drill — run it quarterly. Last run 2026-07-14, PASSED

Litestream with a **file replica** needs no cloud at all, so the drill runs
anywhere against a COPY (never the live file). What was actually run on the
dev box (`<TMP>` = a temp dir; source = a `sqlite3.backup()` copy of
`prisma/dev.db`):

```sh
# drill-litestream.yml
dbs:
  - path: <TMP>/prod.db
    replica:
      path: <TMP>/replica

# 1. replicate, writing 3 probe rows MID-replication (proves WAL shipping,
#    not just the initial snapshot); -exec supervision = production semantics
litestream replicate -config drill-litestream.yml -exec "python probe_write.py"
#   ...ltx file uploaded minTXID=...001 (snapshot: 22 rows)
#   probe: wrote 3 rows to _drill_probe mid-replication
#   ...ltx file uploaded minTXID=...002 (the probe rows)
#   subprocess exited, litestream shutting down

# 2. restore through THIS kit's script
LITESTREAM_CONFIG=drill-litestream.yml restore.sh -o <TMP>/restored.db <TMP>/prod.db

# 3. verify
restore.sh --counts <TMP>/prod.db      > source-counts.txt
restore.sh --counts <TMP>/restored.db  > restored-counts.txt
diff source-counts.txt restored-counts.txt && echo DRILL PASS
```

Result (2026-07-14, litestream v0.5.14 windows-x86_64; prod pins the same
version's linux build):

```
integrity: ok
Account: 4          AuthUser: 4         Membership: 4
PortfolioItem: 0    PortfolioRun: 0     UsageEvent: 10
VerificationToken: 0                    _drill_probe: 3
_litestream_lock: 0 _litestream_seq: 0
TOTAL: 25
DRILL PASS: restored DB matches source (integrity ok, all row counts identical)
```

Also verified in the same session: overwrite without `FORCE=1` refuses with a
clear message; `FORCE=1` keeps a `.pre-restore.<ts>` copy; the production
`litestream.yml` parses + env-expands against the real binary
(`litestream databases -config litestream.yml` → lists the db + s3 replica).

## 4. Uptime monitoring — external pinger first

Railway restarts crashed containers, but nobody probes your URL unless you
make them. Register **one public URL** with an external prober (UptimeRobot
free tier, BetterStack, Pingdom — anything that GETs a URL and alerts on
non-2xx):

```
https://compbird.com/api/health        interval 1-5 min, alert on non-200
                                       (set "confirm down" ~2 checks to ride out deploys)
```

Current response (verified live): `{"ok":true,"version":"0.1.0","db":"up"}` —
HTTP 200 only when the SQLite DB answers `SELECT 1`, 503 otherwise. Probing
through `https://compbird.com` also exercises DNS + TLS + Railway's proxy,
i.e. what users actually experience.

**Why one URL / why the engine stays private:** the engine has an open (by
design) `/healthz`, but it lives on Railway's private network
(`engine.railway.internal:8765`) — publishing it publicly would add an
internet-facing surface (and its bearer-token exemption on /healthz) purely
for monitoring. Instead:

1. fold engine reachability into `/api/health` (app change — REPORTED, patch
   below), so the ONE public probe covers both services; and
2. the engine container's freshness loop doubles as a dead-man switch via
   `PING_URL` (below) — if the engine container dies, the pings stop, and
   healthchecks.io alerts you without the engine ever being reachable from
   outside.

### REPORTED app change (app owner: do not let ops edit src/)

`src/app/api/health/route.ts` currently checks only the DB. In production the
app is WORKER-ONLY (no Python fallback): engine down = profile/preview/
generate all dead while `/api/health` stays green. Recommended fold-in:

```ts
import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { workerBaseUrl } from "@/lib/cma/worker";
import pkg from "../../../../package.json";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 10;

export async function GET() {
  let dbUp = false;
  try {
    await db.$queryRaw`SELECT 1`;
    dbUp = true;
  } catch {}
  let engine: "up" | "down" = "down";
  try {
    const res = await fetch(workerBaseUrl() + "/healthz", {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    engine = res.ok ? "up" : "down";
  } catch {}
  const ok = dbUp && engine === "up";
  return NextResponse.json(
    { ok, version: pkg.version, db: dbUp ? "up" : "down", engine },
    { status: ok ? 200 : 503, headers: { "Cache-Control": "no-store" } },
  );
}
```

Consequences to accept knowingly: an engine redeploy (~2 min sklearn/AVM
warm-up) will 503 the app's health for that window — hence "confirm down: 2
checks" on the prober; and if Railway's app-service `healthcheckPath` points
at `/api/health`, an app deploy during an engine outage will be held back
(arguably correct — the new app instance couldn't serve anyway).

**Railway healthcheck config** (deploy agent): Railway ignores Dockerfile
`HEALTHCHECK` — set per-service in the dashboard/railway.json instead:
app → `healthcheckPath=/api/health`; engine → `/healthz` with a generous
timeout (the worker only listens after warm-up; 300s is safe).

## 5. Data freshness — `freshness-check.sh` (engine container)

The app UI stamps "MLS data — refreshed hourly". The chain keeping that true:
Windows Task Scheduler (`mls-hourly`) → R2 push → engine pull loop → atomic
swap → `touch $DATA_DIR/.freshness`. The watchdog turns a stalled marker into
a page.

**Asks of the data-sync agent** (their loop, engine container):

1. after every successful sync cycle — including zero-file cycles, which
   still prove the chain runs end-to-end — refresh the marker:
   `date -u +%FT%TZ > "$DATA_DIR/.freshness"`
2. call the watchdog once per iteration, never letting it kill the loop:

```sh
while :; do
  pull_and_swap && date -u +%FT%TZ > "$DATA_DIR/.freshness"
  sh /app/deploy/ops/freshness-check.sh || true
  sleep 300
done
```

3. the engine image builds from the ENGINE repo ("MLS Bot"), so bake this
   script in next to your loop (same canonical-copy pattern as
   Dockerfile.engine): copy `deploy/ops/freshness-check.sh` from the app repo
   into the engine build context, e.g. `COPY deploy/ops/freshness-check.sh
   /app/deploy/ops/freshness-check.sh` after staging it there.

Behavior (all verified — transcript below): fresh → silent (exit 0, one log
line, no webhook) + optional dead-man ping; stale or missing marker → ONE
webhook per `COOLDOWN_MIN` (30) while it stays stale, exit 1; recovery → one
RECOVERED webhook. Transport: curl if present, else python3 stdlib — the
engine image (python:3.12-slim) has no curl, and the python path is
explicitly tested. Webhook formats: Slack / Discord (JSON) auto-sniffed from
the URL, anything else (ntfy) gets raw text; override with `WEBHOOK_FORMAT`.

Threshold defaults: `FRESHNESS_MAX_AGE_MIN=120` — one fully-missed hourly
cycle plus slack, so a dead chain pages within ~2h while a single slow push
doesn't. Cooldown state lives in `/tmp` (ephemeral): a container restart can
repeat one alert — acceptable.

**healthchecks.io (dead-man):** create a check "compbird-engine-data",
period 10 min, grace 30 min; set its ping URL as `PING_URL` on the engine
service. Fresh cycles ping it, stale cycles ping `/fail`, and SILENCE (container
dead, loop wedged, Railway incident) alerts too — that is the property a
push-based pinger has that a webhook can't give you, and it covers engine
liveness with the engine fully private.

### Freshness drill — 2026-07-14, all PASSED (webhook sink = local echo server)

```
T1 fresh marker             -> exit 0, sink EMPTY (silent)
T2 marker 240min old        -> exit 1, POST /hook:
   ALERT [drill-engine] MLS data is STALE: marker is 240min old (max 120min).
   The hourly refresh -> R2 -> pull chain has stopped; the app's 'MLS data
   refreshed hourly' stamp is currently FALSE. Check: the Windows mls-hourly
   task, the R2 push, and this container's pull loop (railway logs --service engine).
T3 re-run 2s later          -> exit 1, NO new webhook (30min cooldown)
T4 marker touched fresh     -> exit 0, one webhook:
   RECOVERED [drill-engine] MLS data is fresh again (marker 0min old, max 120min).
T5 marker MISSING, discord  -> exit 1, JSON body {"content": "ALERT ... does not exist ..."}
T6 PING_URL set             -> fresh: POST /ping ; stale: POST /ping/fail
T7 HTTP_TOOL=python         -> alert delivered via python3 stdlib (no curl — engine-image path)
```

## 6. Error alerting & logs

- **Railway deploy webhooks (native):** Project → Settings → Webhooks → add
  your Discord/Slack webhook URL. Fires on deployment status changes,
  including FAILED and CRASHED — this is your "app crash-looped at 3am" page,
  no code needed. Do it before launch.
- **This kit's webhooks:** data staleness (`freshness-check.sh`) and the
  external prober's alerts. Same Slack/Discord/ntfy target works everywhere.
- **Logs (Railway CLI):**

```sh
railway logs --service app          # runtime logs (follow)
railway logs --service engine
railway logs --deployment           # build/deploy logs of the latest deploy
railway ssh --service app           # shell into the running container
```

  UI: project → service → Deployments → View logs; Observability tab for
  CPU/RAM/network per service. Retention is limited on lower plans — for
  stack-trace grouping/history the documented (not built) upgrade is Sentry
  in the app + engine; these scripts are the zero-dependency floor.
- **Engine request failures** surface in the app as clean 5xx JSON (the
  worker client falls back/errors without crashing), so the external prober +
  the folded-in `engine` field are the detection path, not process death.

## 7. Env reference

See `ops.env.example` for the full annotated list: `LITESTREAM_*` (app),
`DB_PATH`/`BACKUP_DIR`/`KEEP`/`R2_*` (fallback backup, app), `DATA_DIR` /
`FRESHNESS_MAX_AGE_MIN` / `WEBHOOK_URL` / `WEBHOOK_FORMAT` / `PING_URL` /
`COOLDOWN_MIN` / `STATE_DIR` / `HOST_LABEL` / `HTTP_TOOL` (engine watchdog),
plus `LITESTREAM_BIN` / `LITESTREAM_CONFIG` / `FORCE` /
`LITESTREAM_RESTORE_ARGS` (restore.sh).

## Launch checklist (ops)

- [ ] R2 bucket + scoped token created; `LITESTREAM_*` set on the app service
- [ ] deploy agent adopted the Dockerfile + entrypoint blocks (section 1)
- [ ] first deploy log shows "Starting compbird under litestream replication"
- [ ] `railway ssh --service app` → `compbird-restore -o /tmp/drill.db && compbird-restore --counts /tmp/drill.db` (in-prod restore drill)
- [ ] UptimeRobot monitor on `https://compbird.com/api/health` (alert non-200)
- [ ] `/api/health` engine fold-in patch landed (section 4) — or accept blind spot
- [ ] Railway deploy webhook → Discord/Slack
- [ ] healthchecks.io check created; `PING_URL` + `WEBHOOK_URL` set on engine service
- [ ] data-sync loop touches `.freshness`, calls `freshness-check.sh`, pushes the blind-anchor cache (section 1 + 5 asks)
- [ ] Railway volume backups enabled on the app volume (secondary)
