#!/bin/sh
# deploy/data-sync/entrypoint.app.sh — APP-side search-index seeder (Railway
# service "app"). Owned by the data-sync kit; CALLED (not exec'd) by
# deploy/entrypoint.app.sh AFTER `prisma db push` and BEFORE the server start.
#
# WHY THIS EXISTS
# ───────────────
# src/lib/cma/search-index.ts opens data/search_index.sqlite ONCE with
# {fileMustExist:true} and memoizes the handle on globalThis — AND it memoizes
# `null` on failure (search-index.ts:81/97): if the ~1.1 GB index is absent at
# the first read, the app caches a dead handle FOREVER and typeahead stays
# broken until the process restarts. Production has no Python spawn fallback in
# the app image, so the index MUST exist on the app volume BEFORE node starts.
# This script blocks boot until it has tried to put the index there.
#
# CONTRACT (with deploy/entrypoint.app.sh — the NEW, post-litestream contract)
# ───────────────────────────────────────────────────────────────────────────
#   * This script SEEDS the index and RETURNS. It does NOT start the server —
#     entrypoint.app.sh owns the server exec (under litestream). It replaces the
#     old "hook execs node server.js" contract.
#   * It is BLOCKING but NON-FATAL: entrypoint.app.sh calls it with `|| true`,
#     so a seed failure (network blip, R2 down) degrades to broken typeahead,
#     never a boot failure. The next container start / refresh cycle retries.
#   * No arguments; all config via env (mirrors pull_and_swap.sh).
#
# WHAT IT DOES
# ────────────
#   1. Reuse pull_and_swap.sh with SYNC_INCLUDE=data/search_index.sqlite so ONLY
#      the index is fetched onto the app volume (DATA_DIR, e.g. /data). The
#      sqlite validation probe is python3-stdlib (no duckdb needed for this
#      file), and the download uses the puller's own stdlib SigV4 client.
#   2. If R2 is not configured (R2_ENDPOINT/BUCKET/KEY/SECRET unset), log a loud
#      warning and return 0 — a no-R2 local/dev run must still boot.
#   3. OPTIONAL background refresh, OFF by default. See below.
#
# REFRESH (SEARCH_INDEX_REFRESH_HOURS — OPTIONAL, OFF by default)
# ──────────────────────────────────────────────────────────────
# Unset or <= 0  ⇒  SEED ONCE. The index is pulled at boot and never re-checked;
# a new index (it ships ~daily on the heavy tier) is picked up on the next
# container restart/redeploy. This is the recommended, lowest-surprise default.
#
# Set > 0  ⇒  after the blocking seed, background a loop that every N hours
# re-pulls the index and, IF the on-disk index actually changed, EXITS THIS
# CONTAINER (kill PID 1) so Railway's restart policy brings up a fresh process.
# That restart is the ONLY way to drop search-index.ts's cached DB handle — the
# running node process holds the old inode open and would keep serving stale
# typeahead otherwise (see the reopen caveat in deploy/data-sync/README.md).
# The refresh loop is a blunt instrument (a short blip of 5xx during the
# restart); leave it off unless intra-day address freshness in typeahead
# matters more than uptime smoothness.
set -eu

log() { echo "[data-sync/app] $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PULL="$SCRIPT_DIR/pull_and_swap.sh"

# The app volume. pull_and_swap.sh places data/<rel> at DATA_DIR/<rel-sub>, so
# with DATA_DIR=/data the index lands at /data/search_index.sqlite — matching
# the app's SEARCH_INDEX_PATH default (.env.production.example).
DATA_DIR="${DATA_DIR:-/data}"
# Only the index — never the engine's multi-GB parquets (they belong on the
# engine volume, not the app volume).
INCLUDE="data/search_index.sqlite"
INDEX_PATH="$DATA_DIR/search_index.sqlite"
REFRESH_HOURS="${SEARCH_INDEX_REFRESH_HOURS:-0}"

if [ ! -f "$PULL" ]; then
  log "WARNING: $PULL missing from the image — cannot seed the search index; typeahead will fail"
  exit 0
fi

# No R2 config ⇒ don't block a local/dev boot. pull_and_swap.sh itself exits 78
# in this case, but detect it up-front so the message is unambiguous.
if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_BUCKET:-}" ] || [ -z "${R2_KEY:-}" ] || [ -z "${R2_SECRET:-}" ]; then
  log "WARNING: R2_ENDPOINT/R2_BUCKET/R2_KEY/R2_SECRET not all set — search-index seed SKIPPED."
  log "WARNING: address typeahead will fail until $INDEX_PATH is seeded onto the app volume."
  exit 0
