param([switch]$ResumeAfterDependencies)
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$profileRoot = Join-Path $PSScriptRoot 'court-state/js-profile'
foreach ($name in @('LOCALAPPDATA','APPDATA','USERPROFILE','HOME','TEMP','TMP')) {
    $directory = Join-Path $profileRoot $name
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [Environment]::SetEnvironmentVariable($name, $directory, 'Process')
}
$env:ARCHHUB_TEST_STATE_DIR = Join-Path $env:LOCALAPPDATA 'ArchHub'
$env:PYTHON = 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe'
foreach ($name in @('LAZYBOOT_CANVAS_REPORT','LAZYBOOT_WORKSPACE_REPORT','LAZYBOOT_GRAPH_REPORT','ARCHHUB_LEGACY_STATE_DIR')) {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
if (-not $ResumeAfterDependencies) {
    & (Join-Path $PSScriptRoot 'cleanup_big_fixture.ps1')
    $env:npm_config_cache = Join-Path $PSScriptRoot 'court-state/npm-cache'
    & $env:COMSPEC /d /s /c '""C:\Program Files\nodejs\npm.cmd" ci --ignore-scripts --no-audit --no-fund > evidence\mainrel\npm-ci.txt 2>&1"'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
# Production Studio was compiled once in run_local_checks; only a fixture changed.
& 'C:\Program Files\nodejs\node.exe' '--test' '--test-concurrency=1' '--test-force-exit' 'tests_js/studio_home_session.test.cjs' 'tests_js/studio_existing_workshop.test.cjs' 'tests_js/studio_lazyboot_home.test.cjs'
exit $LASTEXITCODE
