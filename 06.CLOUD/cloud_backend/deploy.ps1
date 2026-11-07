# ArchHub Cloud backend — Fly.io deploy helper.
#
# One-command setup + deploy. Idempotent — safe to re-run.
#
# Pre-reqs:
#   1. flyctl installed (see ENSURE_FLYCTL block below; auto-installs)
#   2. Stripe account + 3 recurring prices created (see docs/STRIPE_SETUP.md)
#   3. Anthropic / OpenAI / Google / Resend keys ready
#
# Usage:
#   ./cloud_backend/deploy.ps1                       # interactive secret prompts
#   ./cloud_backend/deploy.ps1 -SecretsFile <path>   # read from .env-style file
#   ./cloud_backend/deploy.ps1 -SkipSecrets          # keep secrets already on the app
#   ./cloud_backend/deploy.ps1 -NonInteractive       # never prompt; print the one login command

[CmdletBinding()]
param(
    [string]$SecretsFile = "",
    [switch]$SkipSecrets,
    [switch]$DnsAttach,
    [switch]$NonInteractive,
    [string]$PublicHealthUrl = "https://api.archhub.io/healthz",
    [string]$AppName = "archhub-cloud",
    [string]$Region  = "ord"
)

$ErrorActionPreference = "Stop"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
if (-not $PSBoundParameters.ContainsKey("NonInteractive")) {
    $attached = [Environment]::UserInteractive
    if ($attached) {
        try {
            $attached = -not [Console]::IsInputRedirected
        } catch {
            $attached = $false
        }
    }
    if (-not $attached) { $NonInteractive = $true }
}

function Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n] $msg" -ForegroundColor Cyan
}
function Done($msg) { Write-Host "    OK $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !! $msg" -ForegroundColor Yellow }

function Get-FlyResult {
    param([Parameter(Mandatory = $true)][string[]]$FlyArgs)
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    & flyctl @FlyArgs > $outFile 2> $errFile
    $flyExit = $LASTEXITCODE
    $stdoutText = [System.IO.File]::ReadAllText($outFile)
    $stderrText = [System.IO.File]::ReadAllText($errFile)
    Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    [pscustomobject]@{
        ExitCode = $flyExit
        StdOut = $stdoutText
        StdErr = $stderrText
    }
}
function Get-FlyFailureText {
    param($Result)
    $detail = [string]$Result.StdErr
    if ([string]::IsNullOrWhiteSpace($detail)) { $detail = [string]$Result.StdOut }
    $detail = (($detail -replace '\s+', ' ').Trim())
    if (-not $detail) { $detail = "exit $($Result.ExitCode)" }
    $detail
}
function Stop-IfFlyFailed {
    param([string]$StepName, $Result)
    if ($Result.ExitCode -ne 0) {
        $detail = Get-FlyFailureText $Result
        Write-Host "REFUSED: $StepName failed: $detail" -ForegroundColor Red
        exit 1
    }
}
function Convert-FlyJson {
    param([string]$Text)
    $trimmed = ""
    if ($null -ne $Text) { $trimmed = $Text.Trim() }
    if (-not $trimmed -or $trimmed -eq "[]" -or $trimmed -eq "null") { return @() }
    @($trimmed | ConvertFrom-Json)
}
function Get-NewestRelease {
    param([string]$JsonText)
    $rows = @(Convert-FlyJson $JsonText)
    $chosen = $null
    foreach ($row in $rows) {
        if ($null -eq $row) { continue }
        $verProp = $row.PSObject.Properties["Version"]
        if (-not $verProp) { $verProp = $row.PSObject.Properties["version"] }
        if (-not $verProp) { continue }
        $ver = [int]$verProp.Value
        $statusProp = $row.PSObject.Properties["Status"]
        if (-not $statusProp) { $statusProp = $row.PSObject.Properties["status"] }
        $statusText = ""
        if ($statusProp) { $statusText = [string]$statusProp.Value }
        if ($null -eq $chosen -or $ver -gt $chosen.Version) {
            $chosen = [pscustomobject]@{ Version = $ver; Status = $statusText }
        }
    }
    $chosen
}

