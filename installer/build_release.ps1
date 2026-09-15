[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9._-]{1,128}$')]
    [string]$BuildId,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$IsccPath,
    [string]$NodePath,
    [switch]$PrepareCandidateManifest,
    [string]$LocalCandidateManifest,
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$LocalCandidateManifestSha256
)

# Build only the selected colleague installer. No installed state, builder-home
# skills, PyInstaller runtime, or implicit sibling checkout enters this package.
$ErrorActionPreference = 'Stop'
$utf8 = [Text.UTF8Encoding]::new($false, $true)
$builtAt = [DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
$selectedRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$selectedInputs = @(
    'nodelang', 'launch_archhub_test.py', 'colleague_setup.py',
    'requirements.txt', 'installer', 'packaging/windows/Test-SourcePortability.ps1',
    'package.json', 'packaging/compile_studio.cjs',
    'app/secrets_store.py', 'app/credential_lock.py', 'app/__init__.py', 'bridges', 'archhub.ico',
    'personal_brain/__init__.py', 'personal_brain/hook_coverage.py',
    'personal_brain/installer.py', 'personal_brain/ambient_policy.py',
    'packaging/windows/licenses/Node-v24.13.0-LICENSE.txt',
    'packaging/windows/licenses/ArchHub-components-MIT.txt'
)

function Assert-TrackedInputs([string]$Checkout, [string[]]$Inputs) {
    foreach ($relative in $Inputs) {
        if (-not (Test-Path -LiteralPath (Join-Path $Checkout $relative))) {
            throw "Missing release input: $relative"
        }
    }
    & git -C $Checkout diff --quiet HEAD -- @Inputs
    if ($LASTEXITCODE -ne 0) { throw 'Release inputs must match their committed revision.' }
    # Enumerate ignored files too, so an ignored admissible source file cannot
    # silently evade the committed-payload requirement. The compiler receives
    # only the tracked, allowlisted snapshot below: excluded caches and generated
    # Studio output cannot enter it and need not be deleted to build a release.
    $untracked = @(& git -C $Checkout ls-files --others -- @Inputs)
    if ($LASTEXITCODE -ne 0) {
        throw 'Release input tracking cannot be verified.'
    }
    if (@($untracked | Where-Object { Test-CandidateInput 'selected' $_ }).Count -ne 0) {
        throw 'Release inputs contain untracked admissible payload files.'
    }
}

# Local candidates are explicit reviewed byte inventories, not a dirty-tree
# exception for public releases. Manifest format (literal tabs, UTF-8):
# ARCHHUB_LOCAL_CANDIDATE_MANIFEST_V2
# build_id<TAB>candidate-...
# selected_root<TAB>absolute selected source directory
# selected_base_revision<TAB>40 lowercase hex (context, not payload identity)
# source<TAB>path<TAB>bytes<TAB>sha256
# selected<TAB>nodelang/__init__.py<TAB>123<TAB>64 lowercase hex
# Only listed files are copied. Retain a failed output intact for inspection;
# this helper never removes a previous candidate, state, or source directory.
function Assert-PlainAncestors([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Candidate paths cannot contain symlinks or junctions: $cursor"
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}

function Test-Below([string]$Path, [string]$Root) {
    return $Path.StartsWith($Root.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)
}

function Get-SourceIdentity([string]$Path) {
    Assert-PlainAncestors $Path
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) { throw "Expected an ordinary candidate file: $Path" }
    return ('{0}:{1}:{2}' -f $item.Length, $item.CreationTimeUtc.Ticks, $item.LastWriteTimeUtc.Ticks)
}

function Test-CandidateInput([string]$Source, [string]$Path) {
    if ($Path -cnotmatch '^[A-Za-z0-9_][A-Za-z0-9_./-]*$') { return $false }
    foreach ($part in $Path.Split('/')) {
        if (-not $part -or $part.StartsWith('.') -or $part.EndsWith('.') -or
            $part -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)' -or
            $part -match '^(?i:__pycache__|node_modules|build|dist|state|backups|sessions|tests|tests_replica|venv)$') {
            return $false
        }
    }
    if ([IO.Path]::GetFileName($Path) -match '^(?i:cloud|credentials|secrets|tokens?)\.json$') {
        return $false
    }
    if ($Source -ceq 'selected') {
        # Generated scripts must come from this build's verified snapshot.
        # The generic JavaScript allowlist must never admit stale compiled files.
        if ($Path.StartsWith('nodelang/studio/compiled/', [StringComparison]::OrdinalIgnoreCase)) { return $false }
        if ($Path -cin @(
            'launch_archhub_test.py', 'colleague_setup.py', 'requirements.txt',
            'package.json', 'packaging/compile_studio.cjs',
            'installer/ArchHub.iss', 'installer/ArchHub.bat', 'installer/ArchHub.vbs',
            'installer/build_release.ps1', 'packaging/windows/Test-SourcePortability.ps1',
            'packaging/windows/licenses/Node-v24.13.0-LICENSE.txt',
            'packaging/windows/licenses/ArchHub-components-MIT.txt',
            'app/secrets_store.py', 'app/credential_lock.py', 'app/__init__.py', 'archhub.ico',
            'personal_brain/__init__.py', 'personal_brain/hook_coverage.py',
            'personal_brain/installer.py', 'personal_brain/ambient_policy.py',
            'bridges/rhino/archhub_mcp.py', 'bridges/blender/archhub_mcp/__init__.py',
            'nodelang/session_link/vendor/LICENSE', 'nodelang/session_link/vendor/PROVENANCE.md',
            'nodelang/session_link/README.md', 'nodelang/session_link/session-link.ps1',
            'nodelang/assets/LUCIDE-1.25.0-LICENSE.txt',
            'nodelang/assets/lucide-icons-1.25.0.json', 'nodelang/data/public_runtime_map.json',
            'nodelang/samples/sample-plan.dxf'
        )) { return $true }
        return $Path -cmatch '^nodelang/.+\.(py|jsx|js|mjs|cjs|html|png)$'
    }
    return $false
}

