#requires -Version 5.1
<#
    Creates the ArchHub Start Menu shortcut and the Windows Startup shortcut.
    Called by Install.bat with two arguments:
        $args[0] = install dir (e.g. C:\Users\fargaly\AppData\Local\ArchHub)
        $args[1] = python launcher path (full path to ArchHub.cmd)
#>
param(
    [Parameter(Mandatory=$true)] [string] $InstallDir,
    [Parameter(Mandatory=$true)] [string] $LauncherPath
)

$ErrorActionPreference = 'Continue'

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$startup   = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'

$silentLauncher = Join-Path $InstallDir 'ArchHub-silent.cmd'

try {
    $ws = New-Object -ComObject WScript.Shell

    # Start Menu entry — full launcher
    $sm = $ws.CreateShortcut((Join-Path $startMenu 'ArchHub.lnk'))
    $sm.TargetPath       = $LauncherPath
    $sm.WorkingDirectory = $InstallDir
    $sm.Save()
    Write-Host "  Created Start Menu shortcut."

    # Startup entry — silent launcher (no console window flash on login)
    if (Test-Path $silentLauncher) {
        $st = $ws.CreateShortcut((Join-Path $startup 'ArchHub.lnk'))
        $st.TargetPath       = $silentLauncher
        $st.WorkingDirectory = $InstallDir
        $st.Save()
        Write-Host "  Created Startup shortcut."
    }
} catch {
    Write-Host "  Shortcut creation failed: $_" -ForegroundColor Yellow
    exit 1
}
