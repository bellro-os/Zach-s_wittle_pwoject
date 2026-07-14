# push_prod_data.ps1 - ship the CMA engine's data files to S3-compatible object
# storage (Cloudflare R2) after each hourly refresh. RAILWAY EDITION: there is
# NO SSH into a Railway service, so the pipeline is push -> bucket -> the
# engine container's own puller (Compbird/deploy/data-sync/pull_and_swap.sh)
# fetches + validates + atomically swaps every N minutes.
#
# Runs on the PIPELINE machine (this Windows box) as the final step of the
# "MLS Bot Hourly" Task Scheduler job (see Compbird/deploy/data-sync/README.md
# for the exact scheduling change - do NOT edit the live task without reading it).
#
# DESIGN
#   push (this script)  ->  R2 bucket  ->  pull_and_swap.sh (inside the engine
#                                          container, every SYNC_INTERVAL_MIN)
#   - hash-skip: every file is SHA256-hashed; files unchanged since the last
#     SUCCESSFUL push are not re-uploaded (state in logs/push_prod_data.state.json,
#     keyed per target so a dry run never affects prod skips).
#   - staging-then-finalize: objects are uploaded to CONTENT-ADDRESSED keys
#     (<prefix>/objects/<rel>.<sha16>) which nothing reads until the single
#     <prefix>/manifest.json - uploaded LAST - points at them. A puller
#     therefore only ever sees complete uploads: every S3 PUT is atomic per
#     object, keys are immutable (a new hash = a new key, never an overwrite),
#     and the manifest carries the full sha256 of every file so the puller
#     re-verifies each download before activating anything.
#   - superseded keys from the previous push are deleted AFTER the new manifest
#     is live (best-effort; a failure only leaves garbage, never breaks prod).
#   - idempotent: nothing changed -> nothing uploads, but the manifest is
#     re-uploaded with a fresh generated_utc so the engine-side freshness
#     marker keeps advancing (the "pipeline ran end-to-end" health signal).
#   - non-zero exit on ANY failure so Task Scheduler shows the run red.
#   - rotating local log: logs/push_prod_data.log (1 MB x 3).
#
# SHIPPED FILES - the complete set the engine (or the Next app) reads at
# request time. Enumerated from source (path -> reader evidence, source:line);
# verified 2026-07-14 by grepping read_parquet/joblib.load/sqlite/json opens:
#
#   data/mls_lookup.parquet          THE hourly comp pool (the freshness claim)
#       src/mls_bot/analytics/cma_compset.py:25,54    (listings view for pick_comps)
#       src/mls_bot/analytics/property_lookup.py:36,110,155,193
#       src/mls_bot/analytics/blind_valuer.py:69,167  (blind-anchor comp packet)
#       src/mls_bot/analytics/cma_hygiene.py:66,118
#       src/mls_bot/analytics/market_index.py:65      (index fallback pool)
#       src/mls_bot/analytics/nl_query.py:22,127
#       scripts/property_profile.py:84,277,356        (profile + market context)
#       scripts/build_cma.py:768                      (prior-sale lookup)
#   data/market_index.parquet        county monthly $/sqft index (AVM debias,
#                                    prior-sale anchors)
#       src/mls_bot/analytics/market_index.py:64
#   data/supplemental_listings.parquet  compbird's public-records comp pool,
#                                    selected per-request via CMA_LISTINGS_PARQUET
#       worker/cma_worker.py:90-96 (_select_pool) ->
#       src/mls_bot/analytics/cma_compset.py:44-49
#   data/parcel_lookup.parquet       parcel attributes (subject resolution)
#       src/mls_bot/analytics/property_lookup.py:35,188,250,623,755
#   data/search_index.sqlite         address typeahead FTS index - read by the
#                                    COMPBIRD NEXT APP (better-sqlite3), NOT python
#       Compbird/src/lib/cma/search-index.ts:74-75 (SEARCH_INDEX_PATH env or
#       PROJECT_ROOT/data/search_index.sqlite); built by scripts/build_search_index.py
#       NOTE: rebuilt hourly and a SQLite rebuild changes bytes even when content
#       barely moved, so raw hash-compare would ship ~1.1 GB EVERY hour. Marked
#       "heavy": ships at most every -HeavyMinIntervalHours (default 20 -> ~daily).
#   data/cma_regions.json            per-region dialed CMA knobs
#       src/mls_bot/analytics/cma_regions.py:28
#   outputs/mls_analytics/avm_model/regressor.joblib + meta.joblib
#       src/mls_bot/analytics/avm.py:36,201-205       (AVM regressor)
#   outputs/mls_analytics/dom_model/bundle_meta.joblib + q25/q50/q75.joblib
#       src/mls_bot/analytics/dom_model.py:37,379-382 (via build_cma.py:1907)
#   outputs/mls_analytics/price_cut_model/cut_clf.joblib + cut_meta.joblib
#       src/mls_bot/analytics/price_cut_model.py:36,213-216
#
# DELIBERATELY NOT SHIPPED (engine-owned runtime caches - pushing them would
# clobber the production container's own state):
#   data/cma_blind_cache.json        blind-anchor cache (blind_valuer.py:70).
#       Anchors are keyed by (subject signature, model, prompt version) and do
#       NOT invalidate on pool refresh - BY DESIGN (the one-number invariant).
#       The puller can clear it behind CLEAR_BLIND_CACHE_ON_SWAP=1 (default OFF).
#   data/cma_hygiene_cache.json      hygiene cache (cma_hygiene.py:69) - keyed
#       by content hash, so pool refreshes naturally miss; engine-owned.
#
# BUCKET LAYOUT (all under -R2Prefix, default "engine-data"):
#   objects/<rel>.<sha16>   immutable content-addressed blobs (rel with / kept)
#   manifest.json           {version, generated_utc, files:[{rel,key,sha256,bytes,kind}]}
#
# CONFIG - parameters, each falling back to an environment variable:
#   -R2Endpoint  https://<accountid>.r2.cloudflarestorage.com  ($env:R2_ENDPOINT)
#   -R2Bucket    bucket name                                   ($env:R2_BUCKET)
#   -R2Key       access key id                                 ($env:R2_KEY)
#   -R2Secret    secret access key                             ($env:R2_SECRET)
#   -R2Prefix    key prefix, default "engine-data"             ($env:R2_PREFIX)
#   -R2Region    SigV4 region, default "auto" (R2's region)    ($env:R2_REGION)
#   -LocalTarget DIR - VERIFICATION MODE: no network; writes the same
#                objects/ + manifest.json layout into DIR (atomic .part->rename).
#                pull_and_swap.sh --local-source DIR consumes it. Exists exactly
#                so the whole pipeline dry-runs end-to-end with no bucket.
#   -Force       ignore the hash state, ship everything
#   -HeavyMinIntervalHours N   min hours between ships of "heavy" files (default 20)
#   -SelfTest    verify the SigV4 signer against the published AWS test vector
#                and exit (0 = pass). No config needed.
#
# TRANSPORT: native SigV4 over HttpWebRequest (streams; no buffering of the
# 1.1 GB index in RAM; zero external deps - rclone is NOT installed on this
# box). If an rclone binary is ever on PATH you may prefer it manually, but
# this script deliberately has ONE tested code path.

