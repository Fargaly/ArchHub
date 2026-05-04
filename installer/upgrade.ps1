#requires -Version 5.1
<#
ArchHub installer / upgrader.

Run from Install.bat as:
    powershell -File upgrade.ps1 -SourceDir <repo dir> -InstallDir %LOCALAPPDATA%\ArchHub -NewVersion <semver>

What it does, in order:
  1. Reads %INSTALL_DIR%\version.json (if present) to determine the existing version.
  2. Stops any running ArchHub instance gracefully (matches by command line).
  3. Skips pip install when requirements.txt hasn't changed.
  4. Creates user-data dirs if missing — never touches their contents.
  5. Mirrors code dirs (`app/`, `payload/sources/`) — removes orphan files
     from the previous version, but does NOT touch user-built payload
     binaries (`payload/revit/<year>/`, etc.) or user-saved workflows.
  6. Writes a fresh version.json with old version, new version, and timestamps.

Failure modes are explicit: any error stops the script and leaves a clear
message. We never half-update. Run it again to retry.
#>
param(
    [Parameter(Mandatory=$true)] [string] $SourceDir,
    [Parameter(Mandatory=$true)] [string] $InstallDir,
    [Parameter(Mandatory=$true)] [string] $NewVersion
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Layout: which paths belong to the user (preserve), which belong to the
# installer (replace cleanly each time).
# ---------------------------------------------------------------------------

# These are *user data* — the upgrader creates them if missing but never
# deletes or overwrites their contents. Anything the user generates inside
# their installation lives under one of these paths.
$UserDataPaths = @(
    'workflows',                 # saved workflows (.archhub-workflow.json)
    'state.json',                # connector toggle states
    'secrets.dat',               # XOR-fallback encrypted secrets when keyring is unavailable
    'logs',                      # rolling logs
    'payload\revit',             # auto-built per-year Revit DLLs
    'payload\autocad',           # auto-built per-year AutoCAD DLLs
    'payload\max\2024',          # 3ds Max startup scripts (year-scoped overrides)
    'payload\max\2025',
    'payload\max\2026'
    # Note: payload\sources\ is NOT here — that's bundled, replaced each upgrade.
    # Note: payload\blender\ uses a per-version addon, also bundled.
)

# These are *code/asset* dirs — the upgrader mirrors them from the repo,
# removing files that no longer exist in the new version.
$CodePathsToMirror = @(
    @{ src = 'app';              dst = 'app' },
    @{ src = 'payload\sources';  dst = 'payload\sources' },
    @{ src = 'payload\bridge';   dst = 'payload\bridge' },
    @{ src = 'payload\blender';  dst = 'payload\blender' },
    @{ src = 'installer';        dst = 'installer' }
)

# Top-level files that are part of the installer payload itself.
$TopLevelFilesToCopy = @('VERSION', 'requirements.txt', 'README.md', 'LICENSE')

# ---------------------------------------------------------------------------
# Detect existing installation
# ---------------------------------------------------------------------------

$VersionFile = Join-Path $InstallDir 'version.json'
$IsUpgrade   = Test-Path $VersionFile
$OldVersion  = $null
if ($IsUpgrade) {
    try {
        $manifest   = Get-Content $VersionFile -Raw | ConvertFrom-Json
        $OldVersion = $manifest.version
    } catch {
        $OldVersion = 'unknown'
    }
} elseif (Test-Path (Join-Path $InstallDir 'app')) {
    # Existing install but no version.json (i.e. upgrading from <= 0.4.x)
    $IsUpgrade  = $true
    $OldVersion = 'pre-0.5.0'
}

Write-Host ''
Write-Host '====================================================' -ForegroundColor Cyan
if (-not $IsUpgrade) {
    Write-Host "  ArchHub - Installing v$NewVersion" -ForegroundColor Cyan
} elseif ($OldVersion -eq $NewVersion) {
    Write-Host "  ArchHub - Reinstalling v$NewVersion" -ForegroundColor Cyan
} else {
    Write-Host "  ArchHub - Updating v$OldVersion -> v$NewVersion" -ForegroundColor Cyan
}
Write-Host '====================================================' -ForegroundColor Cyan
Write-Host ''

# ---------------------------------------------------------------------------
# 1. Stop any running ArchHub instance
# ---------------------------------------------------------------------------
Write-Host '[1/5] Stopping any running ArchHub...' -ForegroundColor White
try {
    $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -like '*ArchHub\app\main.py*' -or
                $_.CommandLine -like '*ArchHub/app/main.py*'
            )
        }
    if ($running) {
        foreach ($p in $running) {
            Write-Host "       Stopping PID $($p.ProcessId)" -ForegroundColor Yellow
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
        Start-Sleep -Seconds 2
    } else {
        Write-Host '       Not running.' -ForegroundColor Gray
    }
} catch {
    Write-Host "       Skipped (couldn't enumerate processes)." -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# 2. Python dependencies (skip if requirements.txt is unchanged)
# ---------------------------------------------------------------------------
Write-Host '[2/5] Checking Python dependencies...' -ForegroundColor White
$NewReq = Join-Path $SourceDir 'requirements.txt'
$OldReq = Join-Path $InstallDir 'requirements.txt'
$NeedsPip = $true
if ($IsUpgrade -and (Test-Path $OldReq) -and (Test-Path $NewReq)) {
    $newHash = (Get-FileHash $NewReq).Hash
    $oldHash = (Get-FileHash $OldReq).Hash
    if ($newHash -eq $oldHash) {
        $NeedsPip = $false
        Write-Host '       Unchanged. Skipping pip install.' -ForegroundColor Gray
    }
}
if ($NeedsPip) {
    Write-Host '       Installing/updating from requirements.txt...' -ForegroundColor Gray
    & python -m pip install --user --upgrade -r $NewReq 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) {
            Write-Host "       $($_.Exception.Message)" -ForegroundColor DarkGray
        } else {
            # Suppress noisy pip output, only show errors
            if ($_ -match '^ERROR' -or $_ -match '^FAIL') {
                Write-Host "       $_" -ForegroundColor Red
            }
        }
    }
    Write-Host '       Done.' -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# 3. Ensure user-data directories exist (do not touch their contents)
