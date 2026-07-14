<#
.SYNOPSIS
Register Windows Task Scheduler entries for the MLS Bot daily + weekly runs.

.DESCRIPTION
Creates two scheduled tasks:
  - "MLS Bot Daily"  runs `python tasks.py mls-daily`  every day at 06:30
  - "MLS Bot Weekly" runs `python tasks.py mls-weekly` every Sunday at 04:00

Tasks log stdout+stderr to logs/<task>_<timestamp>.log under the project root.
Uses the current user account (no admin elevation needed for user-scope tasks).

.NOTES
Run from any PowerShell prompt:
    powershell -ExecutionPolicy Bypass -File scripts\schedule\install_schedules.ps1

Uninstall:
    Unregister-ScheduledTask -TaskName "MLS Bot Daily"  -Confirm:$false
    Unregister-ScheduledTask -TaskName "MLS Bot Weekly" -Confirm:$false
#>

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path "$PSScriptRoot\..\.."
$pythonExe = (Get-Command python).Source
$logsDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }

function Register-MLSTask {
    param(
        [string]$TaskName,
        [string]$Argument,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger,
        [string]$Description,
        [string]$WorkingDir = "",
        [string]$Script = "tasks.py"
    )
    if (-not $WorkingDir) { $WorkingDir = $projectRoot }
    # Build a wrapper command: cd <workdir>; set PYTHONPATH=src; run; redirect log
    $logBase = $TaskName -replace '\s', '_'
    $logFile = Join-Path $logsDir "${logBase}.log"
    $cmd = "/d /c set PYTHONPATH=src && cd /d `"$WorkingDir`" && `"$pythonExe`" $Script $Argument >> `"$logFile`" 2>&1"

    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmd
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -RestartCount 2 `
        -RestartInterval (New-TimeSpan -Minutes 10)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Write-Host "  removing existing task: $TaskName"
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $Trigger `
                            -Settings $settings -Principal $principal -Description $Description | Out-Null
    Write-Host "  installed: $TaskName -> log $logFile"
}

# Daily 06:30
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At 06:30
Register-MLSTask -TaskName "MLS Bot Daily" -Argument "mls-daily" `
                 -Trigger $dailyTrigger `
                 -Description "Pull MLS incremental, merge deeds, rebuild analytics, leads, alerts, digest"

# Weekly Sunday 04:00
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 04:00
Register-MLSTask -TaskName "MLS Bot Weekly" -Argument "mls-weekly" `
                 -Trigger $weeklyTrigger `
                 -Description "Refresh agent/office directory, retrain DOM model"

# Hourly — lightweight CMA freshness: incremental RETS delta -> merge -> enrich
# -> rebuild mls_lookup.parquet. Keeps comps <=1h stale. Repeats every hour,
# indefinitely, starting at the next top of the hour.
$hourlyStart = (Get-Date).Date.AddHours((Get-Date).Hour + 1)
$hourlyTrigger = New-ScheduledTaskTrigger -Once -At $hourlyStart `
                 -RepetitionInterval (New-TimeSpan -Hours 1) `
                 -RepetitionDuration (New-TimeSpan -Days 3650)
Register-MLSTask -TaskName "MLS Bot Hourly" -Argument "mls-hourly" `
                 -Trigger $hourlyTrigger `
                 -Description "Hourly: incremental MLS delta + rebuild CMA parquet (fresh comps)"

# Daily 05:00 — county parcel/CAMA freshness check. County records change
# slowly (daily-to-monthly), so this CHECKS daily and only re-pulls sources
# that actually changed (or are older than --max-age-days). Runs in the sibling
# va-parcels-pipeline repo. (Hourly polling of 70+ county GIS servers would be
# impolite and add no data — daily change-detection is the right cadence.)
$parcelsDir = Join-Path (Split-Path $projectRoot -Parent) "va-parcels-pipeline"
if (Test-Path (Join-Path $parcelsDir "refresh.py")) {
    $parcelsTrigger = New-ScheduledTaskTrigger -Daily -At 05:00
    Register-MLSTask -TaskName "VA Parcels Daily Refresh" -Argument "--all --max-age-days 14" `
                     -Trigger $parcelsTrigger `
                     -Description "Daily change-detect + re-pull changed county parcel sources" `
                     -WorkingDir $parcelsDir -Script "refresh.py"
} else {
    Write-Host "  SKIP: VA Parcels Daily Refresh (refresh.py not found at $parcelsDir)"
}

Write-Host ""
Write-Host "Done. View tasks:  Get-ScheduledTask -TaskName 'MLS Bot*'"
Write-Host "Trigger now:        Start-ScheduledTask -TaskName 'MLS Bot Daily'"
Write-Host "Logs:               $logsDir"