function Read-CandidateManifest([string]$Path) {
    Assert-PlainAncestors $Path
    $identity = Get-SourceIdentity $Path
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $length = $stream.Length
        if ($length -le 0 -or $length -gt 262144) { throw 'Candidate manifest must be at most 256 KiB.' }
        $bytes = [byte[]]::new([int]$length)
        $offset = 0
        while ($offset -lt $length) {
            $read = $stream.Read($bytes, $offset, [int]$length - $offset)
            if ($read -eq 0) { throw 'Candidate manifest changed while read.' }
            $offset += $read
        }
        if ($stream.ReadByte() -ne -1) { throw 'Candidate manifest grew while read.' }
    } finally { $stream.Dispose() }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($digest -cne $LocalCandidateManifestSha256.ToLowerInvariant() -or
        (Get-SourceIdentity $Path) -cne $identity) {
        throw 'Candidate manifest does not match the reviewed SHA256 or changed while read.'
    }
    $lines = @($utf8.GetString($bytes).Split("`n") | ForEach-Object { $_.TrimEnd("`r") })
    if ($lines[-1] -ceq '') { $lines = $lines[0..($lines.Count - 2)] }
    $headers = @(
        'ARCHHUB_LOCAL_CANDIDATE_MANIFEST_V2', "build_id`t$BuildId",
        "selected_root`t$selectedRoot",
        "selected_base_revision`t$sourceRevision",
        "source`tpath`tbytes`tsha256"
    )
    if ($lines.Count -le $headers.Count -or $lines.Count -gt ($headers.Count + 1024)) {
        throw 'Candidate manifest requires 1..1024 file rows.'
    }
    for ($i = 0; $i -lt $headers.Count; $i++) {
        if ($lines[$i] -cne $headers[$i]) { throw "Candidate manifest header $i does not match the explicit build inputs." }
    }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $rows = [Collections.Generic.List[object]]::new()
    [long]$total = 0
    foreach ($line in $lines[$headers.Count..($lines.Count - 1)]) {
        $fields = $line.Split("`t")
        if ($fields.Count -ne 4 -or -not (Test-CandidateInput $fields[0] $fields[1]) -or
            $fields[2] -cnotmatch '^(0|[1-9][0-9]{0,7})$' -or $fields[3] -cnotmatch '^[0-9a-f]{64}$') {
            throw 'Invalid candidate file row; only explicit public code/assets are admitted.'
        }
        if (-not $seen.Add($fields[0] + '/' + $fields[1])) { throw 'Duplicate or case-aliased candidate file.' }
        [long]$fileBytes = $fields[2]
        $total += $fileBytes
        if ($fileBytes -gt 16MB -or $total -gt 128MB) { throw 'Candidate input exceeds 16 MiB per file or 128 MiB total.' }
        $root = $selectedRoot
        $sourcePath = [IO.Path]::GetFullPath((Join-Path $root $fields[1]))
        if (-not (Test-Below $sourcePath $root)) { throw 'Candidate source escaped its explicit root.' }
        $sourceIdentity = Get-SourceIdentity $sourcePath
        if ((Get-Item -LiteralPath $sourcePath).Length -ne $fileBytes) { throw "Candidate size changed: $($fields[1])" }
        $rows.Add([pscustomobject]@{
            Source = $fields[0]; Path = $fields[1]; Bytes = $fileBytes; Sha256 = $fields[3]
            SourcePath = $sourcePath; Identity = $sourceIdentity
        })
    }
    $required = @(
        'selected/launch_archhub_test.py', 'selected/colleague_setup.py', 'selected/requirements.txt',
        'selected/installer/ArchHub.iss', 'selected/installer/ArchHub.bat', 'selected/installer/ArchHub.vbs',
        'selected/installer/build_release.ps1', 'selected/packaging/windows/Test-SourcePortability.ps1',
        'selected/package.json', 'selected/packaging/compile_studio.cjs',
        'selected/packaging/windows/licenses/Node-v24.13.0-LICENSE.txt',
        'selected/nodelang/session_link_transport.py',
        'selected/nodelang/session_link/worker.mjs', 'selected/nodelang/session_link/ask.mjs',
        'selected/nodelang/session_link/bridge.mjs', 'selected/nodelang/session_link/native.mjs',
        'selected/nodelang/session_link/extra-apps.mjs', 'selected/nodelang/session_link/paths.mjs',
        'selected/nodelang/session_link/opencode-plugin.mjs',
        'selected/nodelang/session_link/scoped-attachment.mjs',
        'selected/nodelang/session_link/host-attachment.mjs',
        'selected/nodelang/session_link/host-worker.mjs',
        'selected/nodelang/session_link_host.py',
        'selected/nodelang/session_link/session-link.ps1',
        'selected/nodelang/session_link/vendor/src/peer-protocol.mjs',
        'selected/nodelang/session_link/vendor/src/platform.mjs',
        'selected/nodelang/session_link/vendor/src/reload-control.mjs',
        'selected/nodelang/session_link/vendor/LICENSE',
        'selected/nodelang/session_link/vendor/PROVENANCE.md',
        'selected/nodelang/studio/studio.html', 'selected/nodelang/studio/vendor/babel.js',
        'selected/nodelang/studio/tokens.jsx', 'selected/nodelang/studio/design-canvas.jsx',
        'selected/nodelang/studio/shared-data.jsx', 'selected/nodelang/studio/studio-suite.jsx',
        'selected/nodelang/studio/param-types.jsx', 'selected/nodelang/studio/studio-params.jsx',
        'selected/nodelang/studio/studio-mobile.jsx', 'selected/nodelang/studio/studio-account.jsx',
        'selected/nodelang/studio/studio-lm.jsx', 'selected/nodelang/studio/mount.jsx',
        'selected/nodelang/__init__.py',
        'selected/personal_brain/__init__.py', 'selected/personal_brain/hook_coverage.py',
        'selected/personal_brain/installer.py', 'selected/personal_brain/ambient_policy.py',
        'selected/bridges/rhino/archhub_mcp.py', 'selected/bridges/blender/archhub_mcp/__init__.py',
        'selected/archhub.ico', 'selected/app/secrets_store.py', 'selected/app/credential_lock.py', 'selected/app/__init__.py',
        'selected/packaging/windows/licenses/ArchHub-components-MIT.txt'
    )
    foreach ($name in $required) {
        if (-not $seen.Contains($name)) { throw "Candidate manifest omits required input: $name" }
    }
    if ($seen.Contains('selected/nodelang/assets/lucide-icons-1.25.0.json') -and
        -not $seen.Contains('selected/nodelang/assets/LUCIDE-1.25.0-LICENSE.txt')) {
        throw 'The Lucide asset requires its accompanying license.'
    }
    return [pscustomobject]@{
        Rows = $rows; Bytes = $bytes; Sha256 = $digest; TotalBytes = $total
        SelectedCheckout = $selectedRoot
    }
}

