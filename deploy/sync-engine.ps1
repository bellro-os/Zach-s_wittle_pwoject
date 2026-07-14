<#
.SYNOPSIS
  Re-mirror the MLS Bot CMA engine into this repo's engine/ directory.

.DESCRIPTION
  The engine is a VENDORED COPY (see engine/.vendored-from). It is developed
  in the MLS Bot repo; this script copies its git-tracked files (code only,
  via `git archive` — never data/models/.env/caches) into engine/, so the two
  copies stay in lockstep. The certified accuracy depends on the vendored code
  matching the tested engine byte-for-byte, so ALWAYS edit in MLS Bot and re-sync
  here rather than hand-editing engine/.

.PARAMETER EngineRepo
  Path to the MLS Bot repo. Default: C:\Users\zach\Desktop\MLS Bot

.EXAMPLE
  pwsh deploy/sync-engine.ps1
#>
param(
  [string]$EngineRepo = "C:\Users\zach\Desktop\MLS Bot"
)
$ErrorActionPreference = "Stop"

$appRoot = Split-Path -Parent $PSScriptRoot
$engineDir = Join-Path $appRoot "engine"

if (-not (Test-Path (Join-Path $EngineRepo ".git"))) {
  throw "Not a git repo: $EngineRepo (pass -EngineRepo <path>)"
}

Push-Location $EngineRepo
try {
  $head = (git rev-parse HEAD).Trim()
  $branch = (git rev-parse --abbrev-ref HEAD).Trim()
  $dirty = (git status --porcelain)
  if ($dirty) {
    Write-Warning "MLS Bot has UNCOMMITTED changes — they will NOT be vendored (git archive uses HEAD only). Commit them first if you want them in."
  }
  Write-Host "Vendoring engine @ $head ($branch) ..."
  # git archive streams only tracked files; extract into a temp dir then swap.
  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("engine-sync-" + [System.Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  git archive HEAD | tar -x -C $tmp
  if (Test-Path $engineDir) { Remove-Item -Recurse -Force $engineDir }
  Move-Item $tmp $engineDir
}
finally { Pop-Location }

# Re-stamp provenance.
$stamp = @"
This engine/ directory is a VENDORED COPY of the MLS Bot CMA engine.

Canonical source repo: MLS Bot  (branch $branch)
Vendored at commit:     $head
Vendored on:            $(Get-Date -Format 'yyyy-MM-dd')

It contains only git-tracked code (via ``git archive``) — never data
(*.parquet/*.jsonl), models, caches, or .env. Production data reaches the
running engine via the R2 object-storage sync (see deploy/data-sync/), not
this directory.

To refresh this copy after engine changes, run from the app repo root:
    pwsh deploy/sync-engine.ps1        # or: bash deploy/sync-engine.sh

That re-mirrors the engine repo's tracked files here and re-stamps this file.
Do NOT hand-edit engine code here — edit it in the MLS Bot repo and re-sync,
so the two copies cannot silently drift (the certified accuracy depends on
the engine being byte-for-byte the tested code).
"@
Set-Content -Path (Join-Path $engineDir ".vendored-from") -Value $stamp -Encoding utf8

$count = (Get-ChildItem -Recurse -File $engineDir | Measure-Object).Count
Write-Host "Done. engine/ now holds $count files from $head." -ForegroundColor Green
Write-Host "Review + commit:  git add engine && git commit -m 'Sync engine to <hash>'"
