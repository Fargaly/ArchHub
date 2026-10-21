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
$release = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
if (-not $PythonPath) {
    $PythonPath = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
$checker = Join-Path $PSScriptRoot 'check_update_offer.py'
$arguments = @($checker, $release, '--live', '--repository', $Repository)
if ($ExpectedSourceRevision) { $arguments += @('--expected-revision', $ExpectedSourceRevision) }
$report = (& $PythonPath @arguments) -join "`n"
$checkExit = $LASTEXITCODE
Write-Output $report
if ($checkExit -ne 0) { throw 'Release refused before upload; nothing was published.' }
$offer = ($report | ConvertFrom-Json).offer
$tag = $offer.tag
$assets = @('ArchHub-Setup-0.exe', 'release.json', 'source-manifest.tsv', 'studio-build.json', 'BUILD_METADATA.json') |
    ForEach-Object { Join-Path $release $_ }
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
if ($LASTEXITCODE -ne 0) { throw 'gh is not signed in (run gh auth login, or set GH_TOKEN); nothing was published.' }
& gh @create
if ($LASTEXITCODE -ne 0) { throw 'Draft release upload failed; nothing was promoted.' }
& gh @promote
if ($LASTEXITCODE -ne 0) { throw 'Release promotion did not complete; inspect its current state before retrying.' }
# Read back through the installed updater's own parser, from the live API.
$probe = "import json,sys; sys.path.insert(0, sys.argv[1]); from nodelang import quiet_update as q; print(json.dumps(q.read_latest_release()))"
$live = (& $PythonPath -c $probe (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) -join ''
Write-Output "LIVE latest as installed users read it: $live"
if (($live | ConvertFrom-Json).build_id -cne $offer.build_id) {
    throw "Published $tag but releases/latest does not yet read as it; re-check before announcing."
}
Write-Output "PUBLISHED $tag as latest; installed users stage it on their next update check."
