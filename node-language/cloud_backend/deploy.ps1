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

[CmdletBinding()]
param(
    [string]$SecretsFile = "",
    [switch]$SkipSecrets,
    [switch]$DnsAttach,
    [string]$AppName = "archhub-cloud",
    [string]$Region  = "ord"
)

$ErrorActionPreference = "Stop"

function Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n] $msg" -ForegroundColor Cyan
}
function Done($msg) { Write-Host "    OK $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !! $msg" -ForegroundColor Yellow }

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
$signedIn = $false
try {
    flyctl auth whoami 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $signedIn = $true }
} catch {}
if (-not $signedIn) {
    Write-Host "    Running flyctl auth login..."
    flyctl auth login
}
Done "signed in as $(flyctl auth whoami)"

# ----- 3. App + region ---------------------------------------------------
Step 3 "App $AppName in region $Region"
$existing = flyctl apps list --json 2>$null | ConvertFrom-Json
$found = $existing | Where-Object { $_.Name -eq $AppName }
if (-not $found) {
    Write-Host "    Creating app $AppName..."
    flyctl apps create $AppName --org personal 2>&1
}
Done "app ready"

# ----- 4. Volume ---------------------------------------------------------
Step 4 "Persistent volume archhub_data (1GB) in $Region"
$vols = flyctl volumes list -a $AppName --json 2>$null | ConvertFrom-Json
$volExists = $vols | Where-Object { $_.Name -eq "archhub_data" }
if (-not $volExists) {
    Write-Host "    Creating volume..."
    flyctl volumes create archhub_data --size 1 --region $Region -a $AppName --yes
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
            $existing = flyctl secrets list -a $AppName --json 2>$null | ConvertFrom-Json
            if ($existing | Where-Object { $_.Name -eq $k }) {
                Write-Host "    $k already set — skip"
                continue
            }
            $v = Read-Host "    Enter $k (leave blank to skip)"
            if ($v) { $secrets[$k] = $v }
        }
    }
    if ($secrets.Count -gt 0) {
        $args = @("secrets", "set", "-a", $AppName)
        foreach ($k in $secrets.Keys) {
            $args += "$k=$($secrets[$k])"
        }
        & flyctl @args
        Done "$($secrets.Count) secret(s) written"
    } else {
        Warn "no new secrets set; deploy will inherit existing config"
    }
}

# ----- 6. Deploy ---------------------------------------------------------
Step 6 "Deploying $AppName"
$repoRoot = Split-Path -Parent $PSScriptRoot
$flyToml  = Join-Path $repoRoot "cloud_backend\fly.toml"
flyctl deploy --config $flyToml --dockerfile (Join-Path $repoRoot "cloud_backend\Dockerfile") -a $AppName
Done "deployed"

# ----- 7. Health check --------------------------------------------------
Step 7 "Health check"
Start-Sleep -Seconds 5
$healthUrl = "https://$AppName.fly.dev/healthz"
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
    Step 8 "Attaching custom domain cloud.archhub.io"
    flyctl certs add cloud.archhub.io -a $AppName 2>&1
    Write-Host "    Add these DNS records at your DNS provider:"
    flyctl ips list -a $AppName
    Write-Host ""
    Write-Host "    Add an A record: cloud.archhub.io  →  <v4 from above>"
    Write-Host "    Add an AAAA record: cloud.archhub.io  →  <v6 from above>"
}

# ----- 9. Stripe webhook reminder ----------------------------------------
Step 9 "Stripe webhook registration (manual step)"
Write-Host ""
Write-Host "  Open Stripe Dashboard → Developers → Webhooks → Add endpoint:" -ForegroundColor Yellow
Write-Host "    URL:    https://$AppName.fly.dev/v1/webhooks/stripe" -ForegroundColor Yellow
Write-Host "    Events: checkout.session.completed" -ForegroundColor Yellow
Write-Host "            customer.subscription.updated" -ForegroundColor Yellow
Write-Host "            customer.subscription.deleted" -ForegroundColor Yellow
Write-Host "            invoice.payment_failed" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Copy the new endpoint's signing secret (whsec_...) and rerun:" -ForegroundColor Yellow
Write-Host "    flyctl secrets set STRIPE_WEBHOOK_SECRET=whsec_... -a $AppName" -ForegroundColor Yellow
Write-Host ""
Write-Host "Done. Cloud backend deployed at https://$AppName.fly.dev" -ForegroundColor Green
