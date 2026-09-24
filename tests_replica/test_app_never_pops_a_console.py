"""The app runs windowless (pythonw). A child spawned without CREATE_NO_WINDOW opens a
console on the founder's desktop at every probe tick -- he saw `tasklist` windows while
working (2026-09-04). This court reads every spawn in the shipped app and asserts the flag
is passed, so the absence cannot come back unnoticed."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = sorted(ROOT.glob("nodelang/*.py")) + [ROOT / "launch_archhub_test.py"]
SPAWN = re.compile(r"(?:subprocess|_sp|_sub)\.(?:run|Popen|call|check_output|check_call)\s*\(")


def _call_text(src: str, start: int) -> str:
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    return src[start:]


def test_every_spawn_in_the_shipped_app_hides_its_console():
    naked = []
    for path in SHIPPED:
        src = path.read_text(encoding="utf-8")
        for m in SPAWN.finditer(src):
            call = _call_text(src, m.end() - 1)
            if "creationflags" not in call:
                line = src.count("\n", 0, m.start()) + 1
                naked.append("%s:%d %s" % (path.name, line, call[:70].replace("\n", " ")))
    assert not naked, "spawns without creationflags (console would pop on the desktop):\n" + "\n".join(naked)


def test_tasklist_probe_is_silent():
    """The host probe no longer spawns tasklist at all: it reads a Toolhelp32
    process snapshot in-process, so there is no child that could open a console."""
    import inspect

    from nodelang import host_brokers

    running = inspect.getsource(host_brokers._running)
    assert "_windows_process_names()" in running
    snapshot = inspect.getsource(host_brokers._windows_process_names)
    assert "CreateToolhelp32Snapshot" in snapshot
    src = (ROOT / "nodelang" / "host_brokers.py").read_text(encoding="utf-8")
    assert "tasklist" not in src.lower()


def test_process_presence_probe_does_not_spawn(monkeypatch):
    from types import SimpleNamespace
    from nodelang import host_brokers as hosts
    def forbidden(*args, **kwargs):
        raise AssertionError("Process observation spawned a child")
    monkeypatch.setattr(hosts, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(hosts.subprocess, "run", forbidden)
    monkeypatch.setattr(hosts.subprocess, "Popen", forbidden)
    monkeypatch.setattr(hosts, "_windows_process_names", lambda: frozenset({"rhino.exe"}))
    assert hosts._running(("RHINO.EXE",))
    assert not hosts._running(("Rhino",))
