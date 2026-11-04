$ErrorActionPreference = 'Stop'
$laneRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $laneRoot '03.TOOLS/installer/build_release.ps1'
$source = [IO.File]::ReadAllText($scriptPath)
# Reuse the release's exact read-only manifest generator, stopping before candidate preparation/runtime packing.
$boundary = $source.IndexOf('if ($PrepareCandidateManifest) {', [StringComparison]::Ordinal)
if ($boundary -lt 0) { throw 'Release manifest boundary missing' }
$releaseScriptDirectory = Split-Path -Parent $scriptPath
$prefix = $source.Substring(0, $boundary).Replace('$PSScriptRoot', '$releaseScriptDirectory')
$operation = [scriptblock]::Create($prefix + '$candidateBuffer = [byte[]]::new(1MB)' + "`nRead-ReleaseSnapshotManifest`n")
$goose = 'C:\Users\fargaly\AppData\Local\Temp\claude\C--Users-fargaly-00-ARCHUB\9df7d82e-cf7b-4916-b0ba-7d9ee744173a\scratchpad\RELEASE\GOOSE.zip'
$timer = [Diagnostics.Stopwatch]::StartNew()
$manifest = & $operation -BuildId 'repolayout-baseline-8866b397' -OutputDirectory (Join-Path $env:TEMP 'repolayout-unused') -GooseArchivePath $goose
$timer.Stop()
[IO.File]::WriteAllBytes((Join-Path $PSScriptRoot 'repo-layout-source-manifest.txt'), $manifest.Bytes)
$rows = @($manifest.Rows | ForEach-Object { "$($_.Source)`t$($_.Path)`t$($_.Bytes)`t$($_.Sha256)" } | Sort-Object)
$bytes = [Text.UTF8Encoding]::new($false).GetBytes(($rows -join "`n") + "`n")
[IO.File]::WriteAllBytes((Join-Path $PSScriptRoot 'repo-layout-payload-rows.txt'), $bytes)
@{method='Exact read-only Read-ReleaseSnapshotManifest from build_release.ps1; excludes generated runtime and compiler outputs'; source_revision=(& git -C $laneRoot rev-parse HEAD); observed_wall_clock_s=$timer.Elapsed.TotalSeconds; files=$manifest.Rows.Count; bytes=$manifest.TotalBytes; manifest_sha256=$manifest.Sha256; native_rows_sha256=([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()); release_script_sha256=(Get-FileHash $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant()} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $PSScriptRoot 'repo-layout-source-measurement.json')