fi

# One index pull. SYNC_INCLUDE filters pull_and_swap.sh to just the index; a
# no-op cycle (index already current) is a success. rc 78 = R2 unset (handled
# above, but stay defensive); any other non-zero is a real failure we surface
# without aborting boot (the caller runs us non-fatally).
seed_once() {
  log "seeding search index -> $INDEX_PATH (SYNC_INCLUDE=$INCLUDE, DATA_DIR=$DATA_DIR)"
  rc=0
  # bash, NOT sh: pull_and_swap.sh needs bash (set -o pipefail); Debian's
  # sh=dash rejects it with exit 2. bash is Essential in Debian => present.
  DATA_DIR="$DATA_DIR" SYNC_INCLUDE="$INCLUDE" bash "$PULL" || rc=$?
  if [ "$rc" -eq 0 ]; then
    if [ -f "$INDEX_PATH" ]; then
      log "search index present ($INDEX_PATH)"
    else
      log "WARNING: pull reported success but $INDEX_PATH is absent — typeahead will fail"
    fi
  elif [ "$rc" -eq 78 ]; then
    log "WARNING: pull reports R2 not configured (rc=78) — index NOT seeded"
  else
    log "WARNING: search-index pull failed (rc=$rc) — typeahead will fall back / fail until next attempt"
  fi
  return "$rc"
}

# Cheap change fingerprint of the on-disk index (inode:size:mtime). os.replace
# in pull_and_swap.sh swaps the inode on a real change, so any of these moving
# means the index was refreshed.
index_fingerprint() {
  if [ -f "$INDEX_PATH" ]; then
    # stat flavors differ (GNU vs BusyBox); fall back to ls if -c is unsupported.
    stat -c '%i:%s:%Y' "$INDEX_PATH" 2>/dev/null \
      || ls -li --time-style=+%s "$INDEX_PATH" 2>/dev/null \
      || echo "unknown"
  else
    echo "absent"
  fi
}

# ── 1) blocking initial seed (non-fatal) ─────────────────────────────────────
seed_once || true

# ── 2) optional background refresh (OFF unless SEARCH_INDEX_REFRESH_HOURS>0) ──
case "$REFRESH_HOURS" in
  ''|*[!0-9]*) REFRESH_HOURS=0 ;;  # non-numeric ⇒ treat as OFF
esac

if [ "$REFRESH_HOURS" -gt 0 ]; then
  APP_PID="$PPID"  # deploy/entrypoint.app.sh, which becomes the litestream/node
                   # parent as PID 1 — killing it drops node + its cached handle.
  log "search-index refresh loop ON: every ${REFRESH_HOURS}h; on a changed index the container EXITS so Railway restarts it (drops the cached DB handle)"
  (
    before="$(index_fingerprint)"
    while true; do
      sleep "$(( REFRESH_HOURS * 3600 ))"
      if DATA_DIR="$DATA_DIR" SYNC_INCLUDE="$INCLUDE" bash "$PULL"; then
        after="$(index_fingerprint)"
        if [ "$after" != "$before" ]; then
          log "search index changed ($before -> $after) — exiting PID 1 so Railway restarts with a fresh handle"
          kill -TERM "$APP_PID" 2>/dev/null || true
          exit 0
        fi
      else
        log "refresh pull failed (rc=$?) — keeping current index; retry next cycle"
      fi
    done
  ) &
  log "refresh loop backgrounded (pid $!)"
fi

# Return to deploy/entrypoint.app.sh, which starts the server under litestream.
exit 0
