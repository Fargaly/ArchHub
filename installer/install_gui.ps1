#requires -Version 5.1
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
# Layout
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
# Form
# ---------------------------------------------------------------------------
$bgColor     = [System.Drawing.Color]::FromArgb(26, 26, 28)
$panelColor  = [System.Drawing.Color]::FromArgb(36, 36, 40)
$mutedColor  = [System.Drawing.Color]::FromArgb(160, 160, 165)
$textColor   = [System.Drawing.Color]::FromArgb(230, 230, 232)
$accentColor = [System.Drawing.Color]::FromArgb(204, 120, 92)
$borderColor = [System.Drawing.Color]::FromArgb(60, 60, 65)

$form = New-Object System.Windows.Forms.Form
$form.Text            = "ArchHub"
$form.Size            = New-Object System.Drawing.Size(560, 340)
$form.StartPosition   = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox     = $false
$form.BackColor       = $bgColor
$form.ForeColor       = $textColor
$form.Font            = New-Object System.Drawing.Font('Segoe UI', 9.5)

$title = New-Object System.Windows.Forms.Label
$title.Location  = New-Object System.Drawing.Point(32, 32)
$title.Size      = New-Object System.Drawing.Size(490, 32)
$title.Font      = New-Object System.Drawing.Font('Segoe UI Semibold', 17)
$title.ForeColor = $textColor
if ($IsUpgrade -and $OldVersion -ne $NewVersion) { $title.Text = "Updating ArchHub" }
elseif ($IsUpgrade) { $title.Text = "Repairing ArchHub" }
else { $title.Text = "Installing ArchHub" }
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Location  = New-Object System.Drawing.Point(32, 70)
$subtitle.Size      = New-Object System.Drawing.Size(490, 24)
$subtitle.Font      = New-Object System.Drawing.Font('Segoe UI', 10)
$subtitle.ForeColor = $mutedColor
if ($IsUpgrade -and $OldVersion -ne $NewVersion) { $subtitle.Text = "Updating from version $OldVersion to $NewVersion." }
elseif ($IsUpgrade) { $subtitle.Text = "Reinstalling version $NewVersion." }
else { $subtitle.Text = "Installing version $NewVersion. This usually takes under a minute." }
$form.Controls.Add($subtitle)

$status = New-Object System.Windows.Forms.Label
$status.Location  = New-Object System.Drawing.Point(32, 150)
$status.Size      = New-Object System.Drawing.Size(490, 22)
$status.Font      = New-Object System.Drawing.Font('Segoe UI', 9.5)
$status.ForeColor = $textColor
$status.Text      = "Starting..."
$form.Controls.Add($status)

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

$btn = New-Object System.Windows.Forms.Button
$btn.Location  = New-Object System.Drawing.Point(420, 252)
$btn.Size      = New-Object System.Drawing.Size(102, 32)
$btn.Text      = "Cancel"
$btn.BackColor = [System.Drawing.Color]::FromArgb(50, 50, 55)
$btn.ForeColor = $textColor
$btn.FlatStyle = 'Flat'
$btn.FlatAppearance.BorderSize = 0
$btn.Font      = New-Object System.Drawing.Font('Segoe UI', 9.5)
$btn.Cursor    = [System.Windows.Forms.Cursors]::Hand
$form.Controls.Add($btn)

$script:installComplete  = $false
$script:installSucceeded = $false

