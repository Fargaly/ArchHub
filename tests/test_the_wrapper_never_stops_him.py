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


def test_a_listening_daemon_is_waited_for_never_duplicated():
    body = inspect.getsource(brainwrap.ensure_daemon)
    held = body.index("_port_held(DAEMON_PORT)")
    spawn = body.index("subprocess.Popen")
    assert held < spawn, "a listener must be seen BEFORE another is started"
    assert "already listening" in body


def test_nothing_else_guards_the_start():
    """The daemon takes its port before it builds anything, so a redundant
    start loses the bind in milliseconds and exits. A lock here solved what
    the port claim already solves, and when a starter died mid-boot its lock
    outlived it and left the machine with no brain at all (2026-09-07)."""
    source = inspect.getsource(brainwrap)
    for gone in (
        "_claim_daemon_start_lock",
        "_release_daemon_start_lock",
        "_daemon_start_lock_path",
        "_DAEMON_START_LOCK_SECONDS",
    ):
        assert gone not in source, "%s must not come back" % gone


def test_the_daemon_itself_refuses_to_be_the_second_one():
    """The whole guard lives in the daemon, where it cannot go stale."""
    server = (
        ROOT / "personal-brain-mcp" / "src" / "personal_brain" / "server.py"
    ).read_text(encoding="utf-8")
    assert "_refuse_if_port_is_taken(" in server
    refusal = server.index("_refuse_if_port_is_taken(args.http)")
    engine = server.index('server.run(transport="http"')
    assert refusal < engine, "the question comes before the engine"
    assert "raise SystemExit(1)" in server[
        server.index("def _refuse_if_port_is_taken"):engine
    ]


def test_one_backup_per_shortcut_not_one_per_rewrite():
    script = (ROOT / "tools" / "governed_sessions.py").read_text(
        encoding="utf-8"
    )
    assert '"$path.archhub-raw-bak.lnk"' in script
    assert "ToUnixTimeSeconds()).lnk" not in script, (
        "a stamped backup per rewrite fills his Start menu"
    )
    assert "if (-not (Test-Path -LiteralPath $backup))" in script
