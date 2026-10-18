param([ValidateSet('home','rollback','zero','final','wiring')][string]$Court = 'home')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $root
foreach ($name in @('LOCALAPPDATA','APPDATA','USERPROFILE','HOME','TEMP','TMP')) {
    $directory = Join-Path $PSScriptRoot ('court-state/round2/' + $name)
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [Environment]::SetEnvironmentVariable($name, $directory, 'Process')
}
$env:ARCHHUB_TEST_STATE_DIR = Join-Path $env:LOCALAPPDATA 'ArchHub'
$env:PYTHON = 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe'
$env:CODEX_HOME = Join-Path $env:USERPROFILE '.codex'
$env:CLAUDE_CONFIG_DIR = Join-Path $env:USERPROFILE '.claude'
$env:PYTHONDONTWRITEBYTECODE = '1'
if ($Court -eq 'home') {
    if (-not (Test-Path -LiteralPath 'node_modules/jsdom/package.json')) {
        $env:npm_config_cache = Join-Path $PSScriptRoot 'court-state/round2/npm'
        & 'C:\Program Files\nodejs\npm.cmd' ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    & 'C:\Program Files\nodejs\node.exe' '--test' '--test-concurrency=1' '--test-force-exit' 'tests_js/studio_home_session.test.cjs' 'tests_js/studio_existing_workshop.test.cjs' 'tests_js/studio_lazyboot_home.test.cjs' 'tests_js/studio_ds_port.test.cjs' 'tests_js/studio_baboom5.test.cjs'
} elseif ($Court -eq 'rollback') {
    & $env:PYTHON -m pytest -q -p no:cacheprovider tests_replica/test_mainrel_rollback.py
} elseif ($Court -eq 'zero') {
    & $env:PYTHON -m pytest -q -p no:cacheprovider tests/test_zero_idle_growth.py
} elseif ($Court -eq 'wiring') {
    & $env:PYTHON -m pytest -q -p no:cacheprovider tests_replica/test_mainrel_update.py tests_replica/test_reads_desktop.py tests_replica/test_backups_keep_three_days.py
} else {
    & $env:PYTHON -m pytest -q -p no:cacheprovider tests_replica/test_mainrel_update.py tests_replica/test_mainrel_rollback.py tests/test_zero_idle_growth.py
}
exit $LASTEXITCODE