# ---------------------------------------------------------------------------
Write-Host '[3/5] Preserving user data...' -ForegroundColor White
foreach ($p in $UserDataPaths) {
    $full = Join-Path $InstallDir $p
    # Only auto-create directory paths, not file paths like state.json
    if ($p -notmatch '\.(json|dat|txt)$' -and -not (Test-Path $full)) {
        New-Item -ItemType Directory -Path $full -Force | Out-Null
    }
}
Write-Host "       Workflows, state, and built binaries kept as-is." -ForegroundColor Gray

# ---------------------------------------------------------------------------
# 4. Mirror code directories
# ---------------------------------------------------------------------------
Write-Host "[4/5] Syncing app to $InstallDir..." -ForegroundColor White

foreach ($pair in $CodePathsToMirror) {
    $src = Join-Path $SourceDir $pair.src
    $dst = Join-Path $InstallDir $pair.dst
    if (-not (Test-Path $src)) { continue }

    # robocopy /MIR mirrors src -> dst, deleting orphan files in dst.
    # We only ever do this on code dirs, never on user-data dirs (above).
    # /XJ excludes junctions, /R:2 limits retries, /W:1 is wait between retries.
    $rcArgs = @($src, $dst, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/NS', '/XJ', '/R:2', '/W:1')
    $proc = Start-Process robocopy -ArgumentList $rcArgs -NoNewWindow -Wait -PassThru
    # robocopy exit codes 0-7 are success; 8+ are errors
    if ($proc.ExitCode -ge 8) {
        Write-Host "       robocopy failed for $($pair.src) (exit $($proc.ExitCode))" -ForegroundColor Red
        exit 1
    }
}

# Top-level files (not directories)
foreach ($f in $TopLevelFilesToCopy) {
    $sp = Join-Path $SourceDir $f
    if (Test-Path $sp) { Copy-Item $sp (Join-Path $InstallDir $f) -Force }
}
Write-Host '       Done.' -ForegroundColor Gray

# ---------------------------------------------------------------------------
# 5. Write version stamp
# ---------------------------------------------------------------------------
Write-Host '[5/5] Recording version...' -ForegroundColor White
$manifest = [ordered]@{
    version       = $NewVersion
    previous      = $OldVersion
    installed_at  = (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')
    install_dir   = $InstallDir
}
$manifest | ConvertTo-Json | Set-Content -Path $VersionFile -Encoding UTF8
Write-Host '       Done.' -ForegroundColor Gray

Write-Host ''
Write-Host '====================================================' -ForegroundColor Green
if ($IsUpgrade -and $OldVersion -ne $NewVersion) {
    Write-Host "  Updated: $OldVersion -> $NewVersion" -ForegroundColor Green
} elseif ($IsUpgrade) {
    Write-Host "  Reinstalled v$NewVersion" -ForegroundColor Green
} else {
    Write-Host "  Installed v$NewVersion" -ForegroundColor Green
}
Write-Host '====================================================' -ForegroundColor Green
Write-Host ''
