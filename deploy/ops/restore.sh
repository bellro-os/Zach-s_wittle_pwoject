#!/bin/sh
# restore.sh — restore the Compbird SQLite DB from its Litestream replica, then
# integrity-check it and print per-table row counts. POSIX sh.
#
# Runs INSIDE the Railway app container (baked in as /usr/local/bin/compbird-restore
# by the Dockerfile block in deploy/ops/README.md) or anywhere a litestream
# binary + the replica are reachable (the local restore DRILL uses a file://
# style replica via a drill config — see README "Restore drill").
#
# Usage:
#   restore.sh [-o OUTPUT_DB] [DB_PATH | REPLICA_URL]
#       Restores the newest backup. DB_PATH (default: $LITESTREAM_DB_PATH or
#       /data/compbird.db) is looked up in the litestream config; passing an
#       s3://... REPLICA_URL instead bypasses the config (creds via env).
#       OUTPUT_DB defaults to the DB path itself — i.e. restore-in-place.
#
#   restore.sh --counts DB
#       No restore: just integrity-check DB and print its per-table row counts
#       (the drill diffs this output between source and restored copies).
#
# Safety:
#   - refuses to overwrite an existing output unless FORCE=1;
#   - with FORCE=1 the live file is MOVED ASIDE to <out>.pre-restore.<ts>
#     first (nothing is destroyed) and stale -wal/-shm sidecars are removed;
#   - the restored DB is integrity-checked and counted before we call it done.
#
# Point-in-time: pass extra litestream args through LITESTREAM_RESTORE_ARGS,
# e.g. LITESTREAM_RESTORE_ARGS="-timestamp 2026-07-14T04:00:00Z".
#
# Env: LITESTREAM_BIN (default litestream), LITESTREAM_CONFIG (default
#      /etc/litestream.yml), LITESTREAM_DB_PATH, FORCE (default 0),
#      LITESTREAM_RESTORE_ARGS (default empty).
set -eu

LITESTREAM_BIN="${LITESTREAM_BIN:-litestream}"
LITESTREAM_CONFIG="${LITESTREAM_CONFIG:-/etc/litestream.yml}"
FORCE="${FORCE:-0}"

log() { printf '%s restore: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

# ── verification helpers ──────────────────────────────────────────────────────
# Tool chain: sqlite3 CLI -> python3 -> python -> node(better-sqlite3). Covers
# the app container (node + better-sqlite3, no python), the engine container
# (python3, no sqlite3 CLI) and a dev box. Interpreters are probed with a real
# import so Windows Store "python3" aliases don't false-positive.

PY_COUNT_SNIPPET='
import sqlite3, sys
db = sys.argv[1]
con = sqlite3.connect(db)
print("integrity:", con.execute("PRAGMA integrity_check").fetchone()[0])
total = 0
q = "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE ? ORDER BY name"
for (t,) in con.execute(q, ("table", "sqlite_%")):
    n = con.execute("SELECT count(*) FROM \"%s\"" % t.replace("\"", "\"\"")).fetchone()[0]
    total += n
    print("%s: %d" % (t, n))
print("TOTAL: %d" % total)
'

NODE_COUNT_SNIPPET='
const D = require("better-sqlite3");
const db = new D(process.argv[1], { readonly: true, fileMustExist: true });
console.log("integrity:", db.prepare("PRAGMA integrity_check").get().integrity_check);
let total = 0;
const q = "SELECT name FROM sqlite_master WHERE type=@t AND name NOT LIKE @p ORDER BY name";
for (const { name } of db.prepare(q).all({ t: "table", p: "sqlite_%" })) {
  const n = db.prepare(`SELECT count(*) c FROM "${name.replace(/"/g, "\"\"")}"`).get().c;
  total += n;
  console.log(`${name}: ${n}`);
}
console.log("TOTAL: " + total);
'

pick_python() {
  for p in python3 python; do
    command -v "$p" >/dev/null 2>&1 || continue
    "$p" -c "import sqlite3" >/dev/null 2>&1 || continue
    printf '%s' "$p"
    return 0
  done
  return 1
}

counts() { # counts <db> — integrity + per-table rows + TOTAL, stable ordering
  db="$1"
  [ -f "$db" ] || die "no database at $db"

  if command -v sqlite3 >/dev/null 2>&1; then
    printf 'integrity: %s\n' "$(sqlite3 "$db" 'PRAGMA integrity_check;')"
    total=0
    # NOTE: word-splits table names; Prisma names contain no whitespace.
    for t in $(sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"); do
      n="$(sqlite3 "$db" "SELECT count(*) FROM \"$t\";")"
      printf '%s: %s\n' "$t" "$n"
      total=$((total + n))
    done
    printf 'TOTAL: %s\n' "$total"
    return 0
  fi

  if PY="$(pick_python)"; then
    "$PY" -c "$PY_COUNT_SNIPPET" "$db"
    return 0
  fi

  if command -v node >/dev/null 2>&1; then
    # App container: better-sqlite3 ships in the standalone node_modules.
    NODE_PATH="${NODE_PATH:-/app/node_modules}" node -e "$NODE_COUNT_SNIPPET" "$db" \
      && return 0
  fi

  log "WARN: no sqlite3/python/node(better-sqlite3) available — restored file NOT verified"
  return 1
}

# ── arg parsing ───────────────────────────────────────────────────────────────
MODE=restore
OUT=""
SRC=""
while [ $# -gt 0 ]; do
  case "$1" in
    --counts) MODE=counts; shift ;;
    -o)       OUT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    -*) die "unknown flag: $1 (see --help)" ;;
    *)  SRC="$1"; shift ;;
  esac