function Assert-CandidateBudget {
    if ($candidateClock.Elapsed.TotalSeconds -gt 180) { throw 'Source snapshot copy/verification exceeded 180 seconds.' }
}

function Read-CandidateFile($Row, [string]$Path, [string]$Destination, [switch]$CollectDigest) {
    if ($CollectDigest -and ($Destination -or $Row.Sha256)) {
        throw 'Digest collection is only for an unpopulated committed-source manifest row.'
    }
    Assert-CandidateBudget
    Assert-PlainAncestors $Path
    $inputStream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $outputStream = $null
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        if ($inputStream.Length -ne $Row.Bytes) { throw "Candidate file size changed: $($Row.Path)" }
        if ($Destination) {
            $parent = [IO.Path]::GetDirectoryName($Destination)
            [IO.Directory]::CreateDirectory($parent) | Out-Null
            Assert-PlainAncestors $parent
            $outputStream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        }
        [long]$count = 0
        while (($read = $inputStream.Read($candidateBuffer, 0, $candidateBuffer.Length)) -gt 0) {
            Assert-CandidateBudget
            $count += $read
            if ($count -gt $Row.Bytes) { throw "Candidate file grew: $($Row.Path)" }
            [void]$sha.TransformBlock($candidateBuffer, 0, $read, $candidateBuffer, 0)
            if ($outputStream) { $outputStream.Write($candidateBuffer, 0, $read) }
            # One serial stream, 1 MiB working buffer, no worker or parallel hash.
            [Threading.Thread]::Sleep(5)
        }
        [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
        $digest = ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
        if ($count -ne $Row.Bytes -or (-not $CollectDigest -and $digest -cne $Row.Sha256)) {
            throw "Source content differs from its bound bytes: $($Row.Path)"
        }
        if ($outputStream) { $outputStream.Flush($true) }
        if ($CollectDigest) { return $digest }
    }
    finally {
        if ($outputStream) { $outputStream.Dispose() }
        $inputStream.Dispose()
        $sha.Dispose()
    }
}

