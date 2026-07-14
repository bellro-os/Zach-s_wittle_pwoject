#!/usr/bin/env bash
# pull_and_swap.sh - runs INSIDE the engine container (Railway service
# "engine"). One invocation = one sync cycle:
#
#   1. GET <R2_PREFIX>/manifest.json from the bucket (the push side uploads it
#      LAST, after every referenced object is fully uploaded, and objects live
#      at immutable content-addressed keys - so a manifest NEVER points at a
#      half-written object).
#   2. Diff the manifest against the locally-applied state
#      ($SYNC_STATE_DIR/applied.json). Nothing changed -> refresh the freshness
#      marker and exit 0 (a no-op cycle still proves the loop is alive).
#   3. Download each changed file into a tmp dir ON THE SAME FILESYSTEM as its
#      destination (DATA_DIR/.sync-tmp or OUTPUTS_DIR/.sync-tmp - both inside
#      the volume), verifying the manifest's sha256 while streaming.
#   4. VALIDATE every downloaded file (the exact bytes that will go live):
#        parquet -> python duckdb probe: COUNT(*) via read_parquet + a
#                   min-row floor (an accidentally-empty pool must never go live)
#        sqlite  -> python stdlib sqlite3 probe (open + schema read)
#        json    -> json.load
#        opaque  -> non-empty + pickle magic byte (joblib models; a full
#                   joblib.load happens at worker warm-up with the pinned sklearn)
#      ANY failure aborts the whole cycle BEFORE any rename - the live files
#      are untouched and the worker can never read a torn or garbage file.
#   5. Atomically activate: os.replace() (rename on the same fs) per file,
#      only after EVERY file in the batch validated.
#   6. Write the freshness marker: $DATA_DIR/.freshness - first line is the
#      manifest's generated_utc (see README "Staleness alerting"). Plus
#      machine-readable $SYNC_STATE_DIR/last_success.json / last_failure.json.
#
# The loop lives in entrypoint.sh (initial seed at boot + every
# SYNC_INTERVAL_MIN); this script is deliberately single-cycle so it can also
# be run by hand ("sync now") or from a dry-run harness.
#
# BLIND-ANCHOR CACHE (honest note): data/cma_blind_cache.json (env override
# CMA_BLIND_CACHE - blind_valuer.py:70) caches the LLM blind valuation per
# (subject signature, model, prompt version). Anchors do NOT auto-invalidate
# when the comp pool refreshes. That is BY DESIGN ("one anchor per subject"):
# profile == preview == generate must show one number, and tuned recomputes
# never pay a second LLM call. Consequence: a subject valued last week keeps
# folding last week's blind anchor into its ensemble after today's swap.
# CLEAR_BLIND_CACHE_ON_SWAP=1 deletes the cache whenever a comp-pool parquet is
# swapped. DEFAULT OFF. Tradeoffs of turning it ON:
#   + anchors re-read fresh comp evidence on each subject's next valuation
#   - every subject's next valuation pays a new Haiku call (cost + latency)
#   - a subject's displayed number can shift between visits with no user action
#   - the running worker memoizes anchors IN-PROCESS (_MEM, blind_valuer.py:75);
#     a disk clear alone is partial until the worker restarts
# The hygiene cache (cma_hygiene_cache.json) is content-hash-keyed - pool
# refreshes miss it naturally; it is never touched.
#
# CONFIG (all env; no arguments required):
#   R2_ENDPOINT   https://<accountid>.r2.cloudflarestorage.com   (required*)
#   R2_BUCKET     bucket name                                    (required*)
#   R2_KEY        access key id                                  (required*)
#   R2_SECRET     secret access key                              (required*)
#   R2_PREFIX     key prefix (default "engine-data")
#   R2_REGION     SigV4 region (default "auto" - R2's region string)
#   DATA_DIR      live data dir the engine reads   (default /app/data)
#   OUTPUTS_DIR   live outputs dir (model joblibs) (default /app/outputs)
#   SYNC_STATE_DIR         state + status dir (default $DATA_DIR/.sync)
#   SYNC_INCLUDE           optional comma/space list of rel-path prefixes to
#                          sync (e.g. "data/search_index.sqlite" for an
#                          app-side index puller); default = everything
#   SYNC_PROBE             full (default) | hash-only (skip open-probes where
#                          duckdb isn't installed; sha256 is still enforced)
#   SYNC_MIN_ROWS_MLS      row floor for mls_lookup.parquet (default: manifest kind)
#   SYNC_MIN_ROWS_PARCEL   row floor for parcel_lookup.parquet (ditto)
#   CLEAR_BLIND_CACHE_ON_SWAP  1 = clear blind cache when a pool parquet swaps
#                              (default 0 - see tradeoffs above)
#   CMA_BLIND_CACHE        path of the blind cache (engine also reads this)
#   PYTHON_BIN             python for probes/S3 (default python3, then python)
#
#   *not required with --local-source (dry-run mode).
#
# USAGE:
#   pull_and_swap.sh                      # one cycle against the bucket
#   pull_and_swap.sh --local-source DIR   # dry run: DIR holds the layout the
#                                         # push script's -LocalTarget wrote
#                                         # (objects/... + manifest.json)
#
# EXIT CODES: 0 = success (including no-op) | 1 = failure (nothing activated
# unless every file validated) | 78 = R2 config missing (sync disabled).

