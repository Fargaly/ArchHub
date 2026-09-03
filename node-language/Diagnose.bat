@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "LOG=%ROOT%\diagnose_output.txt"

echo ArchHub Diagnostics > "%LOG%"
echo ================== >> "%LOG%"
echo Date: %date% %time% >> "%LOG%"
echo. >> "%LOG%"

echo [1] Python search... >> "%LOG%"

set "PY="

py --version >> "%LOG%" 2>&1
if not errorlevel 1 (
    for /f "tokens=2" %%V in ('py --version 2^>^&1') do (
        echo   py = %%V >> "%LOG%"
        set "PY=py"
    )
)

py -3 --version >> "%LOG%" 2>&1
if not errorlevel 1 (
    for /f "tokens=2" %%V in ('py -3 --version 2^>^&1') do (
        echo   py -3 = %%V >> "%LOG%"
        if not defined PY set "PY=py -3"
    )
)

python --version >> "%LOG%" 2>&1
if not errorlevel 1 (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do (
        echo   python = %%V >> "%LOG%"
        if not defined PY set "PY=python"
    )
)

if not defined PY (
    echo   FAIL: no python found >> "%LOG%"
    echo [FAIL] Python not found, see diagnose_output.txt
    notepad "%LOG%"
    exit /b 1
)

echo PY = %PY% >> "%LOG%"
echo. >> "%LOG%"

echo [2] pip check... >> "%LOG%"
%PY% -m pip --version >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [3] Package check... >> "%LOG%"
%PY% -c "import PyQt6; print('PyQt6 OK')" >> "%LOG%" 2>&1
%PY% -c "import anthropic; print('anthropic OK')" >> "%LOG%" 2>&1
%PY% -c "import openai; print('openai OK')" >> "%LOG%" 2>&1
%PY% -c "import keyring; print('keyring OK')" >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [4] App import check... >> "%LOG%"
cd /d "%ROOT%\app"
%PY% -c "import sys; sys.path.insert(0,'.'); import session; print('session OK')" >> "%LOG%" 2>&1
%PY% -c "import sys; sys.path.insert(0,'.'); import secrets_store; print('secrets_store OK')" >> "%LOG%" 2>&1
%PY% -c "import sys; sys.path.insert(0,'.'); import llm_router; print('llm_router OK')" >> "%LOG%" 2>&1
%PY% -c "import sys; sys.path.insert(0,'.'); import chat_window; print('chat_window OK')" >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [5] Full startup test... >> "%LOG%"
%PY% -c "
import sys, traceback
sys.path.insert(0, '.')
try:
    import session; print('session OK')
    import secrets_store; print('secrets_store OK')
    import llm_router; print('llm_router OK')
    import manager; print('manager OK')
    import tool_engine; print('tool_engine OK')
    print('All non-Qt imports OK')
except Exception as e:
    traceback.print_exc()
" >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo Done. >> "%LOG%"

echo Diagnostics complete. Opening results...
notepad "%LOG%"
