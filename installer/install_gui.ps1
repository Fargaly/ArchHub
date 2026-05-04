#requires -Version 5.1
<#
ArchHub GUI installer.

  - Detects existing version
  - Stops running instance
  - Preserves user data (workflows, state, built binaries)
  - Mirrors code dirs cleanly
  - Records version stamp
  - Shows ONE window: header, status, progress bar, single button
  - No cmd output, no prompts, no developer text

Launched by Install.bat in WindowStyle Hidden so PowerShell never shows a console.
#>
param(
    [Parameter(Mandatory=$true)] [string] $SourceDir,
    [Parameter(Mandatory=$true)] [string] $NewVersion
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ---------------------------------------------------------------------------
# Paths and version detection
# ---------------------------------------------------------------------------
$InstallDir  = Join-Path $env:LOCALAPPDATA 'ArchHub'
$VersionFile = Join-Path $InstallDir 'version.json'

$IsUpgrade  = $false
$OldVersion = $null
if (Test-Path $VersionFile) {
    $IsUpgrade = $true
    try { $OldVersion = (Get-Content $VersionFile -Raw | ConvertFrom-Json).version }
    catch { $OldVersion = 'unknown' }
} elseif (Test-Path (Join-Path $InstallDir 'app')) {
    $IsUpgrade  = $true
    $OldVersion = 'pre-0.5.0'
}

# ---------------------------------------------------------------------------
# Layout: code (mirrored) vs user data (preserved)
# ---------------------------------------------------------------------------
$UserDataDirs = @(
    'workflows', 'logs', 'payload\revit', 'payload\autocad',
    'payload\max\2024', 'payload\max\2025', 'payload\max\2026'
)
$CodePathsToMirror = @(
    @{ src = 'app';              dst = 'app' },
    @{ src = 'payload\sources';  dst = 'payload\sources' },
    @{ src = 'payload\bridge';   dst = 'payload\bridge' },
    @{ src = 'payload\blender';  dst = 'payload\blender' },
    @{ src = 'installer';        dst = 'installer' }
)
$TopLevelFilesToCopy = @('VERSION', 'requirements.txt', 'README.md', 'LICENSE')

# ---------------------------------------------------------------------------
# Build the form
# ---------------------------------------------------------------------------
$bgColor      = [System.Drawing.Color]::FromArgb(26, 26, 28)
$panelColor   = [System.Drawing.Color]::FromArgb(36, 36, 40)
$mutedColor   = [System.Drawing.Color]::FromArgb(160, 160, 165)
$textColor    = [System.Drawing.Color]::FromArgb(230, 230, 232)
$accentColor  = [System.Drawing.Color]::FromArgb(204, 120, 92)
$borderColor  = [System.Drawing.Color]::FromArgb(60, 60, 65)

$form = New-Object System.Windows.Forms.Form
$form.Text            = "ArchHub"
$form.Size            = New-Object System.Drawing.Size(560, 340)
$form.StartPosition   = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox     = $false
$form.BackColor       = $bgColor
$form.ForeColor       = $textColor
$form.Font            = New-Object System.Drawing.Font('Segoe UI', 9.5)

# Title
$title = New-Object System.Windows.Forms.Label
$title.Location  = New-Object System.Drawing.Point(32, 32)
$title.Size      = New-Object System.Drawing.Size(490, 32)
$title.Font      = New-Object System.Drawing.Font('Segoe UI Semibold', 17)
$title.ForeColor = $textColor
if ($IsUpgrade -and $OldVersion -ne $NewVersion) {
    $title.Text = "Updating ArchHub"
} elseif ($IsUpgrade) {
    $title.Text = "Repairing ArchHub"
} else {
    $title.Text = "Installing ArchHub"
}
$form.Controls.Add($title)

# Subtitle
$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Location  = New-Object System.Drawing.Point(32, 70)
$subtitle.Size      = New-Object System.Drawing.Size(490, 24)
$subtitle.Font      = New-Object System.Drawing.Font('Segoe UI', 10)
$subtitle.ForeColor = $mutedColor
if ($IsUpgrade -and $OldVersion -ne $NewVersion) {
    $subtitle.Text = "Updating from version $OldVersion to $NewVersion."
} elseif ($IsUpgrade) {
    $subtitle.Text = "Reinstalling version $NewVersion."
} else {
    $subtitle.Text = "Installing version $NewVersion. This usually takes under a minute."
}
$form.Controls.Add($subtitle)

# Status label
$status = New-Object System.Windows.Forms.Label
$status.Location  = New-Object System.Drawing.Point(32, 150)
$status.Size      = New-Object System.Drawing.Size(490, 22)
$status.Font      = New-Object System.Drawing.Font('Segoe UI', 9.5)
$status.ForeColor = $textColor
$status.Text      = "Starting..."
$form.Controls.Add($status)

# Progress bar — use a panel + filled child for a clean flat look
$progressBg = New-Object System.Windows.Forms.Panel
$progressBg.Location  = New-Object System.Drawing.Point(32, 184)
$progressBg.Size      = New-Object System.Drawing.Size(490, 4)
$progressBg.BackColor = $borderColor
$form.Controls.Add($progressBg)

$progressFill = New-Object System.Windows.Forms.Panel
$progressFill.Location  = New-Object System.Drawing.Point(0, 0)
$progressFill.Size      = New-Object System.Drawing.Size(0, 4)
$progressFill.BackColor = $accentColor
$progressBg.Controls.Add($progressFill)

# Footer button
$btn = New-Object System.Windows.Forms.Button
$btn.Location          = New-Object System.Drawing.Point(420, 252)
$btn.Size              = New-Object System.Drawing.Size(102, 32)
$btn.Text              = "Cancel"
$btn.BackColor         = [System.Drawing.Color]::FromArgb(50, 50, 55)
$btn.ForeColor         = $textColor
$btn.FlatStyle         = 'Flat'
$btn.FlatAppearance.BorderSize  = 0
$btn.Font              = New-Object System.Drawing.Font('Segoe UI', 9.5)
$btn.Cursor            = [System.Windows.Forms.Cursors]::Hand
$form.Controls.Add($btn)

$script:installComplete = $false
$script:installSucceeded = $false

$btn.Add_Click({
    if ($script:installComplete -and $script:installSucceeded) {
        # Launch ArchHub
        try {
            $launcher = Join-Path $InstallDir 'ArchHub.cmd'
            if (Test-Path $launcher) {
                Start-Process -FilePath $launcher -WindowStyle Hidden -WorkingDirectory $InstallDir
            }
        } catch {}
    }
    $form.Close()
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Set-Status {
    param([string]$text, [int]$pct)
    $status.Text = $text
    $clamped = [Math]::Max(0, [Math]::Min(100, $pct))
    $width = [int]($progressBg.Width * $clamped / 100)
    $progressFill.Size = New-Object System.Drawing.Size($width, 4)
    [System.Windows.Forms.Application]::DoEvents()
}

function Stop-RunningArchHub {
    try {
        $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and (
                    $_.CommandLine -like '*ArchHub\app\main.py*' -or
                    $_.CommandLine -like '*ArchHub/app/main.py*'
                )
            }
        foreach ($p in $running) {
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
        }
        if ($running) { Start-Sleep -Seconds 2 }
    } catch {}
}

# ---------------------------------------------------------------------------
# The install routine — runs on the UI thread, interleaved with DoEvents
# ---------------------------------------------------------------------------
$installRoutine = {
    try {
        Set-Status "Stopping any running ArchHub..." 5
        Stop-RunningArchHub

        Set-Status "Checking dependencies..." 12
        $newReq = Join-Path $SourceDir 'requirements.txt'
        $oldReq = Join-Path $InstallDir 'requirements.txt'
        $needsPip = $true
        if ($IsUpgrade -and (Test-Path $oldReq) -and (Test-Path $newReq)) {
            if ((Get-FileHash $newReq).Hash -eq (Get-FileHash $oldReq).Hash) {
                $needsPip = $false
            }
        }

        if ($needsPip) {
            Set-Status "Installing Python packages (about 30 seconds)..." 20
            # Run pip silently in a background process so the UI keeps repainting
            $pipArgs = @('-m', 'pip', 'install', '--user', '--upgrade',
                         '--disable-pip-version-check', '--quiet', '-r', $newReq)
            $pip = Start-Process -FilePath 'python' -ArgumentList $pipArgs `
                       -NoNewWindow -PassThru -RedirectStandardOutput "$env:TEMP\archhub-pip.log" `
                       -RedirectStandardError  "$env:TEMP\archhub-piperr.log"
            while (-not $pip.HasExited) {
                [System.Windows.Forms.Application]::DoEvents()
                Start-Sleep -Milliseconds 150
            }
            if ($pip.ExitCode -ne 0) {
                # Try py launcher as fallback for systems where 'python' isn't on PATH
                $pip = Start-Process -FilePath 'py' -ArgumentList $pipArgs `
                           -NoNewWindow -PassThru `
                           -RedirectStandardOutput "$env:TEMP\archhub-pip.log" `
                           -RedirectStandardError  "$env:TEMP\archhub-piperr.log"
                while (-not $pip.HasExited) {
                    [System.Windows.Forms.Application]::DoEvents()
                    Start-Sleep -Milliseconds 150
                }
                if ($pip.ExitCode -ne 0) {
                    throw "Couldn't install Python packages. Make sure Python 3.10 or newer is installed."
                }
            }
        }

        Set-Status "Preserving your workflows and settings..." 50
        foreach ($d in $UserDataDirs) {
            $f = Join-Path $InstallDir $d
            if (-not (Test-Path $f)) { New-Item -ItemType Directory -Path $f -Force | Out-Null }
        }

        Set-Status "Copying application files..." 65
        foreach ($pair in $CodePathsToMirror) {
            $src = Join-Path $SourceDir $pair.src
            $dst = Join-Path $InstallDir $pair.dst
            if (-not (Test-Path $src)) { continue }
            $rcArgs = @($src, $dst, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/NS', '/XJ', '/R:2', '/W:1')
            $rc = Start-Process robocopy -ArgumentList $rcArgs -NoNewWindow -Wait -PassThru
            if ($rc.ExitCode -ge 8) { throw "Couldn't copy $($pair.src). The install dir may be in use." }
            [System.Windows.Forms.Application]::DoEvents()
        }
        foreach ($f in $TopLevelFilesToCopy) {
            $sp = Join-Path $SourceDir $f
            if (Test-Path $sp) { Copy-Item $sp (Join-Path $InstallDir $f) -Force }
        }

        Set-Status "Setting up launcher..." 82
        $py = 'python'
        if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $py = 'py' }

        $launcherCmd = @(
            '@echo off',
            "cd /d `"$InstallDir`"",
            "$py `"$InstallDir\app\main.py`" %*"
        ) -join "`r`n"
        Set-Content -Path (Join-Path $InstallDir 'ArchHub.cmd') -Value $launcherCmd -Encoding ASCII

        $silentCmd = @(
            '@echo off',
            "cd /d `"$InstallDir`"",
            "start /min `"`" $py `"$InstallDir\app\main.py`" --silent"
        ) -join "`r`n"
        Set-Content -Path (Join-Path $InstallDir 'ArchHub-silent.cmd') -Value $silentCmd -Encoding ASCII

        Set-Status "Adding shortcuts..." 90
        $ws = New-Object -ComObject WScript.Shell
        $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
        $startup   = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'

        $sm = $ws.CreateShortcut((Join-Path $startMenu 'ArchHub.lnk'))
        $sm.TargetPath       = Join-Path $InstallDir 'ArchHub.cmd'
        $sm.WorkingDirectory = $InstallDir
        $sm.Save()

        $st = $ws.CreateShortcut((Join-Path $startup 'ArchHub.lnk'))
        $st.TargetPath       = Join-Path $InstallDir 'ArchHub-silent.cmd'
        $st.WorkingDirectory = $InstallDir
        $st.Save()

        Set-Status "Recording version..." 96
        $manifest = [ordered]@{
            version       = $NewVersion
            previous      = $OldVersion
            installed_at  = (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')
            install_dir   = $InstallDir
        }
        $manifest | ConvertTo-Json | Set-Content -Path $VersionFile -Encoding UTF8

        Set-Status "Done." 100
        Start-Sleep -Milliseconds 350

        # Success state
        if ($IsUpgrade -and $OldVersion -ne $NewVersion) {
            $title.Text = "ArchHub updated"
            $subtitle.Text = "You're now on version $NewVersion."
        } elseif ($IsUpgrade) {
            $title.Text = "ArchHub repaired"
            $subtitle.Text = "Version $NewVersion is ready."
        } else {
            $title.Text = "ArchHub installed"
            $subtitle.Text = "Version $NewVersion is ready. Click Launch to open it."
        }
        $status.Text = ""

        $btn.Text      = "Launch"
        $btn.BackColor = $accentColor
        $script:installSucceeded = $true

    } catch {
        $title.Text    = "Installation failed"
        $subtitle.Text = $_.Exception.Message
        $status.Text   = ""
        # Reset progress bar
        $progressFill.Size = New-Object System.Drawing.Size(0, 4)
        $btn.Text      = "Close"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(50, 50, 55)
        $script:installSucceeded = $false
    }

    $script:installComplete = $true
}

$form.Add_Shown({ & $installRoutine })

# Show modally
[System.Windows.Forms.Application]::EnableVisualStyles()
[void]$form.ShowDialog()