$btn.Add_Click({
    if ($script:installComplete -and $script:installSucceeded) {
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
    $progressFill.Size = New-Object System.Drawing.Size(([int]($progressBg.Width * $clamped / 100)), 4)
    [System.Windows.Forms.Application]::DoEvents()
}

function Stop-RunningArchHub {
    try {
        $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and ($_.CommandLine -like '*ArchHub\app\main.py*' -or $_.CommandLine -like '*ArchHub/app/main.py*') }
        foreach ($p in $running) { try { Stop-Process -Id $p.ProcessId -Force -EA SilentlyContinue } catch {} }
        if ($running) { Start-Sleep -Seconds 2 }
    } catch {}
}

function Find-Python {
    # 1. Candidates from PATH
    $candidates = @('python', 'python3', 'py')

    # 2. Common install locations (python.org, Conda, WinPython, etc.)
    $commonRoots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python",
        "${env:ProgramFiles(x86)}\Python",
        "$env:ProgramData\miniconda3",
        "$env:LOCALAPPDATA\miniconda3",
        "$env:ProgramFiles\Miniconda3",
        "$env:LOCALAPPDATA\anaconda3",
        "$env:ProgramFiles\Anaconda3"
    )
    foreach ($root in $commonRoots) {
        if (Test-Path $root) {
            $dirs = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending
            foreach ($d in $dirs) {
                $exe = Join-Path $d.FullName 'python.exe'
                if (Test-Path $exe) { $candidates += $exe }
            }
            $exe = Join-Path $root 'python.exe'
            if (Test-Path $exe) { $candidates += $exe }
        }
    }

    # 3. Registry scan (HKCU + HKLM)
    $regPaths = @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\Wow6432Node\Python\PythonCore'
    )
    foreach ($rp in $regPaths) {
        if (Test-Path $rp) {
            Get-ChildItem $rp -ErrorAction SilentlyContinue | ForEach-Object {
                $installPath = "$($_.PSPath)\InstallPath"
                if (Test-Path $installPath) {
                    try {
                        $ip = (Get-ItemProperty $installPath -ErrorAction SilentlyContinue).'(default)'
                        if (-not $ip) { $ip = (Get-ItemProperty $installPath -ErrorAction SilentlyContinue).ExecutablePath }
                        if ($ip) {
                            $exe = if ($ip -like '*.exe') { $ip } else { Join-Path $ip 'python.exe' }
                            if (Test-Path $exe) { $candidates += $exe }
                        }
                    } catch {}
                }
            }
        }
    }

    foreach ($c in $candidates) {
        try {
            $ver = & $c --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $ver -match 'Python 3\.(\d+)') {
                $minor = [int]$Matches[1]
                if ($minor -ge 10) { return $c }
            }
        } catch {}
    }
    return $null
}