function Assert-CandidateSources($Manifest) {
    $selectedHead = (& git -C $Manifest.SelectedCheckout rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $selectedHead -cne $sourceRevision) { throw 'Selected candidate base revision changed.' }
    foreach ($row in $Manifest.Rows) {
        if ((Get-SourceIdentity $row.SourcePath) -cne $row.Identity) {
            throw "Candidate source identity changed: $($row.Path)"
        }
    }
}

function Read-ReleaseSnapshotManifest([switch]$WorkingCandidate) {
    # Public builds retain the original clean/committed checks. Enumerate only
    # those exact tracked scopes; the build compiler never receives a checkout.
    $rows = [Collections.Generic.List[object]]::new()
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [long]$total = 0
    foreach ($role in @('selected')) {
        $checkout = $selectedRoot
        $scope = $selectedInputs
        $paths = if ($WorkingCandidate) {
            @(& git -C $checkout ls-files --cached --others --exclude-standard -- @scope | Sort-Object -Unique)
        } else { @(& git -C $checkout ls-files -- @scope) }
        if ($LASTEXITCODE -ne 0 -or $paths.Count -eq 0) { throw 'Committed release input enumeration failed.' }
        if ($WorkingCandidate) {
            # Cached Git paths include unstaged deletions. A candidate describes
            # the reviewed working payload, including retired source removals.
            # Required payload entries are still checked by Read-CandidateManifest.
            $deleted = @(& git -C $checkout ls-files --deleted -- @scope)
            if ($LASTEXITCODE -ne 0) { throw 'Candidate deletion enumeration failed.' }
            $paths = @($paths | Where-Object { $_ -cnotin $deleted })
        }
        foreach ($relative in $paths) {
            if ($WorkingCandidate -and -not (Test-CandidateInput $role $relative)) { continue }
            if (-not (Test-CandidateInput $role $relative) -or -not $seen.Add($role + '/' + $relative)) {
                throw "Committed release input is outside the selected public payload: $role/$relative"
            }
            $sourcePath = [IO.Path]::GetFullPath((Join-Path $checkout $relative))
            if (-not (Test-Below $sourcePath $checkout)) { throw 'Committed source escaped its selected root.' }
            $identity = Get-SourceIdentity $sourcePath
            [long]$size = (Get-Item -LiteralPath $sourcePath).Length
            $total += $size
            if ($rows.Count -ge 1024 -or $size -gt 16MB -or $total -gt 128MB) {
                throw 'Release snapshot exceeds 1024 files, 16 MiB per file or 128 MiB total.'
            }
            $row = [pscustomobject]@{
                Source = $role; Path = $relative; Bytes = $size; Sha256 = $null
                SourcePath = $sourcePath; Identity = $identity
            }
            $row.Sha256 = Read-CandidateFile $row $sourcePath '' -CollectDigest
            if ((Get-SourceIdentity $sourcePath) -cne $identity) { throw 'Committed source changed while hashing.' }
            $rows.Add($row)
        }
    }
    $marker = if ($WorkingCandidate) { 'ARCHHUB_LOCAL_CANDIDATE_MANIFEST_V2' } else { 'ARCHHUB_RELEASE_SOURCE_MANIFEST_V2' }
    $revisionKey = if ($WorkingCandidate) { 'selected_base_revision' } else { 'selected_revision' }
    $lines = @(
        $marker, "build_id`t$BuildId",
        "selected_root`t$selectedRoot",
        "$revisionKey`t$sourceRevision",
        "source`tpath`tbytes`tsha256"
    )
    $lines += @($rows | ForEach-Object { "$($_.Source)`t$($_.Path)`t$($_.Bytes)`t$($_.Sha256)" })
    $bytes = $utf8.GetBytes(($lines -join "`n") + "`n")
    if ($bytes.Length -gt 262144) { throw 'Release source manifest exceeds 256 KiB.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    return [pscustomobject]@{
        Rows = $rows; Bytes = $bytes; Sha256 = $digest; TotalBytes = $total
        SelectedCheckout = $selectedRoot
    }
}

