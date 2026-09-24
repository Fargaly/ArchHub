@echo off
rem First-use setup. ArchHub.vbs runs this when the folder has not been
rem prepared and passes the absolute interpreter it found as %1; every
rem shortcut opens ArchHub.vbs, so this window is the only place a colleague
rem ever sees setup, and it stays open on failure.
setlocal
set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONNOUSERSITE=1"
cd /d "%~dp0"
set "ARCHHUB_PY=%~1"
if "%ARCHHUB_PY%"=="" (
  echo.
  echo ArchHub needs Python 3.11 or newer and found none on this machine.
  echo Install it from python.org, then run ArchHub again.
  pause
  exit /b 9009
)
"%ARCHHUB_PY%" -E -s colleague_setup.py --check-ready
if "%errorlevel%"=="0" goto launch
echo Preparing this ArchHub build. ArchHub opens by itself when it finishes.
rem The interpreter is the absolute path the launcher found; a bare "py" or
rem "python" would be resolved from this user-writable folder first.
"%ARCHHUB_PY%" -E -s colleague_setup.py
set "ARCHHUB_SETUP_RC=%errorlevel%"
if not "%ARCHHUB_SETUP_RC%"=="0" (
  echo.
  echo ArchHub setup did not finish. Nothing was faked and nothing was marked ready.
  echo Send this window text to your ArchHub administrator, then run ArchHub again once it is fixed.
  pause
  exit /b %ARCHHUB_SETUP_RC%
)
rem Setup writes the build-bound marker only after dependency checks succeed.
rem Read the return code OUTSIDE a block so cmd does not reuse a stale value.
:launch
exit /b 0
