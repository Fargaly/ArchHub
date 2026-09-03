# scripts/sign_installer.ps1 — Code-signing dispatcher for the ArchHub installer.
#
# Two code-signing paths are supported, selected purely by which
# environment variables are present at runtime. Nothing about the
# .iss file or the rest of the build needs to change when you flip
# between them — wire up the secrets, push a tag, you're signed.
#
# ── PATH A: Azure Trusted Signing (preferred — $9/mo, no token) ─────
#   Microsoft's hosted code-signing service. Uses Azure.CodeSigning.Dlib,
#   a signtool plug-in that proxies the signing request to a cert
#   profile that lives inside an Entra-protected Azure resource. No
#   .pfx file, no hardware token, no manual cert rotation.
#
#   Selected when AZURE_TENANT_ID is set. All six env vars below must
#   then be present or the script aborts with exit 1.
#       AZURE_TENANT_ID
#       AZURE_CLIENT_ID
#       AZURE_CLIENT_SECRET
#       AZURE_TRUSTED_SIGNING_ENDPOINT          # e.g. https://eus.codesigning.azure.net
#       AZURE_TRUSTED_SIGNING_ACCOUNT_NAME
#       AZURE_TRUSTED_SIGNING_CERT_PROFILE
#
#   Reference: https://learn.microsoft.com/en-us/azure/trusted-signing/quickstart-signing-windows-installer
#
# ── PATH B: Classic .pfx (Sectigo / SSL.com / DigiCert EV or OV) ────
#   Standard signtool.exe sign /f cert.pfx /p <password>. Used when
#   you've bought a cert from a traditional CA and exported it as a
#   password-protected .pfx.
#
#   Selected when ARCHHUB_SIGN_CERT_PATH is set (and Path A wasn't).
#       ARCHHUB_SIGN_CERT_PATH       # absolute path to .pfx
#       ARCHHUB_SIGN_CERT_PASSWORD   # optional, empty for unprotected
#
# ── PATH C: No signing ──────────────────────────────────────────────
#   Neither path configured. The script logs "unsigned — no signing
#   config" and exits 0 so the build still succeeds. This is the
#   default state while we don't yet have a cert; the produced
#   installer triggers SmartScreen but is still functional.
#
# Compatible with Windows PowerShell 5.1 — no Pwsh-only syntax.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    # Optional override — defaults to DigiCert's RFC 3161 timestamp server.
    # The same URL works for both Azure Trusted Signing and classic .pfx.
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InstallerPath)) {
    Write-Error "Installer not found at: $InstallerPath"
    exit 1
}

$InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
$installerName = Split-Path -Leaf $InstallerPath

# ── Locate signtool.exe ────────────────────────────────────────────
# signtool ships with the Windows SDK and is not on PATH by default
# on GitHub-hosted runners. We probe PATH first, then the common
# Windows Kits locations, then bail with a clear message.
function Resolve-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $kitsRoot = "C:\Program Files (x86)\Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitsRoot) {
        $candidates = Get-ChildItem -Path $kitsRoot -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending
        if ($candidates -and $candidates.Count -gt 0) { return $candidates[0].FullName }
    }
    return $null
}

