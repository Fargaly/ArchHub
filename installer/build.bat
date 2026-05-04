@echo off
REM ArchHub end-to-end installer build.
REM
REM Prerequisites on the build machine (one-time):
REM   - Python 3.11+ on PATH
REM   - pip install pyinstaller PyQt6 anthropic openai keyring
REM   - Inno Setup 6 installed
REM
REM Output: dist\ArchHub-Setup.exe — single double-clickable installer.

setlocal enabledelayedexpansion
set "ROOT=%~dp0.."
cd /d "%ROOT%"

echo.
echo =====================================
echo   ArchHub installer build (v0.2.0)
echo =====================================
echo.

REM --- 1. Python embeddable + bundled deps ---------------------------------
if not exist "python\python.exe" (
    echo [1/4] Downloading Python 3.11 embeddable...
    if not exist "python" mkdir python
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile python\embed.zip"
    powershell -NoProfile -Command "Expand-Archive -LiteralPath python\embed.zip -DestinationPath python -Force"
    del python\embed.zip
    powershell -NoProfile -Command "(Get-Content python\python311._pth) -replace '^#import site', 'import site' | Set-Content python\python311._pth"
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile python\get-pip.py"
    python\python.exe python\get-pip.py --no-warn-script-location -q
    del python\get-pip.py
    echo   Installing app dependencies into bundled Python...
    python\python.exe -m pip install --no-warn-script-location -q -r app\requirements.txt
) else (
    echo [1/4] Python embeddable already present, skipping.
)

REM --- 2. Build launcher exe with PyInstaller ------------------------------
echo [2/4] Building ArchHub.exe launcher with PyInstaller...
if not exist "dist-staging" mkdir dist-staging

pyinstaller --onefile --noconsole --name ArchHub ^
    --icon app\assets\archhub.ico ^
    --distpath dist-staging ^
    --workpath build ^
    --specpath build ^
    --add-data "app;app" ^
    --add-data "python;python" ^
    --hidden-import PyQt6 ^
    --hidden-import anthropic ^
    --hidden-import openai ^
    --hidden-import keyring ^
    app\main.py
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)

REM --- 3. Verify connector payloads ----------------------------------------
echo [3/4] Verifying connector payloads...
if not exist "payload\bridge\server.py"   echo   WARNING: payload\bridge\server.py missing.
if not exist "payload\revit"              echo   NOTE: payload\revit\<year>\RevitMCP.dll not built. Build via dev kit.
if not exist "payload\autocad"            echo   NOTE: payload\autocad\<year>\AcadMCP.dll not built.
if not exist "payload\max"                echo   NOTE: payload\max\max_mcp_startup.py missing.
if not exist "payload\blender"            echo   NOTE: payload\blender\archhub_mcp\ missing.

REM --- 4. Compile Inno Setup installer -------------------------------------
echo [4/4] Compiling Inno Setup installer...
where /q iscc
if errorlevel 1 (
    where /q Compil32
    if errorlevel 1 (
        echo Inno Setup not found on PATH. Install from https://jrsoftware.org/isinfo.php
        exit /b 1
    )
    Compil32 /cc installer\setup.iss
) else (
    iscc installer\setup.iss
)
if errorlevel 1 (
    echo Inno Setup compilation failed.
    exit /b 1
)

echo.
echo =====================================
echo   BUILD COMPLETE
echo =====================================
echo Output: dist\ArchHub-Setup.exe
echo Size: ~120-150 MB ^(bundles Python + PyQt6 + LLM SDKs^)
echo.
echo Distribute that single file. End users double-click and the install completes
echo without prompts. After install, they open ArchHub from the Start Menu, add
echo their API key in Settings, toggle a connector, and start prompting.
echo.
endlocal
