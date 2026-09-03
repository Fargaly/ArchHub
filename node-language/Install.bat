@echo off
setlocal

:: ----------------------------------------------------------------------
:: Resolve our own folder, stripping the trailing backslash so it survives
:: PowerShell argument parsing. (Trailing \ before " is the classic Windows
:: quoting trap — \" gets read as an escape, eating the next argument.)
:: ----------------------------------------------------------------------
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if not exist "%ROOT%\VERSION" (
    mshta "javascript:alert('ArchHub installer cannot find its files. Please extract the entire archive before running.');close()"
    exit /b 1
)

set /p NEW_VERSION=<"%ROOT%\VERSION"

:: ----------------------------------------------------------------------
:: Hand off to the GUI installer with the PowerShell window hidden.
:: User sees a brief cmd flash, then the GUI window only.
:: ----------------------------------------------------------------------
start "" powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%ROOT%\installer\install_gui.ps1" -SourceDir "%ROOT%" -NewVersion "%NEW_VERSION%"

endlocal
exit /b 0
