@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\ArchHub"

:: ----------------------------------------------------------------------
:: Read version from the VERSION file
:: ----------------------------------------------------------------------
if not exist "%SCRIPT_DIR%VERSION" (
    echo Error: VERSION file missing. This Install.bat must run from
    echo the ArchHub repo root, next to the VERSION, app, and payload folders.
    pause
    exit /b 1
)
set /p NEW_VERSION=<"%SCRIPT_DIR%VERSION"

:: ----------------------------------------------------------------------
:: Run the upgrade-aware installer (PowerShell)
:: ----------------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%installer\upgrade.ps1" -SourceDir "%SCRIPT_DIR%" -InstallDir "%INSTALL_DIR%" -NewVersion "%NEW_VERSION%"
if errorlevel 1 (
    echo.
    echo Setup failed. See messages above.
    pause
    exit /b 1
)

:: ----------------------------------------------------------------------
:: Resolve the Python launcher (prefer 'python' on PATH, fall back to 'py')
:: ----------------------------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    set "PY=py"
) else (
    set "PY=python"
)

:: ----------------------------------------------------------------------
:: Write the launcher .cmd files
:: ----------------------------------------------------------------------
> "%INSTALL_DIR%\ArchHub.cmd"        echo @echo off
>>"%INSTALL_DIR%\ArchHub.cmd"        echo cd /d "%INSTALL_DIR%"
>>"%INSTALL_DIR%\ArchHub.cmd"        echo "%PY%" "%INSTALL_DIR%\app\main.py" %%*

> "%INSTALL_DIR%\ArchHub-silent.cmd" echo @echo off
>>"%INSTALL_DIR%\ArchHub-silent.cmd" echo cd /d "%INSTALL_DIR%"
>>"%INSTALL_DIR%\ArchHub-silent.cmd" echo start /min "" "%PY%" "%INSTALL_DIR%\app\main.py" --silent

:: ----------------------------------------------------------------------
:: Recreate Start Menu and Startup shortcuts
:: ----------------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%installer\make_shortcuts.ps1" "%INSTALL_DIR%" "%INSTALL_DIR%\ArchHub.cmd"

echo.
echo Launching ArchHub...
echo The window should appear in a few seconds.
echo First time? Open Settings (gear icon, top-right) to add an LLM API key.
echo.
start "" "%INSTALL_DIR%\ArchHub.cmd"

endlocal
