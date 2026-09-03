@echo off
REM Stops the ArchHub departments daemon launched by Run-Departments.bat
REM or Run-Departments-Hidden.vbs. Looks for a python process whose
REM command line contains "agents.run" and kills only that one.
REM
REM Safe: leaves every other python.exe alone (so your IDE keeps
REM running).

setlocal
echo Looking for ArchHub daemon...

set FOUND=0
for /f "tokens=2 delims=," %%P in (
  'wmic process where "name='python.exe' and commandline like '%%agents.run%%'" get ProcessId /format:csv ^| findstr /R "[0-9]"'
) do (
    echo Killing PID %%P
    taskkill /F /PID %%P >nul 2>&1
    set FOUND=1
)

if "%FOUND%"=="0" (
    echo No ArchHub daemon found. Already stopped.
) else (
    echo Daemon stopped.
)

endlocal
pause
