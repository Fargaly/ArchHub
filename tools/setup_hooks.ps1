# setup_hooks.ps1 - one-time per-clone hook activation.
#
# git config core.hooksPath is a per-repo local-config setting that
# does NOT travel with `git clone`. Every fresh clone (founder's
# machine, CI, another agent's checkout) must run this once.
#
# Idempotent: re-running is safe.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/setup_hooks.ps1

$ErrorActionPreference = "Stop"

if (-not (Test-Path .git)) {
    Write-Error "setup_hooks: no .git in current directory (cwd=$(Get-Location))"
    exit 2
}

$current = & git config --get core.hooksPath 2>$null
if ($current -eq ".githooks") {
    Write-Host "OK core.hooksPath already pointing at .githooks" -ForegroundColor Green
} else {
    & git config core.hooksPath .githooks
    Write-Host "Set core.hooksPath = .githooks (was: '$current')" -ForegroundColor Green
}

# Verify hook files exist + are executable (on Unix).
foreach ($hook in @("pre-commit", "pre-push")) {
    $p = ".githooks/$hook"
    if (-not (Test-Path $p)) {
        Write-Warning "$p MISSING -- hooks not fully installed"
    } else {
        Write-Host "  - $p present" -ForegroundColor Cyan
    }
}

# Run tripwire so the user sees current state.
Write-Host ""
Write-Host "Running tripwire..." -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/cs_tripwire.ps1
exit $LASTEXITCODE
