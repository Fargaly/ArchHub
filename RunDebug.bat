@echo off
cd /d "%~dp0app"
echo Running ArchHub with error capture...
py main.py 2>"%~dp0startup_error.log" 1>&2
echo.
echo Exit code: %errorlevel%
echo.
if exist "%~dp0startup_error.log" (
    echo --- startup_error.log ---
    type "%~dp0startup_error.log"
)
pause
