"""One Brain per port, and a losing daemon leaves nothing behind.

The founder repeatedly found three to six `personal_brain.server --http 8473`
processes, several holding gigabytes, while the port was free or held by one
that answered nothing.

The chain, read out of the code rather than guessed:

  * The real bind happens LAST, after the engine is built and every worker
    runs, so a daemon paid for a whole engine before finding out it lost.
  * The bind failure does NOT raise: run() returns normally, main() returns,
    and the process then LIVES FOREVER because its worker threads are not
    daemon threads -- loading the graph and syncing to the cloud while
    serving nothing.

Both halves are closed here. A separate earlier attempt hung the claimed
socket off mcp_core.InHouseMCP.run; build_server returns a FastMCP object,
so that path is never taken and the daemon bound twice and died. The court
below holds that this fix lives where the code actually runs (2026-09-07).
"""
from __future__ import annotations

import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (
    ROOT / "personal-brain-mcp" / "src" / "personal_brain" / "server.py"
).read_text(encoding="utf-8")


def test_a_second_daemon_refuses_before_it_builds_anything():
    refusal = SERVER.index("_refuse_if_port_is_taken(args.http)")
    engine = SERVER.index('server.run(transport="http"')
    assert refusal < engine, "the port question must come before the engine"
    body = SERVER[SERVER.index("def _refuse_if_port_is_taken"):engine]
    assert "raise SystemExit(1)" in body, "a losing daemon must exit"
    assert "probe.close()" in body, (
        "this is a question, not the serving bind; the socket is released"
    )


def test_nothing_outlives_the_listener():
    """A returned run() means serving is over, so the process is over."""
    after = SERVER[SERVER.index('server.run(transport="http"'):]
    after = after[:after.index("# stdio is the default transport.")]
    assert "raise SystemExit(0)" in after, (
        "without this a daemon that lost the bind lives forever, because its "
        "worker threads are not daemon threads"
    )


def test_the_fix_is_on_the_path_the_daemon_actually_takes():
    """build_server returns FastMCP, so a fix on InHouseMCP.run never runs."""
    assert 'mcp = FastMCP("personal-brain")' in SERVER
    assert "claimed_socket" not in SERVER, (
        "handing a held socket to FastMCP.run does nothing: it ignores the "
        "kwarg and binds the port itself, so the daemon bound twice and died"
    )
    core = (
        ROOT / "personal-brain-mcp" / "src" / "personal_brain" / "mcp_core.py"
    ).read_text(encoding="utf-8")
    assert "claimed_socket" not in core


def test_the_refusal_says_which_port_and_why():
    body = SERVER[SERVER.index("def _refuse_if_port_is_taken"):]
    body = body[:body.index("def main(")]
    assert "already owned by another Brain" in body
    assert "serve nothing" in body
