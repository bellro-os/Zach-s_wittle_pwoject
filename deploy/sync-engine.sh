#!/usr/bin/env bash
# Re-mirror the MLS Bot CMA engine into this repo's engine/ directory.
#
# The engine is a VENDORED COPY (see engine/.vendored-from). It is developed in
# the MLS Bot repo; this copies its git-tracked files (code only, via
# `git archive` — never data/models/.env/caches) into engine/. The certified
# accuracy depends on the vendored code matching the tested engine byte-for-byte,
# so ALWAYS edit in MLS Bot and re-sync here rather than hand-editing engine/.
#
# Usage: bash deploy/sync-engine.sh [ENGINE_REPO_PATH]
set -euo pipefail

ENGINE_REPO="${1:-/c/Users/zach/Desktop/MLS Bot}"
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_DIR="$APP_ROOT/engine"

[ -d "$ENGINE_REPO/.git" ] || { echo "Not a git repo: $ENGINE_REPO" >&2; exit 1; }

HEAD="$(git -C "$ENGINE_REPO" rev-parse HEAD)"
BRANCH="$(git -C "$ENGINE_REPO" rev-parse --abbrev-ref HEAD)"
if [ -n "$(git -C "$ENGINE_REPO" status --porcelain)" ]; then
  echo "WARNING: MLS Bot has uncommitted changes — git archive vendors HEAD only. Commit first if you want them." >&2
fi

echo "Vendoring engine @ $HEAD ($BRANCH) ..."
TMP="$(mktemp -d)"
git -C "$ENGINE_REPO" archive HEAD | tar -x -C "$TMP"
rm -rf "$ENGINE_DIR"
mv "$TMP" "$ENGINE_DIR"

cat > "$ENGINE_DIR/.vendored-from" <<EOF
This engine/ directory is a VENDORED COPY of the MLS Bot CMA engine.

Canonical source repo: MLS Bot  (branch $BRANCH)
Vendored at commit:     $HEAD
Vendored on:            $(date +%Y-%m-%d 2>/dev/null || echo unknown)

It contains only git-tracked code (via \`git archive\`) — never data
(*.parquet/*.jsonl), models, caches, or .env. Production data reaches the
running engine via the R2 object-storage sync (see deploy/data-sync/), not
this directory.

To refresh this copy after engine changes, run from the app repo root:
    pwsh deploy/sync-engine.ps1        # or: bash deploy/sync-engine.sh

That re-mirrors the engine repo's tracked files here and re-stamps this file.
Do NOT hand-edit engine code here — edit it in the MLS Bot repo and re-sync,
so the two copies cannot silently drift (the certified accuracy depends on
the engine being byte-for-byte the tested code).
EOF

echo "Done. engine/ now holds $(find "$ENGINE_DIR" -type f | wc -l) files from $HEAD."
echo "Review + commit:  git add engine && git commit -m 'Sync engine to ${HEAD:0:10}'"
