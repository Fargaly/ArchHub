@echo off
REM ArchHub Quick Install (development path).
REM Use this until ArchHub-Setup.exe (built via installer\build.bat) is available.

setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\ArchHub"

echo.
echo ====================================================
echo   ArchHub - Install
echo ====================================================
echo.

REM 1. Python check
where /q python
if errorlevel 1 (
    where /q py
    if errorlevel 1 (
        echo Python is not installed or not on PATH.
        echo Install Python 3.10+ from https://python.org and tick "Add Python to PATH".
        pause
        exit /b 1
    )
    set "PY=py -3"
) else (
    set "PY=python"
)

echo [1/4] Installing Python dependencies (PyQt6, anthropic, openai, keyring)...
%PY% -m pip install --user --quiet --upgrade pip
%PY% -m pip install --user --quiet -r "%SCRIPT_DIR%app\requirements.txt"
if errorlevel 1 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
)

echo [2/4] Staging ArchHub to %INSTALL_DIR%...
if exist "%INSTALL_DIR%\app" rmdir /s /q "%INSTALL_DIR%\app"
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
xcopy /e /q /y "%SCRIPT_DIR%app"     "%INSTALL_DIR%\app\"      >nul
xcopy /e /q /y "%SCRIPT_DIR%payload" "%INSTALL_DIR%\payload\"  >nul

echo [3/4] Resolving Python and creating launcher...
for /f "delims=" %%I in ('where python 2^>nul') do (
    set "PY_EXE=%%I"
    goto :py_found
)
for /f "delims=" %%I in ('where py 2^>nul') do set "PY_EXE=%%I"
:py_found

> "%INSTALL_DIR%\ArchHub.cmd" (
    echo @echo off
    echo "%PY_EXE%" "%INSTALL_DIR%\app\main.py" %%*
)
> "%INSTALL_DIR%\ArchHub-silent.cmd" (
    echo @echo off
    echo start "" /min "%PY_EXE%" "%INSTALL_DIR%\app\main.py" --silent
)

echo [4/4] Adding shortcuts...
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $s = $ws.CreateShortcut('%STARTMENU%\ArchHub.lnk'); ^
     $s.TargetPath = '%INSTALL_DIR%\ArchHub.cmd'; ^
     $s.WorkingDirectory = '%INSTALL_DIR%'; ^
     $s.Save()"

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $s = $ws.CreateShortcut('%STARTUP%\ArchHub.lnk'); ^
     $s.TargetPath = '%INSTALL_DIR%\ArchHub-silent.cmd'; ^
     $s.WorkingDirectory = '%INSTALL_DIR%'; ^
     $s.Save()"

echo.
echo ====================================================
echo   Install complete!
echo ====================================================
echo.
echo Launching ArchHub...
start "" "%INSTALL_DIR%\ArchHub.cmd"
echo.
echo The ArchHub window should appear in a few seconds.
echo First time? Open Settings (gear icon top-right) and add at least one
echo LLM API key to start chatting.
echo.
pause
endlocal
