@echo off
cd /d "%~dp0"
py -3 colleague_setup.py || python colleague_setup.py
pause