[CmdletBinding()]
param(
  [string]$R2Endpoint = $env:R2_ENDPOINT,
  [string]$R2Bucket = $env:R2_BUCKET,
  [string]$R2Key = $env:R2_KEY,
  [string]$R2Secret = $env:R2_SECRET,
  [string]$R2Prefix = $env:R2_PREFIX,
  [string]$R2Region = $env:R2_REGION,
  [string]$LocalTarget = "",
  [switch]$Force,
  [int]$HeavyMinIntervalHours = 20,
  [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── locations ────────────────────────────────────────────────────────────────
$RepoRoot  = Split-Path -Parent $PSScriptRoot          # ...\MLS Bot
$LogDir    = Join-Path $RepoRoot "logs"
$LogFile   = Join-Path $LogDir "push_prod_data.log"
$StateFile = Join-Path $LogDir "push_prod_data.state.json"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
if (-not $R2Prefix) { $R2Prefix = "engine-data" }
if (-not $R2Region) { $R2Region = "auto" }

# ── rotating log (1 MB, keep .1 and .2) ──────────────────────────────────────
function Rotate-Log {
  if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 1MB)) {
    $l2 = "$LogFile.2"; $l1 = "$LogFile.1"
    if (Test-Path $l2) { Remove-Item -Force $l2 }
    if (Test-Path $l1) { Move-Item -Force $l1 $l2 }
    Move-Item -Force $LogFile $l1
  }
}
function Log([string]$msg) {
  $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $msg
  Write-Host $line
  Add-Content -Path $LogFile -Value $line -Encoding UTF8
}
function Fail([string]$msg) {
  Log "FAIL: $msg"
  Log "=== push FAILED ==="
  exit 1
}

