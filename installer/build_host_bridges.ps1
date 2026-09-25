[CmdletBinding()]
param(
    # bridges/sources of the verified release snapshot (never a live checkout).
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    # New directory; receives bridges/revit/<year>/, bridges/autocad/<year>/ and HOST_ARTIFACTS.json.
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    # Source revision the host bridges were built from (40-64 lowercase hex).
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40,64}$')]
    [string]$SourceRevision,
    # The independent custody review of THIS authenticated bridge source. Without
    # it the manifests say so and setup activates nothing
    # (nodelang/host_broker_installation.py, colleague_setup.register_max_startup);
    # this script never invents one.
    [string]$BrokerReviewPath,
    [string]$DotnetPath
)

# Build the authenticated host bridges once per host year installed on this
# build machine, each against that year's own API assemblies, and write the
# index setup reads (HOST_ARTIFACTS.json):
#   revit.<year>   -> bridges/revit/<year>/ + host-artifacts.json, the
#                     archhub-host-artifacts/v1 manifest setup verifies before
#                     it registers the add-in for that year;
#   autocad.<year> -> bridges/autocad/<year>/AcadMCP.dll (+ deps), pinned; no
#                     registration owner exists yet, so setup registers nothing;
#   max            -> the single startup script shipped at bridges/max/, pinned,
#                     deployed by setup only when the review is present.
# A year that is not installed here gets no payload: its host API pins could
# not be taken from a real installation.
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

function Get-Framework([int]$Year, [int]$LastNet48) {
    if ($Year -le 2020) { return 'net47' }
    if ($Year -le $LastNet48) { return 'net48' }
    # Autodesk 2027 hosts run on .NET 10: their API assemblies reference
    # System.Runtime 10.0, which a net8 build cannot compile against (CS1705).
    if ($Year -ge 2027) { return 'net10.0-windows' }
    return 'net8.0-windows'
}

# The compiler server can still hold a file of a finished build for a moment;
# a failed scratch delete must not fail the whole release.
function Remove-BuildScratch([string]$Path) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try { Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop; return }
        catch {
            if ($attempt -eq 1) { & $dotnet build-server shutdown *> $null }
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
    Remove-Item -LiteralPath $Path -Recurse -Force
}

# One project built for one host year into $Payload, from a fresh copy so restore
# state for one framework never leaks into another.
function Build-Project([string]$Project, [string[]]$Properties, [string]$Payload, [string]$Work) {
    if (-not (Test-Path -LiteralPath $Work)) { Copy-Item -LiteralPath $source -Destination $Work -Recurse }
    & $dotnet restore (Join-Path $Work $Project) @Properties -v q
    if ($LASTEXITCODE -ne 0) { throw "Restore failed for $Project ($($Properties -join ' '))." }
    & $dotnet build (Join-Path $Work $Project) --no-restore -c Release -nologo -v q @Properties -o $Payload
    if ($LASTEXITCODE -ne 0) { throw "Build failed for $Project ($($Properties -join ' '))." }
}

function Get-Closure([string]$Payload, [string]$Relative) {
    # Only the loadable closure ships; build byproducts do not.
    Get-ChildItem -LiteralPath $Payload -File | Where-Object { $_.Extension -in '.pdb', '.xml' } | Remove-Item -Force
    return @(Get-ChildItem -LiteralPath $Payload -File | Where-Object { $_.Name -ne 'host-artifacts.json' } |
        Sort-Object Name | ForEach-Object {
            $pin = Get-Pin $_.FullName
            [ordered]@{ path = "$Relative/$($_.Name)"; size = $pin.size; sha256 = $pin.sha256 }
        })
}

New-Item -ItemType Directory -Path $output | Out-Null
$index = [ordered]@{
    schema = 'archhub-host-artifacts-index/v1'; source_revision = $SourceRevision
    revit = [ordered]@{}; autocad = [ordered]@{}; max = $null
}
$autodesk = Join-Path $env:ProgramFiles 'Autodesk'

