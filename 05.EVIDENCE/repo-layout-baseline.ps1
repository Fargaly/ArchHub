param([string]$BrokerReviewPath)
$ErrorActionPreference = 'Stop'
$laneRoot = Split-Path -Parent $PSScriptRoot
$env:ARCHHUB_INTENT_CONTEXT = Join-Path $PSScriptRoot 'repo-layout-intent-context.json'
$env:CARGO_HOME = Join-Path $env:LOCALAPPDATA 'rs/cargo'
$env:RUSTUP_HOME = Join-Path $env:LOCALAPPDATA 'rs/rustup'
$baselineOutput = Join-Path $env:TEMP ('repolayout-baseline-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$timer = [Diagnostics.Stopwatch]::StartNew()
$buildArgs = @{
 BuildId = 'repolayout-baseline-8866b397'
 OutputDirectory = $baselineOutput
 GooseArchivePath = 'C:\Users\fargaly\AppData\Local\Temp\claude\C--Users-fargaly-00-ARCHUB\9df7d82e-cf7b-4916-b0ba-7d9ee744173a\scratchpad\RELEASE\GOOSE.zip'
}
if ($BrokerReviewPath) { $buildArgs.BrokerReviewPath = $BrokerReviewPath }
$buildError = $null
try { & (Join-Path $laneRoot '03.TOOLS/installer/build_release.ps1') @buildArgs *>&1 | Tee-Object (Join-Path $PSScriptRoot 'repo-layout-baseline.log') }
catch { $buildError = $_.Exception.Message; $_ | Out-String | Tee-Object -Append (Join-Path $PSScriptRoot 'repo-layout-baseline.log') }
$timer.Stop()
$manifest = Join-Path $baselineOutput 'source-manifest.tsv'
$manifestHash = if (Test-Path -LiteralPath $manifest) { (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
@{base_sha=(& git -C $laneRoot rev-parse HEAD); observed_wall_clock_s=$timer.Elapsed.TotalSeconds; success=($null -eq $buildError); error=$buildError; output=$baselineOutput; payload_manifest_sha256=$manifestHash; installed=$false; build_script='03.TOOLS/installer/build_release.ps1'} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $PSScriptRoot 'repo-layout-baseline.json')
if ($buildError) { exit 1 }
