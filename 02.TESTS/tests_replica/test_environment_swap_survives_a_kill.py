"""Court: a kill between the two renames of an environment swap never leaves setup
with neither environment.

Verifier 2026-09-28 (first-run v3): replace_environment moves .venv to .venv.old and
then .venv.new to .venv. A process killed between those renames left no .venv; the
next setup discarded .venv.old as a leftover and built an empty environment, so the
working installation was lost. Now setup first moves .venv.old back, so a restart
finds the old environment (and rebuilds from it) or the new one, never neither.
No real interpreter or venv is created: subprocess.run and the renames are fixtures.
"""
import os
import sys
from types import SimpleNamespace

import pytest

import colleague_setup


class Killed(BaseException):
    """Stands in for the process dying: not an OSError, so nothing catches it."""


def _environment(path, version):
    (path / "Scripts").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (path / "Scripts" / name).write_text("")
    (path / "pyvenv.cfg").write_text(
        "home = C:\\Python\ninclude-system-site-packages = false\nversion = %s\n" % version)
    return path


@pytest.fixture
def killed_mid_swap(tmp_path, monkeypatch):
    _environment(tmp_path / ".venv", "3.12.4")
    (tmp_path / "requirements.txt").write_text("example==1\n")
    fail = {}

    def run(args, **kwargs):
        args = [str(arg) for arg in args]
        if "venv" in args:
            if fail.get("venv"):
                return SimpleNamespace(returncode=fail["venv"])
            _environment(tmp_path / ".venv.new", "%d.%d.1" % sys.version_info[:2])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(colleague_setup.subprocess, "run", run)
    monkeypatch.setattr(colleague_setup, "owned_interpreter", lambda root: False)
    real = os.replace

    def killed_on_second_rename(source, target):
        if str(source) == str(tmp_path / ".venv.new"):
            raise Killed()
        return real(source, target)

    monkeypatch.setattr(colleague_setup.os, "replace", killed_on_second_rename)
    with pytest.raises(Killed):
        colleague_setup.prepare_environment(tmp_path)
    assert not (tmp_path / ".venv").exists(), "the kill landed between the two renames"
    assert (tmp_path / ".venv.old").exists()
    monkeypatch.setattr(colleague_setup.os, "replace", real)
    return SimpleNamespace(root=tmp_path, fail=fail)


def test_a_restart_after_the_kill_finishes_with_the_new_environment(killed_mid_swap):
    root = killed_mid_swap.root
    assert colleague_setup.prepare_environment(root) == 0
    assert colleague_setup.environment_version(root / ".venv") == tuple(sys.version_info[:2])
    assert not (root / ".venv.old").exists() and not (root / ".venv.new").exists()


def test_a_restart_whose_rebuild_fails_still_has_the_old_environment(killed_mid_swap):
    root = killed_mid_swap.root
    killed_mid_swap.fail["venv"] = 23
    assert colleague_setup.prepare_environment(root) == 23
    assert colleague_setup.environment_version(root / ".venv") == (3, 12), \
        "the old environment was moved back, not discarded"


def test_check_ready_after_the_kill_changes_nothing(killed_mid_swap):
    root = killed_mid_swap.root
    assert colleague_setup.prepare_environment(root, check_only=True) == 1
    assert not (root / ".venv").exists() and (root / ".venv.old").exists()


def test_recovery_leaves_a_complete_environment_alone(tmp_path):
    _environment(tmp_path / ".venv", "3.14.0")
    _environment(tmp_path / ".venv.old", "3.12.4")
    assert colleague_setup.recover_environment_swap(tmp_path) == 0
    assert colleague_setup.environment_version(tmp_path / ".venv") == (3, 14)
