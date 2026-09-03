@echo off
REM Launches the ArchHub agent daemon — five Ollama-backed departments
REM (Docs / QA / R&D / Engineering / Ops) running locally, free, no
REM Claude tokens. Outputs land in agents\outputs\<dept>\<task-id>\.
REM
REM Double-click this file to start the company. Close the window to
REM stop. To run hidden / on Windows startup, see agents\README.md.

setlocal
cd /d "%~dp0"

REM Quick check Ollama is running
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri http://localhost:11434/api/tags -UseBasicParsing -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo.
    echo Ollama is not running on localhost:11434.
    echo Open Ollama from your Start menu, wait until it says "running",
    echo then re-run this script.
    pause
    exit /b 1
)

echo ArchHub Departments — daemon starting.
echo Cycle = 300 seconds (every 5 minutes)
echo Outputs → agents\outputs\
echo Logs    → agents\logs\
echo Status  → python -m agents.run --status
echo.
echo Close this window to stop the daemon.
echo.

python -m agents.run --cycle 300
endlocal
