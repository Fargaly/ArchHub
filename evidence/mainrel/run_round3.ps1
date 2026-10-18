param([ValidateSet('guards','syntax','settings','ci','armed','payload','final')][string]$Court='guards')
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $root
foreach ($name in @('LOCALAPPDATA','APPDATA','USERPROFILE','HOME','TEMP','TMP')) {
    $directory=Join-Path $PSScriptRoot ('court-state/round3/'+$name)
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [Environment]::SetEnvironmentVariable($name,$directory,'Process')
}
$env:ARCHHUB_TEST_STATE_DIR=Join-Path $env:LOCALAPPDATA 'ArchHub'
$env:CODEX_HOME=Join-Path $env:USERPROFILE '.codex'
$env:CLAUDE_CONFIG_DIR=Join-Path $env:USERPROFILE '.claude'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PSModulePath=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/Modules'
$interpreter='C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe'
if ($Court -eq 'syntax') {
    $tokens=$null; $errors=$null
    foreach ($script in @('installer/rollback-rehearsal.ps1','installer/rollback-rehearsal-ci/prepare-rehearsal.ps1')) {
        [Management.Automation.Language.Parser]::ParseFile((Join-Path $root $script),[ref]$tokens,[ref]$errors) | Out-Null
        if ($errors.Count) { $errors | Format-List; exit 1 }
    }
    Write-Output 'ROLLBACK_POWERSHELL_PARSE_ERRORS=0'
    & (Join-Path $PSScriptRoot 'compile_installer_code.ps1')
} elseif ($Court -eq 'armed') {
    & $interpreter '-B' '-m' 'pytest' '-q' '-s' '-p' 'no:cacheprovider' '-p' 'evidence.mainrel.round3_fixture' '--tb=short' 'tests_replica/test_mainrel_round3.py::test_three_installs_replace_pin_with_real_size_accounting[True]'
} elseif ($Court -eq 'payload') {
    & $interpreter '-B' '-m' 'pytest' '-x' '-q' '-p' 'no:cacheprovider' '-p' 'evidence.mainrel.round3_fixture' '--tb=short' 'tests_replica/test_autoupd.py'
} elseif ($Court -eq 'ci') {
    & $interpreter '-B' '-m' 'pytest' '-q' '-s' '-p' 'no:cacheprovider' '-p' 'evidence.mainrel.round3_fixture' '--tb=short' 'tests_replica/test_mainrel_ci.py' 'tests_replica/test_mainrel_rollback.py' 'tests_replica/test_mainrel_round3.py'
} elseif ($Court -eq 'settings') {
    & $interpreter '-B' '-m' 'pytest' '-q' '-p' 'no:cacheprovider' '-p' 'evidence.mainrel.round3_fixture' '--tb=short' 'tests_replica/test_stage2b_integration.py' 'tests_replica/test_mainrel_settings.py'
} else {
    $courts=@('tests_replica/test_mainrel_installer.py','tests_replica/test_adopt_backup_resume5.py',
        'tests_replica/test_mainrel_connectors.py','tests_replica/test_assistant_registration.py',
        'tests_replica/test_mainrel_update.py','tests_replica/test_quiet_update.py','tests_replica/test_autoupd.py',
        'tests_replica/test_mainrel_rollback.py','tests_replica/test_backups_keep_three_days.py')
    if ($Court -eq 'final') { $courts += @('tests_replica/test_mainrel_round3.py','tests_replica/test_mainrel_ci.py','tests/test_zero_idle_growth.py') }
    & $interpreter '-B' '-m' 'pytest' '-q' '-s' '-p' 'no:cacheprovider' '-p' 'evidence.mainrel.round3_fixture' '--tb=short' @courts
}
exit $LASTEXITCODE