foreach ($year in 2020..2030) {
    $hostDir = Join-Path $autodesk "Revit $year"
    $api = Join-Path $hostDir 'RevitAPI.dll'
    $apiUi = Join-Path $hostDir 'RevitAPIUI.dll'
    if (-not ((Test-Path -LiteralPath $api -PathType Leaf) -and (Test-Path -LiteralPath $apiUi -PathType Leaf))) { continue }
    $framework = Get-Framework $year 2024
    $work = Join-Path $output ".build-revit-$year"
    $payload = Join-Path $output "bridges/revit/$year"
    New-Item -ItemType Directory -Path $payload -Force | Out-Null
    foreach ($project in 'revit_mcp_core/RevitMCPCore.csproj', 'revit_mcp/RevitMCP.csproj') {
        Build-Project $project @("-p:TargetFramework=$framework", "-p:RevitYear=$year", "-p:RevitInstallDir=$hostDir") $payload $work
    }
    Remove-BuildScratch $work
    $manifest = [ordered]@{
        schema          = 'archhub-host-artifacts/v1'
        source_revision = $SourceRevision
        host            = 'revit'
        host_version    = "$year"
        assembly        = "bridges/revit/$year/RevitMCP.dll"
        files           = (Get-Closure $payload "bridges/revit/$year")
        host_api        = [ordered]@{ 'RevitAPI.dll' = (Get-Pin $api); 'RevitAPIUI.dll' = (Get-Pin $apiUi) }
    }
    if ($review) {
        $manifest.runtime_closure_reviewed = $true
        $manifest.activation = $review
    }
    $manifestPath = Join-Path $payload 'host-artifacts.json'
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 6) + "`n", $utf8)
    $index.revit["$year"] = [ordered]@{
        manifest  = "bridges/revit/$year/host-artifacts.json"
        sha256    = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        framework = $framework
        reviewed  = [bool]$review
    }
}

foreach ($year in 2020..2030) {
    $hostDir = Join-Path $autodesk "AutoCAD $year"
    $apis = @('acmgd.dll', 'acdbmgd.dll', 'accoremgd.dll') | ForEach-Object { Join-Path $hostDir $_ }
    if (@($apis | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -ne 0) { continue }
    $framework = Get-Framework $year 2024
    $work = Join-Path $output ".build-autocad-$year"
    $payload = Join-Path $output "bridges/autocad/$year"
    New-Item -ItemType Directory -Path $payload -Force | Out-Null
    Build-Project 'acad_mcp/AcadMCP.csproj' @("-p:TargetFramework=$framework", "-p:AcadYear=$year", "-p:AcadInstallDir=$hostDir") $payload $work
    Remove-BuildScratch $work
    $hostApi = [ordered]@{}
    foreach ($api in $apis) { $hostApi[[IO.Path]::GetFileName($api)] = Get-Pin $api }
    $index.autocad["$year"] = [ordered]@{
        assembly  = "bridges/autocad/$year/AcadMCP.dll"
        files     = (Get-Closure $payload "bridges/autocad/$year")
        host_api  = $hostApi
        framework = $framework
        reviewed  = [bool]$review
        registration = 'none: no AutoCAD registration owner exists; setup registers nothing'
    }
}

$maxScript = Join-Path $source 'max_mcp/max_mcp_startup.py'
$index.max = [ordered]@{
    script   = 'bridges/max/max_mcp_startup.py'
    sha256   = (Get-FileHash -LiteralPath $maxScript -Algorithm SHA256).Hash.ToLowerInvariant()
    reviewed = [bool]$review
}
if ($review) { $index.max.activation = $review }

[IO.File]::WriteAllText((Join-Path $output 'HOST_ARTIFACTS.json'), ($index | ConvertTo-Json -Depth 8) + "`n", $utf8)
Write-Output ("Revit add-in built for: " + (($index.revit.Keys | Sort-Object) -join ', '))
Write-Output ("AutoCAD add-in built for: " + (($index.autocad.Keys | Sort-Object) -join ', '))
