@echo off
cd /d "%~dp0"
if not exist ".archhub-ready" (
  echo Preparing ArchHub for first use...
  py -3 colleague_setup.py || python colleague_setup.py
  echo ready> ".archhub-ready"
)
start "" pythonw launch_archhub_test.py
