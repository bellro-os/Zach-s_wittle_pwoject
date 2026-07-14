<#
  compbird_engine_setup.ps1 — stand up compbird's SEPARATE, tweakable engine.

  Model: compbird gets its own engine WORKING COPY (a git worktree on branch
  `compbird-engine`) so you can edit build_cma.py / the comp scorer / the
  supplemental-source weighting WITHOUT touching Ratifyly's production engine.
  It SHARES the data pool + outputs read-only-by-convention (one refresh, no
  drift) and shares the LLM hygiene cache so the two engines drop the same comps.
  Accuracy tweaks proven on compbird are PROMOTED back by merging
  `compbird-engine` -> the shared engine branch (backtest-gated) so both
  ultimately converge — compbird is the lab, Ratifyly is the validated release.

  Run from anywhere. Idempotent-ish: it refuses to clobber an existing worktree.

  Usage:
    pwsh scripts/compbird_engine_setup.ps1                 # defaults: port 8766
    pwsh scripts/compbird_engine_setup.ps1 -Port 8766 -WorktreePath "C:\Users\zach\Desktop\MLS Bot - compbird"
#>
[CmdletBinding()]
param(
  [string]$EngineRoot   = "C:\Users\zach\Desktop\MLS Bot",
  [string]$WorktreePath = "C:\Users\zach\Desktop\MLS Bot - compbird",
  [string]$Branch       = "compbird-engine",
  [int]   $Port         = 8766,
  [string]$Token        = ""   # optional; leave empty for localhost
)

$ErrorActionPreference = "Stop"

function Info($m){ Write-Host "[compbird-engine] $m" -ForegroundColor Cyan }
function Warn($m){ Write-Host "[compbird-engine] $m" -ForegroundColor Yellow }

if (-not (Test-Path $EngineRoot)) { throw "EngineRoot not found: $EngineRoot" }
$canonData    = Join-Path $EngineRoot "data"
$canonOutputs = Join-Path $EngineRoot "outputs"
$canonCache   = Join-Path $canonData "cma_hygiene_cache.json"

# 1. Warn if the shared engine has uncommitted changes — a worktree branches
#    from the last COMMIT, so anything uncommitted won't be in compbird's copy.
Push-Location $EngineRoot
$dirty = (git status --porcelain) | Where-Object { $_ -and $_ -notmatch '^\?\? ' }
if ($dirty) {
  Warn "The shared engine has uncommitted changes. The worktree branches from HEAD,"
  Warn "so those edits will NOT be in compbird's copy. Commit them first if you want"
  Warn "compbird to start from the same baseline (e.g. the _confidence + atomic-swap fixes)."
}

# 2. Create the worktree (new branch off current HEAD) if absent.
if (Test-Path $WorktreePath) {
  Info "Worktree already exists at $WorktreePath — skipping creation."
} else {
  Info "Creating worktree at $WorktreePath on branch '$Branch'..."
  git worktree add $WorktreePath -b $Branch
}
Pop-Location

# 3. Share the stateful dirs: junction the worktree's data/ + outputs/ to the
#    canonical engine so there is exactly ONE pool and ONE outputs volume.
#    (Junctions need no admin; the engine only READS data/, and writes outputs/
#    with brand-prefixed filenames so the two engines never collide.)
foreach ($pair in @(@{ link = (Join-Path $WorktreePath "data");    target = $canonData },
                    @{ link = (Join-Path $WorktreePath "outputs"); target = $canonOutputs })) {
  if (Test-Path $pair.link) {
    $item = Get-Item $pair.link -Force
    if ($item.LinkType) { Info "$($pair.link) already linked -> $($item.Target)"; continue }
    # A real (non-link) dir created by the worktree: remove it so we can link.
    if (-not (Get-ChildItem $pair.link -Force | Select-Object -First 1)) {
      Remove-Item $pair.link -Force
    } else {
      Warn "$($pair.link) exists and is non-empty; leaving as-is (resolve manually)."; continue
    }
  }
  Info "Linking $($pair.link) -> $($pair.target)"
  cmd /c mklink /J "`"$($pair.link)`"" "`"$($pair.target)`"" | Out-Null
}

# 4. Launch compbird's warm worker on its own port, pointed at the SHARED data,
#    outputs, and hygiene cache. (Single-threaded by design; its own process.)
$env:CMA_WORKER_PORT   = "$Port"
$env:CMA_WORKER_HOST   = "127.0.0.1"
$env:CMA_HYGIENE_CACHE = $canonCache              # share the comp-drop verdicts
# Comp-workshop similarity surface (per-comp similarity/subscores/reasons in
# /preview + /profile). COMPBIRD-ONLY: set here and nowhere else — Ratifyly's
# engine leaves it unset, keeping its serialization byte-identical.
$env:CMA_COMP_SCORE_SURFACE = "1"
$env:CMA_COMP_TUNING_DISCLOSURE = "1"
# Blind-Haiku ensemble (certified 2026-07: engine 13.24% -> ensemble 11.54%
# median APE @ n=1000): final mid = mean(engine mid, blind AI comp read),
# anchor cached once per subject (data/cma_blind_cache.json). COMPBIRD-ONLY:
# Ratifyly's engine leaves it unset -> byte-identical valuations there.
$env:CMA_BLIND_ENSEMBLE = "1"
# Agent what-if damping: bed/bath subject overrides no longer re-anchor comp
# selection (the 6bd-override luxury-cohort re-pricing bug); the value effect
# is a bounded explicit adjustment (+2%/bed, +1.5%/full bath, +0.75%/half,
# ±8% cap) on record-anchored comps. COMPBIRD-ONLY: Ratifyly's engine leaves
# it unset -> byte-identical valuations there.
$env:CMA_OVERRIDE_DAMPING = "1"
if ($Token) { $env:CMA_WORKER_TOKEN = $Token }

Info "Starting compbird engine worker on 127.0.0.1:$Port (cwd=$WorktreePath)..."
Info "Hygiene cache shared at: $canonCache"
$proc = Start-Process -FilePath "python" -ArgumentList @("worker/cma_worker.py") `
          -WorkingDirectory $WorktreePath -PassThru
Info "Worker PID $($proc.Id). Health: curl http://127.0.0.1:$Port/healthz"

Write-Host ""
Info "DONE. Now point the app's compbird routes at this engine:"
Write-Host "  Add to the app's .env.local (Document Compliance AI Laptop):" -ForegroundColor Green
Write-Host "    COMPBIRD_ENGINE_URL=http://127.0.0.1:$Port" -ForegroundColor Green
if ($Token) { Write-Host "    (and the matching CMA_WORKER_TOKEN on the app side)" -ForegroundColor Green }
Write-Host ""
Info "Promotion workflow (keeps the two engines CONVERGENT):"
Write-Host "  1. Tweak the engine in:  $WorktreePath  (on branch $Branch)"
Write-Host "  2. Validate:             python scripts/backtest_cma.py   (in that worktree)"
Write-Host "  3. Promote when it wins: git -C `"$EngineRoot`" merge $Branch   (-> subtree -> Ratifyly prod)"
