@echo off
echo Removing stale RevitMCP.addin files from Revit Addins folder...
set ADDINS=%APPDATA%\Autodesk\Revit\Addins
for /D %%Y in ("%ADDINS%\*") do (
    if exist "%%Y\RevitMCP.addin" (
        echo   Deleting %%Y\RevitMCP.addin
        del /f /q "%%Y\RevitMCP.addin"
    )
)
echo Done. Revit will no longer show the "Assembly Not Found" error.
pause
