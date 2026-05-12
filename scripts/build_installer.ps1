# scripts/build_installer.ps1 — One-command installer build.
#
# Wraps the Inno Setup compile step + sha256 checksum + optional
# GitHub release upload. Run from any directory; resolves repo root
# automatically.
#
# Usage:
#   .\scripts\build_installer.ps1                   # build only
#   .\scripts\build_installer.ps1 -Release          # build + gh release
#   .\scripts\build_installer.ps1 -Release -Sign    # build + sign + release
#
# Prerequisites:
#   - Inno Setup 6 installed (https://jrsoftware.org/isdl.php)
#   - Optional for -Release: gh CLI logged in
#   - Optional for -Sign: signtool.exe in PATH + a code-signing cert
#                          configured via SIGNING_CERT_THUMBPRINT env var

[CmdletBinding()]
param(
    [switch]$Release,
    [switch]$Sign,
    [string]$IsccPath = ""
)

$ErrorActionPreference = "Stop"

# Resolve repo root from the script's location.
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Resolve-Path (Join-Path $ScriptRoot "..")
$IssFile    = Join-Path $RepoRoot "installer\setup.iss"
$DistDir    = Join-Path $RepoRoot "dist"
$VersionFile = Join-Path $RepoRoot "VERSION"

if (-not (Test-Path $IssFile)) {
    Write-Error "Inno script not found: $IssFile"
    exit 1
}
if (-not (Test-Path $VersionFile)) {
    Write-Error "VERSION file missing"
    exit 1
}

$Version = (Get-Content $VersionFile -Raw).Trim()
Write-Host "Building ArchHub v$Version installer..." -ForegroundColor Cyan

# Locate iscc.exe (Inno Setup Compiler).
if (-not $IsccPath) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { $IsccPath = $p; break }
    }
}
if (-not $IsccPath -or -not (Test-Path $IsccPath)) {
    Write-Error "Inno Setup 6 not found. Install from https://jrsoftware.org/isdl.php or pass -IsccPath"
    exit 1
}

# Ensure dist exists.
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null

# Compile.
Push-Location (Split-Path $IssFile -Parent)
try {
    & $IsccPath $IssFile
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Inno Setup compile failed (exit $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

$Setup = Get-ChildItem -Path $DistDir -Filter "ArchHub-Setup-$Version*.exe" | Select-Object -First 1
if (-not $Setup) {
    Write-Error "Expected installer not found in $DistDir"
    exit 1
}
Write-Host "Built: $($Setup.FullName)" -ForegroundColor Green

# Optional Authenticode signing.
if ($Sign) {
    $Thumbprint = $env:SIGNING_CERT_THUMBPRINT
    if (-not $Thumbprint) {
        Write-Warning "SIGNING_CERT_THUMBPRINT env var not set — skipping sign step"
    } else {
        Write-Host "Signing with cert thumbprint $Thumbprint..." -ForegroundColor Cyan
        $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
        if (-not $signtool) {
            Write-Warning "signtool.exe not on PATH — skipping sign step"
        } else {
            & $signtool sign /sha1 $Thumbprint /fd SHA256 `
                /tr "http://timestamp.digicert.com" /td SHA256 `
                $Setup.FullName
        }
    }
}

# Compute sha256 next to the .exe.
$Hash = (Get-FileHash -Algorithm SHA256 $Setup.FullName).Hash.ToLower()
$HashFile = "$($Setup.FullName).sha256"
"$Hash *$($Setup.Name)" | Out-File -FilePath $HashFile -Encoding ascii -NoNewline
Write-Host "SHA256: $Hash" -ForegroundColor Yellow

# Optional GitHub release upload.
if ($Release) {
    $gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
    if (-not $gh) {
        Write-Warning "gh CLI not found — skipping release upload"
    } else {
        Write-Host "Creating GitHub release v$Version..." -ForegroundColor Cyan
        $NotesFile = Join-Path $RepoRoot "CHANGELOG.md"
        $TagExists = & $gh release view "v$Version" 2>$null
        if ($TagExists) {
            Write-Host "Release v$Version exists — uploading assets only" -ForegroundColor Yellow
            & $gh release upload "v$Version" $Setup.FullName $HashFile --clobber
        } else {
            & $gh release create "v$Version" $Setup.FullName $HashFile `
                --title "ArchHub v$Version" `
                --notes-file $NotesFile
        }
        Write-Host "Release uploaded." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Done. Installer at:" -ForegroundColor Green
Write-Host "  $($Setup.FullName)"
Write-Host "  $HashFile"
