param([string]$Base)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$toolchain = 'C:\Users\fargaly\00.ARCHUB\10.PRODUCT\rust'
$setup = 'C:\Users\fargaly\00.ARCHUB\10.PRODUCT\13.NODE-LANGUAGE\tools\archhub-compiler\target\msvc\setup_x64.bat'
$environmentLines = & $env:COMSPEC /d /s /c ('""' + $setup + '" >nul && set"')
if ($LASTEXITCODE -ne 0) { throw 'Supplied compiler toolchain environment refused' }
foreach ($line in $environmentLines) {
    if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') }
}
$env:CARGO_HOME = Join-Path $toolchain 'cargo'
$env:RUSTUP_HOME = Join-Path $toolchain 'rustup'
$env:CARGO_TARGET_DIR = Join-Path $root '.c'
$env:PATH = (Join-Path $toolchain 'cargo/bin') + ';' + $env:PATH
$env:ARCHHUB_INTENT_CONTEXT = Join-Path $PSScriptRoot 'intent-context.json'
Set-Location $root
$clock = [Diagnostics.Stopwatch]::StartNew()
Write-Output ('STAGED_PATH_COUNT=' + @(git diff --cached --name-only).Count)
if ($Base) {
    & 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe' tools/pipeline/strict_check.py --base $Base
} else {
    & 'C:\Users\fargaly\AppData\Local\ArchHub\.venv\Scripts\python.exe' tools/pipeline/strict_check.py --changed
}
$status = $LASTEXITCODE
Write-Output ('STRICT_SECONDS=' + $clock.Elapsed.TotalSeconds.ToString('R', [Globalization.CultureInfo]::InvariantCulture))
exit $status
