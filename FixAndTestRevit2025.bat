@echo off
setlocal
echo.
echo  ArchHub -- Fix + Build Revit 2025
echo  ===================================
echo.

:: AgDR-0029 — single source of truth.  The Connectors panel + this
:: bat + BuildRevit2023.bat all call app/auto_build.py through the
:: same code path so a missing csproj can't slip past one entry
:: point and break the other.

:: 1. Clear false Revit active state.
set STATE=%LOCALAPPDATA%\ArchHub\state.json
echo  [1] State file: %STATE%
if exist "%STATE%" (
    py -c "import json; d=json.load(open(r'%STATE%')); d['active_connectors']=[x for x in d.get('active_connectors',[]) if 'revit' not in x.lower()]; json.dump(d,open(r'%STATE%','w'),indent=2); print('  Cleared stale Revit state.')"
) else (
    echo  No state.json found.
)

:: 2. Check Python.  AgDR-0029 — bat delegates to auto_build.py so
::    `py` must be on PATH.  Honest failure if not.
echo.
echo  [2] Checking py launcher...
py -3 -c "import sys; print('  Python', sys.version.split()[0])" 2>nul
if errorlevel 1 (
    echo  ERROR: py launcher not found.
    echo  Install Python 3.10+ from https://www.python.org/downloads/
    pause ^& exit /b 1
)

:: 3. Check dotnet SDK.
echo.
echo  [3] dotnet version:
dotnet --version
if errorlevel 1 (
    echo  ERROR: dotnet SDK not found on PATH.
    echo  Install from: https://dot.net/8
    pause ^& exit /b 1
)

:: 4. Delegate to canonical builder.  Builds RevitMCP.dll +
::    RevitMCPCore.dll into payload\revit\2025\, then verifies the
::    deploy manifest.
echo.
echo  [4] Building RevitMCP shim + Core for Revit 2025...
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
pushd "%ROOT%\app" >nul
py auto_build.py revit 2025
set BUILD_RC=%ERRORLEVEL%
popd >nul

if not "%BUILD_RC%"=="0" (
    echo.
    echo  BUILD FAILED -- exit code %BUILD_RC%.  See above.
    pause ^& exit /b %BUILD_RC%
)

echo.
echo  =====================================
echo  BUILD SUCCEEDED
echo  =====================================
dir /b "%ROOT%\payload\revit\2025"
echo.
echo  Next steps:
echo  1. Close this window
echo  2. Close and restart ArchHub (Run.bat)
echo  3. In Connectors panel, toggle Revit 2025 ON
echo  4. Open Revit 2025 -- the add-in loads automatically.
echo     /reload supports hot-swap (AgDR-0027); no Revit restart for
echo     future updates.
echo.
pause
