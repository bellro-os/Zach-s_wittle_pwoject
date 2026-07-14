#!/usr/bin/env bash
# entrypoint.sh - the engine container's PID-1 supervisor (Railway service
# "engine"). Dockerfile.engine execs this with NO arguments; everything is
# configured via env. It does three things:
#
#   1. INITIAL SEED: runs pull_and_swap.sh once at boot. An empty volume plus
#      a populated bucket = a self-seeding first deploy (the puller downloads,
#      validates and activates the full dataset before the worker warms).
#   2. WORKER: starts the warm CMA worker (worker/cma_worker.py). Its exit
#      PROPAGATES as the container's exit code, so Railway's restart policy
#      owns worker crashes - this script never masks them.
#   3. SYNC LOOP: re-runs pull_and_swap.sh every SYNC_INTERVAL_MIN minutes
#      (default 15). A failed cycle logs + retries next tick; it never kills
#      the worker (stale-but-valid data beats an outage; staleness is alerted
#      via the DATA_DIR/.freshness marker - see README).
#
# CONTRACT (for Dockerfile.engine): exec-able, no args, bash, expects the
# engine checkout at $ENGINE_DIR (default /app) with worker/cma_worker.py,
# and this script's own directory to contain pull_and_swap.sh.
#
# ENV (all optional unless noted):
#   R2_ENDPOINT/R2_BUCKET/R2_KEY/R2_SECRET/R2_PREFIX/R2_REGION
#                       bucket config for the puller. UNSET endpoint = data
#                       sync disabled (local/dev image) - loudly logged.
#   DATA_DIR            default /app/data   (Railway volume mount)
#   OUTPUTS_DIR         default /app/outputs (models land here; regenerated
#                       PDFs/HTML also write here at request time)
#   SYNC_INTERVAL_MIN   minutes between pull cycles (default 15)
#   REQUIRE_SEED        1 = exit(1) when the comp pool is still missing after
#                       the initial pull (Railway restarts with backoff until
#                       the first Windows push lands). Default 0: start the
#                       worker anyway - /healthz stays green, CMA requests
#                       fail until data arrives, the app's spawn-fallback
#                       degrades gracefully.
#   CMA_WORKER_HOST     default :: here — Railway's <svc>.railway.internal mesh
#                       is IPv6-ONLY, so the worker must bind IPv6 (cma_worker.py
#                       binds AF_INET6 when HOST contains ":"; "::" is dual-stack
#                       on Linux). 0.0.0.0 binds IPv4-only and is UNREACHABLE over
#                       the private network — do NOT set it. cma_worker.py's own
#                       default is 127.0.0.1 (localhost-only) so we override here.
#   CMA_BLIND_CACHE / CMA_HYGIENE_CACHE
#                       set them INTO the volume (e.g. /app/data/cache/…) so
#                       anchors survive restarts; parent dir is created here.
#   ENGINE_DIR          engine checkout root (default /app)
#
# Signals: TERM/INT are forwarded to the worker so Railway deploys drain
# cleanly; the sync loop is then torn down and the worker's code is returned.

# The caller may invoke this as `sh entrypoint.sh` (deploy/entrypoint.engine.sh
# does); this script needs bash (wait -n semantics, BASH_SOURCE, indirect
# expansion), so re-exec under bash when started by a POSIX sh.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="${ENGINE_DIR:-/app}"
DATA_DIR="${DATA_DIR:-/app/data}"
OUTPUTS_DIR="${OUTPUTS_DIR:-/app/outputs}"
SYNC_INTERVAL_MIN="${SYNC_INTERVAL_MIN:-15}"
REQUIRE_SEED="${REQUIRE_SEED:-0}"
PULL="$SCRIPT_DIR/pull_and_swap.sh"

# Railway private networking is IPv6-ONLY: the worker must bind IPv6, not IPv4.
# cma_worker.py reads CMA_WORKER_HOST (defaults to localhost) and binds AF_INET6
# when the host contains ":". "::" is the dual-stack wildcard on Linux, so it
# serves both engine.railway.internal (IPv6) and any IPv4 healthcheck. Setting
# 0.0.0.0 here would bind IPv4-only and make the engine unreachable — do NOT.
export CMA_WORKER_HOST="${CMA_WORKER_HOST:-::}"

log() { echo "[entrypoint] $*"; }

mkdir -p "$DATA_DIR" "$OUTPUTS_DIR"
# AI caches: when pointed into the volume, make sure the parent dir exists
# before the worker first writes (blind_valuer.py:70 / cma_hygiene.py:69).
for cache_var in CMA_BLIND_CACHE CMA_HYGIENE_CACHE; do
  cache_path="${!cache_var:-}"
  if [ -n "$cache_path" ]; then mkdir -p "$(dirname "$cache_path")"; fi
done

[ -f "$PULL" ] || { log "FATAL: $PULL missing from the image"; exit 1; }

SYNC_ENABLED=1
if [ -z "${R2_ENDPOINT:-}" ]; then
  SYNC_ENABLED=0
  log "WARNING: R2_ENDPOINT unset - hourly data sync DISABLED; the engine will serve whatever the volume already holds"
fi

# ── 1) initial seed (blocking, before the worker warms on the data) ─────────
if [ "$SYNC_ENABLED" = "1" ]; then
  log "initial data pull (self-seeds an empty volume)…"
  if bash "$PULL"; then
    log "initial pull ok"
  else
    rc=$?
    log "initial pull failed (rc=$rc) - continuing; the sync loop retries every ${SYNC_INTERVAL_MIN}m"
  fi
fi
if [ ! -f "$DATA_DIR/mls_lookup.parquet" ]; then
  if [ "$REQUIRE_SEED" = "1" ]; then
    log "FATAL: $DATA_DIR/mls_lookup.parquet still missing and REQUIRE_SEED=1 - exiting so Railway retries"
    exit 1
  fi
  log "WARNING: comp pool not present yet - worker starts anyway (healthz green, CMA requests will fail until data lands)"
fi

# ── 2) worker ────────────────────────────────────────────────────────────────
cd "$ENGINE_DIR"
python -X utf8 worker/cma_worker.py &
WORKER_PID=$!
log "worker started (pid $WORKER_PID, host $CMA_WORKER_HOST)"

# ── 3) sync loop ─────────────────────────────────────────────────────────────
SYNC_PID=""
if [ "$SYNC_ENABLED" = "1" ]; then
  (
    while true; do
      sleep "$(( SYNC_INTERVAL_MIN * 60 ))"
      if ! bash "$PULL"; then
        echo "[entrypoint] sync cycle failed (rc=$?) - next attempt in ${SYNC_INTERVAL_MIN}m" >&2
      fi
    done
  ) &
  SYNC_PID=$!
  log "sync loop started (pid $SYNC_PID, every ${SYNC_INTERVAL_MIN}m)"
fi

# ── supervision: propagate the worker's exit; drain cleanly on TERM ──────────
term() {
  log "signal received - stopping worker"
  kill -TERM "$WORKER_PID" 2>/dev/null
}
trap term TERM INT

wait "$WORKER_PID"
WORKER_RC=$?
if [ "$WORKER_RC" -gt 128 ]; then
  # a trapped signal interrupted `wait` before the worker was reaped - wait
  # again to collect the worker's REAL exit status for Railway
  wait "$WORKER_PID"
  WORKER_RC=$?
fi
log "worker exited (rc=$WORKER_RC) - shutting down"
if [ -n "$SYNC_PID" ]; then kill "$SYNC_PID" 2>/dev/null; fi
exit "$WORKER_RC"
