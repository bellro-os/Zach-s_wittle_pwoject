#!/bin/sh
# Compbird app container boot (Railway). PID-1 sequence — ORDER IS LOAD-BEARING:
#   1. Litestream RESTORE (only if LITESTREAM_REPLICA_URL is set): pull the
#      newest backup onto a FRESH volume BEFORE prisma db push. This must run
#      first — `prisma db push` on an empty volume CREATES an empty DB, after
#      which `restore -if-db-not-exists` no-ops forever and the backup is never
#      recovered. No-ops harmlessly when the DB already exists or the replica is
#      empty (normal first-ever launch).
#   2. prisma db push — sync the schema onto the volume-mounted SQLite (creates
#      $DATABASE_URL's file on a truly fresh volume). The repo has NO
#      prisma/migrations history — dev flow is `prisma db push` (package.json
#      db:push), so boot mirrors it. --skip-generate: client generated at build.
#   3. SEARCH-INDEX SEED — call deploy/data-sync/entrypoint.app.sh (blocking,
#      NON-FATAL). It pulls ONLY data/search_index.sqlite onto the app volume so
#      the ~1.1 GB typeahead index exists BEFORE node opens it (search-index.ts
#      memoizes a null handle forever if it's absent at first read). NEW
#      CONTRACT: the seeder RETURNS — it does NOT start the server. This replaces
#      the old "hand off to the hook and let it exec node server.js" seam.
#   4. Start the server. Under Litestream when LITESTREAM_REPLICA_URL is set
#      (`litestream replicate -exec "node server.js"` streams every WAL frame to
#      R2 and exits when node exits); otherwise plain `node server.js` with a
#      loud WARN. Both paths require the litestream binary; a litestream-less
#      local image still boots (plain node) because the start is guarded on
#      `command -v litestream`.
#
# Env an operator sets on the Railway app service (see deploy/ops/README.md §1
# + ops.env.example, and deploy/data-sync/README.md for the R2_* names):
#   Litestream:  LITESTREAM_REPLICA_URL, LITESTREAM_ACCESS_KEY_ID,
#                LITESTREAM_SECRET_ACCESS_KEY  (+ LITESTREAM_DB_PATH, defaulted
#                below to /data/compbird.db = DATABASE_URL's file: path)
#   Index seed:  R2_ENDPOINT, R2_BUCKET, R2_KEY, R2_SECRET (+ optional
#                R2_PREFIX; SEARCH_INDEX_REFRESH_HOURS to enable refresh)
set -e

: "${LITESTREAM_DB_PATH:=/data/compbird.db}"; export LITESTREAM_DB_PATH

# ── 1) Litestream restore (before prisma db push — see header) ───────────────
if command -v litestream >/dev/null 2>&1 && [ -n "${LITESTREAM_REPLICA_URL:-}" ]; then
  echo "-> Litestream: restoring DB if missing (disaster recovery / fresh volume)..."
  litestream restore -if-db-not-exists -if-replica-exists \
    -config /etc/litestream.yml "$LITESTREAM_DB_PATH"
fi

# ── 2) schema sync ───────────────────────────────────────────────────────────
# Apply the build-generated prisma/schema.sql with better-sqlite3 (a guaranteed
# runtime dep) rather than the Prisma CLI, whose transitive closure (effect/c12/
# @prisma/config) is absent from Next's standalone trace and crash-looped boot
# with "Cannot find module 'effect'". Idempotent; see deploy/apply-schema.mjs.
echo "-> Syncing database schema (apply-schema.mjs)..."
node /app/deploy/apply-schema.mjs

# ── 3) search-index seed (blocking, NON-FATAL) ───────────────────────────────
# The seeder pulls data/search_index.sqlite onto the app volume, then RETURNS
# (it does not start the server). Non-fatal: a seed failure degrades to broken
# typeahead, never a boot failure — the next start / refresh cycle retries.
if [ -f /app/deploy/data-sync/entrypoint.app.sh ]; then
  echo "-> Seeding search index via deploy/data-sync/entrypoint.app.sh..."
  sh /app/deploy/data-sync/entrypoint.app.sh || \
    echo "!! WARNING: search-index seed failed (non-fatal) — typeahead may not work until seeded" >&2
elif [ -n "${SEARCH_INDEX_PATH:-}" ] && [ ! -f "${SEARCH_INDEX_PATH}" ]; then
  # No seeder in the image: keep the old loud warning so the missing index is
  # visible in logs (the Python spawn fallback does NOT exist in this image, so
  # /api/compbird/search will error until search_index.sqlite is on the volume).
  echo "!! WARNING: SEARCH_INDEX_PATH=${SEARCH_INDEX_PATH} does not exist and no" >&2
  echo "!! data-sync seeder is present — address typeahead will fail."           >&2
fi

# ── 4) start the server ──────────────────────────────────────────────────────
# Cap the Node old-space so a runaway request fails with an allocation error
# instead of OOM-killing the whole server process (proven on the sibling app).
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=1024}"

if command -v litestream >/dev/null 2>&1 && [ -n "${LITESTREAM_REPLICA_URL:-}" ]; then
  echo "-> Starting compbird under litestream replication (port ${PORT:-3000})..."
  exec litestream replicate -config /etc/litestream.yml -exec "node server.js"
fi

if [ -n "${LITESTREAM_REPLICA_URL:-}" ]; then
  echo "!! WARNING: LITESTREAM_REPLICA_URL set but litestream binary not found — running WITHOUT continuous DB backup" >&2
else
  echo "!! WARNING: LITESTREAM_REPLICA_URL unset — running WITHOUT continuous DB backup" >&2
fi
echo "-> Starting compbird on port ${PORT:-3000}..."
exec node server.js