# ----- 0. The one address must already answer ------------------------------
# fly.toml sets PUBLIC_URL = https://api.archhub.io, so every company invite,
# Google return and cockpit claim this deploy builds points there. Refuse to
# deploy unless that address answers /healthz with 200 over TLS on a live
# certificate (no certificate bypass here, on purpose).
Step 0 "Checking $PublicHealthUrl answers 200 over TLS"
$publicHealth = $PublicHealthUrl
try {
    $publicResp = Invoke-WebRequest -Uri $publicHealth -TimeoutSec 15 -UseBasicParsing -MaximumRedirection 0
} catch {
    Write-Host "    REFUSED: $publicHealth did not answer over TLS: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    Attach the certificate first (flyctl certs add api.archhub.io -a $AppName) and wait until it is issued." -ForegroundColor Red
    exit 1
}
if ($publicResp.StatusCode -ne 200) {
    Write-Host "    REFUSED: $publicHealth answered HTTP $($publicResp.StatusCode), not 200." -ForegroundColor Red
    exit 1
}
Done "api.archhub.io is live: $($publicResp.Content)"

# ----- 1. Ensure flyctl --------------------------------------------------
Step 1 "Ensuring flyctl is installed"
$fly = Get-Command flyctl -ErrorAction SilentlyContinue
if (-not $fly) {
    Write-Host "    flyctl not found. Installing via PowerShell installer..."
    iwr https://fly.io/install.ps1 -useb | iex
    $env:Path = "$env:USERPROFILE\.fly\bin;$env:Path"
    $fly = Get-Command flyctl -ErrorAction SilentlyContinue
    if (-not $fly) {
        Write-Error "flyctl install failed. Manual install: https://fly.io/docs/flyctl/install/"
        exit 1
    }
}
Done "flyctl found at $($fly.Source)"

# ----- 2. Sign in --------------------------------------------------------
Step 2 "Verifying Fly.io sign-in"
$who = Get-FlyResult -FlyArgs @("auth", "whoami")
if ($who.ExitCode -ne 0) {
    if ($NonInteractive) {
        Write-Host "REFUSED: sign-in failed: $(Get-FlyFailureText $who)" -ForegroundColor Red
        Write-Host "flyctl auth login"
        exit 1
    }
    Write-Host "    Running flyctl auth login..."
    $login = Get-FlyResult -FlyArgs @("auth", "login")
    Stop-IfFlyFailed "sign-in" $login
    $who = Get-FlyResult -FlyArgs @("auth", "whoami")
    Stop-IfFlyFailed "sign-in" $who
}
Done "signed in as $($who.StdOut.Trim())"

# ----- 3. App + region ---------------------------------------------------
Step 3 "App $AppName in region $Region"
$apps = Get-FlyResult -FlyArgs @("apps", "list", "--json")
Stop-IfFlyFailed "apps" $apps
$existing = @(Convert-FlyJson $apps.StdOut)
$found = $existing | Where-Object { $_ -and $_.Name -eq $AppName }
if (-not $found) {
    Write-Host "    Creating app $AppName..."
    $created = Get-FlyResult -FlyArgs @("apps", "create", $AppName, "--org", "personal")
    Stop-IfFlyFailed "create-app" $created
}
Done "app ready"

# ----- 4. Volume ---------------------------------------------------------
Step 4 "Persistent volume archhub_data (1GB) in $Region"
$volsResult = Get-FlyResult -FlyArgs @("volumes", "list", "-a", $AppName, "--json")
Stop-IfFlyFailed "volumes" $volsResult
$vols = @(Convert-FlyJson $volsResult.StdOut)
$volExists = $vols | Where-Object { $_ -and $_.Name -eq "archhub_data" }
if (-not $volExists) {
    Write-Host "    Creating volume..."
    $createdVol = Get-FlyResult -FlyArgs @("volumes", "create", "archhub_data", "--size", "1", "--region", $Region, "-a", $AppName, "--yes")
    Stop-IfFlyFailed "create-volume" $createdVol
}
Done "volume ready"

# ----- 5. Secrets --------------------------------------------------------
if (-not $SkipSecrets) {
    Step 5 "Setting Fly secrets"
    $secrets = @{}
    if ($SecretsFile -and (Test-Path $SecretsFile)) {
        Get-Content $SecretsFile | ForEach-Object {
            if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)\s*$') {
                $secrets[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
            }
        }
        Done "loaded $($secrets.Count) secret(s) from $SecretsFile"
    } else {
        Write-Host "    No -SecretsFile passed; interactive prompts for each missing var."
        $required = @(
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PRICE_SOLO", "STRIPE_PRICE_STUDIO", "STRIPE_PRICE_FIRM",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY", "GOOGLE_API_KEY",
            "RESEND_API_KEY",
            "JWT_SECRET"
        )
        foreach ($k in $required) {
            $listed = Get-FlyResult -FlyArgs @("secrets", "list", "-a", $AppName, "--json")
            Stop-IfFlyFailed "secrets-list" $listed
            $existing = @(Convert-FlyJson $listed.StdOut)
            if ($existing | Where-Object { $_ -and $_.Name -eq $k }) {
                Write-Host "    $k already set — skip"
                continue
            }
            $v = Read-Host "    Enter $k (leave blank to skip)"
            if ($v) { $secrets[$k] = $v }
        }
    }
    if ($secrets.Count -gt 0) {
        $flyArgs = @("secrets", "set", "-a", $AppName)
        foreach ($k in $secrets.Keys) {
            $flyArgs += "$k=$($secrets[$k])"
        }
        $written = Get-FlyResult -FlyArgs $flyArgs
        Stop-IfFlyFailed "secrets-set" $written
        Done "$($secrets.Count) secret(s) written"
    } else {
        Warn "no new secrets set; deploy will inherit existing config"
    }
}

