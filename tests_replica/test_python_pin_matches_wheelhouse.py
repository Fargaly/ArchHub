"""Court: every surface that picks an interpreter accepts only the wheelhouse's Python.

Audit 2026-09-28: build_release.ps1 assembles the offline wheelhouse for
--python-version 3.14 (cp314 wheels only), but the installer, the launcher and
setup accepted any Python 3.11+. On a 3.11-3.13 machine the offline install
failed and setup fell back to PyPI, which a firm proxy blocks. The accepted
interpreter is now the wheelhouse's minor version, and a machine without it is
offered the pinned python.org 3.14 installer the setup already carries.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def _wheelhouse_minor():
    build = _read("installer/build_release.ps1")
    match = re.search(r"--python-version\s+3\.(\d+)", build)
    assert match, "build_release.ps1 no longer names the wheelhouse Python"
    return int(match.group(1))


def test_installer_launcher_and_setup_accept_only_the_wheelhouse_python():
    minor = _wheelhouse_minor()
    pinned = "sys.version_info[:2] == (3,%d)" % minor
    iss = _read("installer/ArchHub.iss")
    vbs = _read("installer/ArchHub.vbs")
    assert pinned in iss, "ArchHub.iss PythonRuns must accept only 3.%d" % minor
    assert pinned in vbs, "ArchHub.vbs PythonUsable must accept only 3.%d" % minor
    assert ">= (3,11)" not in iss and ">= (3,11)" not in vbs
    setup = _read("colleague_setup.py")
    assert "sys.version_info[:2] != (3, %d)" % minor in setup
    assert "sys.version_info < (3, 11)" not in setup


def test_the_bundled_python_download_is_the_wheelhouse_python():
    minor = _wheelhouse_minor()
    iss = _read("installer/ArchHub.iss")
    url = re.search(r"PythonUrl = 'https://www\.python\.org/ftp/python/3\.(\d+)\.\d+/", iss)
    assert url and int(url.group(1)) == minor


def _pascal_function(iss, name):
    start = iss.index("function " + name)
    return iss[start:iss.index("\nend;", start)]


def test_an_upgrade_without_the_pinned_python_installs_it_before_files():
    """A 3.12-only machine: FindPython (3.14 only) finds nothing, so PythonWanted.
    PrepareToInstall fetches the pinned 3.14 before any file is copied; when 3.14 is
    still missing it returns the reason, which Inno documents as stopping Setup with
    that message and a dedicated exit code, silent or not (jrsoftware.org/ishelp,
    topic_scriptevents), so the quiet updater can read why it stopped."""
    iss = _read("installer/ArchHub.iss")
    prepare = _pascal_function(iss, "PrepareToInstall(var NeedsRestart: Boolean): String;")
    assert "PythonWanted" in prepare and "InstallPython()" in prepare
    assert "Result := " in prepare and "3.14" in prepare
    install = _pascal_function(iss, "InstallPython(): Boolean;")
    assert "PythonPage.Add(PythonUrl, PythonFile, PythonSha256)" in install
    assert "Result := PythonPresent();" in install
    assert "(CurPageID = wpReady) and PythonWanted" not in iss, "one trigger only"
    for claim in ("launcher reports it on first run", "never ran", "has no wizard to show a page in"):
        assert claim not in iss, claim

def test_no_message_still_promises_python_3_11_or_newer():
    for relative in ("installer/ArchHub.iss", "installer/ArchHub.bat", "colleague_setup.py"):
        assert "3.11 or newer" not in _read(relative), relative
