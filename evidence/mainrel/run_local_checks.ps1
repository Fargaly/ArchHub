$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe'
Set-Location $root
& (Join-Path $PSScriptRoot 'reset_fixture_backups.ps1')
& $python (Join-Path $PSScriptRoot 'measure_big.py')
$measurementStatus = $LASTEXITCODE
& 'C:\Program Files\nodejs\node.exe' '--max-old-space-size=256' 'packaging/compile_studio.cjs'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& 'C:\Program Files\nodejs\node.exe' '--test' '--test-concurrency=1' '--test-force-exit' 'tests_js/studio_home_session.test.cjs' 'tests_js/studio_existing_workshop.test.cjs' 'tests_js/studio_lazyboot_home.test.cjs'
$jsStatus = $LASTEXITCODE
& (Join-Path $PSScriptRoot 'compile_installer_code.ps1')
$innoStatus = $LASTEXITCODE
$receipt = [ordered]@{measurement_exit=$measurementStatus;studio_compile_exit=0;js_exit=$jsStatus;inno_exit=$innoStatus}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'local-check-status.json'), ($receipt | ConvertTo-Json))
if ($measurementStatus -ne 0 -or $jsStatus -ne 0 -or $innoStatus -ne 0) { exit 1 }
exit 0
