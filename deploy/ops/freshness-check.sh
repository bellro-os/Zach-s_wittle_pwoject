#!/bin/sh
# freshness-check.sh — MLS-data freshness watchdog for the ENGINE container.
# POSIX sh, zero dependencies beyond coreutils + (curl OR python3 — the engine
# image is python:3.12-slim, so the python transport is the one that runs
# in production; curl is used when present, e.g. on a dev box).
#
# WHY: the app's UI stamps "MLS data — refreshed hourly". The chain that keeps
# that true is: Windows Task Scheduler (mls-hourly) -> R2 push -> the engine
# container's data-sync pull loop -> atomic swap -> `touch $DATA_DIR/.freshness`.
# If ANY link stalls, the marker's mtime stops advancing. This script turns
# that into a webhook page.
#
# CALL IT ONCE PER LOOP ITERATION from the data-sync pull loop (Railway has no
# host cron — periodic work lives inside the container):
#
#     while :; do
#       pull_and_swap && touch "$DATA_DIR/.freshness"
#       /app/deploy/ops/freshness-check.sh || true   # never kill the loop
#       sleep 300
#     done
#
# Behavior:
#   fresh  -> exit 0, one stdout log line, NO webhook. If PING_URL is set, a
#             dead-man ping is sent (healthchecks.io-style): the ping STOPPING
#             is itself an alert, which covers "engine container died" without
#             exposing the engine publicly.
#   stale  -> exit 1 + ONE webhook per COOLDOWN_MIN while it stays stale
#             (+ PING_URL/fail every cycle if set). Missing marker counts as
#             stale (the puller has never succeeded).
#   recovery -> one RECOVERED webhook, state cleared.
#
# Webhook is generic: Slack / Discord / ntfy compatible (WEBHOOK_FORMAT=auto
# sniffs the URL; override with slack|discord|text).
#
# Env (all optional):
#   DATA_DIR                 /app/data      dir the marker lives in
#   FRESHNESS_MARKER         $DATA_DIR/.freshness
#   FRESHNESS_MAX_AGE_MIN    120            page when older than this
#   WEBHOOK_URL              (unset = stdout only — fine for dry runs,
#                             useless for 3am pages; set it before launch)
#   WEBHOOK_FORMAT           auto | slack | discord | text
#   PING_URL                 healthchecks.io check URL (dead-man ping)
#   COOLDOWN_MIN             30             re-alert cadence while stale
#   STATE_DIR                /tmp/compbird-ops   (ephemeral: a container
#                             restart may repeat one alert — acceptable)
#   HOST_LABEL               compbird-engine     tag inside messages
#   HTTP_TOOL                auto | curl | python   (transport override)
set -u

DATA_DIR="${DATA_DIR:-/app/data}"
MARKER="${FRESHNESS_MARKER:-$DATA_DIR/.freshness}"
MAX_MIN="${FRESHNESS_MAX_AGE_MIN:-120}"
WEBHOOK_URL="${WEBHOOK_URL:-}"
WEBHOOK_FORMAT="${WEBHOOK_FORMAT:-auto}"
PING_URL="${PING_URL:-}"
COOLDOWN_MIN="${COOLDOWN_MIN:-30}"
STATE_DIR="${STATE_DIR:-/tmp/compbird-ops}"
HOST_LABEL="${HOST_LABEL:-compbird-engine}"
HTTP_TOOL="${HTTP_TOOL:-auto}"

STATE_FILE="$STATE_DIR/freshness.down"