# ── PATH A: Azure Trusted Signing ──────────────────────────────────
function Invoke-AzureTrustedSigning {
    param([string]$ExePath, [string]$Timestamp)

    Write-Host "Signing via Azure Trusted Signing..." -ForegroundColor Cyan

    # Validate the full Azure env-var set. If the user set
    # AZURE_TENANT_ID but forgot one of the others, fail loudly
    # instead of silently falling through to "unsigned" — at this
    # point they clearly want signing, just misconfigured.
    $required = @(
        'AZURE_TENANT_ID',
        'AZURE_CLIENT_ID',
        'AZURE_CLIENT_SECRET',
        'AZURE_TRUSTED_SIGNING_ENDPOINT',
        'AZURE_TRUSTED_SIGNING_ACCOUNT_NAME',
        'AZURE_TRUSTED_SIGNING_CERT_PROFILE'
    )
    $missing = @()
    foreach ($name in $required) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($value)) { $missing += $name }
    }
    if ($missing.Count -gt 0) {
        Write-Error ("Azure Trusted Signing selected (AZURE_TENANT_ID is set) but missing required env vars: " + ($missing -join ', '))
        return 1
    }

    $signtool = Resolve-SignTool
    if (-not $signtool) {
        Write-Error "signtool.exe not found. Install the Windows 10/11 SDK or add signtool to PATH."
        return 1
    }
    Write-Host "  signtool: $signtool" -ForegroundColor DarkGray

    # ── Install Azure.CodeSigning.Dlib if not already cached ───────
    # The dlib is a signtool plug-in distributed via NuGet. We cache
    # it under %LOCALAPPDATA% so repeated CI runs in the same job
    # don't re-download, and local-dev runs don't either.
    $dlibCacheRoot = Join-Path $env:LOCALAPPDATA "ArchHub\TrustedSigning"
    $dlibPackageId = "Microsoft.Trusted.Signing.Client"
    $dlibPackageVersion = "1.0.60"
    $dlibCacheDir = Join-Path $dlibCacheRoot "$dlibPackageId.$dlibPackageVersion"
    $dlibPath = Join-Path $dlibCacheDir "bin\x64\Azure.CodeSigning.Dlib.dll"

    if (-not (Test-Path -LiteralPath $dlibPath)) {
        Write-Host "  Downloading $dlibPackageId $dlibPackageVersion..." -ForegroundColor DarkGray
        New-Item -ItemType Directory -Force -Path $dlibCacheRoot | Out-Null
        $nupkgUrl = "https://www.nuget.org/api/v2/package/$dlibPackageId/$dlibPackageVersion"
        $nupkgPath = Join-Path $env:TEMP "$dlibPackageId.$dlibPackageVersion.nupkg"
        try {
            Invoke-WebRequest -Uri $nupkgUrl -OutFile $nupkgPath -UseBasicParsing
        } catch {
            Write-Error "Failed to download $dlibPackageId from NuGet: $($_.Exception.Message)"
            return 1
        }
        # A .nupkg is a renamed .zip — Expand-Archive only accepts .zip,
        # so copy/rename rather than relying on extension sniffing.
        $zipPath = [System.IO.Path]::ChangeExtension($nupkgPath, '.zip')
        Copy-Item -LiteralPath $nupkgPath -Destination $zipPath -Force
        Expand-Archive -Path $zipPath -DestinationPath $dlibCacheDir -Force
        Remove-Item -LiteralPath $nupkgPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $dlibPath)) {
        Write-Error "Azure.CodeSigning.Dlib.dll not found after install at: $dlibPath"
        return 1
    }
    Write-Host "  dlib:     $dlibPath" -ForegroundColor DarkGray

    # ── Write the dlib metadata JSON ───────────────────────────────
    # signtool /dlib passes this file path to the plug-in; the
    # plug-in reads it to discover the endpoint, account, and cert
    # profile. The Entra credentials come from environment variables
    # picked up by the underlying Azure.Identity DefaultAzureCredential
    # chain (EnvironmentCredential -> client-secret flow).
    $metadata = [pscustomobject]@{
        Endpoint            = $env:AZURE_TRUSTED_SIGNING_ENDPOINT
        CodeSigningAccountName = $env:AZURE_TRUSTED_SIGNING_ACCOUNT_NAME
        CertificateProfileName = $env:AZURE_TRUSTED_SIGNING_CERT_PROFILE
        CorrelationId       = [guid]::NewGuid().ToString()
    }
    $metadataPath = Join-Path $env:TEMP "archhub-trusted-signing-metadata.json"
    $metadata | ConvertTo-Json -Depth 4 | Out-File -FilePath $metadataPath -Encoding utf8 -Force

    # Azure.Identity reads these without us having to pass them on
    # the signtool command line. Re-export to be defensive in case
    # the caller set them only for the parent process.
    $env:AZURE_TENANT_ID     = $env:AZURE_TENANT_ID
    $env:AZURE_CLIENT_ID     = $env:AZURE_CLIENT_ID
    $env:AZURE_CLIENT_SECRET = $env:AZURE_CLIENT_SECRET

    Write-Host "  endpoint: $($metadata.Endpoint)" -ForegroundColor DarkGray
    Write-Host "  account:  $($metadata.CodeSigningAccountName)" -ForegroundColor DarkGray
    Write-Host "  profile:  $($metadata.CertificateProfileName)" -ForegroundColor DarkGray

    & $signtool sign `
        /v `
        /debug `
        /fd SHA256 `
        /tr $Timestamp `
        /td SHA256 `
        /dlib $dlibPath `
        /dmdf $metadataPath `
        $ExePath
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Error "signtool (Azure Trusted Signing) failed for $installerName with exit code $code"
        return $code
    }
    Write-Host "Signed $installerName via Azure Trusted Signing." -ForegroundColor Green
    return 0
}

