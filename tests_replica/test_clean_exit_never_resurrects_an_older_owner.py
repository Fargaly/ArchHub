"""Court: a clean desktop exit never leaves an "active" owner with a dead process.

On 2026-09-30 two owner records for one graph disagreed: the state directory's
said "stopped", %LOCALAPPDATA%/ArchHub/active-universal-runtime.json named an
OLDER runtime as "active" with a dead process id. The launcher saved the
announcement it found at start and wrote it back at a clean exit
(launch_archhub_test.py, _previous_active). Each clean exit resurrected a
stale owner. The exit now writes this runtime's own final ("stopped") record
into the announcement when it still names this runtime, and restores nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"


def _finished() -> int:
    """A process id that is certainly not running: a child that has exited."""
    child = subprocess.Popen([sys.executable, "-c", "0"])
    child.wait()
    return child.pid


def _record(path: Path, runtime_id: str, status: str, pid: int) -> bytes:
    raw = json.dumps({"runtime_id": runtime_id, "status": status, "process_id": pid}).encode()
    path.write_bytes(raw)
    return raw


def _launch_and_exit(owner: Path, machine: Path, runtime_id: str, pid: int):
    """What the launcher does: own the graph, announce, stop, release."""
    from nodelang import runtime_announcement
    _record(owner, runtime_id, "active", pid)
    announced = runtime_announcement.announce(machine, owner)
    _record(owner, runtime_id, "stopped", pid)          # server.close() writes this
    return runtime_announcement.release(announced)


def test_two_clean_launches_leave_no_active_record_with_a_dead_process(tmp_path):
    owner, machine = tmp_path / "state" / "runtime-descriptor.json", tmp_path / "local" / "active-universal-runtime.json"
    owner.parent.mkdir()
    assert _launch_and_exit(owner, machine, "runtime-one", _finished()) == "released"
    assert _launch_and_exit(owner, machine, "runtime-two", _finished()) == "released"
    for record in (owner, machine):
        held = json.loads(record.read_text())
        assert held["runtime_id"] == "runtime-two"
        assert held["status"] == "stopped", record   # nothing older and "active" came back


def test_a_stale_active_record_found_at_start_is_not_restored(tmp_path):
    owner, machine = tmp_path / "runtime-descriptor.json", tmp_path / "active-universal-runtime.json"
    stale = _record(machine, "runtime-older", "active", _finished())
    assert _launch_and_exit(owner, machine, "runtime-now", _finished()) == "released"
    assert machine.read_bytes() != stale
    assert json.loads(machine.read_text())["runtime_id"] == "runtime-now"


def test_another_runtime_announced_since_is_left_alone(tmp_path):
    from nodelang import runtime_announcement
    owner, machine = tmp_path / "runtime-descriptor.json", tmp_path / "active-universal-runtime.json"
    _record(owner, "runtime-mine", "active", _finished())
    announced = runtime_announcement.announce(machine, owner)
    theirs = _record(machine, "runtime-theirs", "active", 4242)
    _record(owner, "runtime-mine", "stopped", 1)
    assert runtime_announcement.release(announced) == "left"
    assert machine.read_bytes() == theirs


def test_the_launcher_releases_instead_of_restoring():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "_previous_active" not in source
    assert "runtime_announcement.announce(" in source
    assert "runtime_announcement.release(" in source
