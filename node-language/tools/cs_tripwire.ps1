# cs_tripwire.ps1 - out-of-band tripwire for broker .cs drift.
#
# Compares the current working-tree contents of payload/sources/**/*.cs
# against the most recent git HEAD. If anything drifts AND
# ARCHHUB_ALLOW_CS_EDIT is not set, prints a loud warning + returns
# exit 1.
#
# Wired into tools/loop_audit.ps1. Founder runs preflight too.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/cs_tripwire.ps1
#   powershell -ExecutionPolicy Bypass -File tools/cs_tripwire.ps1 -Quiet
#   powershell -ExecutionPolicy Bypass -File tools/cs_tripwire.ps1 -ShowDiff
#
# Exit codes:
#   0 - no drift OR drift but ARCHHUB_ALLOW_CS_EDIT=1
#   1 - drift detected without opt-in
#   2 - repo state bad (no .git, not on a branch, etc)

param(
    [switch]$Quiet,
    [switch]$ShowDiff
)

$ErrorActionPreference = "Continue"

if (-not (Test-Path .git)) {
    Write-Error "tripwire: no .git in current directory (cwd=$(Get-Location))"
    exit 2
}

$drift = git diff --name-only HEAD -- 'payload/sources/**/*.cs' 2>$null
if (-not $drift) {
    if (-not $Quiet) {
        Write-Host "OK cs_tripwire: no broker .cs drift vs HEAD" -ForegroundColor Green
    }
    exit 0
}

$optin = $env:ARCHHUB_ALLOW_CS_EDIT -eq "1"

Write-Host ""
Write-Host "=======================================================================" -ForegroundColor Yellow
Write-Host "  CS TRIPWIRE -- broker .cs drift detected" -ForegroundColor Yellow
Write-Host "=======================================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "Files diverged from HEAD:" -ForegroundColor Yellow
foreach ($f in $drift) { Write-Host "  $f" -ForegroundColor Yellow }
Write-Host ""

if ($ShowDiff) {
    Write-Host "Diff vs HEAD:" -ForegroundColor Cyan
    git diff HEAD -- 'payload/sources/**/*.cs'
    Write-Host ""
}

if ($optin) {
    Write-Host "ARCHHUB_ALLOW_CS_EDIT=1 set -- drift is approved." -ForegroundColor Green
    exit 0
}

Write-Host "Founder mandate (AGENTS.md): broker .cs needs an AgDR + sign-off." -ForegroundColor Red
Write-Host ""
Write-Host "To accept the drift (after reviewing it):" -ForegroundColor Cyan
Write-Host "  `$env:ARCHHUB_ALLOW_CS_EDIT='1'; git add payload/sources/...; git commit ..." -ForegroundColor Cyan
Write-Host ""
Write-Host "To revert:" -ForegroundColor Cyan
Write-Host "  git checkout -- payload/sources/" -ForegroundColor Cyan
Write-Host ""
Write-Host "=======================================================================" -ForegroundColor Yellow
exit 1
