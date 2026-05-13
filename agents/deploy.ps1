# Deploy archhub-agents to Fly.io.
#
# Idempotent — safe to run repeatedly. Each step skips if the resource
# already exists. The script ends by tailing logs so you immediately
# see the first heartbeat appear.
#
# Usage:
#   .\agents\deploy.ps1
#   .\agents\deploy.ps1 -ApiKey sk-ant-...      # bypass prompt
#   .\agents\deploy.ps1 -Region ord              # deploy elsewhere

[CmdletBinding()]
param(
    [string]$AppName = "archhub-agents",
    [string]$VolumeName = "archhub_agents_data",
    [string]$Region = "iad",
    [int]$VolumeSizeGB = 1,
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"

# Always run from the repo root so the Dockerfile build context is correct.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
Write-Host "[deploy] repo root: $RepoRoot"

# --- Pre-flight ------------------------------------------------------------
$flyctl = Get-Command flyctl -ErrorAction SilentlyContinue
if (-not $flyctl) {
    Write-Error @"
flyctl not found on PATH. Install it first:
  iwr https://fly.io/install.ps1 -useb | iex
Then re-run this script.
"@
    exit 1
}

# --- Step 1: app -----------------------------------------------------------
Write-Host "[deploy] step 1/5 — ensure app '$AppName' exists"
$existingApps = flyctl apps list --json 2>$null | ConvertFrom-Json
$appExists = $false
foreach ($a in $existingApps) {
    if ($a.Name -eq $AppName) { $appExists = $true; break }
}
if ($appExists) {
    Write-Host "  app already exists — skipping create"
} else {
    flyctl apps create $AppName
    if ($LASTEXITCODE -ne 0) { throw "flyctl apps create failed" }
}

# --- Step 2: volume --------------------------------------------------------
Write-Host "[deploy] step 2/5 — ensure volume '$VolumeName' exists"
$volJson = flyctl volumes list -a $AppName --json 2>$null
$volExists = $false
if ($volJson) {
    $vols = $volJson | ConvertFrom-Json
    foreach ($v in $vols) {
        if ($v.Name -eq $VolumeName) { $volExists = $true; break }
    }
}
if ($volExists) {
    Write-Host "  volume already exists — skipping create"
} else {
    flyctl volumes create $VolumeName --size $VolumeSizeGB --region $Region -a $AppName --yes
    if ($LASTEXITCODE -ne 0) { throw "flyctl volumes create failed" }
}

# --- Step 3: secrets -------------------------------------------------------
Write-Host "[deploy] step 3/5 — set ANTHROPIC_API_KEY secret"
if (-not $ApiKey) {
    $ApiKey = $env:ANTHROPIC_API_KEY
}
if (-not $ApiKey) {
    $secure = Read-Host -AsSecureString "Enter ANTHROPIC_API_KEY (sk-ant-...)"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}
if (-not $ApiKey) {
    throw "No ANTHROPIC_API_KEY provided. Set env var or pass -ApiKey."
}

flyctl secrets set "ANTHROPIC_API_KEY=$ApiKey" -a $AppName
if ($LASTEXITCODE -ne 0) { throw "flyctl secrets set failed" }

# --- Step 4: deploy --------------------------------------------------------
Write-Host "[deploy] step 4/5 — fly deploy"
flyctl deploy --config agents/fly.toml --dockerfile agents/Dockerfile -a $AppName --remote-only
if ($LASTEXITCODE -ne 0) { throw "flyctl deploy failed" }

# --- Step 5: next steps ----------------------------------------------------
Write-Host ""
Write-Host "[deploy] step 5/5 — done."
Write-Host "----------------------------------------------------------"
Write-Host "  Tail logs:        flyctl logs -a $AppName"
Write-Host "  Open dashboard:   flyctl proxy 8080 -a $AppName"
Write-Host "                    then GET http://localhost:8080/healthz"
Write-Host "  Stop the daemon:  flyctl scale count 0 -a $AppName"
Write-Host "  Restart:          flyctl scale count 1 -a $AppName"
Write-Host "  See CLOUD_DEPLOY.md for full operational notes."
Write-Host "----------------------------------------------------------"
