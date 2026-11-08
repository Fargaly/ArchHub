[CmdletBinding()]
param(
    # A build_release.ps1 output directory (release mode, not a candidate).
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDirectory,
    # CI passes GITHUB_SHA so the published bytes are the commit it checked out.
    [ValidatePattern('^([0-9a-f]{40})?$')]
    [string]$ExpectedSourceRevision = '',
    [string]$Repository = 'Fargaly/ArchHub',
    [string]$PythonPath,
    # Reconcile and print the exact publish plan; upload nothing.
    [switch]$DryRun
)

# The one publish path for installed users' updates, local or GitHub Actions.
# check_update_offer.py proves the bytes reconcile, the installed updater can
# read the release, it is newer than the live latest, its tag is free and its
# source revision is pushed. Only then is it uploaded as a draft and promoted.
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$release = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
if (-not $PythonPath) {
    $PythonPath = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
$checker = Join-Path $PSScriptRoot 'check_update_offer.py'
$profileGuard = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'tools/real_app_check/profile_guard.py'
$checkProfile = Join-Path $release 'CHECK-PROFILE'
$arguments = @($checker, $release, '--live', '--repository', $Repository)
if ($ExpectedSourceRevision) { $arguments += @('--expected-revision', $ExpectedSourceRevision) }
$report = (& $PythonPath $profileGuard --profile $checkProfile @arguments) -join "`n"
# A build caller's local LASTEXITCODE can shadow the global native status.
$checkExit = $global:LASTEXITCODE
Write-Output $report
if ($checkExit -ne 0) { throw 'Release refused before upload; nothing was published.' }
$checked = $report | ConvertFrom-Json
if ($checked.ok -isnot [bool] -or $checked.ok -ne $true -or $null -eq $checked.offer) {
    throw 'Release checker did not approve this build; nothing was published.'
}
$offer = $checked.offer
$manifest = Get-Content -LiteralPath (Join-Path $release 'release.json') -Raw | ConvertFrom-Json
if ($offer.build_id -isnot [string] -or $offer.build_id -cnotmatch '^[A-Za-z0-9._-]{1,128}$' -or
    $offer.build_id -cne $manifest.build_id -or
    $offer.tag -isnot [string] -or $offer.tag -cne "build-$($manifest.build_id)" -or
    $offer.source_revision -isnot [string] -or $offer.source_revision -cnotmatch '^[0-9a-f]{40}$' -or
    $offer.source_revision -cne $manifest.source_revision -or
    ($ExpectedSourceRevision -and $offer.source_revision -cne $ExpectedSourceRevision) -or
    $offer.asset_sha256 -isnot [string] -or $offer.asset_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $offer.asset_sha256 -cne $manifest.asset_sha256 -or $offer.asset_bytes -ne $manifest.asset_bytes -or
    $manifest.asset_name -cne 'ArchHub-Setup-0.exe' -or
    $manifest.payload_manifest -cne 'source-manifest.tsv' -or $manifest.studio_manifest -cne 'studio-build.json') {
    throw 'Release checker identity does not match this build; nothing was published.'
}
$tag = $offer.tag
$assets = @('ArchHub-Setup-0.exe', 'release.json', 'source-manifest.tsv', 'studio-build.json', 'BUILD_METADATA.json') |
    ForEach-Object { Join-Path $release $_ }
foreach ($asset in $assets + (Join-Path $release 'release-notes.md')) {
    if (-not (Test-Path -LiteralPath $asset -PathType Leaf)) {
        throw "Release asset missing: $asset; nothing was published."
    }
}
if ((Get-FileHash -LiteralPath $assets[0] -Algorithm SHA256).Hash.ToLowerInvariant() -cne $offer.asset_sha256 -or
    (Get-Item -LiteralPath $assets[0]).Length -ne $offer.asset_bytes) {
    throw 'Release installer no longer matches the checked build; nothing was published.'
}
$create = @('release', 'create', $tag) + $assets + @(
    '--repo', $Repository, '--draft', '--target', $offer.source_revision,
    '--title', "ArchHub $($offer.build_id)", '--notes-file', (Join-Path $release 'release-notes.md'))
$promote = @('release', 'edit', $tag, '--repo', $Repository, '--draft=false', '--latest')
Write-Output ('PLAN 1: gh ' + ($create -join ' '))
Write-Output ('PLAN 2: gh ' + ($promote -join ' '))
if ($DryRun) {
    Write-Output "DRY RUN: $tag reconciled and readable by the installed updater; nothing was published."
    return
}
& gh auth status *> $null
if ($global:LASTEXITCODE -ne 0) { throw 'gh is not signed in (run gh auth login, or set GH_TOKEN); nothing was published.' }
& gh @create
if ($global:LASTEXITCODE -ne 0) { throw 'Draft release upload failed; nothing was promoted.' }
& gh @promote
if ($global:LASTEXITCODE -ne 0) { throw 'Release promotion did not complete; inspect its current state before retrying.' }
# Read back through the installed updater's own parser, from the live API.
$probe = "import json,sys; sys.path.insert(0, sys.argv[1]); from nodelang import quiet_update as q; print(json.dumps(q.read_latest_release()))"
$live = (& $PythonPath $profileGuard --profile $checkProfile -c $probe (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) -join ''
if ($global:LASTEXITCODE -ne 0) { throw 'Published release readback failed; inspect the guard receipt.' }
Write-Output "LIVE latest as installed users read it: $live"
if (($live | ConvertFrom-Json).build_id -cne $offer.build_id) {
    throw "Published $tag but releases/latest does not yet read as it; re-check before announcing."
}
Write-Output "PUBLISHED $tag as latest; installed users stage it on their next update check."
