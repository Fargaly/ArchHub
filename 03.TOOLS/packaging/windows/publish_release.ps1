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
    # Edit prose on an existing opt-in release without publishing binaries or changing latest.
    [string]$PreviewTag,
    [string]$PreviewNotesFile,
    [switch]$CreatePreview,
    [switch]$PromotePreview,
    [long]$StableReleaseId,
    [long]$PreviewReleaseId,
    # With -CreatePreview: resume this existing draft (a create whose response timed out) instead of creating another.
    [long]$ResumeDraftId,
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
$toolsRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$profileGuard = Join-Path $toolsRoot 'tools/real_app_check/profile_guard.py'
# The installed updater's parser, as check_update_offer.py finds it: nodelang beside packaging/ (flattened release
# snapshot), else 01.APP beside 03.TOOLS (numbered repository). Resolved before upload so a readback that cannot
# import it refuses here instead of failing after the release is already latest.
$appRoot = @($toolsRoot, (Join-Path (Split-Path -Parent $toolsRoot) '01.APP')) |
    Where-Object { Test-Path -LiteralPath (Join-Path $_ 'nodelang/quiet_update.py') -PathType Leaf } | Select-Object -First 1
if (-not $appRoot) { throw 'The installed updater parser (nodelang/quiet_update.py) is not beside this script; nothing was published.' }
$checkProfile = Join-Path $release 'CHECK-PROFILE'
$mode = if ($CreatePreview) { 'create' } elseif ($PromotePreview) { 'promote' }
if (($CreatePreview -and $PromotePreview) -or
    ($mode -and ($PreviewTag -or $PreviewNotesFile -or -not $ExpectedSourceRevision -or
        $StableReleaseId -le 0 -or $Repository -cne 'Fargaly/ArchHub')) -or
    ($PromotePreview -and ($PreviewReleaseId -le 0 -or $PreviewReleaseId -eq $StableReleaseId)) -or
    ($CreatePreview -and $PreviewReleaseId) -or
    ($ResumeDraftId -and (-not $CreatePreview -or $ResumeDraftId -le 0 -or $ResumeDraftId -eq $StableReleaseId)) -or
    (-not $mode -and ($StableReleaseId -or $PreviewReleaseId))) {
    throw 'Choose one release operation. Preview publication requires the expected revision and stable ID; promotion also requires the approved preview ID.'
}
if ($PSBoundParameters.ContainsKey('PreviewTag') -or $PSBoundParameters.ContainsKey('PreviewNotesFile')) {
    if ($PreviewTag -cnotmatch '^build-[A-Za-z0-9._-]{1,128}$' -or -not $PreviewNotesFile -or
        $Repository -cnotmatch '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$') { throw 'Specify a build tag, repository and prose file.' }
    $scratch = New-Item -ItemType Directory -Path (Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N')))
    $utf8 = [Text.UTF8Encoding]::new($false)
    $encoding = [Console]::OutputEncoding
    $base = "repos/$Repository/releases"
    function Read-PreviewSnapshot($phase) {
        foreach ($pair in @(@('stable','latest'), @('preview',"tags/$PreviewTag"))) {
            $json = (& gh api "$base/$($pair[1])") -join "`n"
            if ($global:LASTEXITCODE -ne 0) { throw "Could not read $($pair[0]) release." }
            [IO.File]::WriteAllText((Join-Path $scratch "$phase-$($pair[0]).json"), $json, $utf8)
        }
        $revision = & gh api "repos/$Repository/commits/tags/$PreviewTag" --jq .sha
        if ($global:LASTEXITCODE -ne 0 -or $revision -cnotmatch '^[a-f0-9]{40}$') { throw 'Cannot resolve preview tag.' }
        [IO.File]::WriteAllText((Join-Path $scratch "$phase-revision"), $revision, $utf8)
    }
    function Get-PreviewBinding($phase) {
        $preview = Get-Content -LiteralPath (Join-Path $scratch "$phase-preview.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        $stable = Get-Content -LiteralPath (Join-Path $scratch "$phase-stable.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($releaseRecord in $preview, $stable) {
            if ($releaseRecord -isnot [pscustomobject] -or
                ($releaseRecord.id -isnot [long] -and $releaseRecord.id -isnot [int]) -or $releaseRecord.id -le 0 -or
                $releaseRecord.draft -isnot [bool] -or $releaseRecord.draft -or $releaseRecord.prerelease -isnot [bool] -or
                $releaseRecord.tag_name -isnot [string] -or -not $releaseRecord.tag_name) {
                throw 'Invalid published release identity.'
            }
        }
        if ($preview.tag_name -cne $PreviewTag -or -not $preview.prerelease -or $stable.prerelease -or
            $preview.id -eq $stable.id -or $stable.tag_name -ceq $PreviewTag) {
            throw 'Selected tag is not a distinct published preview.'
        }
        return @{previewId=$preview.id; stableId=$stable.id; stableTag=$stable.tag_name}
    }
    function Test-PreviewSnapshot($phase, $binding) {
        $check = @($checker, $release, '--preview-tag', $PreviewTag, '--preview-notes', $prose, '--snapshot', $scratch.FullName, '--phase', $phase)
        if ($ExpectedSourceRevision) { $check += @('--expected-revision', $ExpectedSourceRevision) }
        # GitHub authentication stays with the outer gh process.
        $saved = @{}
        try {
            foreach ($name in 'GH_TOKEN','GITHUB_TOKEN','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN','GH_CONFIG_DIR') {
                $saved[$name] = [Environment]::GetEnvironmentVariable($name)
                [Environment]::SetEnvironmentVariable($name, $null)
            }
            $result = (& $PythonPath $profileGuard --profile (Join-Path $scratch 'profile') @check) -join "`n"
            if ($global:LASTEXITCODE -ne 0) { throw "Preview notes $phase refused: $result" }
            if ($result -notmatch '^\s*\{') { throw "Invalid preview $phase verdict." }
            $verdict = $result | ConvertFrom-Json
            if ($verdict.ok -isnot [bool] -or -not $verdict.ok -or $verdict.changed -isnot [bool] -or
                ($verdict.id -isnot [int] -and $verdict.id -isnot [long]) -or $verdict.id -ne $binding.previewId -or
                $verdict.stable_tag -isnot [string] -or $verdict.stable_tag -cne $binding.stableTag -or
                ($phase -ne 'before' -and $verdict.changed)) {
                throw "Preview $phase verdict refused or mismatched."
            }
            return $verdict
        } finally {
            foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
        }
    }
    try {
        [Console]::OutputEncoding = $utf8
        $prose = (Resolve-Path -LiteralPath $PreviewNotesFile).Path
        Read-PreviewSnapshot 'before'
        $binding = Get-PreviewBinding 'before'
        $plan = Test-PreviewSnapshot 'before' $binding
        if ($DryRun) { Write-Output "DRY RUN: $PreviewTag verified; changed=$($plan.changed)"; return }
        if ($plan.changed) {
            Read-PreviewSnapshot 'recheck'
            $null = Test-PreviewSnapshot 'recheck' $binding
            $bodyFile = Join-Path $scratch 'body.md'
            & gh api "$base/$($binding.previewId)" --method PATCH --field "body=@$bodyFile" --silent
            if ($global:LASTEXITCODE -ne 0) { throw 'Preview edit failed; inspect the published tag before retrying.' }
        }
        Read-PreviewSnapshot 'after'
        $observed = Get-PreviewBinding 'after'
        if ($observed.previewId -ne $binding.previewId -or $observed.stableId -ne $binding.stableId -or
            $observed.stableTag -cne $binding.stableTag) { throw 'Published release identity changed during edit.' }
        $null = Test-PreviewSnapshot 'after' $observed
        Write-Output "Verified published preview $PreviewTag; stable remains $($plan.stable_tag)."
    } finally {
        [Console]::OutputEncoding = $encoding
        if ($scratch.Parent.FullName -ne ([IO.Path]::GetTempPath()).TrimEnd('\','/')) { throw 'Unexpected preview scratch path.' }
        Remove-Item -LiteralPath $scratch.FullName -Recurse -Force
    }
    return
}
$arguments = @($checker, $release, '--repository', $Repository)
if (-not $PromotePreview) { $arguments += '--live' }
if ($mode) { $arguments += @('--publication', $mode, '--stable-id', $StableReleaseId, '--preview-id', $PreviewReleaseId) }
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
$notesPath = Join-Path $release 'release-notes.md'
$notesText = [IO.File]::ReadAllText($notesPath)
$buildHeading = [regex]::Match($notesText, '(?m)^## Build[ \t]*\r?$')
$buildMatches = [regex]::Matches($notesText, '(?m)^BUILD_ID:[ \t]*([A-Za-z0-9._-]{1,128})[ \t]*\r?$')
$shaMatches = [regex]::Matches($notesText, '(?m)^SHA256 ArchHub-Setup-0\.exe:[ \t]*([0-9a-fA-F]{64})(?: \([1-9][0-9]{0,9} bytes\))?[ \t]*\r?$')
if (-not $buildHeading.Success -or
    $buildMatches.Count -ne 1 -or $buildMatches[0].Groups[1].Value -cne $offer.build_id -or
    $buildMatches[0].Index -lt $buildHeading.Index -or
    $shaMatches.Count -ne 1 -or $shaMatches[0].Groups[1].Value.ToLowerInvariant() -cne $offer.asset_sha256 -or
    $shaMatches[0].Index -lt $buildHeading.Index) {
    throw 'Release notes are missing the ## Build block (BUILD_ID and SHA256 ArchHub-Setup-0.exe); nothing was published.'
}
$create = @('release', 'create', $tag) + $assets + @(
    '--repo', $Repository, '--draft', '--target', $offer.source_revision,
    '--title', "ArchHub $($offer.build_id)", '--notes-file', (Join-Path $release 'release-notes.md'))
if ($mode) {
    $state = $checked.publication
    function Assert-PublicationBinding($result, [long]$id) {
        if ($null -eq $result -or $result.stable_binding -isnot [string] -or
            $result.stable_binding -cnotmatch '^[a-f0-9]{64}$' -or
            ($result.id -isnot [long] -and $result.id -isnot [int]) -or $result.id -ne $id -or
            ($id -gt 0 -and ($result.preview_binding -isnot [string] -or
                              $result.preview_binding -cnotmatch '^[a-f0-9]{64}$'))) {
            throw 'Publication checker returned an invalid release binding.'
        }
    }
    Assert-PublicationBinding $state $PreviewReleaseId
    function Read-PublicationState($phase) {
        $check = @($checker, $release, '--repository', $Repository, '--expected-revision', $ExpectedSourceRevision,
            '--publication', $mode, '--publication-phase', $phase, '--stable-id', $StableReleaseId,
            '--preview-id', $PreviewReleaseId, '--stable-binding', $state.stable_binding)
        if ($state.preview_binding) { $check += @('--preview-binding', $state.preview_binding) }
        if ($CreatePreview -and $phase -eq 'ready') {
            $draft = (& gh api "repos/$Repository/releases/$PreviewReleaseId") -join [Environment]::NewLine
            if ($global:LASTEXITCODE -ne 0) { throw 'Cannot verify uploaded draft.' }
            $draftFile = [IO.Path]::GetTempFileName()
            [IO.File]::WriteAllText($draftFile, $draft, [Text.UTF8Encoding]::new($false))
            $check += @('--draft-snapshot', $draftFile, '--live')
        }
        try {
            $raw = (& $PythonPath $profileGuard --profile $checkProfile @check) -join [Environment]::NewLine
            if ($global:LASTEXITCODE -ne 0) { throw "Publication $phase refused: $raw" }
            $result = $raw | ConvertFrom-Json
            if ($result.ok -isnot [bool] -or -not $result.ok) { throw "Publication $phase refused." }
            Assert-PublicationBinding $result.publication $PreviewReleaseId
            return $result.publication
        } finally {
            if ($draftFile) { Remove-Item -LiteralPath $draftFile -Force }
        }
    }
    Write-Output "PLAN: $mode preview $tag at $ExpectedSourceRevision against stable release $StableReleaseId."
    if ($DryRun) { return }
    if ($CreatePreview -and $ResumeDraftId) {
        # A create whose response timed out left a draft: resume that one, never a second. It must be an unpublished
        # draft for this tag and revision; missing assets are uploaded without overwriting, and the same ready/after
        # checks below decide whether its bytes are the reconciled ones.
        $existing = (& gh api "repos/$Repository/releases/$ResumeDraftId") -join [Environment]::NewLine
        if ($global:LASTEXITCODE -ne 0) { throw 'Cannot read the draft to resume; nothing was published.' }
        $existing = $existing | ConvertFrom-Json
        if ($existing.id -ne $ResumeDraftId -or $existing.draft -ne $true -or $existing.tag_name -cne $tag -or
            $existing.target_commitish -cne $offer.source_revision) {
            throw 'The draft to resume is not an unpublished draft of this tag and revision; nothing was published.'
        }
        $present = @($existing.assets | ForEach-Object { $_.name })
        $missing = @($assets | Where-Object { $present -cnotcontains (Split-Path -Leaf $_) })
        if ($missing.Count) {
            & gh release upload $tag @missing --repo $Repository
            if ($global:LASTEXITCODE -ne 0) { throw 'Resumed draft upload failed; draft retained.' }
        }
        $PreviewReleaseId = $ResumeDraftId
    } elseif ($CreatePreview) {
        & gh @create --prerelease
        if ($global:LASTEXITCODE -ne 0) { throw 'Preview draft upload failed.' }
        $draftId = & gh release view $tag --repo $Repository --json databaseId --jq .databaseId
        if ($global:LASTEXITCODE -ne 0 -or "$draftId" -notmatch '^[1-9][0-9]*$') { throw 'Cannot identify preview draft.' }
        $PreviewReleaseId = [long]$draftId
    }
    $state = Read-PublicationState 'ready'
    $endpoint = "repos/$Repository/releases/$PreviewReleaseId"
    if ($CreatePreview) {
        # Create-only ref: a competing tag must never silently select different bytes.
        & gh api "repos/$Repository/git/refs" --method POST -f "ref=refs/tags/$tag" -f "sha=$ExpectedSourceRevision" --silent
        if ($global:LASTEXITCODE -ne 0) { throw 'Could not reserve exact tag; draft retained.' }
        $patch = @('-F', 'draft=false', '-F', 'prerelease=true', '-f', 'make_latest=false')
    } else {
        $patch = @('-F', 'prerelease=false', '-f', 'make_latest=true')
    }
    # A failed PATCH must reach the after check below: with native-command errors escalated, a non-zero exit threw
    # before it (e988 9e38ad7d). Only this one invocation is exempted.
    $PSNativeCommandUseErrorActionPreference = $false
    try { & gh api $endpoint --method PATCH @patch --silent; $patchExit = $global:LASTEXITCODE }
    finally { $PSNativeCommandUseErrorActionPreference = $true }
    # GitHub serves releases/latest with Cache-Control max-age=60: right after a committed PATCH the read-only after check
    # can still see the previous release (456266664 did). It is retried, read-only, until that window has passed; the
    # mutation is never replayed.
    function Read-AfterSettled {
        foreach ($wait in 0, 35, 35) {
            if ($wait) { Start-Sleep -Seconds $wait }
            try { return Read-PublicationState 'after' } catch { $last = $_ }
        }
        throw $last
    }
    if ($patchExit -ne 0) {
        # A timed-out PATCH may have succeeded (456140451 did): the read-only after check decides; the mutation is
        # never replayed, and an unverifiable state stays reported as unknown.
        try { $null = Read-AfterSettled } catch {
            throw "Publication response uncertain and not verified ($($_.Exception.Message)); inspect release IDs before retrying."
        }
        Write-Output "Publication response was lost; the after check verified release $PreviewReleaseId."
    } else {
        $null = Read-AfterSettled
    }
    Write-Output "Verified $mode of release $PreviewReleaseId through the installed updater parser."
    return
}

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
$live = (& $PythonPath $profileGuard --profile $checkProfile -c $probe $appRoot) -join ''
if ($global:LASTEXITCODE -ne 0) { throw 'Published release readback failed; inspect the guard receipt.' }
Write-Output "LIVE latest as installed users read it: $live"
if (($live | ConvertFrom-Json).build_id -cne $offer.build_id) {
    throw "Published $tag but releases/latest does not yet read as it; re-check before announcing."
}
Write-Output "PUBLISHED $tag as latest; installed users stage it on their next update check."
