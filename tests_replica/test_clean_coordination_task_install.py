"""The clean graph owner runs the code of the tree it is registered for.

2026-10-01: the "ArchHub Clean Coordination" task still ran base pythonw in the
SOURCE checkout after every install, so an installed fix never reached the owner.
Setup now ships the task script into the installed tree and re-registers an
existing task from there (installer/ArchHub.iss RefreshCleanCoordinationTask).

The real script runs with -AuditOnly against synthetic trees in a temp folder:
it reports the action it would register and registers nothing.
"""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "windows" / "install_clean_coordination_task.ps1"
ISS = ROOT / "installer" / "ArchHub.iss"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows task scheduler")


def _tree(tmp_path, *, installed=True, venv=True):
    app = tmp_path / ("app" if installed else "checkout")
    (app / "nodelang").mkdir(parents=True)
    (app / "nodelang" / "__init__.py").write_text("", encoding="utf-8")
    (app / "nodelang" / "clean_coordination_service.py").write_text("", encoding="utf-8")
    if installed:
        (app / "BUILD_ID").write_text("court-build", encoding="ascii")
    if venv:
        (app / ".venv" / "Scripts").mkdir(parents=True)
        (app / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
    (app / "packaging" / "windows").mkdir(parents=True)
    shutil.copy2(SCRIPT, app / "packaging" / "windows" / SCRIPT.name)
    return app


def _audit(app, *extra):
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(app / "packaging" / "windows" / SCRIPT.name), "-AuditOnly",
         "-TaskName", "ArchHub Court " + uuid.uuid4().hex, *extra],
        capture_output=True, text=True, timeout=120)
    return done


def test_an_installed_tree_registers_its_own_private_environment(tmp_path):
    app = _tree(tmp_path)
    done = _audit(app)
    assert done.returncode == 0, done.stderr
    action = json.loads(done.stdout)
    assert Path(action["Execute"]) == app / ".venv" / "Scripts" / "pythonw.exe"
    assert Path(action["WorkingDirectory"]) == app
    assert action["Arguments"] == "-E -s -m nodelang.clean_coordination_service --host 127.0.0.1 --port 8474"
    assert action["Registered"] is False


def test_setup_may_register_before_the_first_open_creates_the_environment(tmp_path):
    app = _tree(tmp_path, venv=False)
    refused = _audit(app)
    assert refused.returncode != 0 and "pythonw executable is unavailable" in refused.stderr
    done = _audit(app, "-AllowPendingRuntime")
    assert done.returncode == 0, done.stderr
    assert Path(json.loads(done.stdout)["Execute"]) == app / ".venv" / "Scripts" / "pythonw.exe"


def test_a_source_checkout_without_an_environment_keeps_the_user_python(tmp_path):
    checkout = _tree(tmp_path, installed=False, venv=False)
    done = _audit(checkout, "-AllowPendingRuntime")
    assert done.returncode == 0, done.stderr
    action = json.loads(done.stdout)
    assert action["Execute"].lower().endswith(r"python\pythoncore-3.14-64\pythonw.exe")
    assert action["Arguments"] == "-m nodelang.clean_coordination_service --host 127.0.0.1 --port 8474"
    assert Path(action["WorkingDirectory"]) == checkout


def test_a_source_checkout_with_a_developer_venv_still_keeps_the_user_python(tmp_path):
    """PM 2026-10-01: 13.NODE-LANGUAGE has a .venv that cannot run the owner (no
    cryptography); only an installed tree (BUILD_ID) selects its private environment."""
    checkout = _tree(tmp_path, installed=False, venv=True)
    done = _audit(checkout)
    assert done.returncode == 0, done.stderr
    action = json.loads(done.stdout)
    assert action["Execute"].lower().endswith(r"python\pythoncore-3.14-64\pythonw.exe")
    assert not action["Arguments"].startswith("-E")


def test_setup_ships_the_script_and_refreshes_only_an_existing_task():
    iss = ISS.read_text(encoding="utf-8")
    assert (r'Source: "..\packaging\windows\install_clean_coordination_task.ps1"; '
            r'DestDir: "{app}\packaging\windows"') in iss
    refresh = iss[iss.index("procedure RefreshCleanCoordinationTask();"):]
    refresh = refresh[:refresh.index("\nend;") + 5]
    # Query first: a machine without the task never gets one from setup.
    assert refresh.index("'/Query /TN \"'") < refresh.index("install_clean_coordination_task.ps1")
    assert "exit;" in refresh and "Register-ScheduledTask" not in iss
    assert "-AllowPendingRuntime" in refresh
    assert "'/End /TN \"'" in refresh and "'/Run /TN \"'" in refresh
    # Never re-register onto, or stop the owner for, a runtime that does not exist
    # yet (PM 2026-10-01): the guard precedes the script call and the restart.
    guard = refresh.index(r"FileExists(ExpandConstant('{app}\.venv\Scripts\pythonw.exe'))")
    assert refresh.count("FileExists(") == 1
    assert guard < refresh.index("install_clean_coordination_task.ps1")
    assert guard < refresh.index("'/End /TN \"'")
    assert r"{sys}\WindowsPowerShell\v1.0\powershell.exe" in refresh
    post = iss[iss.index("if CurStep = ssPostInstall then\n  begin"):]
    assert post.index("BUILD_ID") < post.index("RefreshCleanCoordinationTask();")


BUILD = ROOT / "installer" / "build_release.ps1"
TASK_SCRIPT = "packaging/windows/install_clean_coordination_task.ps1"


def test_the_release_snapshot_carries_the_task_script(tmp_path):
    """build_release.ps1 compiles only its selected inputs: the script setup ships must be one,
    and its own payload filter must admit it (evaluated from the build script itself)."""
    judge = tmp_path / "judge.ps1"
    judge.write_text(r'''
param([string]$Build, [string]$Path)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'build script does not parse' }
$assignment = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -ceq '$selectedInputs' }, $true)
. ([scriptblock]::Create($assignment.Extent.Text))
$definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -ceq 'Test-CandidateInput' }, $true)
. ([scriptblock]::Create($definition.Extent.Text))
@{ selected = ($selectedInputs -ccontains $Path); admitted = (Test-CandidateInput 'selected' $Path) } | ConvertTo-Json -Compress
''', encoding="utf-8")
    done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(judge), "-Build", str(BUILD), "-Path", TASK_SCRIPT],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {"selected": True, "admitted": True}