set -euo pipefail

LOCAL_SOURCE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --local-source) LOCAL_SOURCE="$2"; shift 2 ;;
    *) echo "[pull_and_swap] unknown arg: $1" >&2; exit 2 ;;
  esac
done

DATA_DIR="${DATA_DIR:-/app/data}"
OUTPUTS_DIR="${OUTPUTS_DIR:-/app/outputs}"
SYNC_STATE_DIR="${SYNC_STATE_DIR:-$DATA_DIR/.sync}"
R2_PREFIX="${R2_PREFIX:-engine-data}"
R2_REGION="${R2_REGION:-auto}"

if [ -z "$LOCAL_SOURCE" ]; then
  if [ -z "${R2_ENDPOINT:-}" ] || [ -z "${R2_BUCKET:-}" ] || [ -z "${R2_KEY:-}" ] || [ -z "${R2_SECRET:-}" ]; then
    echo "[pull_and_swap] R2_ENDPOINT/R2_BUCKET/R2_KEY/R2_SECRET not set - data sync disabled" >&2
    exit 78
  fi
fi

PY="${PYTHON_BIN:-}"
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then PY=python3
  elif command -v python >/dev/null 2>&1; then PY=python
  else echo "[pull_and_swap] no python available - failing closed (nothing activated)" >&2; exit 1
  fi
fi

mkdir -p "$DATA_DIR" "$OUTPUTS_DIR" "$SYNC_STATE_DIR"

# Everything correctness-critical (S3 SigV4 GET, sha256 streaming verify,
# probes, atomic os.replace batch swap, marker writes) lives in ONE python
# program so there is a single failure domain: it exits non-zero unless the
# cycle either fully applied or provably touched nothing.
exec "$PY" - "$LOCAL_SOURCE" <<'PULL_PY'
import hashlib, hmac, json, os, re, shutil, sqlite3, sys, tempfile, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

LOCAL_SOURCE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None

DATA_DIR    = Path(os.environ.get("DATA_DIR", "/app/data"))
OUTPUTS_DIR = Path(os.environ.get("OUTPUTS_DIR", "/app/outputs"))
STATE_DIR   = Path(os.environ.get("SYNC_STATE_DIR", str(DATA_DIR / ".sync")))
PREFIX      = os.environ.get("R2_PREFIX", "engine-data").strip("/")
REGION      = os.environ.get("R2_REGION", "auto")
ENDPOINT    = (os.environ.get("R2_ENDPOINT") or "").rstrip("/")
BUCKET      = os.environ.get("R2_BUCKET") or ""
ACCESS_KEY  = os.environ.get("R2_KEY") or ""
SECRET_KEY  = os.environ.get("R2_SECRET") or ""
PROBE_MODE  = os.environ.get("SYNC_PROBE", "full").strip().lower()
INCLUDE     = [t for t in re.split(r"[,\s]+", os.environ.get("SYNC_INCLUDE", "").strip()) if t]
CLEAR_BLIND = os.environ.get("CLEAR_BLIND_CACHE_ON_SWAP", "0").strip() == "1"

