"""Court: a host that has its broker loaded never aborts the ArchHub install,
and is never asked to close.

Release 8890e2b aborted (exit 5, rolled back) because Revit 2027 held
bridges/revit/2027/RevitMCP.dll. Passing /CLOSEAPPLICATIONS then made Restart
Manager quit that Revit. The new DLL is installed beside it, at
bridges/revit/<year>/<build-id>/, and the process holding the old file is left
running. Here Inno Setup itself copies a real payload into a temp folder only;
no host is started or stopped.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BUILD = "court-build"
NEW = b"MZ new reviewed broker bytes\n"


def _compiler():
    compiler = shutil.which("ISCC") or "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
    if os.name != "nt" or not os.path.isfile(compiler):
        pytest.skip("Inno Setup is not installed on this machine")
    return compiler


@pytest.fixture
def harness(tmp_path):
    payload = tmp_path / "payload"
    for rel, data in (("bridges/revit/2027/%s/RevitMCP.dll" % BUILD, NEW),
                      ("bridges/autocad/2026/%s/AcadMCP.dll" % BUILD, b"new autocad\n"),
                      ("bridges/max/max_mcp_startup.py", b"# new max\n"),
                      ("abort.txt", b"court\n")):
        (payload / rel).parent.mkdir(parents=True, exist_ok=True)
        (payload / rel).write_bytes(data)
    source = tmp_path / "tests_replica"
    source.mkdir(exist_ok=True)
    (source / "host_staging_harness.iss").write_text(
        "; Court fixture only. The payload already uses bridges\\<host>\\<year>\\<build>\\.\n"
        "[Setup]\n"
        "AppName=ArchHub host staging court\n"
        "AppVersion=1\n"
        "DefaultDirName={param:app}\n"
        "DisableDirPage=yes\n"
        "DisableProgramGroupPage=yes\n"
        "DisableReadyPage=yes\n"
        "Uninstallable=no\n"
        "PrivilegesRequired=lowest\n"
        "CloseApplications=no\n"
        "RestartApplications=no\n"
        "OutputBaseFilename=host-staging-harness\n"
        "\n"
        "[Files]\n"
        "Source: \"{#PayloadPath}\\bridges\\*\"; DestDir: \"{app}\\bridges\"; Flags: recursesubdirs createallsubdirs ignoreversion\n"
        "Source: \"{#PayloadPath}\\abort.txt\"; DestDir: \"{app}\"; Flags: ignoreversion\n"
        "\n"
        "[Code]\n"
        "procedure DeinitializeSetup();\n"
        "begin\n"
        "  SaveStringToFile(ExpandConstant('{param:done}'), 'ran', False);\n"
        "end;\n",
        encoding="utf-8")
    out = tmp_path / "harness-out"
    built = subprocess.run([_compiler(), "/Q", "/O" + str(out), "/DPayloadPath=" + str(payload),
                            str(source / "host_staging_harness.iss")],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    return out / "host-staging-harness.exe", payload


def _installed(tmp_path, name):
    """An existing install whose Revit broker is a real DLL, loaded by a live process."""
    app = tmp_path / name / "ArchHub"
    locked = app / "bridges" / "revit" / "2027" / "RevitMCP.dll"
    locked.parent.mkdir(parents=True)
    shutil.copy2(Path(sys.base_prefix) / "python3.dll", locked)
    old = locked.read_bytes()
    other = app / "bridges" / "autocad" / "2026" / "AcadMCP.dll"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"old autocad, not loaded\n")
    host = subprocess.Popen([sys.executable, "-c",
                             "import ctypes, sys; ctypes.WinDLL(sys.argv[1]); print('loaded', flush=True); sys.stdin.read()",
                             str(locked)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert host.stdout.readline().strip() == b"loaded"
    with pytest.raises(PermissionError):  # the lock that aborted 8890e2b is real here
        open(locked, "r+b").close()
    return app, locked, old, host


def _run(exe, app, tmp_path, *extra):
    done = tmp_path / ("done-%d.txt" % len(list(tmp_path.glob("done-*.txt"))))
    log = done.with_suffix(".log")
    ran = subprocess.run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                          "/NOCLOSEAPPLICATIONS", "/app=" + str(app), "/done=" + str(done),
                          "/LOG=" + str(log), *extra], timeout=300)
    assert done.read_text() == "ran", "the harness did not run to the end"
    return ran.returncode, log.read_text(encoding="utf-8", errors="replace")


def _stop(host):
    host.stdin.close()
    host.wait(timeout=60)


def _still_held(host, locked, old):
    assert host.poll() is None, "the process holding the bridge DLL was closed"
    assert locked.read_bytes() == old
    with pytest.raises(PermissionError):
        open(locked, "r+b").close()


@pytest.mark.skipif(os.name != "nt", reason="Windows file locking")
def test_a_loaded_broker_stays_loaded_and_the_new_dll_lands_beside_it(harness, tmp_path):
    exe, _payload = harness
    app, locked, old, host = _installed(tmp_path, "one")
    try:
        code, log = _run(exe, app, tmp_path)
        assert code == 0, log
        lowered = log.lower()
        assert "restart manager" not in lowered and "closing applications" not in lowered
        assert "host file in use set aside" not in lowered
        _still_held(host, locked, old)
        installed = app / "bridges" / "revit" / "2027" / BUILD / "RevitMCP.dll"
        assert installed.read_bytes() == NEW
        assert (app / "bridges" / "autocad" / "2026" / BUILD / "AcadMCP.dll").read_bytes() == b"new autocad\n"
        # The previous AutoCAD file was not loaded and was not the install target, so it stays.
        assert (app / "bridges/autocad/2026/AcadMCP.dll").read_bytes() == b"old autocad, not loaded\n"
    finally:
        _stop(host)


@pytest.mark.skipif(os.name != "nt", reason="Windows file locking")
def test_an_unfinished_install_leaves_the_loaded_broker_where_it_is(harness, tmp_path):
    exe, _ = harness
    app, locked, old, host = _installed(tmp_path, "two")
    try:
        (app / "abort.txt").mkdir()  # a later file cannot be written: setup aborts and rolls back
        code, log = _run(exe, app, tmp_path)
        assert code != 0, log
        assert "host file in use set aside" not in log.lower()
        _still_held(host, locked, old)
    finally:
        _stop(host)


def test_the_release_installer_never_closes_a_host_or_replaces_its_loaded_dll():
    iss = (ROOT / "03.TOOLS/installer" / "ArchHub.iss").read_text(encoding="utf-8")
    quiet = (ROOT / "01.APP/nodelang" / "quiet_update.py").read_text(encoding="utf-8")
    script = (ROOT / "03.TOOLS/installer" / "build_host_bridges.ps1").read_text(encoding="utf-8")
    assert "CloseApplications=no" in iss and "RestartApplications=no" in iss
    assert "RetireLockedHostFiles(" not in iss
    assert "host_addin_retarget.py" in iss
    assert '"/NOCLOSEAPPLICATIONS"' in quiet
    assert '"/CLOSEAPPLICATIONS"' not in quiet and '"/FORCECLOSEAPPLICATIONS"' not in quiet
    assert 'bridges/revit/$year/$BuildId' in script
    assert 'bridges/autocad/$year/$BuildId' in script
    assert "restartreplace" not in re.sub(r"(?m)^;.*$", "", iss)
