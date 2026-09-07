"""The wrapper never stops him working, and never litters his machine.

Three things the founder showed on 2026-09-07:

  * He typed CLAUDE and his shell answered "governance: blocked (brain
    unreachable)" and refused to run the CLI. The daemon was merely still
    coming up. This module has always promised that silence degrades a
    session rather than stopping the vendor CLI; strict mode broke it.

  * Five brain daemons were running, because a shell whose health probe
    missed its 12s window started ANOTHER one.

  * His Start menu held eight `.archhub-raw-bak.<stamp>.lnk` copies of every
    shortcut, one per rewrite.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "brainwrap_under_court", ROOT / "tools" / "brainwrap.py"
)
brainwrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brainwrap)


def test_an_unreachable_brain_never_stops_his_cli():
    body = inspect.getsource(brainwrap.cmd_launch)
    blocked = body.index("brain unreachable")
    tail = body[max(0, blocked - 500):blocked + 500]
    assert "fail-open" in tail
    assert "GOVERNANCE_BLOCK_EXIT" not in tail, (
        "silence must degrade the session, never refuse to run his CLI"
    )


def test_a_brain_that_answers_and_refuses_still_blocks():
    """Fail-open on silence is not fail-open on a refusal."""
    body = inspect.getsource(brainwrap.cmd_launch)
    after = body[body.index("governed_preflight("):]
    assert "GOVERNANCE_BLOCK_EXIT" in after, (
        "a real governance refusal must still block"
    )


def test_only_one_shell_may_start_the_daemon():
    body = inspect.getsource(brainwrap.ensure_daemon)
    assert "_port_held(DAEMON_PORT)" in body
    assert "_claim_daemon_start_lock()" in body
    spawn = body.index("subprocess.Popen")
    assert body.index("_port_held(DAEMON_PORT)") < spawn, (
        "a listener must be seen BEFORE another daemon is started"
    )
    assert body.index("_claim_daemon_start_lock()") < spawn


def test_a_shell_that_loses_the_race_waits_instead_of_spawning():
    body = inspect.getsource(brainwrap.ensure_daemon)
    assert body.count("_wait_for_health(") >= 2
    assert "already listening" in body and "another shell is starting" in body


def test_an_abandoned_start_lock_is_taken_over():
    """A shell killed mid-start must not make the brain unstartable."""
    body = inspect.getsource(brainwrap._claim_daemon_start_lock)
    assert "_DAEMON_START_LOCK_SECONDS" in body
    assert "path.unlink()" in body
    assert brainwrap._DAEMON_START_LOCK_SECONDS <= 300


def test_the_lock_is_won_by_exactly_one_caller(tmp_path, monkeypatch):
    monkeypatch.setattr(
        brainwrap, "_daemon_start_lock_path", lambda: tmp_path / "start.lock"
    )
    first = brainwrap._claim_daemon_start_lock()
    assert first is not None
    assert brainwrap._claim_daemon_start_lock() is None
    brainwrap._release_daemon_start_lock(first)
    assert brainwrap._claim_daemon_start_lock() is not None


def test_the_daemon_gets_no_console_window():
    body = inspect.getsource(brainwrap.ensure_daemon)
    assert "CREATE_NO_WINDOW" in body, (
        "DETACHED_PROCESS alone lets a console app allocate its own window"
    )
    assert "pythonw.exe" in inspect.getsource(brainwrap.daemon_start_command)


def test_one_backup_per_shortcut_not_one_per_rewrite():
    script = (ROOT / "tools" / "governed_sessions.py").read_text(
        encoding="utf-8"
    )
    assert '"$path.archhub-raw-bak.lnk"' in script
    assert "ToUnixTimeSeconds()).lnk" not in script, (
        "a stamped backup per rewrite fills his Start menu"
    )
    assert "if (-not (Test-Path -LiteralPath $backup))" in script
