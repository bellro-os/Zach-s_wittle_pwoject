#!/bin/sh
set -e

# Compbird has NO prisma/migrations history — the repo's dev flow is `prisma db
# push` (see package.json db:push). Mirroring that here syncs the schema onto
# the volume-mounted SQLite (creates /data/compbird.db on first boot).
# --skip-generate: the client was generated at image build; regenerating at
# runtime would try to write into the read-only image layers.
echo "-> Syncing database schema (prisma db push)..."
CHECKPOINT_DISABLE=1 node node_modules/prisma/build/index.js db push \
  --skip-generate --schema prisma/schema.prisma

echo "-> Starting compbird on port ${PORT:-3000}..."
# Cap the Node old-space so a runaway request fails with an allocation error
# instead of OOM-killing the whole server process (proven on the sibling app).
export NODE_OPTIONS="--max-old-space-size=1024"
exec node server.js
