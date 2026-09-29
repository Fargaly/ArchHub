"""Court: an upgrade keeps working when the private .venv was built by another Python,
and a failed or blocked rebuild never destroys the environment that works.

Verifier 2026-09-28: after the 3.14-only pin, a .venv built by 3.11-3.13 was reused
as it stood and refused itself forever. Review 2026-09-28: the first repair rebuilt it
in place (venv --clear) after dropping the ready marker, so a failed rebuild (a locked
file, permissions, a full disk) left nothing working. Now the new environment is built
beside the old one (.venv.new), its packages installed and its imports proven, then
swapped in; the old one and its ready marker stay until the swap has succeeded.
No real interpreter or venv is created: subprocess.run and the renames are fixtures.
"""
import os
import sys
from types import SimpleNamespace

import pytest

import colleague_setup


def _environment(path, version):
    (path / "Scripts").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        (path / "Scripts" / name).write_text("")
    (path / "pyvenv.cfg").write_text(
        "home = C:\\Python\ninclude-system-site-packages = false\nversion = %s\n" % version)
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    old = _environment(tmp_path / ".venv", "3.12.4")
    (tmp_path / ".archhub-ready").write_text("venv-v1:old\n")
    (tmp_path / "requirements.txt").write_text("example==1\n")
    seen = []
    fail = {}

    def run(args, **kwargs):
        args = [str(arg) for arg in args]
        seen.append(args)
        if "venv" in args:
            if fail.get("venv"):
                return SimpleNamespace(returncode=fail["venv"])
            _environment(tmp_path / ".venv.new", "%d.%d.1" % sys.version_info[:2])
            return SimpleNamespace(returncode=0)
        if "pip" in args:
            return SimpleNamespace(returncode=fail.get("pip", 0))
        if "-c" in args:
            return SimpleNamespace(returncode=fail.get("imports", 0))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(colleague_setup.subprocess, "run", run)
    monkeypatch.setattr(colleague_setup, "owned_interpreter", lambda root: False)
    return SimpleNamespace(root=tmp_path, old=old, seen=seen, fail=fail)


def _old_still_works(world):
    assert (world.old / "pyvenv.cfg").read_text().endswith("version = 3.12.4\n")
    assert (world.root / ".archhub-ready").read_text() == "venv-v1:old\n", "the ready marker is kept"
    assert not (world.root / ".venv.new").exists(), "a half-built environment is not left behind"


def test_an_environment_built_by_another_python_is_rebuilt_beside_it_then_swapped(world):
    status = colleague_setup.prepare_environment(world.root)
    assert status == 0
    venv = next(call for call in world.seen if "venv" in call)
    assert venv[-1] == str(world.root / ".venv.new") and "--clear" not in venv
    pip = next(call for call in world.seen if "pip" in call)
    assert pip[0] == str(world.root / ".venv.new" / "Scripts" / "python.exe")
    assert any("-c" in call and call[0].endswith(os.path.join(".venv.new", "Scripts", "python.exe"))
               for call in world.seen), "imports are proven in the new environment before the swap"
    version = colleague_setup.environment_version(world.root / ".venv")
    assert version == tuple(sys.version_info[:2]), "the new environment is now .venv"
    assert not (world.root / ".venv.new").exists()
    assert not (world.root / ".archhub-ready").exists(), "the swapped environment records readiness itself"
    assert world.seen[-1][0] == str(world.root / ".venv" / "Scripts/python.exe")


@pytest.mark.parametrize("step", ["venv", "pip", "imports"])
def test_a_failed_rebuild_keeps_the_old_environment_usable(world, step):
    world.fail[step] = 23
    assert colleague_setup.prepare_environment(world.root) == 23
    _old_still_works(world)


def test_a_locked_environment_refuses_safely_and_keeps_the_old_one(world, monkeypatch):
    real = os.replace

    def locked(source, target):
        if str(source) == str(world.root / ".venv"):
            raise PermissionError(32, "The process cannot access the file", str(source))
        return real(source, target)

    monkeypatch.setattr(colleague_setup.os, "replace", locked)
    assert colleague_setup.prepare_environment(world.root) not in (0, None)
    _old_still_works(world)


def test_a_failed_second_rename_puts_the_old_environment_back(world, monkeypatch):
    real = os.replace

    def second_fails(source, target):
        if str(source) == str(world.root / ".venv.new"):
            raise PermissionError(5, "Access is denied", str(source))
        return real(source, target)

    monkeypatch.setattr(colleague_setup.os, "replace", second_fails)
    assert colleague_setup.prepare_environment(world.root) not in (0, None)
    _old_still_works(world)


def test_check_ready_reports_a_foreign_environment_as_not_ready(world):
    assert colleague_setup.prepare_environment(world.root, check_only=True) == 1
    assert world.seen == []


def test_an_environment_built_by_this_python_is_reused(tmp_path, monkeypatch):
    owned = _environment(tmp_path / ".venv", "%d.%d.1" % sys.version_info[:2])
    seen = []
    monkeypatch.setattr(colleague_setup.subprocess, "run",
                        lambda args, **kw: seen.append([str(a) for a in args]) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(colleague_setup, "owned_interpreter", lambda root: False)
    colleague_setup.prepare_environment(tmp_path)
    assert not any("venv" in call for call in seen)
    assert seen[0][0] == str(owned / "Scripts/python.exe")