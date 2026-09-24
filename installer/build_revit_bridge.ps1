[CmdletBinding()]
param(
    # bridges/sources of the verified release snapshot (never a live checkout).
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    # New directory; receives bridges/revit/<year>/ and HOST_ARTIFACTS.json.
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    # Source revision the payload was built from (40-64 lowercase hex).
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40,64}$')]
    [string]$SourceRevision,
    # The independent custody review of THIS authenticated broker source. Without
    # it the manifests say so and setup refuses to register them
    # (nodelang/host_broker_installation.py); this script never invents one.
    [string]$BrokerReviewPath,
    [string]$DotnetPath
)

# Build the authenticated ArchHub Revit add-in once per Revit year installed on
# this build machine, against that year's own RevitAPI.dll, and write the
# archhub-host-artifacts/v1 manifest setup verifies before it registers the
# add-in for that year. A year that is not installed here gets no payload:
# its host API pins could not be taken from a real installation.
$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false, $true)

$source = (Resolve-Path -LiteralPath $SourceRoot).Path
$output = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $output) { throw 'OutputRoot must be new.' }
if (-not $DotnetPath) {
    $DotnetPath = (Get-Command dotnet.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
$dotnet = (Resolve-Path -LiteralPath $DotnetPath).Path

$review = $null
if ($BrokerReviewPath) {
    $reviewFile = (Resolve-Path -LiteralPath $BrokerReviewPath).Path
    $review = [ordered]@{
        eligibility   = 'reviewed-authenticated-broker'
        review_sha256 = (Get-FileHash -LiteralPath $reviewFile -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-Pin([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        size   = [int64]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-Framework([int]$Year) {
    if ($Year -le 2020) { return 'net47' }
    if ($Year -le 2024) { return 'net48' }
    return 'net8.0-windows'
}

New-Item -ItemType Directory -Path $output | Out-Null
$index = [ordered]@{ schema = 'archhub-host-artifacts-index/v1'; source_revision = $SourceRevision; revit = [ordered]@{} }
$autodesk = Join-Path $env:ProgramFiles 'Autodesk'
foreach ($year in 2020..2030) {
    $hostDir = Join-Path $autodesk "Revit $year"
    $api = Join-Path $hostDir 'RevitAPI.dll'
    $apiUi = Join-Path $hostDir 'RevitAPIUI.dll'
    if (-not ((Test-Path -LiteralPath $api -PathType Leaf) -and (Test-Path -LiteralPath $apiUi -PathType Leaf))) { continue }
    $framework = Get-Framework $year
    # A fresh copy per year: restore state for one framework never leaks into another.
    $work = Join-Path $output ".build-$year"
    Copy-Item -LiteralPath $source -Destination $work -Recurse
    $payload = Join-Path $output "bridges/revit/$year"
    New-Item -ItemType Directory -Path $payload -Force | Out-Null
    foreach ($project in 'revit_mcp_core/RevitMCPCore.csproj', 'revit_mcp/RevitMCP.csproj') {
        $properties = @("-p:TargetFramework=$framework", "-p:RevitYear=$year", "-p:RevitInstallDir=$hostDir")
        & $dotnet restore (Join-Path $work $project) @properties -v q
        if ($LASTEXITCODE -ne 0) { throw "Restore failed for $project (Revit $year)." }
        & $dotnet build (Join-Path $work $project) --no-restore -c Release -nologo -v q @properties -o $payload
        if ($LASTEXITCODE -ne 0) { throw "Build failed for $project (Revit $year)." }
    }
    Remove-Item -LiteralPath $work -Recurse -Force
    # Only the loadable closure ships; build byproducts do not.
    Get-ChildItem -LiteralPath $payload -File | Where-Object { $_.Extension -in '.pdb', '.xml' } | Remove-Item -Force
    $files = @(Get-ChildItem -LiteralPath $payload -File | Sort-Object Name | ForEach-Object {
        $pin = Get-Pin $_.FullName
        [ordered]@{ path = "bridges/revit/$year/$($_.Name)"; size = $pin.size; sha256 = $pin.sha256 }
    })
    $manifest = [ordered]@{
        schema          = 'archhub-host-artifacts/v1'
        source_revision = $SourceRevision
        host            = 'revit'
        host_version    = "$year"
        assembly        = "bridges/revit/$year/RevitMCP.dll"
        files           = $files
        host_api        = [ordered]@{ 'RevitAPI.dll' = (Get-Pin $api); 'RevitAPIUI.dll' = (Get-Pin $apiUi) }
    }
    if ($review) {
        $manifest.runtime_closure_reviewed = $true
        $manifest.activation = $review
    }
    $manifestPath = Join-Path $payload 'host-artifacts.json'
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 6) + "`n", $utf8)
    $index.revit["$year"] = [ordered]@{
        manifest = "bridges/revit/$year/host-artifacts.json"
        sha256   = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        framework = $framework
        reviewed = [bool]$review
    }
}
[IO.File]::WriteAllText((Join-Path $output 'HOST_ARTIFACTS.json'), ($index | ConvertTo-Json -Depth 6) + "`n", $utf8)
Write-Output ("Revit add-in built for: " + (($index.revit.Keys | Sort-Object) -join ', '))