# ── PATH B: Classic .pfx ──────────────────────────────────────────
function Invoke-PfxSigning {
    param([string]$ExePath, [string]$Timestamp)

    Write-Host "Signing with .pfx certificate..." -ForegroundColor Cyan

    $pfxPath = $env:ARCHHUB_SIGN_CERT_PATH
    if (-not (Test-Path -LiteralPath $pfxPath)) {
        Write-Error "ARCHHUB_SIGN_CERT_PATH points to a missing file: $pfxPath"
        return 1
    }

    $signtool = Resolve-SignTool
    if (-not $signtool) {
        Write-Error "signtool.exe not found. Install the Windows 10/11 SDK or add signtool to PATH."
        return 1
    }
    Write-Host "  signtool: $signtool" -ForegroundColor DarkGray
    Write-Host "  pfx:      $pfxPath" -ForegroundColor DarkGray

    # Build the argument list dynamically so we don't leak an empty
    # /p '' into the command line when the .pfx is unprotected.
    $args = @(
        'sign',
        '/v',
        '/fd', 'SHA256',
        '/tr', $Timestamp,
        '/td', 'SHA256',
        '/f',  $pfxPath
    )
    $pfxPassword = $env:ARCHHUB_SIGN_CERT_PASSWORD
    if (-not [string]::IsNullOrEmpty($pfxPassword)) {
        $args += @('/p', $pfxPassword)
    }
    $args += $ExePath

    & $signtool @args
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Error "signtool (.pfx) failed for $installerName with exit code $code"
        return $code
    }
    Write-Host "Signed $installerName with .pfx cert." -ForegroundColor Green
    return 0
}

# ── Path selection ─────────────────────────────────────────────────
# AZURE_TENANT_ID wins over ARCHHUB_SIGN_CERT_PATH — if both are set
# we deliberately ignore the .pfx because the cloud cert is the
# preferred path going forward.
$azureSelected = -not [string]::IsNullOrWhiteSpace($env:AZURE_TENANT_ID)
$pfxSelected   = -not [string]::IsNullOrWhiteSpace($env:ARCHHUB_SIGN_CERT_PATH)

if ($azureSelected) {
    $result = Invoke-AzureTrustedSigning -ExePath $InstallerPath -Timestamp $TimestampUrl
    exit $result
}
elseif ($pfxSelected) {
    $result = Invoke-PfxSigning -ExePath $InstallerPath -Timestamp $TimestampUrl
    exit $result
}
else {
    Write-Host "unsigned - no signing config (AZURE_TENANT_ID / ARCHHUB_SIGN_CERT_PATH not set)" -ForegroundColor Yellow
    Write-Host "Installer will still publish; SmartScreen will show 'Unknown Publisher' until a cert is configured." -ForegroundColor DarkGray
    exit 0
}
