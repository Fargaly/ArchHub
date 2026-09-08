"""One brain per port, proven by the window that actually leaked.

The guard was real and the race went straight past it. _refuse_if_port_is_taken
bound the port and released it in the same breath -- "a question, not the
serving bind" -- and then build_server opened a 1.16 GB store before
server.run() bound for real. For those minutes nothing was listening.

The launcher decides a brain is missing by asking whether anything answers a
connect (launch_archhub_test.py:485). So its 20-second watchdog saw no brain
and started another, which also answered nothing while IT built. Measured on
the founder machine 2026-09-08: ten daemons alive, 10.86 GB RSS, nine of them
listening on nothing. Each held an open read snapshot on brain.db, so the WAL
could never checkpoint -- 15.8 GB of it, against 27 GB of free disk. Killing
the nine dropped the WAL to exactly its 256 MB limit within seconds.

What matters is not that a duplicate exits. It is WHEN, and whether the port
is visible in between.
"""
from __future__ import annotations

import inspect
import socket

from personal_brain import server as brain_server


def _source() -> str:
    return inspect.getsource(brain_server._refuse_if_port_is_taken)


def test_the_claim_is_held_not_released():
    """The one line that made the whole race possible."""
    body = _source()

    assert "probe.listen(1)" in body
    assert "_PORT_CLAIM = probe" in body
    assert "finally:\n        probe.close()" not in body


def test_the_claim_is_handed_over_only_at_the_real_bind():
    main = inspect.getsource(brain_server.main)
    release = main.index("_release_port_claim()")
    run = main.index('server.run(')

    assert release < run, "the claim must be released BEFORE the real bind"
    assert "build_server(" in main
    assert main.index("build_server(") > main.index("_refuse_if_port_is_taken")


def test_a_second_daemon_loses_the_port_before_it_opens_a_store(monkeypatch):
    """The loser must exit at the claim, not after building an engine."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        holder.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        opened = []
        monkeypatch.setattr(
            brain_server, "build_server",
            lambda **kw: opened.append(kw) or None,
        )
        try:
            brain_server._refuse_if_port_is_taken(port)
        except SystemExit as exit_code:
            assert exit_code.code == 1
        else:
            raise AssertionError("a second daemon kept going on a taken port")
        assert opened == [], "the loser opened a store before finding out"
    finally:
        holder.close()


def test_the_winner_is_visible_while_it_warms_up():
    """A claim the launcher cannot see is the same as no claim at all."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    brain_server._refuse_if_port_is_taken(port)
    try:
        seen = socket.socket()
        seen.settimeout(0.4)
        try:
            # exactly what launch_archhub_test._port_held asks
            assert seen.connect_ex(("127.0.0.1", port)) == 0
        finally:
            seen.close()
    finally:
        brain_server._release_port_claim()


def test_releasing_the_claim_frees_the_port_for_the_real_server():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    brain_server._refuse_if_port_is_taken(port)
    brain_server._release_port_claim()

    rebind = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        rebind.bind(("127.0.0.1", port))
    finally:
        rebind.close()