APPLIED_PATH  = STATE_DIR / "applied.json"
MARKER_PATH   = DATA_DIR / ".freshness"
SUCCESS_PATH  = STATE_DIR / "last_success.json"
FAILURE_PATH  = STATE_DIR / "last_failure.json"
REL_RE        = re.compile(r"^(data|outputs)/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
EMPTY_SHA     = hashlib.sha256(b"").hexdigest()

def log(msg):
    print(f"[pull_and_swap] {msg}", flush=True)

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fail(reason):
    log(f"FAIL: {reason}")
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        FAILURE_PATH.write_text(json.dumps({"ok": False, "ts": now_utc(), "error": str(reason)}) + "\n")
    except OSError:
        pass
    sys.exit(1)

# ── minimal S3 SigV4 client (stdlib only; R2 path-style) ─────────────────────
def _sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()

def s3_get(key, out_path=None, timeout=900):
    """GET s3://BUCKET/key. Returns bytes when out_path is None, else streams
    to out_path and returns the sha256 hex of what was written."""
    host = ENDPOINT.split("://", 1)[1]
    amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    datestamp = amz_date[:8]
    canonical_uri = f"/{BUCKET}/{key}"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical = "\n".join([
        "GET", canonical_uri, "",
        f"host:{host}", f"x-amz-content-sha256:{EMPTY_SHA}", f"x-amz-date:{amz_date}", "",
        signed_headers, EMPTY_SHA,
    ])
    scope = f"{datestamp}/{REGION}/s3/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                     hashlib.sha256(canonical.encode()).hexdigest()])
    k = _sign(_sign(_sign(_sign(("AWS4" + SECRET_KEY).encode(), datestamp), REGION), "s3"), "aws4_request")
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"{ENDPOINT}{canonical_uri}", headers={
        "x-amz-date": amz_date,
        "x-amz-content-sha256": EMPTY_SHA,
        "Authorization": (f"AWS4-HMAC-SHA256 Credential={ACCESS_KEY}/{scope}, "
                          f"SignedHeaders={signed_headers}, Signature={sig}"),
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if out_path is None:
            return resp.read()
        h = hashlib.sha256()
        with open(out_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                f.write(chunk)
        return h.hexdigest()

def fetch(key, out_path=None):
    """Bucket or --local-source. Local mode copies + hashes the same way.
    The push script's -LocalTarget writes the bucket layout WITHOUT the key
    prefix (the target dir IS the prefix root), so strip it here."""
    if LOCAL_SOURCE:
        rel_key = key[len(PREFIX) + 1:] if key.startswith(PREFIX + "/") else key
        src = Path(LOCAL_SOURCE) / rel_key
        if not src.is_file():
            raise FileNotFoundError(f"local source missing: {src}")
        if out_path is None:
            return src.read_bytes()
        h = hashlib.sha256()
        with open(src, "rb") as fi, open(out_path, "wb") as fo:
            while True:
                chunk = fi.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                fo.write(chunk)
        return h.hexdigest()
    last = None
    for attempt in (1, 2):  # one retry for transient network blips
        try:
            return s3_get(key, out_path)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            last = e
            if attempt == 1:
                log(f"  retrying {key} after error: {e}")
                time.sleep(5)
    raise last

# ── validation probes (fail closed) ──────────────────────────────────────────
def probe(path, kind):
    """Returns a detail string; raises on invalid. `kind`: parquet:<minrows> |
    sqlite | json | opaque. PROBE_MODE=hash-only skips the open-probes (the
    manifest sha256 was already enforced during download)."""
    if PROBE_MODE == "hash-only":
        return "hash-only"
    if kind.startswith("parquet"):
        min_rows = int(kind.split(":", 1)[1]) if ":" in kind else 1
        name = Path(path).name
        if name == "mls_lookup.parquet":
            min_rows = int(os.environ.get("SYNC_MIN_ROWS_MLS", min_rows))
        elif name == "parcel_lookup.parquet":
            min_rows = int(os.environ.get("SYNC_MIN_ROWS_PARCEL", min_rows))
        import duckdb  # fail closed if unavailable: the cycle aborts pre-swap
        n = duckdb.connect().execute(
            "SELECT COUNT(*) FROM read_parquet(?)", [str(path).replace("\\", "/")]
        ).fetchone()[0]
        if n < min_rows:
            raise ValueError(f"parquet opened but has {n} rows (< floor {min_rows})")
        return f"rows={n}"
    if kind == "sqlite":
        con = sqlite3.connect(path)
        try:
            con.execute("PRAGMA schema_version").fetchone()
            n = con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        finally:
            con.close()
        if n < 1:
            raise ValueError("sqlite opened but has no schema objects")
        return f"schema_objects={n}"
    if kind == "json":
        with open(path, "r", encoding="utf-8-sig") as f:
            json.load(f)
        return "json-ok"
    if kind == "opaque":
        size = os.path.getsize(path)
        if size == 0:
            raise ValueError("empty file")
        with open(path, "rb") as f:
            first = f.read(1)
        if first != b"\x80":  # joblib dumps are pickles; 0x80 = protocol marker
            raise ValueError(f"not a pickle (first byte {first!r})")
        return f"opaque-ok bytes={size}"
    raise ValueError(f"unknown kind {kind!r}")

# ── cycle ────────────────────────────────────────────────────────────────────
started = time.time()

try:
    manifest = json.loads(fetch(f"{PREFIX}/manifest.json").decode("utf-8-sig"))
except FileNotFoundError as e:
    fail(f"no manifest yet ({e}) - has the Windows push run once?")
except Exception as e:
    fail(f"cannot fetch manifest: {e}")

if manifest.get("version") != 1 or not isinstance(manifest.get("files"), list):
    fail(f"unrecognized manifest shape (version={manifest.get('version')!r})")
manifest_ts = manifest.get("generated_utc") or ""
if not manifest_ts:
    fail("manifest has no generated_utc")

files = []
for row in manifest["files"]:
    rel, key, sha, kind = row.get("rel"), row.get("key"), row.get("sha256"), row.get("kind", "opaque")
    if not (rel and key and sha):
        fail(f"manifest row incomplete: {row}")
    if not REL_RE.match(rel):  # path-traversal guard: rel decides local placement
        fail(f"manifest rel refused (unsafe path): {rel!r}")
    if INCLUDE and not any(rel == p or rel.startswith(p.rstrip("/") + "/") or rel.startswith(p) for p in INCLUDE):
        continue
    files.append({"rel": rel, "key": key, "sha256": sha.lower(), "kind": kind,
                  "bytes": row.get("bytes", 0)})

applied = {}
if APPLIED_PATH.is_file():
    try:
        applied = json.loads(APPLIED_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        log("applied-state unreadable - treating everything as changed")

def dest_for(rel):
    top, sub = rel.split("/", 1)
    return (DATA_DIR / sub) if top == "data" else (OUTPUTS_DIR / sub)

plan = [f for f in files
        if applied.get(f["rel"], {}).get("sha256") != f["sha256"] or not dest_for(f["rel"]).is_file()]

def write_marker(swapped_rels):
    # .freshness: line 1 = the manifest timestamp (THE staleness contract -
    # ops alerts on its AGE); rewritten every successful cycle so a no-op also
    # bumps mtime (= "loop alive").
    MARKER_PATH.write_text(manifest_ts + "\n")
    SUCCESS_PATH.write_text(json.dumps({
        "ok": True, "ts": now_utc(), "manifest_utc": manifest_ts,
        "files_swapped": swapped_rels, "duration_s": round(time.time() - started, 1),
    }) + "\n")

if not plan:
    write_marker([])
    log(f"up to date (manifest {manifest_ts}); marker refreshed")
    sys.exit(0)

log(f"manifest {manifest_ts}: {len(plan)} file(s) to fetch "
    f"({sum(f['bytes'] for f in plan) / 1e6:,.1f} MB)")

# tmp dirs INSIDE each destination root -> same filesystem -> os.replace is atomic
tmp_data = DATA_DIR / ".sync-tmp"
tmp_out  = OUTPUTS_DIR / ".sync-tmp"
for d in (tmp_data, tmp_out):
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)  # prune a crashed run's leftovers
    d.mkdir(parents=True, exist_ok=True)

staged = []  # (tmp_path, dest_path, file_row, detail)
try:
    for f in plan:
        dest = dest_for(f["rel"])
        tmp_root = tmp_data if f["rel"].startswith("data/") else tmp_out
        tmp = tmp_root / (f["rel"].replace("/", "__") + ".part")
        log(f"  fetching {f['rel']} ({f['bytes'] / 1e6:,.1f} MB)")
        try:
            got_sha = fetch(f["key"], tmp)
        except Exception as e:
            fail(f"download failed for {f['rel']}: {e} (live files untouched)")
        if got_sha != f["sha256"]:
            fail(f"sha256 mismatch for {f['rel']}: manifest {f['sha256'][:16]}… got {got_sha[:16]}… "
                 f"(torn/raced upload; live files untouched - next cycle retries)")
        try:
            detail = probe(tmp, f["kind"])
        except Exception as e:
            fail(f"validation rejected {f['rel']}: {e} (live files untouched)")
        staged.append((tmp, dest, f, detail))

    # every file validated -> activate the whole batch atomically (per-file
    # same-fs rename; nothing was renamed before this point)
    swapped = []
    for tmp, dest, f, detail in staged:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        log(f"  swapped {f['rel']} ({detail})")
        swapped.append(f["rel"])
        applied[f["rel"]] = {"sha256": f["sha256"], "key": f["key"], "applied_utc": now_utc()}
finally:
    for d in (tmp_data, tmp_out):
        shutil.rmtree(d, ignore_errors=True)

STATE_DIR.mkdir(parents=True, exist_ok=True)
APPLIED_PATH.write_text(json.dumps(applied, indent=1) + "\n")
write_marker(swapped)

# ── optional blind-anchor cache clear (default OFF - see header tradeoffs) ───
pool_changed = any(r.startswith("data/") and r.endswith(".parquet") for r in swapped)
if CLEAR_BLIND and pool_changed:
    cache = Path(os.environ.get("CMA_BLIND_CACHE", "").strip() or (DATA_DIR / "cma_blind_cache.json"))
    if cache.is_file():
        cache.unlink()
        log(f"  cleared blind-anchor cache {cache} (running worker keeps its in-process anchors until restart)")

log(f"done: {len(swapped)} file(s) activated in {round(time.time() - started, 1)}s "
    f"(manifest {manifest_ts})")
PULL_PY
