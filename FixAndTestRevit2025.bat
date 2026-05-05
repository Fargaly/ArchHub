@echo off
setlocal
echo.
echo  ArchHub -- Fix + Build Revit 2025
echo  ===================================
echo.

:: 1. Clear false Revit active state
set STATE=%LOCALAPPDATA%\ArchHub\state.json
echo  [1] State file: %STATE%
if exist "%STATE%" (
    py -c "import json; d=json.load(open(r'%STATE%')); d['active_connectors']=[x for x in d.get('active_connectors',[]) if 'revit' not in x.lower()]; json.dump(d,open(r'%STATE%','w'),indent=2); print('  Cleared stale Revit state.')"
) else (
    echo  No state.json found.
)

:: 2. Check dotnet
echo.
echo  [2] dotnet version:
dotnet --version
if errorlevel 1 (
    echo  ERROR: dotnet SDK not found on PATH.
    echo  Install from: https://dot.net/8
    pause & exit /b 1
)

:: 3. Find Revit 2025
echo.
echo  [3] Looking for Revit 2025...
set REVITDIR=C:\Program Files\Autodesk\Revit 2025
if not exist "%REVITDIR%\RevitAPI.dll" (
    echo  Not at default path. Searching...
    for /d %%D in ("C:\Program Files\Autodesk\Revit 2025*") do (
        if exist "%%D\RevitAPI.dll" set REVITDIR=%%D
    )
)
if not exist "%REVITDIR%\RevitAPI.dll" (
    echo  ERROR: Cannot find RevitAPI.dll. Revit 2025 may not be installed.
    pause & exit /b 1
)
echo  Found: %REVITDIR%

:: 4. Build
echo.
echo  [4] Building RevitMCP.dll for Revit 2025 (net8.0-windows)...
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set CSPROJ=%ROOT%\payload\sources\revit_mcp\RevitMCP.csproj
set OUTDIR=%ROOT%\payload\revit\2025

dotnet build "%CSPROJ%" -c Release -p:TargetFramework=net8.0-windows -p:RevitInstallDir="%REVITDIR%" -o "%OUTDIR%"

if errorlevel 1 (
    echo.
    echo  BUILD FAILED -- see above.
    pause & exit /b 1
)

echo.
echo  =====================================
echo  BUILD SUCCEEDED
echo  =====================================
dir /b "%OUTDIR%"
echo.
echo  Next steps:
echo  1. Close this window
echo  2. Close and restart ArchHub (Run.bat)
echo  3. In Connectors panel, toggle Revit 2025 ON
echo  4. Open Revit 2025 -- the add-in loads automatically
echo.
pause
