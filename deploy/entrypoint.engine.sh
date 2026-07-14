#!/bin/sh
# Engine container boot (Railway). CANONICAL COPY lives in the Compbird repo
# (deploy/entrypoint.engine.sh); runs in the ENGINE repo's image as
# /app/deploy/entrypoint.engine.sh. PID-1 sequence:
#
#   1. Volume layout — Railway mounts ONE volume per service. Whatever env
#      exposes its mount path (Railway injects RAILWAY_VOLUME_MOUNT_PATH;
#      ENGINE_VOLUME_ROOT is the manual override), create the canonical
#      subdirs on it and symlink the repo-relative paths the engine resolves:
#          $VOL/data    -> /app/data      (parquets — hourly-synced)
#          $VOL/outputs -> /app/outputs   (model joblibs + generated PDFs)
#          $VOL/cache   -> /app/cache     (AI caches — survive everything)
#      With NO volume env set this step is a no-op, so the same image still
#      works with plain bind mounts at /app/data etc. (local docker, VPS).
#
#   2. Data-sync seam — if deploy/data-sync/entrypoint.sh exists (owned by the
#      data-sync kit), EXEC it: it becomes PID 1 and supervises BOTH the
#      initial pull + hourly R2 puller AND the worker. CONTRACT: it must start
#      the worker itself (python -X utf8 worker/cma_worker.py) and never exit
#      while the worker runs.
#
#   3. Fallback — no data-sync kit shipped: start the worker directly.
set -e

VOL="${RAILWAY_VOLUME_MOUNT_PATH:-${ENGINE_VOLUME_ROOT:-}}"
if [ -n "$VOL" ]; then
  echo "[entrypoint.engine] wiring volume layout under $VOL"
  mkdir -p "$VOL/data" "$VOL/outputs" "$VOL/cache"
  for d in data outputs cache; do
    # Replace any image-baked dir (e.g. the mkdir'd /app/cache) with the link.
    if [ -e "/app/$d" ] && [ ! -L "/app/$d" ]; then rm -rf "/app/$d"; fi
    ln -sfn "$VOL/$d" "/app/$d"
  done
  # Persistent AI caches: keep the blind-anchor + hygiene caches on the volume
  # (a wiped blind cache re-anchors valuations = Haiku spend + value drift).
  # Explicit service variables still win over these defaults.
  export CMA_BLIND_CACHE="${CMA_BLIND_CACHE:-$VOL/cache/cma_blind_cache.json}"
  export CMA_HYGIENE_CACHE="${CMA_HYGIENE_CACHE:-$VOL/cache/cma_hygiene_cache.json}"
fi

# Loud, non-fatal boot warnings — the worker starts fine with an empty volume,
# but every request needs these (see deploy/README.md "First data seed").
[ -f /app/data/mls_lookup.parquet ] || \
  echo "!! WARNING: /app/data/mls_lookup.parquet missing — CMA requests will fail until data is seeded." >&2
[ -f /app/outputs/mls_analytics/avm_model/regressor.joblib ] || \
  echo "!! WARNING: AVM model joblibs missing under /app/outputs/mls_analytics/ — valuations degraded until seeded." >&2
[ -n "${ANTHROPIC_API_KEY:-}" ] || \
  echo "!! WARNING: ANTHROPIC_API_KEY unset — hygiene + blind ensemble silently degrade; valuations will NOT match the certified posture." >&2

# Data-sync supervisor seam (worker + hourly puller in one container).
if [ -f /app/deploy/data-sync/entrypoint.sh ]; then
  echo "[entrypoint.engine] handing off to deploy/data-sync/entrypoint.sh (supervisor)"
  exec sh /app/deploy/data-sync/entrypoint.sh
fi

echo "[entrypoint.engine] no data-sync kit present — starting the worker directly"
exec python -X utf8 worker/cma_worker.py
