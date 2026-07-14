#!/bin/sh
# fallback-backup.sh — nightly SQLite snapshot fallback for the Railway app
# container. POSIX sh. USE LITESTREAM FIRST (deploy/ops/litestream.yml) — this
# script is the documented FALLBACK if Litestream is ever disabled or distrusted,
# and a belt-and-suspenders extra if you want both.
#
# What it does, in-container (Railway has no host cron — run it from a loop,
# see deploy/ops/README.md "Fallback"):
#   1. consistent copy of the app DB via the SQLite online-backup API
#      (a plain cp of a WAL-mode DB under writes is NOT safe),
#   2. integrity_check on the snapshot (a corrupt backup is worse than none),
#   3. gzip + rotate: keep the newest $KEEP locally under $BACKUP_DIR
#      (on the SAME volume — survives redeploys, NOT volume loss; pair with
#      Railway's native volume backups and/or the R2 upload below),
#   4. optional off-volume upload to R2 via `curl --aws-sigv4` (no SDK needed;
#      curl >= 7.75). Falls back to `aws` / `mc` if curl is absent but those
#      exist. No uploader available => WARN, local snapshot still kept.
#
# Tooling note for the app image (node:20-slim has neither sqlite3 nor curl):
# either apt-get install sqlite3 + curl in Dockerfile.app (2 small packages),
# or rely on the built-in fallbacks — the snapshot step falls back to node +
# better-sqlite3 (already in the image), and the upload step is skipped unless
# curl/aws/mc exists. The engine image (python:3.12-slim) covers everything
# via python3 except upload, same caveat.
#
# Env:
#   DB_PATH      /data/compbird.db (or $LITESTREAM_DB_PATH)   source DB
#   BACKUP_DIR   /data/backups                                local snapshots
#   KEEP         7                                            local rotation
#   R2_BUCKET    (unset = no upload)   R2_ENDPOINT  <acct>.r2.cloudflarestorage.com
#   R2_PREFIX    compbird/fallback     R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY
#                (remote objects are never pruned here — set an R2 lifecycle
#                 rule on the prefix, e.g. expire after 30 days)
set -eu

DB_PATH="${DB_PATH:-${LITESTREAM_DB_PATH:-/data/compbird.db}}"
BACKUP_DIR="${BACKUP_DIR:-/data/backups}"
KEEP="${KEEP:-7}"
R2_BUCKET="${R2_BUCKET:-}"
R2_ENDPOINT="${R2_ENDPOINT:-}"
R2_PREFIX="${R2_PREFIX:-compbird/fallback}"
R2_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:-}"
R2_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:-}"

log() { printf '%s fallback-backup: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[ -f "$DB_PATH" ] || die "no database at DB_PATH=$DB_PATH"
mkdir -p "$BACKUP_DIR"

TS="$(date +%Y%m%d-%H%M%S)"
SNAP="$BACKUP_DIR/compbird-$TS.db"

# ── 1+2. consistent snapshot + integrity check (sqlite3 | python | node) ─────
snapshot_ok=0
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB_PATH" ".backup '$SNAP'"
  IC="$(sqlite3 "$SNAP" 'PRAGMA integrity_check;')"
  [ "$IC" = "ok" ] || { rm -f "$SNAP"; die "integrity_check on fresh snapshot: $IC"; }
  snapshot_ok=1
fi
if [ "$snapshot_ok" = "0" ]; then
  for p in python3 python; do
    command -v "$p" >/dev/null 2>&1 || continue
    "$p" -c "import sqlite3" >/dev/null 2>&1 || continue
    "$p" -c '
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
ic = sqlite3.connect(sys.argv[2]).execute("PRAGMA integrity_check").fetchone()[0]
print("integrity:", ic)
sys.exit(0 if ic == "ok" else 1)
' "$DB_PATH" "$SNAP" || { rm -f "$SNAP"; die "python snapshot/integrity failed"; }
    snapshot_ok=1
    break
  done
fi
if [ "$snapshot_ok" = "0" ] && command -v node >/dev/null 2>&1; then
  NODE_PATH="${NODE_PATH:-/app/node_modules}" node -e '
const D = require("better-sqlite3");
const db = new D(process.argv[1], { readonly: true, fileMustExist: true });
db.backup(process.argv[2]).then(() => {
  const ic = new D(process.argv[2], { readonly: true })
    .prepare("PRAGMA integrity_check").get().integrity_check;
  console.log("integrity:", ic);
  process.exit(ic === "ok" ? 0 : 1);
}).catch((e) => { console.error(e); process.exit(1); });
' "$DB_PATH" "$SNAP" || { rm -f "$SNAP"; die "node snapshot/integrity failed"; }
  snapshot_ok=1
fi
[ "$snapshot_ok" = "1" ] || die "no snapshot tool available (need sqlite3, python, or node+better-sqlite3)"
log "snapshot ok -> $SNAP"

# ── 3. gzip + local rotation ──────────────────────────────────────────────────
gzip -f "$SNAP"
SNAP="$SNAP.gz"
# newest first; drop everything after the KEEP-th
ls -1t "$BACKUP_DIR"/compbird-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" \
  | while IFS= read -r f; do log "pruning $f"; rm -f "$f"; done

# ── 4. optional off-volume upload to R2 ──────────────────────────────────────
if [ -n "$R2_BUCKET" ]; then
  [ -n "$R2_ENDPOINT" ] && [ -n "$R2_ACCESS_KEY_ID" ] && [ -n "$R2_SECRET_ACCESS_KEY" ] \
    || die "R2_BUCKET set but R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY incomplete"
  KEY="$R2_PREFIX/compbird-$TS.db.gz"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --aws-sigv4 "aws:amz:auto:s3" \
      --user "$R2_ACCESS_KEY_ID:$R2_SECRET_ACCESS_KEY" \
      --upload-file "$SNAP" "https://$R2_ENDPOINT/$R2_BUCKET/$KEY" \
      || die "R2 upload failed (local snapshot intact at $SNAP)"
    log "uploaded -> s3://$R2_BUCKET/$KEY"
  elif command -v aws >/dev/null 2>&1; then
    AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
      aws s3 cp "$SNAP" "s3://$R2_BUCKET/$KEY" --endpoint-url "https://$R2_ENDPOINT" \
      || die "R2 upload failed (local snapshot intact at $SNAP)"
    log "uploaded -> s3://$R2_BUCKET/$KEY"
  elif command -v mc >/dev/null 2>&1; then
    mc alias set r2fallback "https://$R2_ENDPOINT" "$R2_ACCESS_KEY_ID" "$R2_SECRET_ACCESS_KEY" >/dev/null
    mc cp "$SNAP" "r2fallback/$R2_BUCKET/$KEY" \
      || die "R2 upload failed (local snapshot intact at $SNAP)"
    log "uploaded -> s3://$R2_BUCKET/$KEY"
  else
    log "WARN: R2_BUCKET set but no curl/aws/mc in this image — snapshot is LOCAL ONLY (add curl to the image for uploads)"
  fi
else
  log "R2_BUCKET unset — local snapshot only (same volume; pair with Railway volume backups)"
fi

log "done"
