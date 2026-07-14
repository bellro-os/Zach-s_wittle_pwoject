#!/bin/sh
# Compbird app container boot (Railway). PID-1 sequence:
#   1. prisma db push — sync the schema onto the volume-mounted SQLite
#      (creates $DATABASE_URL's file on a FRESH volume's first boot). The repo
#      has NO prisma/migrations history — dev flow is `prisma db push`
#      (package.json db:push), so boot mirrors it. --skip-generate: the client
#      was generated at image build.
#   2. Optional data-sync hook — if the data-sync kit shipped an app-side boot
#      script (search-index seed/refresh), hand off to it. CONTRACT: the hook
#      owns the rest of boot and MUST end with `exec node /app/server.js`.
#   3. Otherwise start the standalone server directly.
set -e

echo "-> Syncing database schema (prisma db push)..."
CHECKPOINT_DISABLE=1 node node_modules/prisma/build/index.js db push \
  --skip-generate --schema prisma/schema.prisma

# Loud, non-fatal warning when the typeahead index is absent: the Python spawn
# fallback does NOT exist in this image, so /api/compbird/search will error
# until the index lands on the volume (see deploy/README.md "First data seed").
if [ -n "${SEARCH_INDEX_PATH:-}" ] && [ ! -f "${SEARCH_INDEX_PATH}" ]; then
  echo "!! WARNING: SEARCH_INDEX_PATH=${SEARCH_INDEX_PATH} does not exist —" >&2
  echo "!! address typeahead will fail until search_index.sqlite is seeded."  >&2
fi

# Seam for deploy/data-sync (owned by the data-sync kit): app-side puller /
# index refresher. Executed INSTEAD of the plain server start when present.
if [ -f /app/deploy/data-sync/entrypoint.app.sh ]; then
  echo "-> Handing off to deploy/data-sync/entrypoint.app.sh"
  exec sh /app/deploy/data-sync/entrypoint.app.sh
fi

echo "-> Starting compbird on port ${PORT:-3000}..."
# Cap the Node old-space so a runaway request fails with an allocation error
# instead of OOM-killing the whole server process (proven on the sibling app).
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=1024}"
exec node server.js
