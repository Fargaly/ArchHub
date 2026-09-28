"""Court: a host that has its broker loaded never aborts the ArchHub install.

Release 8890e2b aborted (exit 5, rolled back) because Revit 2027 held
bridges/revit/2027/RevitMCP.dll and a loaded DLL cannot be overwritten. The
installer runs as the user, so restartreplace cannot help; the shipped rule
(installer/host_file_staging.iss) moves a locked file aside instead. Here Inno
Setup itself copies a real payload over a DLL that a live process has loaded,
in a temp folder only; no host is started or stopped.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodelang.host_artifact_review import bridges_tree_sha256  # noqa: E402

NEW = b"MZ new reviewed broker bytes\n"


def _compiler():
    compiler = shutil.which("ISCC") or "C:/Program Files (x86)/Inno Setup 6/ISCC.exe"
    if os.name != "nt" or not os.path.isfile(compiler):
        pytest.skip("Inno Setup is not installed on this machine")
    return compiler


@pytest.fixture
def harness(tmp_path):
    payload = tmp_path / "payload"
    for rel, data in (("bridges/revit/2027/RevitMCP.dll", NEW),
                      ("bridges/autocad/2026/ArchHub.AcadMCP.dll", b"new autocad\n"),
                      ("bridges/max/max_mcp_startup.py", b"# new max\n"),
                      ("abort.txt", b"court\n")):
        (payload / rel).parent.mkdir(parents=True, exist_ok=True)
        (payload / rel).write_bytes(data)
    out = tmp_path / "harness-out"
    built = subprocess.run([_compiler(), "/Q", "/O" + str(out), "/DPayloadPath=" + str(payload),
                            str(ROOT / "tests_replica" / "host_staging_harness.iss")],
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
    other = app / "bridges" / "autocad" / "2026" / "ArchHub.AcadMCP.dll"
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
                          "/app=" + str(app), "/done=" + str(done), "/LOG=" + str(log), *extra], timeout=300)
    assert done.read_text() == "ran", "the harness did not run to the end"
    return ran.returncode, log.read_text(encoding="utf-8", errors="replace")


def _stop(host):
    host.stdin.close()
    host.wait(timeout=60)


@pytest.mark.skipif(os.name != "nt", reason="Windows file locking")
def test_a_loaded_broker_is_set_aside_and_the_install_finishes(harness, tmp_path):
    exe, payload = harness
    app, locked, old, host = _installed(tmp_path, "one")
    try:
        code, log = _run(exe, app, tmp_path)
        assert code == 0 and "Host file in use set aside" in log
        assert locked.read_bytes() == NEW
        retired = list((app / ".retired-host-files").rglob("RevitMCP.dll"))
        assert len(retired) == 1 and retired[0].read_bytes() == old
        assert retired[0].relative_to(app / ".retired-host-files").parts[1:] == ("revit", "2027", "RevitMCP.dll")
        # An unlocked file is replaced in place, never set aside.
        assert (app / "bridges/autocad/2026/ArchHub.AcadMCP.dll").read_bytes() == b"new autocad\n"
        assert not list((app / ".retired-host-files").rglob("ArchHub.AcadMCP.dll"))
        # bridges\ holds exactly the shipped files: the reviewed tree digest still verifies.
        assert bridges_tree_sha256(app / "bridges") == bridges_tree_sha256(payload / "bridges")
    finally:
        _stop(host)
    # The next install, with the host closed, clears the set-aside copies.
    assert _run(exe, app, tmp_path)[0] == 0
    assert not (app / ".retired-host-files").exists() or not any((app / ".retired-host-files").rglob("*.dll"))


@pytest.mark.skipif(os.name != "nt", reason="Windows file locking")
def test_an_unfinished_install_puts_the_loaded_broker_back(harness, tmp_path):
    exe, _ = harness
    app, locked, old, host = _installed(tmp_path, "two")
    try:
        (app / "abort.txt").mkdir()  # a later file cannot be written: setup aborts and rolls back
        code, log = _run(exe, app, tmp_path)
        assert code != 0 and "Host file in use set aside" in log
        assert "Host file restored after an unfinished setup" in log
        assert locked.read_bytes() == old
        assert not list((app / ".retired-host-files").rglob("RevitMCP.dll"))
    finally:
        _stop(host)


def test_the_release_installer_sets_host_files_aside_for_every_bridge_folder():
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    staging = (ROOT / "installer" / "host_file_staging.iss").read_text(encoding="utf-8")
    assert '#include "host_file_staging.iss"' in iss
    assert "RetireLockedHostFiles(ExpandConstant('{app}'), '{#BuildId}');" in iss
    assert "HostFilesInstalled();" in iss and "RestoreRetiredHostFiles();" in iss
    assert re.search(r'^Type: filesandordirs; Name: "\{app\}\\\.retired-host-files"$', iss, re.M)
    # Every host folder: the walk starts at bridges\, not at one host.
    assert "AddBackslash(App) + 'bridges', ''" in staging
    # restartreplace needs admin; this setup is per-user, so it must not be relied on.
    assert "restartreplace" not in re.sub(r"(?m)^;.*$", "", iss)