function Assert-BuildSnapshot($Manifest) {
    foreach ($row in $Manifest.Rows) {
        Read-CandidateFile $row (Join-Path (Join-Path (Join-Path $output 'source') $row.Source) $row.Path) ''
    }
    Assert-CandidateSources $Manifest
    if (-not $isCandidate) {
        Assert-TrackedInputs $Manifest.SelectedCheckout $selectedInputs
    }
}

function Read-StudioBuild {
    $generated = Join-Path $selectedRoot 'nodelang/studio/compiled'
    Assert-PlainAncestors $generated
    $names = @('tokens.js', 'design-canvas.js', 'shared-data.js', 'studio-suite.js',
        'param-types.js', 'studio-params.js', 'studio-mobile.js', 'studio-account.js',
        'studio-lm.js', 'mount.js')
    $entries = @(Get-ChildItem -LiteralPath $generated -Force)
    if ($entries.Count -ne 11) { throw 'Studio compiler did not produce exactly ten scripts and one manifest.' }
    foreach ($entry in $entries) {
        if ($entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            ($entry.Name -cne 'manifest.json' -and $entry.Name -cnotin $names)) {
            throw 'Unexpected Studio compiler output.'
        }
    }
    $manifestPath = Join-Path $generated 'manifest.json'
    if ((Get-Item -LiteralPath $manifestPath).Length -gt 32KB) { throw 'Studio compiler manifest exceeds 32 KiB.' }
    $bytes = [IO.File]::ReadAllBytes($manifestPath)
    $manifest = $utf8.GetString($bytes) | ConvertFrom-Json
    if ($manifest.format -ne 1 -or $manifest.files.Count -ne 10) { throw 'Unsupported Studio compiler manifest.' }
    # --check has reconciled source inputs, options and output bytes. Also bind
    # the exact physical output inventory here before handing it to Inno.
    [long]$total = 0
    for ($i = 0; $i -lt $names.Count; $i++) {
        $record = $manifest.files[$i]
        $path = Join-Path $generated $names[$i]
        $size = (Get-Item -LiteralPath $path).Length
        if ($record.output -cne $names[$i] -or $size -gt 2MB -or $record.bytes -ne $size -or
            $record.sha256 -cne (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()) {
            throw 'Studio compiler output does not match its manifest.'
        }
        $total += $size
    }
    if ($total -gt 4MB) { throw 'Studio compiler output exceeds 4 MiB total.' }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $digest = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    return [pscustomobject]@{ Bytes = $bytes; Sha256 = $digest; TotalBytes = $total; Files = 10 }
}

$sourceRevision = (& git -C $selectedRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceRevision -notmatch '^[0-9a-f]{40}$') {
    throw 'Selected source revision is unavailable.'
}
$candidate = $null
if ($PrepareCandidateManifest) {
    if ($BuildId -cnotmatch '^candidate-[A-Za-z0-9._-]+$' -or $env:CI -or $env:GITHUB_ACTIONS -or
        $LocalCandidateManifest -or $LocalCandidateManifestSha256) {
        throw 'Preparation is local candidate-* mode only; do not supply a prior manifest.'
    }
    $publicRoot = Split-Path -Parent $selectedRoot
    if ((Split-Path -Leaf $publicRoot) -cne '10.PRODUCT') { throw 'Canonical public checkout required.' }
    $preparedOutput = [IO.Path]::GetFullPath($OutputDirectory)
    $handoffsRoot = Join-Path (Split-Path -Parent $publicRoot) '70.HANDOFFS'
    if ((-not (Test-Below $preparedOutput $publicRoot) -and -not (Test-Below $preparedOutput $handoffsRoot)) -or
        (Test-Below $preparedOutput $selectedRoot) -or (Test-Path -LiteralPath $preparedOutput)) {
        throw 'Preparation requires a new governed directory outside the canonical checkout.'
    }
    Assert-PlainAncestors $selectedRoot
    Assert-PlainAncestors (Split-Path -Parent $preparedOutput)
    $candidateClock = [Diagnostics.Stopwatch]::StartNew()
    $candidateBuffer = [byte[]]::new(1MB)
    $prepared = Read-ReleaseSnapshotManifest -WorkingCandidate
    New-Item -ItemType Directory -Path $preparedOutput -ErrorAction Stop | Out-Null
    $preparedPath = Join-Path $preparedOutput 'candidate-manifest.tsv'
    [IO.File]::WriteAllBytes($preparedPath, $prepared.Bytes)
    $LocalCandidateManifestSha256 = $prepared.Sha256
    $null = Read-CandidateManifest $preparedPath
    Write-Output "Prepared manifest: $preparedPath"
    Write-Output "SHA256: $($prepared.Sha256)"
    Write-Output "Files: $($prepared.Rows.Count); bytes: $($prepared.TotalBytes). Review before building; no compiler or application launched."
    return
}
$isCandidate = -not [string]::IsNullOrEmpty($LocalCandidateManifest)
if ($isCandidate -ne (-not [string]::IsNullOrEmpty($LocalCandidateManifestSha256))) {
    throw 'LocalCandidateManifest and its reviewed SHA256 must be supplied together.'
}
if ($isCandidate) {
    if ($BuildId -cnotmatch '^candidate-[A-Za-z0-9._-]+$' -or $env:CI -or $env:GITHUB_ACTIONS) {
        throw 'Candidate mode is local only and requires a candidate-* BuildId.'
    }
    $publicRoot = Split-Path -Parent $selectedRoot
    if ((Split-Path -Leaf $publicRoot) -cne '10.PRODUCT') {
        throw 'Local candidates require the canonical selected checkout inside the public 10.PRODUCT area.'
    }
    Assert-PlainAncestors $selectedRoot
    $candidate = Read-CandidateManifest ([IO.Path]::GetFullPath($LocalCandidateManifest))
} else {
    Assert-TrackedInputs $selectedRoot $selectedInputs
}

if (-not $IsccPath) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6/ISCC.exe')
    )
    $IsccPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw 'Inno Setup 6 ISCC.exe is required; pass its installed absolute path.'
}
$compiler = (Resolve-Path -LiteralPath $IsccPath).Path
if (-not $NodePath) {
    $NodePath = (Get-Command node.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
if (-not (Test-Path -LiteralPath $NodePath -PathType Leaf)) { throw 'Node.js 24 is required for the Studio build.' }
$node = (Resolve-Path -LiteralPath $NodePath).Path
$nodeVersion = (& $node --version).Trim()
if ($LASTEXITCODE -ne 0 -or $nodeVersion -cnotmatch '^v24\.[0-9]+\.[0-9]+$') {
    throw 'The reviewed Studio build requires Node.js 24.'
}
$nodeRuntimeSha = 'd14ba95cdce1ef7dc9ad3ac74949ca5db38b27378ee30f30a23cf26f9e875a11'
if ((Get-FileHash -LiteralPath $node -Algorithm SHA256).Hash.ToLowerInvariant() -cne $nodeRuntimeSha) {
    throw 'Bundled Workshop runtime must match the pinned Node v24.13.0 Windows x64 executable.'
}
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) {
    throw 'OutputDirectory must be new; previous build artifacts are never overwritten.'
}
if (-not (Test-Path -LiteralPath (Split-Path -Parent $output) -PathType Container)) {
    throw 'OutputDirectory must have an existing parent.'
}

$buildOutputCreated = $false
$statusName = if ($candidate) { 'candidate-status.txt' } else { 'build-status.txt' }
try {
if ($candidate) {
    $handoffsRoot = Join-Path (Split-Path -Parent $publicRoot) '70.HANDOFFS'
    if (-not (Test-Below $output $publicRoot) -and -not (Test-Below $output $handoffsRoot)) {
        throw 'Candidate output must be a new governed WIP directory under 10.PRODUCT or 70.HANDOFFS.'
    }
}
Assert-PlainAncestors (Split-Path -Parent $output)
if (Test-Below $output $selectedRoot) {
    throw 'Build output must be outside the selected source checkout.'
}
# No -Force: refuse a concurrent creator of the new output directory. Public
# builds use the same bounded snapshot path, retaining their committed gates.
New-Item -ItemType Directory -Path $output -ErrorAction Stop | Out-Null
$buildOutputCreated = $true
Assert-PlainAncestors $output
[IO.File]::WriteAllText((Join-Path $output $statusName), "COPYING: not an installable or accepted artifact.`n", $utf8)
$candidateClock = [Diagnostics.Stopwatch]::StartNew()
$candidateBuffer = [byte[]]::new(1MB)
$snapshot = if ($candidate) { $candidate } else { Read-ReleaseSnapshotManifest }
$volume = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($output))
if ($volume.AvailableFreeSpace -lt ($snapshot.TotalBytes * 2 + 8MB + 256MB)) {
    throw 'Source snapshot, generated Studio files and installer require their logical size plus a 256 MiB disk reserve.'
}
$sourceManifestName = if ($candidate) { 'candidate-manifest.tsv' } else { 'source-manifest.tsv' }
[IO.File]::WriteAllBytes((Join-Path $output $sourceManifestName), $snapshot.Bytes)
Assert-CandidateSources $snapshot
if (-not $isCandidate) {
    Assert-TrackedInputs $snapshot.SelectedCheckout $selectedInputs
}
foreach ($row in $snapshot.Rows) {
    $destination = Join-Path (Join-Path (Join-Path $output 'source') $row.Source) $row.Path
    Read-CandidateFile $row $row.SourcePath $destination
}
Assert-CandidateSources $snapshot
$selectedRoot = Join-Path $output 'source/selected'

# Apply the existing portability gate to shipped code, not tests or private
# workspace areas. A refusal needs a source repair, never a gate bypass.
$portabilityGate = Join-Path $selectedRoot 'packaging/windows/Test-SourcePortability.ps1'
$shippedCode = @(
    (Join-Path $selectedRoot 'nodelang'),
    (Join-Path $selectedRoot 'launch_archhub_test.py'),
    (Join-Path $selectedRoot 'colleague_setup.py'),
    (Join-Path $selectedRoot 'personal_brain'),
    (Join-Path $selectedRoot 'app/secrets_store.py'),
    (Join-Path $selectedRoot 'app/credential_lock.py'),
    (Join-Path $selectedRoot 'bridges/rhino/archhub_mcp.py'),
    (Join-Path $selectedRoot 'bridges/blender/archhub_mcp')
)
foreach ($codePath in $shippedCode) {
    $LASTEXITCODE = 0
    & $portabilityGate -SourceRoot $codePath
    if ($LASTEXITCODE -ne 0) { throw 'A shipped input failed the source portability gate.' }
}

Assert-BuildSnapshot $snapshot
$candidateClock.Stop()
[IO.File]::WriteAllText((Join-Path $output $statusName), "COMPILING STUDIO: verified source snapshot; no runtime or installer acceptance.`n", $utf8)
$studioCompiler = Join-Path $selectedRoot 'packaging/compile_studio.cjs'
$studioOutput = Join-Path $selectedRoot 'nodelang/studio/compiled'
if (Test-Path -LiteralPath $studioOutput) { throw 'Verified source snapshot already contains generated Studio output.' }
# Serial, explicit build only. 192 MiB bounds V8 old space, not total RSS;
# local physical builds additionally run under the parent's process-tree guard.
# The compiler uses only vendored Babel; no npm install or runtime JSX compiler.
& $node --max-old-space-size=192 $studioCompiler
if ($LASTEXITCODE -ne 0) { throw 'Studio compilation failed; retained output must not be installed.' }
& $node --max-old-space-size=192 $studioCompiler --check
if ($LASTEXITCODE -ne 0) { throw 'Studio compiled output failed its source/output reconciliation.' }
$candidateClock.Start()
Assert-BuildSnapshot $snapshot
$studioBuild = Read-StudioBuild
[IO.File]::WriteAllBytes((Join-Path $output 'studio-build.json'), $studioBuild.Bytes)
$candidateClock.Stop()
[IO.File]::WriteAllText((Join-Path $output $statusName), "COMPILING INSTALLER: source inputs and generated Studio output verified.`n", $utf8)
$requirementsSha = (Get-FileHash -LiteralPath (Join-Path $selectedRoot 'requirements.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
$buildMetadataPath = Join-Path $output 'BUILD_METADATA.json'
$buildMetadata = [ordered]@{ format = 1; build_id = $BuildId; built_at = $builtAt }
[IO.File]::WriteAllText($buildMetadataPath, ($buildMetadata | ConvertTo-Json -Compress) + "`n", $utf8)
$buildMetadataSha = (Get-FileHash -LiteralPath $buildMetadataPath -Algorithm SHA256).Hash.ToLowerInvariant()
$installer = Join-Path $selectedRoot 'installer/ArchHub.iss'
$nodeLicense = Join-Path $selectedRoot 'packaging/windows/licenses/Node-v24.13.0-LICENSE.txt'
if (-not (Test-Path -LiteralPath $nodeLicense -PathType Leaf)) { throw 'Bundled Node license is missing.' }
& $compiler "/DBuildId=$BuildId" "/DRequirementsSha256=$requirementsSha" "/DBuildMetadataPath=$buildMetadataPath" "/DNodeRuntimePath=$node" "/DNodeLicensePath=$nodeLicense" "/O$output" $installer
if ($LASTEXITCODE -ne 0) { throw "Selected installer compilation failed with exit code $LASTEXITCODE." }
if ((Get-FileHash -LiteralPath $node -Algorithm SHA256).Hash.ToLowerInvariant() -cne $nodeRuntimeSha) {
    throw 'Node runtime changed during installer compilation; retain artifact for inspection only.'
}

& $node --max-old-space-size=192 $studioCompiler --check
if ($LASTEXITCODE -ne 0) { throw 'Studio output changed during installer compilation.' }
$candidateClock.Start()
Assert-BuildSnapshot $snapshot
$finalStudioBuild = Read-StudioBuild
if ($finalStudioBuild.Sha256 -cne $studioBuild.Sha256) { throw 'Studio build manifest changed during installer compilation.' }
if ((Get-FileHash -LiteralPath $buildMetadataPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $buildMetadataSha) {
    throw 'Installed build ordering metadata changed during installer compilation.'
}
$candidateClock.Stop()
$assetName = 'ArchHub-Setup-0.exe'
$assetPath = Join-Path $output $assetName
if (-not (Test-Path -LiteralPath $assetPath -PathType Leaf)) {
    throw 'Compiler did not produce the exact updater asset.'
}
Assert-PlainAncestors $assetPath
$assetSha = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($candidate) {
    $metadata = [ordered]@{
        format = 1
        kind = 'local_candidate'
        build_id = $BuildId
        built_at = $builtAt
        build_metadata_sha256 = $buildMetadataSha
        payload_manifest = 'candidate-manifest.tsv'
        payload_manifest_sha256 = $candidate.Sha256
        source_base_revision = $sourceRevision
        payload_files = $candidate.Rows.Count
        payload_bytes = $candidate.TotalBytes
        requirements_sha256 = $requirementsSha
        studio_manifest = 'studio-build.json'
        studio_manifest_sha256 = $studioBuild.Sha256
        studio_files = $studioBuild.Files
        studio_bytes = $studioBuild.TotalBytes
        studio_node_version = $nodeVersion
        asset_name = $assetName
        asset_sha256 = $assetSha
        asset_bytes = (Get-Item -LiteralPath $assetPath).Length
        installation_boundary = 'Build only. The installer retains the real application AppId, registry and shortcuts. It is not an isolated-install fixture. Installing requires the reviewed activation of the real application.'
        acceptance = 'Exact reviewed source bytes compiled; no installed behavior, public release or product-completion claim.'
    }
    [IO.File]::WriteAllText((Join-Path $output 'candidate.json'), ($metadata | ConvertTo-Json) + "`n", $utf8)
    [IO.File]::WriteAllText((Join-Path $output 'candidate-status.txt'), "COMPILED LOCAL CANDIDATE: build only; installation and runtime acceptance remain open.`n", $utf8)
    Write-Output "Built local candidate $assetName with BUILD_ID $BuildId. Nothing installed or published."
} else {
$metadata = [ordered]@{
    format = 1
    build_id = $BuildId
    built_at = $builtAt
    build_metadata_sha256 = $buildMetadataSha
    source_revision = $sourceRevision
    requirements_sha256 = $requirementsSha
    payload_manifest = $sourceManifestName
    payload_manifest_sha256 = $snapshot.Sha256
    payload_files = $snapshot.Rows.Count
    payload_bytes = $snapshot.TotalBytes
    studio_manifest = 'studio-build.json'
    studio_manifest_sha256 = $studioBuild.Sha256
    studio_files = $studioBuild.Files
    studio_bytes = $studioBuild.TotalBytes
    studio_node_version = $nodeVersion
    asset_name = $assetName
    asset_sha256 = $assetSha
    asset_bytes = (Get-Item -LiteralPath $assetPath).Length
}
[IO.File]::WriteAllText((Join-Path $output 'release.json'), ($metadata | ConvertTo-Json) + "`n", $utf8)
$notes = @(
    "BUILD_ID: $BuildId",
    "BUILT_AT: $builtAt",
    "SHA256 ${assetName}: $assetSha",
    "SOURCE_REVISION: $sourceRevision",
    "REQUIREMENTS_SHA256: $requirementsSha"
)
[IO.File]::WriteAllText((Join-Path $output 'release-notes.md'), ($notes -join "`n") + "`n", $utf8)
[IO.File]::WriteAllText((Join-Path $output $statusName), "COMPILED: source snapshot and Studio output reconciled; nothing installed or published.`n", $utf8)
Write-Output "Built $assetName with BUILD_ID $BuildId. No release was published."
}
} catch {
    if ($buildOutputCreated) {
        try {
            [IO.File]::WriteAllText((Join-Path $output $statusName),
                "FAILED: partial source/build output retained for inspection. Do not install or publish.`n", $utf8)
        } catch { Write-Warning "Could not record build failure status at $output" }
        Write-Warning "Failed build output retained at $output; no source or previous artifact was removed."
    }
    throw
}
