@echo off
setlocal

:: Build script — produces dist\ArchHub-Setup-<version>.exe
::
:: Just double-click this file. It finds Inno Setup wherever it's installed
:: and compiles installer\setup.iss for you.
::
:: Prerequisite: install Inno Setup 6 from https://jrsoftware.org/isdl.php
:: (free, ~15 MB, click through the defaults).

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "ISCC="

:: 1. Try iscc on PATH
where iscc >nul 2>nul
if not errorlevel 1 (
    set "ISCC=iscc"
    goto :compile
)

:: 2. Try standard 64-bit and 32-bit install locations
if exist "%ProgramFiles(x86)%\Inno Setup 6\iscc.exe" (
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\iscc.exe"
    goto :compile
)
if exist "%ProgramFiles%\Inno Setup 6\iscc.exe" (
    set "ISCC=%ProgramFiles%\Inno Setup 6\iscc.exe"
    goto :compile
)

echo.
echo ========================================================
echo   Inno Setup 6 not found.
echo ========================================================
echo.
echo Please install it first from:
echo     https://jrsoftware.org/isdl.php
echo.
echo It's free. Click through the defaults. Then run this
echo script again.
echo.
pause
exit /b 1

:compile
echo.
echo ========================================================
echo   Compiling ArchHub installer with Inno Setup
echo ========================================================
echo.
echo Using compiler: %ISCC%
echo Source script:  %SCRIPT_DIR%\installer\setup.iss
echo.

if not exist "%SCRIPT_DIR%\dist" mkdir "%SCRIPT_DIR%\dist"

"%ISCC%" "%SCRIPT_DIR%\installer\setup.iss"

if errorlevel 1 (
    echo.
    echo Compilation failed. See messages above.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo   Done.
echo ========================================================
echo.
echo Your installer is in:
echo     %SCRIPT_DIR%\dist\
echo.
echo Look for ArchHub-Setup-*.exe and double-click it to
echo install ArchHub on this machine, or share the .exe
echo with anyone — that's the single file they double-click
echo to install.
echo.

:: Open the dist folder so the user can see the result
start "" "%SCRIPT_DIR%\dist"

pause
endlocal
