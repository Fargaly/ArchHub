@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

title ArchHub
echo.
echo  ArchHub
echo  -------
echo  Python: checking...

py --version 2>nul
if errorlevel 1 (
    echo.
    echo  ERROR: Python launcher "py" not found.
    echo  Install Python from https://python.org
    echo.
    pause
    exit /b 1
)

echo  Packages: checking...
py -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo  Installing packages...
    py -m pip install --user -r "%ROOT%\requirements.txt"
    if errorlevel 1 (
        echo.
        echo  ERROR: pip install failed.
        echo  Run manually: py -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

echo  Starting ArchHub...
echo.
cd /d "%ROOT%\app"
py main.py

if errorlevel 1 (
    echo.
    echo  *** ArchHub crashed - see error above ***
    pause
)
endlocal
