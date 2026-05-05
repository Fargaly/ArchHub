@echo off
echo ================================================
echo  Building RevitMCP for Revit 2023
echo ================================================
echo.
cd /d "%~dp0app"
py -c "
import sys, os
sys.path.insert(0, '.')

def progress(stage, pct, line):
    msg = f'[{pct:3d}%%] {stage}'
    if line: msg += f': {line}'
    print(msg, flush=True)

from auto_build import build_revit_connector
print('Starting build for Revit 2023...')
print('(Uses NuGet reference assemblies - no admin needed)')
print()
result = build_revit_connector(2023, on_progress=progress)
print()
if result.success:
    print('SUCCESS! Built', len(result.artifacts), 'files.')
    print()
    print('Next steps:')
    print('  1. Open ArchHub and go to Connectors')
    print('  2. Toggle Revit 2023 ON')
    print('  3. Restart Revit 2023 (close and reopen)')
    print('  4. Chat with ArchHub - Revit 2023 will be live!')
else:
    print('FAILED:', result.detail)
    if 'reboot' in result.detail.lower():
        print()
        print('Restart Windows first, then run this script again.')
    elif 'not found' in result.detail.lower():
        print()
        print('Make sure Revit 2023 is installed.')
"
echo.
pause
