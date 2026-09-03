@echo off
rem First-use setup. ArchHub.vbs runs this when the folder has not been
rem prepared, and every shortcut opens ArchHub.vbs -- so this window is the
rem only place a colleague ever sees setup, and it stays open on failure.
setlocal
cd /d "%~dp0"
if exist ".archhub-ready" goto launch
echo Preparing ArchHub for first use...
set "ARCHHUB_SETUP_RC=9009"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 colleague_setup.py
  set "ARCHHUB_SETUP_RC=%errorlevel%"
)
if "%ARCHHUB_SETUP_RC%"=="9009" (
  python colleague_setup.py
  set "ARCHHUB_SETUP_RC=%errorlevel%"
)
if not "%ARCHHUB_SETUP_RC%"=="0" (
  echo.
  echo ArchHub setup did not finish. Nothing was faked and nothing was marked ready.
  echo Send this window text to Ahmed, then run ArchHub again once it is fixed.
  pause
  exit /b %ARCHHUB_SETUP_RC%
)
echo ready> ".archhub-ready"
:launch
rem ArchHub.vbs resolves the installed pythonw itself; a bare pythonw here
rem failed on every machine where Python was installed without Add-to-PATH.
wscript.exe "%~dp0ArchHub.vbs"
