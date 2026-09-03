[CmdletBinding()]
param(
    [switch]$ValidateOnly,
    [switch]$SkipInstaller,
    [switch]$Sign,
    [string]$PythonExe = "python",
    [string]$IsccPath = "",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$packageDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $packageDir "..\..")).Path
$manifestPath = Join-Path $packageDir "package-manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$version = [string]$manifest.product_version
$runtime = [string]$manifest.runtime
$schema = [string]$manifest.universal_application_schema_version
if ($runtime -ne "universal-cell") {
    throw "Package runtime $runtime is not the Universal Cell runtime"
}
$applicationPath = Join-Path $projectRoot "nodelang\universal_application.py"
$applicationText = Get-Content -LiteralPath $applicationPath -Raw
$schemaMatch = [regex]::Match(
    $applicationText, 'UNIVERSAL_APPLICATION_SCHEMA_VERSION\s*=\s*[''"]([^''"]+)[''"]')
if (-not $schemaMatch.Success) { throw "Cannot read UNIVERSAL_APPLICATION_SCHEMA_VERSION" }
if ($schemaMatch.Groups[1].Value -ne $schema) {
    throw "Package schema $schema does not match Universal Cell application schema $($schemaMatch.Groups[1].Value)"
}

& (Join-Path $packageDir "Test-SourcePortability.ps1") -SourceRoot (Join-Path $projectRoot "nodelang")
if (-not $?) { throw "Source portability gate failed" }

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $env:LOCALAPPDATA "ArchHub\packaging\$version"
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$bundleRoot = Join-Path $OutputRoot "bundle"
$workRoot = Join-Path $OutputRoot "work"
$installerRoot = Join-Path $OutputRoot "installer"
$venvRoot = Join-Path $OutputRoot "venv"

$isccCandidates = @(
    $IsccPath,
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$iscc = $isccCandidates | Select-Object -First 1

if ($ValidateOnly) {
    [pscustomobject]@{
        product_version = $version
        runtime = $runtime
        universal_application_schema_version = $schema
        output_root = $OutputRoot
        pyinstaller_installed = [bool](Get-Command pyinstaller -ErrorAction SilentlyContinue)
        inno_setup_installed = [bool]$iscc
        signtool_installed = [bool](Get-Command signtool.exe -ErrorAction SilentlyContinue)
        source_portable = $true
    } | ConvertTo-Json
    exit 0
}

New-Item -ItemType Directory -Force -Path $OutputRoot, $bundleRoot, $workRoot, $installerRoot | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $venvRoot "Scripts\python.exe"))) {
    & $PythonExe -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "Failed to create packaging virtual environment" }
}
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
& $venvPython -m pip install --disable-pip-version-check --no-input -r (Join-Path $packageDir "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "Failed to install pinned packaging dependencies" }

$env:ARCHHUB_PROJECT_ROOT = $projectRoot
& $venvPython -m PyInstaller --noconfirm --clean `
    --distpath $bundleRoot --workpath $workRoot `
    (Join-Path $packageDir "ArchHub.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
$bundleDir = Join-Path $bundleRoot "ArchHub"
$executable = Join-Path $bundleDir "ArchHub.exe"
if (-not (Test-Path -LiteralPath $executable)) { throw "Bundled ArchHub.exe was not produced" }
Copy-Item -LiteralPath (Join-Path $packageDir "Launch-ArchHub.vbs") -Destination $bundleDir -Force

if ($Sign) { & (Join-Path $packageDir "sign.ps1") -Path $executable }
if ($SkipInstaller) {
    Write-Output "Bundle built: $bundleDir"
    exit 0
}
if (-not $iscc) { throw "Inno Setup 6 is required to build the installer; pass -IsccPath after installing it" }

& $iscc "/DAppVersion=$version" "/DBundleDir=$bundleDir" `
    "/DOutputDir=$installerRoot" (Join-Path $packageDir "setup.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE" }
$installer = Join-Path $installerRoot "ArchHub-Setup-$version-x64.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer was not produced: $installer" }
if ($Sign) { & (Join-Path $packageDir "sign.ps1") -Path $installer }
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$installer.sha256" -Value "$hash *$(Split-Path -Leaf $installer)" -Encoding ascii -NoNewline
Write-Output "Installer built: $installer"
