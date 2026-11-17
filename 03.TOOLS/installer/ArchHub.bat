@echo off
rem First-use setup. ArchHub.vbs runs this when the folder has not been
rem prepared and passes the absolute interpreter it found as %1.
rem A shortcut or hidden caller never waits for console input.
setlocal
set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONNOUSERSITE=1"
cd /d "%~dp0"
set "ARCHHUB_PY=%~1"
if "%ARCHHUB_PY%"=="" (
  echo.
  echo ArchHub needs Python 3.14 and found none on this machine.
  echo Install it from python.org, then run ArchHub again.
  if "%~2"=="--interactive" pause
  exit /b 9009
)
"%ARCHHUB_PY%" -E -s colleague_setup.py --check-ready
if "%errorlevel%"=="0" goto launch
echo Preparing this ArchHub build. ArchHub opens by itself when it finishes.
rem The interpreter is the absolute path the launcher found; a bare "py" or
rem "python" would be resolved from this user-writable folder first.
if "%~2"=="--interactive" (
  "%ARCHHUB_PY%" -E -s colleague_setup.py --interactive
) else (
  "%ARCHHUB_PY%" -E -s colleague_setup.py --launcher-setup <nul
)
set "ARCHHUB_SETUP_RC=%errorlevel%"
if not "%ARCHHUB_SETUP_RC%"=="0" (
  echo.
  echo ArchHub setup did not finish. Nothing was faked and nothing was marked ready.
  echo Send this window text to your ArchHub administrator, then run ArchHub again once it is fixed.
  if "%~2"=="--interactive" pause
  exit /b %ARCHHUB_SETUP_RC%
)
rem Setup writes the build-bound marker only after dependency checks succeed.
rem Read the return code OUTSIDE a block so cmd does not reuse a stale value.
:launch
exit /b 0
