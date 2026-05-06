@echo off
REM ArchHub one-click updater. Double-click this file to pull the latest
REM from GitHub, close any running ArchHub, and relaunch with the new code.
REM After the next launch you can use the in-app "Update" button in the
REM header instead of this script.
setlocal
cd /d "%~dp0"

echo ============================================
echo ArchHub Updater
echo ============================================
echo Repo: %~dp0
echo.

echo [1/4] Killing any running ArchHub instance...
REM pythonw.exe is what Launch.bat / restart() use; python.exe handles dev runs.
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq ArchHub*" 2>nul
taskkill /F /IM python.exe  /FI "WINDOWTITLE eq ArchHub*" 2>nul
REM Fallback: anything running app\main.py from this folder.
wmic process where "CommandLine like '%%app\\main.py%%' and ExecutablePath like '%%python%%'" delete 2>nul >nul

echo.
echo [2/4] Showing current version BEFORE update...
git log -1 --oneline
echo.

echo [3/4] Pulling latest from origin...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo *** UPDATE FAILED ***
    echo Common causes:
    echo   - You have local edits in app\ — commit or discard them first.
    echo   - git is not on PATH — install Git for Windows.
    echo   - Network issue or you are not signed in to GitHub via gh auth.
    echo.
    echo Showing repo status to help diagnose:
    git status --short
    echo.
    pause
    exit /b 1
)

echo.
echo [4/4] Showing version AFTER update...
git log -1 --oneline
echo.
echo Launching ArchHub...
start "" pythonw "app\main.py"
echo.
echo Done. You can close this window.
timeout /t 3 >nul
exit /b 0
