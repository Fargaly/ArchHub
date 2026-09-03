@echo off
REM Double-click to launch ArchHub. No terminal stays open afterwards.
setlocal
cd /d "%~dp0"
start "" pythonw "app\main.py"
exit /b 0