function Run-Pip {
    param([string]$python, [string]$reqFile)
    $argsList = @('-m', 'pip', 'install', '--user', '--upgrade',
                  '--disable-pip-version-check', '--quiet', '-r', $reqFile)
    $proc = Start-Process -FilePath $python -ArgumentList $argsList `
                -NoNewWindow -PassThru `
                -RedirectStandardOutput "$env:TEMP\archhub-pip.log" `
                -RedirectStandardError  "$env:TEMP\archhub-piperr.log"
    while (-not $proc.HasExited) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 150
    }
    return $proc.ExitCode
}

# ---------------------------------------------------------------------------
# Install routine
# ---------------------------------------------------------------------------
$installRoutine = {
    try {
        Set-Status "Stopping any running ArchHub..." 5
        Stop-RunningArchHub

        Set-Status "Finding Python 3.10+..." 10
        $python = Find-Python
        if (-not $python) {
            throw "Python 3.10 or newer not found.`nPlease install it from https://python.org and run this installer again.`nDuring install, check 'Add Python to PATH'."
        }

        Set-Status "Checking dependencies..." 15
        $newReq = Join-Path $SourceDir 'requirements.txt'
        $oldReq = Join-Path $InstallDir 'requirements.txt'
        $needsPip = $true
        if ($IsUpgrade -and (Test-Path $oldReq) -and (Test-Path $newReq)) {
            if ((Get-FileHash $newReq).Hash -eq (Get-FileHash $oldReq).Hash) {
                $needsPip = $false
            }
        }

        if ($needsPip) {
            Set-Status "Installing Python packages (30-60 seconds)..." 22
            $exitCode = Run-Pip -python $python -reqFile $newReq
            if ($exitCode -ne 0) {
                # Check if packages already importable — if so, warn but continue
                $importCheck = & $python -c "import PyQt6, anthropic, openai, keyring" 2>&1
                if ($LASTEXITCODE -ne 0) {
                    $pipErr = ''
                    if (Test-Path "$env:TEMP\archhub-piperr.log") {
                        $pipErr = (Get-Content "$env:TEMP\archhub-piperr.log" -Raw).Trim()
                        if ($pipErr.Length -gt 200) { $pipErr = $pipErr.Substring(0, 200) + '...' }
                    }
                    throw "Package install failed (exit $exitCode).`n$pipErr`n`nTry running: $python -m pip install -r requirements.txt"
                }
                # Packages importable — pip may have just shown warnings. Continue.
            }
        }

        Set-Status "Preserving your data..." 50
        foreach ($d in $UserDataDirs) {
            $f = Join-Path $InstallDir $d
            if (-not (Test-Path $f)) { New-Item -ItemType Directory -Path $f -Force | Out-Null }
        }

        Set-Status "Copying application files..." 65
        foreach ($pair in $CodePathsToMirror) {
            $src = Join-Path $SourceDir $pair.src
            $dst = Join-Path $InstallDir $pair.dst
            if (-not (Test-Path $src)) { continue }
            $rc = Start-Process robocopy -ArgumentList @($src, $dst, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/NS', '/XJ', '/R:2', '/W:1') -NoNewWindow -Wait -PassThru
            if ($rc.ExitCode -ge 8) { throw "Copy failed for $($pair.src). The install dir may be in use." }
            [System.Windows.Forms.Application]::DoEvents()
        }
        foreach ($f in $TopLevelFilesToCopy) {
            $sp = Join-Path $SourceDir $f
            if (Test-Path $sp) { Copy-Item $sp (Join-Path $InstallDir $f) -Force }
        }

        Set-Status "Setting up launcher..." 82
        $launcherCmd = "@echo off`r`ncd /d `"$InstallDir`"`r`n`"$python`" `"$InstallDir\app\main.py`" %*"
        Set-Content -Path (Join-Path $InstallDir 'ArchHub.cmd') -Value $launcherCmd -Encoding ASCII

        $silentCmd = "@echo off`r`ncd /d `"$InstallDir`"`r`nstart /min `"`" `"$python`" `"$InstallDir\app\main.py`" --silent"
        Set-Content -Path (Join-Path $InstallDir 'ArchHub-silent.cmd') -Value $silentCmd -Encoding ASCII

        Set-Status "Adding shortcuts..." 90
        $ws = New-Object -ComObject WScript.Shell
        $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'

        $sm = $ws.CreateShortcut((Join-Path $startMenu 'ArchHub.lnk'))
        $sm.TargetPath       = Join-Path $InstallDir 'ArchHub.cmd'
        $sm.WorkingDirectory = $InstallDir
        $sm.Save()

        $startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
        $st = $ws.CreateShortcut((Join-Path $startup 'ArchHub.lnk'))
        $st.TargetPath       = Join-Path $InstallDir 'ArchHub-silent.cmd'
        $st.WorkingDirectory = $InstallDir
        $st.Save()

        Set-Status "Recording version..." 96
        $manifest = [ordered]@{
            version         = $NewVersion
            previous        = $OldVersion
            installed_at    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')
            install_dir     = $InstallDir
            python          = $python
            source_dir      = $SourceDir
            dev_source_sync = (Test-Path (Join-Path $SourceDir '.git'))
        }
        $manifest | ConvertTo-Json | Set-Content -Path $VersionFile -Encoding UTF8

        Set-Status "Done." 100
        Start-Sleep -Milliseconds 350

        if ($IsUpgrade -and $OldVersion -ne $NewVersion) { $title.Text = "ArchHub updated"; $subtitle.Text = "You're now on version $NewVersion." }
        elseif ($IsUpgrade) { $title.Text = "ArchHub repaired"; $subtitle.Text = "Version $NewVersion is ready." }
        else { $title.Text = "ArchHub installed"; $subtitle.Text = "Version $NewVersion is ready. Click Launch to open it." }
        $status.Text = ""

        $btn.Text      = "Launch"
        $btn.BackColor = $accentColor
        $script:installSucceeded = $true

    } catch {
        $title.Text    = "Installation failed"
        $subtitle.Text = $_.Exception.Message
        $status.Text   = ""
        $progressFill.Size = New-Object System.Drawing.Size(0, 4)
        $btn.Text      = "Close"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(50, 50, 55)
        $script:installSucceeded = $false
    }

    $script:installComplete = $true
}

$form.Add_Shown({ & $installRoutine })
[System.Windows.Forms.Application]::EnableVisualStyles()
[void]$form.ShowDialog()
