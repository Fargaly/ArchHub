# Install the status-report daemon as a Windows scheduled task so it
# survives reboots. Idempotent — re-running replaces the existing task.
#
# Runs as the current user on logon AND every 10 minutes thereafter
# (the inner Python loop also has its own 10-min cadence; outer
# schedule is a safety net that respawns it if the process dies).
#
# After this script:
#   - Task name:  ArchHub-StatusReportDaemon
#   - Action:     pythonw.exe -u -m agents.github_report_loop
#   - User:       current user
#   - Trigger:    AtLogOn + every 10 min indefinitely
#   - Window:     hidden (pythonw, not python)
#
# Uninstall:
#   schtasks /Delete /TN ArchHub-StatusReportDaemon /F

$ErrorActionPreference = "Stop"

$TaskName = "ArchHub-StatusReportDaemon"
$RepoRoot = (Split-Path -Parent $PSScriptRoot)
$LogDir   = Join-Path $RepoRoot "agents\state"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# Try to resolve pythonw on PATH; fall back to python.exe (visible window).
$Pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $Pythonw) {
    $Pythonw = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Pythonw) {
    Write-Error "Neither pythonw.exe nor python.exe found on PATH"
    exit 1
}

# Grab the GitHub token from gh CLI once + bake it into the task action.
# (Tasks run in a non-interactive session, so they can't call gh keyring.)
$GhToken = ""
$ghExe = Get-Command gh -ErrorAction SilentlyContinue
if ($ghExe) {
    $GhToken = (& $ghExe.Source auth token 2>$null).Trim()
}
if (-not $GhToken) {
    Write-Warning "gh CLI not authed; daemon will run but every post will fail. Run 'gh auth login' then re-run this script to bake in a fresh token."
}

# Wrapper batch file — sets GH_TOKEN + spawns the python module.
# Using a wrapper keeps the token out of the Task XML (which is
# world-readable). Wrapper sits inside the user-profile data dir which
# is per-user ACL'd.
$WrapperDir = Join-Path $env:LOCALAPPDATA "ArchHub"
New-Item -ItemType Directory -Path $WrapperDir -Force | Out-Null
$WrapperPath = Join-Path $WrapperDir "run_status_report_daemon.bat"

@"
@echo off
set GH_TOKEN=$GhToken
set ARCHHUB_REPORT_GH_ISSUE=20
set ARCHHUB_REPORT_INTERVAL_MIN=10
cd /d "$RepoRoot"
"$Pythonw" -u -m agents.github_report_loop --issue 20 --interval 10
"@ | Set-Content -Path $WrapperPath -Encoding ASCII

# Remove any prior version of the task so we don't multiplex it.
# Suppress both stdout + stderr; the query "fails" cleanly when the
# task doesn't exist, which is fine on first install.
$prev = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
& schtasks /Query /TN $TaskName *> $null
if ($LASTEXITCODE -eq 0) {
    & schtasks /Delete /TN $TaskName /F *> $null
}
$ErrorActionPreference = $prev

# Create the task. /SC ONLOGON + /RI 600 covers both fresh-login and
# survive-process-death. /F = force overwrite, /RL LIMITED = current
# user scope (no elevation), /IT = interactive so pythonw spawns
# inside the user's session and can write to user-profile dirs.
schtasks /Create `
    /TN $TaskName `
    /TR "`"$WrapperPath`"" `
    /SC ONLOGON `
    /RL LIMITED `
    /IT `
    /F | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks /Create failed with exit code $LASTEXITCODE"
    exit 1
}

# Also kick it off RIGHT NOW so the user doesn't have to log out / log in.
schtasks /Run /TN $TaskName | Out-Null

Write-Output ""
Write-Output "Installed scheduled task: $TaskName"
Write-Output "Wrapper script:           $WrapperPath"
Write-Output "Triggers on every user login + manually started just now."
Write-Output ""
Write-Output "Verify:"
Write-Output "  schtasks /Query /TN $TaskName /V /FO LIST"
Write-Output ""
Write-Output "Logs:"
Write-Output "  $LogDir\github_report_loop.log"
Write-Output ""
Write-Output "Uninstall:"
Write-Output "  schtasks /Delete /TN $TaskName /F"
