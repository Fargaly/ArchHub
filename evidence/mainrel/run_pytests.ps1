param([ValidateSet('fast','rest','transport','first','zero')][string]$Mode = 'fast',
      [switch]$FailFast, [string[]]$Court, [switch]$Baseline)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$profileRoot = Join-Path $PSScriptRoot 'court-state/test-profile'
New-Item -ItemType Directory -Path $profileRoot -Force | Out-Null
foreach ($name in @('LOCALAPPDATA','APPDATA','USERPROFILE','HOME','TEMP','TMP')) {
    $directory = Join-Path $profileRoot $name
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [Environment]::SetEnvironmentVariable($name, $directory, 'Process')
}
$env:CODEX_HOME = Join-Path $env:USERPROFILE '.codex'
$env:CLAUDE_CONFIG_DIR = Join-Path $env:USERPROFILE '.claude'
$env:ARCHHUB_TEST_STATE_DIR = Join-Path $env:LOCALAPPDATA 'ArchHub-Test'
Remove-Item Env:ARCHHUB_LEGACY_STATE_DIR -ErrorAction SilentlyContinue
Set-Location $root
if ($Baseline) {
    & 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe' -B evidence/mainrel/baseline_red.py
    exit $LASTEXITCODE
}
$courts = @('tests_replica/test_mainrel_installer.py', 'tests_replica/test_adopt_backup_resume5.py',
    'tests_replica/test_mainrel_connectors.py', 'tests_replica/test_assistant_registration.py',
    'tests_replica/test_mainrel_update.py')
if ($Mode -eq 'rest') {
    $courts += @('tests_replica/test_colleague_install.py', 'tests_replica/test_a_colleague_machine_is_not_the_founders.py',
        'tests_replica/test_backups_keep_three_days.py', 'tests_replica/test_autoupd.py',
        'tests_replica/test_baboom_asks_before_restart_and_answers_its_menu.py',
        'tests_replica/test_ogboot_upgrade_selection.py', 'tests_replica/test_adopt_resume5.py')
}
if ($Mode -eq 'transport') { $courts = @('tests_replica/test_application_machine_transport.py') }
if ($Mode -eq 'first') { $courts += @('tests_replica/test_colleague_install.py', 'tests_replica/test_application_machine_transport.py') }
if ($Mode -eq 'zero') { $courts = @('tests/test_zero_idle_growth.py') }
if ($Court) { $courts = $Court }
$options = @('-q', '-p', 'no:cacheprovider', '--tb=short')
if ($Mode -eq 'first' -or $FailFast) { $options += '-x' }
& 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe' -m pytest @options @courts
exit $LASTEXITCODE