done

if [ "$MODE" = "counts" ]; then
  [ -n "$SRC" ] || die "usage: restore.sh --counts <db>"
  counts "$SRC"
  exit 0
fi

DB_DEFAULT="${LITESTREAM_DB_PATH:-/data/compbird.db}"
SRC="${SRC:-$DB_DEFAULT}"
case "$SRC" in
  *://*) OUT="${OUT:-$DB_DEFAULT}" ;; # replica URL: config not consulted
  *)     OUT="${OUT:-$SRC}" ;;
esac

command -v "$LITESTREAM_BIN" >/dev/null 2>&1 \
  || die "litestream binary not found (LITESTREAM_BIN=$LITESTREAM_BIN)"

# ── never clobber silently ────────────────────────────────────────────────────
if [ -e "$OUT" ]; then
  [ "$FORCE" = "1" ] \
    || die "output $OUT exists. STOP writes first (Railway: scale/redeploy after), then re-run with FORCE=1 — the current file will be kept as a .pre-restore copy."
  PRE="$OUT.pre-restore.$(date +%Y%m%d-%H%M%S)"
  mv "$OUT" "$PRE"
  rm -f "$OUT-wal" "$OUT-shm" # sidecars belong to the OLD db; leaving them corrupts the new one
  log "live db moved aside -> $PRE"
fi
mkdir -p "$(dirname "$OUT")"

# ── restore ───────────────────────────────────────────────────────────────────
log "restoring '$SRC' -> $OUT"
# LITESTREAM_RESTORE_ARGS is intentionally unquoted: it carries extra flags
# (e.g. -timestamp <ts>). Flags contain no spaces beyond separators.
# shellcheck disable=SC2086
case "$SRC" in
  *://*) "$LITESTREAM_BIN" restore ${LITESTREAM_RESTORE_ARGS:-} -o "$OUT" "$SRC" ;;
  *)     "$LITESTREAM_BIN" restore -config "$LITESTREAM_CONFIG" ${LITESTREAM_RESTORE_ARGS:-} -o "$OUT" "$SRC" ;;
esac
[ -f "$OUT" ] || die "litestream restore completed but produced no file at $OUT"

# ── verify ────────────────────────────────────────────────────────────────────
counts "$OUT" || true
log "restored -> $OUT"
log "next: restart the app service so it reopens the DB (railway redeploy --service app),"
log "      then point LITESTREAM_REPLICA_URL at a FRESH prefix so the old lineage stays intact,"
log "      then GET /api/health and expect {\"ok\":true}"