log() { printf '%s freshness: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

# ── transport: curl if present, else python3/python (engine image path) ──────
pick_python() {
  for p in python3 python; do
    command -v "$p" >/dev/null 2>&1 || continue
    "$p" -c "import urllib.request" >/dev/null 2>&1 || continue
    printf '%s' "$p"
    return 0
  done
  return 1
}

http_post() { # http_post <url> <content-type> <body>; rc!=0 on failure, never fatal
  _url="$1"; _ct="$2"; _body="$3"
  if [ "$HTTP_TOOL" != "python" ] && command -v curl >/dev/null 2>&1; then
    curl -fsS -m 10 -o /dev/null -X POST -H "Content-Type: $_ct" \
      --data-binary "$_body" "$_url"
    return $?
  fi
  if _py="$(pick_python)"; then
    FRESH_URL="$_url" FRESH_CT="$_ct" FRESH_BODY="$_body" "$_py" -c '
import os, sys, urllib.request
req = urllib.request.Request(
    os.environ["FRESH_URL"],
    data=os.environ["FRESH_BODY"].encode("utf-8"),
    headers={"Content-Type": os.environ["FRESH_CT"]},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=10).read()
except Exception as e:
    sys.exit("post failed: %s" % e)
'
    return $?
  fi
  log "WARN: neither curl nor python available — cannot POST"
  return 1
}

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

send_webhook() { # send_webhook <message>
  _msg="$1"
  log "$_msg"
  [ -n "$WEBHOOK_URL" ] || { log "WEBHOOK_URL unset — stdout only"; return 0; }
  _fmt="$WEBHOOK_FORMAT"
  if [ "$_fmt" = "auto" ]; then
    case "$WEBHOOK_URL" in
      *hooks.slack.com*)                                        _fmt=slack ;;
      *discord.com/api/webhooks*|*discordapp.com/api/webhooks*) _fmt=discord ;;
      *)                                                        _fmt=text ;;
    esac
  fi
  _esc="$(json_escape "$_msg")"
  case "$_fmt" in
    slack)   http_post "$WEBHOOK_URL" "application/json" "{\"text\": \"$_esc\"}" ;;
    discord) http_post "$WEBHOOK_URL" "application/json" "{\"content\": \"$_esc\"}" ;;
    *)       http_post "$WEBHOOK_URL" "text/plain" "$_msg" ;;
  esac || log "WARN: webhook POST failed (alert above is stdout-only)"
}

ping_hc() { # ping_hc <suffix> <body> — healthchecks.io dead-man ping, best-effort
  [ -n "$PING_URL" ] || return 0
  http_post "$PING_URL$1" "text/plain" "$2" || log "WARN: PING_URL ping failed"
}

# ── measure marker age ────────────────────────────────────────────────────────
mkdir -p "$STATE_DIR"
NOW="$(date +%s)"
AGE_MIN=""
if [ -f "$MARKER" ]; then
  MTIME="$(stat -c %Y "$MARKER" 2>/dev/null || date -r "$MARKER" +%s)"
  AGE_MIN=$(( (NOW - MTIME) / 60 ))
fi

if [ -z "$AGE_MIN" ]; then
  STALE=1
  DETAIL="marker $MARKER does not exist - the data-sync puller has never succeeded in this container"
elif [ "$AGE_MIN" -gt "$MAX_MIN" ]; then
  STALE=1
  DETAIL="marker is ${AGE_MIN}min old (max ${MAX_MIN}min)"
else
  STALE=0
fi

# ── act ───────────────────────────────────────────────────────────────────────
if [ "$STALE" = "1" ]; then
  ping_hc "/fail" "stale: $DETAIL"
  LAST=0
  [ -f "$STATE_FILE" ] && LAST="$(cat "$STATE_FILE" 2>/dev/null || echo 0)"
  case "$LAST" in *[!0-9]*|"") LAST=0 ;; esac
  if [ $(( NOW - LAST )) -ge $(( COOLDOWN_MIN * 60 )) ]; then
    # Webhook text stays pure ASCII: non-ASCII punctuation mojibakes on some
    # transport/locale combos (verified with the Windows curl in the drill).
    send_webhook "ALERT [$HOST_LABEL] MLS data is STALE: $DETAIL. The hourly refresh -> R2 -> pull chain has stopped; the app's 'MLS data refreshed hourly' stamp is currently FALSE. Check: the Windows mls-hourly task, the R2 push, and this container's pull loop (railway logs --service engine)."
    printf '%s\n' "$NOW" > "$STATE_FILE"
  else
    log "still stale ($DETAIL) — within ${COOLDOWN_MIN}min cooldown, not re-alerting"
  fi
  exit 1
fi

ping_hc "" "fresh: marker ${AGE_MIN}min old"
if [ -f "$STATE_FILE" ]; then
  send_webhook "RECOVERED [$HOST_LABEL] MLS data is fresh again (marker ${AGE_MIN}min old, max ${MAX_MIN}min)."
  rm -f "$STATE_FILE"
fi
log "fresh: marker ${AGE_MIN}min old (max ${MAX_MIN}min)"
exit 0
