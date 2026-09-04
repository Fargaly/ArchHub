@echo off
rem First-use setup. ArchHub.vbs runs this when the folder has not been
rem prepared and passes the absolute interpreter it found as %1; every
rem shortcut opens ArchHub.vbs, so this window is the only place a colleague
rem ever sees setup, and it stays open on failure.
setlocal
cd /d "%~dp0"
if exist ".archhub-ready" goto launch
echo Preparing ArchHub for first use...
set "ARCHHUB_PY=%~1"
if "%ARCHHUB_PY%"=="" (
  echo.
  echo ArchHub needs Python 3.11 or newer and found none on this machine.
  echo Install it from python.org, then run ArchHub again.
  pause
  exit /b 9009
)
rem The interpreter is the absolute path the launcher found; a bare "py" or
rem "python" would be resolved from this user-writable folder first.
"%ARCHHUB_PY%" colleague_setup.py
set "ARCHHUB_SETUP_RC=%errorlevel%"
if not "%ARCHHUB_SETUP_RC%"=="0" (
  echo.
  echo ArchHub setup did not finish. Nothing was faked and nothing was marked ready.
  echo Send this window text to Ahmed, then run ArchHub again once it is fixed.
  pause
  exit /b %ARCHHUB_SETUP_RC%
)
rem Written only here, after a zero exit read OUTSIDE any parenthesised block
rem (inside one, %errorlevel% expands at parse time and always read 0).
echo ready> ".archhub-ready"
:launch
wscript.exe "%~dp0ArchHub.vbs"
