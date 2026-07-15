#!/bin/sh
# Compbird app container boot (Railway). PID-1 sequence — ORDER IS LOAD-BEARING:
#   1. SCHEMA SYNC — apply the build-generated prisma/schema.sql to the Postgres
#      database (DATABASE_URL) via deploy/apply-schema.mjs (the `pg` driver, NOT
#      the Prisma CLI — its dep closure isn't in Next's standalone trace and
#      crash-looped boot with "Cannot find module 'effect'"). Guarded
#      apply-if-fresh: first boot on an empty DB provisions the schema, later
#      boots no-op. FATAL on failure — an app with no schema can't serve.
#   2. SEARCH-INDEX SEED — call deploy/data-sync/entrypoint.app.sh (blocking,
#      NON-FATAL). It pulls ONLY data/search_index.sqlite onto the app volume so
#      the ~1.1 GB typeahead index exists BEFORE node opens it (search-index.ts
#      memoizes a null handle forever if it's absent at first read). The search
#      index is the ONLY thing still on the /data volume — the app DB is Postgres.
#   3. Start the server (plain `node server.js`). Postgres durability is owned by
#      the managed database service, so there is no Litestream WAL shipping here.
#
# Env an operator sets on the Railway app service:
#   DATABASE_URL   postgres connection string (reference the Postgres service)
#   Index seed:    R2_ENDPOINT, R2_BUCKET, R2_KEY, R2_SECRET (+ optional
#                  R2_PREFIX; SEARCH_INDEX_REFRESH_HOURS to enable refresh)
set -e

# ── 1) schema sync (Postgres) ────────────────────────────────────────────────
echo "-> Syncing database schema (apply-schema.mjs -> Postgres)..."
node /app/deploy/apply-schema.mjs

# ── 2) search-index seed (blocking, NON-FATAL) ───────────────────────────────
# The seeder pulls data/search_index.sqlite onto the app volume, then RETURNS
# (it does not start the server). Non-fatal: a seed failure degrades to broken
# typeahead, never a boot failure — the next start / refresh cycle retries.
if [ -f /app/deploy/data-sync/entrypoint.app.sh ]; then
  echo "-> Seeding search index via deploy/data-sync/entrypoint.app.sh..."
  sh /app/deploy/data-sync/entrypoint.app.sh || \
    echo "!! WARNING: search-index seed failed (non-fatal) — typeahead may not work until seeded" >&2
elif [ -n "${SEARCH_INDEX_PATH:-}" ] && [ ! -f "${SEARCH_INDEX_PATH}" ]; then
  # No seeder in the image: keep the loud warning so the missing index is visible
  # (the Python spawn fallback does NOT exist in this image, so
  # /api/compbird/search errors until search_index.sqlite is on the volume).
  echo "!! WARNING: SEARCH_INDEX_PATH=${SEARCH_INDEX_PATH} does not exist and no" >&2
  echo "!! data-sync seeder is present — address typeahead will fail."           >&2
fi

# ── 3) start the server ──────────────────────────────────────────────────────
# Cap the Node old-space so a runaway request fails with an allocation error
# instead of OOM-killing the whole server process (proven on the sibling app).
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=1024}"
echo "-> Starting compbird on port ${PORT:-3000}..."
exec node server.js