# ── SigV4 signer (generic; the -SelfTest vector drives the same functions) ───
function Get-HmacSha256([byte[]]$KeyBytes, [string]$Data) {
  $h = New-Object System.Security.Cryptography.HMACSHA256
  $h.Key = $KeyBytes
  try { return $h.ComputeHash([Text.Encoding]::UTF8.GetBytes($Data)) } finally { $h.Dispose() }
}
function Get-Sha256HexOfString([string]$s) {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($s))
    return ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
  } finally { $sha.Dispose() }
}
function Get-Sha256HexOfFile([string]$path) {
  return (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLowerInvariant()
}
$EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Returns @{ Authorization = "..."; StringToSign = "..."; Signature = "..." }.
# $SignedHeaders: ORDERED hashtable of lowercase-name -> value; MUST include
# host and x-amz-date (and x-amz-content-sha256 for s3).
function New-SigV4Authorization(
    [string]$Method, [string]$CanonicalUri, [string]$CanonicalQuery,
    [System.Collections.Specialized.OrderedDictionary]$SignedHeaders,
    [string]$PayloadHash, [string]$AmzDate, [string]$Region, [string]$Service,
    [string]$AccessKey, [string]$SecretKey) {
  $headerLines = ""
  $names = @()
  foreach ($k in $SignedHeaders.Keys) {
    $headerLines += ("{0}:{1}`n" -f $k, ([string]$SignedHeaders[$k]).Trim())
    $names += $k
  }
  $signedNames = ($names -join ";")
  $canonicalRequest = ($Method, $CanonicalUri, $CanonicalQuery, $headerLines, $signedNames, $PayloadHash) -join "`n"
  $dateStamp = $AmzDate.Substring(0, 8)
  $scope = "$dateStamp/$Region/$Service/aws4_request"
  $stringToSign = ("AWS4-HMAC-SHA256", $AmzDate, $scope, (Get-Sha256HexOfString $canonicalRequest)) -join "`n"
  $kDate    = Get-HmacSha256 ([Text.Encoding]::UTF8.GetBytes("AWS4" + $SecretKey)) $dateStamp
  $kRegion  = Get-HmacSha256 $kDate $Region
  $kService = Get-HmacSha256 $kRegion $Service
  $kSigning = Get-HmacSha256 $kService "aws4_request"
  $sigBytes = Get-HmacSha256 $kSigning $stringToSign
  $signature = ([BitConverter]::ToString($sigBytes) -replace "-", "").ToLowerInvariant()
  return @{
    Authorization = "AWS4-HMAC-SHA256 Credential=$AccessKey/$scope, SignedHeaders=$signedNames, Signature=$signature"
    StringToSign = $stringToSign
    Signature = $signature
  }
}

# ── -SelfTest: the published AWS SigV4 example (docs "Signature Version 4
#    signing process", GET iam ListUsers, 20150830) must reproduce exactly ────
if ($SelfTest) {
  $h = New-Object System.Collections.Specialized.OrderedDictionary
  $h["content-type"] = "application/x-www-form-urlencoded; charset=utf-8"
  $h["host"] = "iam.amazonaws.com"
  $h["x-amz-date"] = "20150830T123600Z"
  $r = New-SigV4Authorization "GET" "/" "Action=ListUsers&Version=2010-05-08" $h `
        $EMPTY_SHA256 "20150830T123600Z" "us-east-1" "iam" `
        "AKIDEXAMPLE" "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
  $expected = "5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7"
  if ($r.Signature -eq $expected) {
    Write-Host "SigV4 self-test PASS ($($r.Signature))"
    exit 0
  }
  Write-Host "SigV4 self-test FAIL"
  Write-Host "  expected $expected"
  Write-Host "  got      $($r.Signature)"
  exit 1
}

# ── S3 request over HttpWebRequest (streams uploads; no 1.1 GB in RAM) ───────
# Keys are restricted to [A-Za-z0-9._/-] (enforced below), so no URI encoding
# is needed for the canonical path.
function Invoke-S3Request(
    [string]$Method, [string]$Key, [string]$InFile, [string]$PayloadHash,
    [string]$OutFile) {
  $endpointUri = [Uri]$R2Endpoint
  $s3host = $endpointUri.Host
  $canonicalUri = "/$R2Bucket/$Key"
  $url = "$($R2Endpoint.TrimEnd('/'))/$R2Bucket/$Key"
  $amzDate = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
  if (-not $PayloadHash) { $PayloadHash = $EMPTY_SHA256 }

  $h = New-Object System.Collections.Specialized.OrderedDictionary
  $h["host"] = $s3host
  $h["x-amz-content-sha256"] = $PayloadHash
  $h["x-amz-date"] = $amzDate
  $auth = New-SigV4Authorization $Method $canonicalUri "" $h $PayloadHash $amzDate $R2Region "s3" $R2Key $R2Secret

  $req = [System.Net.HttpWebRequest]::Create($url)
  $req.Method = $Method
  $req.Timeout = 3600000            # 1h ceiling for the heavy index on slow upstream
  $req.ReadWriteTimeout = 3600000
  $req.AllowWriteStreamBuffering = $false   # STREAM the body; never buffer in RAM
  $req.Headers.Add("x-amz-content-sha256", $PayloadHash)
  $req.Headers.Add("x-amz-date", $amzDate)
  $req.Headers.Add("Authorization", $auth.Authorization)

  if ($Method -eq "PUT" -and $InFile) {
    $fi = Get-Item $InFile
    $req.ContentLength = $fi.Length
    $src = [System.IO.File]::OpenRead($InFile)
    try {
      $dst = $req.GetRequestStream()
      try { $src.CopyTo($dst, 1MB) } finally { $dst.Dispose() }
    } finally { $src.Dispose() }
  } else {
    if ($Method -ne "GET") { $req.ContentLength = 0 }
  }

  try {
    $resp = $req.GetResponse()
    try {
      $status = [int]$resp.StatusCode
      if ($OutFile) {
        $rs = $resp.GetResponseStream()
        try {
          $fs = [System.IO.File]::Create($OutFile)
          try { $rs.CopyTo($fs, 1MB) } finally { $fs.Dispose() }
        } finally { $rs.Dispose() }
      }
      return $status
    } finally { $resp.Close() }
  } catch [System.Net.WebException] {
    $we = $_.Exception
    if ($we.Response) {
      $status = [int]$we.Response.StatusCode
      $body = ""
      try {
        $sr = New-Object System.IO.StreamReader($we.Response.GetResponseStream())
        $body = $sr.ReadToEnd(); $sr.Dispose()
      } catch {}
      $we.Response.Close()
      throw ("S3 {0} {1} -> HTTP {2}: {3}" -f $Method, $Key, $status, ($body -replace "\s+", " ").Substring(0, [Math]::Min(300, $body.Length)))
    }
    throw ("S3 {0} {1} -> {2}" -f $Method, $Key, $we.Message)
  }
}

Rotate-Log
Log "=== push_prod_data start ==="

# ── mode resolution ──────────────────────────────────────────────────────────
$LocalMode = [bool]$LocalTarget
if (-not $LocalMode) {
  if (-not $R2Endpoint) { Fail "no target: set -R2Endpoint (`$env:R2_ENDPOINT) or use -LocalTarget for a dry run" }
  if (-not $R2Bucket)   { Fail "set -R2Bucket (`$env:R2_BUCKET)" }
  if (-not $R2Key)      { Fail "set -R2Key (`$env:R2_KEY)" }
  if (-not $R2Secret)   { Fail "set -R2Secret (`$env:R2_SECRET)" }
}

# Target identity keys the hash state, so switching targets never wrongly skips.
if ($LocalMode) { $TargetId = "local:" + $LocalTarget }
else { $TargetId = "r2:" + $R2Endpoint + "/" + $R2Bucket + "/" + $R2Prefix }
Log "target: $TargetId"

# ── manifest of shipped files (kind drives the puller's validation probe) ────
# kinds: parquet:<minrows> | sqlite | json | opaque (joblib pickle).
# required = fail the push when missing locally (the upstream refresh is broken).
# heavy = rate-limited by -HeavyMinIntervalHours even when the hash changed.
$Manifest = @(
  @{ rel = "data/mls_lookup.parquet";            kind = "parquet:1000"; required = $true;  heavy = $false },
  @{ rel = "data/market_index.parquet";          kind = "parquet:1";    required = $true;  heavy = $false },
  @{ rel = "data/supplemental_listings.parquet"; kind = "parquet:1";    required = $true;  heavy = $false },
  @{ rel = "data/parcel_lookup.parquet";         kind = "parquet:1000"; required = $true;  heavy = $false },
  @{ rel = "data/search_index.sqlite";           kind = "sqlite";       required = $true;  heavy = $true  },
  @{ rel = "data/cma_regions.json";              kind = "json";         required = $true;  heavy = $false },
  @{ rel = "outputs/mls_analytics/avm_model/regressor.joblib";      kind = "opaque"; required = $true;  heavy = $false },
  @{ rel = "outputs/mls_analytics/avm_model/meta.joblib";           kind = "opaque"; required = $true;  heavy = $false },
  @{ rel = "outputs/mls_analytics/dom_model/bundle_meta.joblib";    kind = "opaque"; required = $false; heavy = $false },
  @{ rel = "outputs/mls_analytics/dom_model/q25.joblib";            kind = "opaque"; required = $false; heavy = $false },
  @{ rel = "outputs/mls_analytics/dom_model/q50.joblib";            kind = "opaque"; required = $false; heavy = $false },
  @{ rel = "outputs/mls_analytics/dom_model/q75.joblib";            kind = "opaque"; required = $false; heavy = $false },
  @{ rel = "outputs/mls_analytics/price_cut_model/cut_clf.joblib";  kind = "opaque"; required = $false; heavy = $false },
  @{ rel = "outputs/mls_analytics/price_cut_model/cut_meta.joblib"; kind = "opaque"; required = $false; heavy = $false }
)

# ── load hash state ──────────────────────────────────────────────────────────
# shape: { "<targetId>": { "<rel>": { hash, key, shippedUtc } } } - parsed
# defensively (older/foreign shapes are ignored, treated as "changed").
$State = @{}
if (Test-Path $StateFile) {
  try {
    $raw = Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($tp in $raw.PSObject.Properties) {
      $files = @{}
      foreach ($fp in $tp.Value.PSObject.Properties) {
        $entry = @{ hash = ""; key = ""; shippedUtc = ""; bytes = "0" }
        foreach ($n in @("hash", "key", "shippedUtc", "bytes")) {
          if ($fp.Value.PSObject.Properties[$n]) { $entry[$n] = [string]$fp.Value.$n }
        }
        $files[$fp.Name] = $entry
      }
      $State[$tp.Name] = $files
    }
  } catch {
    Log "  [warn] state file unreadable ($($_.Exception.Message)) - treating all files as changed"
    $State = @{}
  }
}
if (-not $State.ContainsKey($TargetId)) { $State[$TargetId] = @{} }
$TState = $State[$TargetId]

# ── hash everything; decide what uploads; build the new manifest ─────────────
$ToShip = @()          # entries: @{ rel; abs; hash; bytes; key }
$NewManifestFiles = @()  # EVERY manifest row (uploaded or carried forward)
$SupersededKeys = @()  # old content-addressed keys to delete after finalize
$SkippedUnchanged = 0

foreach ($m in $Manifest) {
  if ($m.rel -notmatch "^[A-Za-z0-9._/-]+$") { Fail "manifest rel has unsafe characters: $($m.rel)" }
  $abs = Join-Path $RepoRoot ($m.rel -replace "/", "\")
  if (-not (Test-Path $abs)) {
    if ($m.required) { Fail "required local file missing: $($m.rel) - the upstream refresh is broken; not publishing a partial dataset" }
    Log "  [skip] optional file absent locally: $($m.rel)"
    continue
  }
  $hash = Get-Sha256HexOfFile $abs
  $bytes = (Get-Item $abs).Length
  $key = "$R2Prefix/objects/$($m.rel).$($hash.Substring(0,16))"

  $prev = $null
  if ($TState.ContainsKey($m.rel)) { $prev = $TState[$m.rel] }
  $havePrev = ($null -ne $prev) -and $prev.hash -and $prev.key
  $changed = $Force -or (-not $havePrev) -or ($prev.hash -ne $hash)

  if (-not $changed) {
    $SkippedUnchanged++
    Log ("  [skip] unchanged (hash match): {0}" -f $m.rel)
    $NewManifestFiles += @{ rel = $m.rel; key = $prev.key; sha256 = $prev.hash; bytes = $bytes; kind = $m.kind }
    continue
  }
  if ($m.heavy -and -not $Force -and $havePrev -and $prev.shippedUtc) {
    $ageH = ((Get-Date).ToUniversalTime() - [datetime]::Parse($prev.shippedUtc).ToUniversalTime()).TotalHours
    if ($ageH -lt $HeavyMinIntervalHours) {
      Log ("  [skip] heavy file changed but shipped {0:n1}h ago (< {1}h): {2}" -f $ageH, $HeavyMinIntervalHours, $m.rel)
      # carry the PREVIOUS (still-live) object forward in the manifest
      $NewManifestFiles += @{ rel = $m.rel; key = $prev.key; sha256 = $prev.hash; bytes = 0 + $prev["bytes"]; kind = $m.kind }
      continue
    }
  }
  $ToShip += @{ rel = $m.rel; abs = $abs; hash = $hash; bytes = $bytes; key = $key }
  $NewManifestFiles += @{ rel = $m.rel; key = $key; sha256 = $hash; bytes = $bytes; kind = $m.kind }
  if ($havePrev -and ($prev.key -ne $key)) { $SupersededKeys += $prev.key }
}
Log ("plan: {0} file(s) to upload, {1} unchanged" -f $ToShip.Count, $SkippedUnchanged)

# Carried-forward heavy rows may have bytes=0 from old state; patch from disk.
foreach ($row in $NewManifestFiles) {
  if (-not $row.bytes) {
    $abs = Join-Path $RepoRoot ($row.rel -replace "/", "\")
    if (Test-Path $abs) { $row.bytes = (Get-Item $abs).Length }
  }
}

# ── upload objects (staging: content-addressed keys nothing points at yet) ───
foreach ($f in $ToShip) {
  Log ("  uploading {0} ({1:n1} MB) -> {2}" -f $f.rel, ($f.bytes / 1MB), $f.key)
  if ($LocalMode) {
    $dst = Join-Path $LocalTarget (($f.key -replace "^$([regex]::Escape($R2Prefix))/", "") -replace "/", "\")
    $dstDir = Split-Path -Parent $dst
    if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Force -Path $dstDir | Out-Null }
    $part = "$dst.part"
    Copy-Item -Force $f.abs $part
    Move-Item -Force $part $dst        # rename: the final name is never half-written
  } else {
    try {
      $status = Invoke-S3Request "PUT" $f.key $f.abs $f.hash $null
    } catch { Fail "upload failed for $($f.rel): $($_.Exception.Message)" }
    if ($status -lt 200 -or $status -ge 300) { Fail "upload failed for $($f.rel): HTTP $status" }
  }
}

# ── finalize: write manifest.json LAST (the only key pullers ever read first) ─
$nowUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
$manifestObj = @{
  version = 1
  generated_utc = $nowUtc
  source = $env:COMPUTERNAME
  files = $NewManifestFiles
}
$manifestJson = $manifestObj | ConvertTo-Json -Depth 6
$tmpManifest = Join-Path $env:TEMP ("push_prod_manifest_{0}.json" -f $PID)
# .NET WriteAllText: UTF-8 no BOM (PS 5.1 Out-File utf8 adds a BOM; json.load
# on the pull side tolerates BOM via utf-8-sig, but keep it clean anyway).
[System.IO.File]::WriteAllText($tmpManifest, $manifestJson, (New-Object System.Text.UTF8Encoding($false)))
try {
  if ($LocalMode) {
    if (-not (Test-Path $LocalTarget)) { New-Item -ItemType Directory -Force -Path $LocalTarget | Out-Null }
    $dst = Join-Path $LocalTarget "manifest.json"
    Copy-Item -Force $tmpManifest "$dst.part"
    Move-Item -Force "$dst.part" $dst
    Log "  finalized manifest.json (local) generated_utc=$nowUtc files=$($NewManifestFiles.Count)"
  } else {
    $mHash = Get-Sha256HexOfFile $tmpManifest
    try {
      $status = Invoke-S3Request "PUT" "$R2Prefix/manifest.json" $tmpManifest $mHash $null
    } catch { Fail "manifest upload failed: $($_.Exception.Message)" }
    if ($status -lt 200 -or $status -ge 300) { Fail "manifest upload failed: HTTP $status" }
    Log "  finalized manifest.json generated_utc=$nowUtc files=$($NewManifestFiles.Count)"
  }
} finally {
  Remove-Item -Force $tmpManifest -ErrorAction SilentlyContinue
}

# ── record state ONLY after the manifest is live (fail -> re-ship next run) ──
foreach ($f in $ToShip) {
  $TState[$f.rel] = @{ hash = $f.hash; key = $f.key; bytes = $f.bytes; shippedUtc = $nowUtc }
}
$State[$TargetId] = $TState
($State | ConvertTo-Json -Depth 6) | Out-File -FilePath $StateFile -Encoding utf8
Log ("state updated: {0} file(s) recorded" -f $ToShip.Count)

# ── garbage-collect superseded objects (best-effort, AFTER finalize) ─────────
# A puller mid-download of an old key gets a 404, aborts that cycle cleanly,
# and retries with the new manifest - never activates a partial set.
foreach ($k in $SupersededKeys) {
  if ($LocalMode) {
    $old = Join-Path $LocalTarget (($k -replace "^$([regex]::Escape($R2Prefix))/", "") -replace "/", "\")
    if (Test-Path $old) { Remove-Item -Force $old -ErrorAction SilentlyContinue }
    Log "  gc: removed superseded $k"
  } else {
    try {
      $status = Invoke-S3Request "DELETE" $k $null $null $null
      Log "  gc: deleted superseded $k (HTTP $status)"
    } catch {
      Log "  [warn] gc delete failed for ${k}: $($_.Exception.Message) (harmless; orphaned object)"
    }
  }
}

Log "=== push OK ==="
exit 0