# ----- 6. Deploy ---------------------------------------------------------
Step 6 "Deploying $AppName"
$flyToml  = Join-Path $PSScriptRoot "fly.toml"
# Include the one desktop defaults module in the relay image.
$context  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$before = Get-FlyResult -FlyArgs @("releases", "-a", $AppName, "--json")
Stop-IfFlyFailed "releases" $before
$beforeNewest = Get-NewestRelease $before.StdOut
$beforeVersion = 0
if ($beforeNewest) { $beforeVersion = $beforeNewest.Version }
$dockerfile = Join-Path $PSScriptRoot "Dockerfile"
$ignorefile = Join-Path $PSScriptRoot "dockerignore.txt"
$deployed = Get-FlyResult -FlyArgs @("deploy", $context, "--config", $flyToml, "--dockerfile", $dockerfile, "--ignorefile", $ignorefile, "-a", $AppName)
Stop-IfFlyFailed "deploy" $deployed
$after = Get-FlyResult -FlyArgs @("releases", "-a", $AppName, "--json")
Stop-IfFlyFailed "releases" $after
$newest = Get-NewestRelease $after.StdOut
$live = $false
if ($newest -and $newest.Version -gt $beforeVersion -and $newest.Status -eq "complete") { $live = $true }
if (-not $live) {
    $shown = "no release"
    if ($newest) { $shown = "version $($newest.Version) status $($newest.Status); previous version $beforeVersion" }
    Write-Host "REFUSED: release failed: $shown" -ForegroundColor Red
    exit 1
}
Done "deployed release v$($newest.Version) ($($newest.Status))"

# ----- 7. Health check --------------------------------------------------
Step 7 "Health check"
Start-Sleep -Seconds 5
$healthUrl = "https://api.archhub.io/healthz"
try {
    $resp = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 15 -UseBasicParsing
    if ($resp.StatusCode -eq 200) {
        Done "healthy: $($resp.Content)"
    } else {
        Warn "got HTTP $($resp.StatusCode)"
    }
} catch {
    Warn "health check threw: $_. App may still be starting; check 'flyctl logs -a $AppName'."
}

# ----- 8. DNS attach (optional) -----------------------------------------
if ($DnsAttach) {
    Step 8 "Attaching custom domain api.archhub.io"
    $certs = Get-FlyResult -FlyArgs @("certs", "add", "api.archhub.io", "-a", $AppName)
    Stop-IfFlyFailed "certs" $certs
    Write-Host "    Add these DNS records at your DNS provider:"
    $ips = Get-FlyResult -FlyArgs @("ips", "list", "-a", $AppName)
    Stop-IfFlyFailed "ips" $ips
    Write-Host $ips.StdOut
    Write-Host ""
    Write-Host "    Add an A record: api.archhub.io  →  <v4 from above>"
    Write-Host "    Add an AAAA record: api.archhub.io  →  <v6 from above>"
}

# ----- 9. Stripe webhook reminder ----------------------------------------
Step 9 "Stripe webhook registration (manual step)"
Write-Host ""
Write-Host "  Open Stripe Dashboard → Developers → Webhooks → Add endpoint:" -ForegroundColor Yellow
Write-Host "    URL:    https://api.archhub.io/v1/webhooks/stripe" -ForegroundColor Yellow
Write-Host "    Events: checkout.session.completed" -ForegroundColor Yellow
Write-Host "            customer.subscription.updated" -ForegroundColor Yellow
Write-Host "            customer.subscription.deleted" -ForegroundColor Yellow
Write-Host "            invoice.payment_failed" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Copy the new endpoint's signing secret (whsec_...) and rerun:" -ForegroundColor Yellow
Write-Host "    flyctl secrets set STRIPE_WEBHOOK_SECRET=whsec_... -a $AppName" -ForegroundColor Yellow
Write-Host ""
Write-Host "Done. Cloud backend deployed at https://api.archhub.io" -ForegroundColor Green
