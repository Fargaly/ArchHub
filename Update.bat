@echo off
REM ArchHub one-click updater. Double-click this file to pull the latest
REM from GitHub and relaunch the app. After the next launch you can use
REM the in-app "Update" button in the header instead of this script.
setlocal
cd /d "%~dp0"

echo Updating ArchHub...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo Update failed. Press any key to close.
    pause >nul
    exit /b 1
)

echo.
echo Launching ArchHub...
start "" pythonw "app\main.py"
exit /b 0
