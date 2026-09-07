"""One brain per machine, and a second daemon costs a socket -- not gigabytes.

The founder asked why several brain servers open, and told me to fix it
properly rather than patch it.

The chain: the daemon binds its port LAST -- after building the engine and
starting every worker, which takes minutes. For all that time the port looks
FREE, so everything that wants a brain (the app's 20-second watchdog, every
shell, the supervisor) concludes none is coming and starts one. The loser of
the bind race logged "[Errno 10048]" and then KEPT RUNNING forever, loading
the graph and syncing to the cloud while serving nothing. He had three,
holding 8.4 GB between them, and none of them answered (2026-09-07).

Two mechanisms fix it at the root, and these courts hold both:
  * the daemon takes its port BEFORE building the engine and holds it until
    uvicorn serves on that very socket, so a losing daemon exits at once;
  * every starter -- the app and the shell wrapper -- takes the SAME
    machine-wide claim, held through the whole boot.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "launch_archhub_test.py").read_text(encoding="utf-8")
PRODUCTION = ROOT.parent / "12.PRODUCTION"


def test_the_port_is_one_fixed_number():
    """A brain nobody can find is a brain nobody has."""
    service = (
        PRODUCTION / "personal-brain-mcp" / "src" / "personal_brain"
        / "service.py"
    ).read_text(encoding="utf-8")
    assert "DEFAULT_PORT = 8473" in service
    wrapper = (PRODUCTION / "tools" / "brainwrap.py").read_text(encoding="utf-8")
    assert "DAEMON_PORT = 8473" in wrapper
    assert '"--http", "8473"' in LAUNCHER


def test_the_daemon_takes_its_port_before_it_builds_anything():
    server = (
        PRODUCTION / "personal-brain-mcp" / "src" / "personal_brain"
        / "server.py"
    ).read_text(encoding="utf-8")
    assert "_claim_http_port_or_exit(" in server
    claim = server.index("_http_claim = _claim_http_port_or_exit(")
    serve = server.index('server.run(transport="http"')
    assert claim < serve, "the port must be taken before the engine serves"
    assert "raise SystemExit(1)" in server[
        server.index("def _claim_http_port_or_exit"):serve
    ], "a daemon that cannot take the port must exit, not keep running"


def test_the_daemon_serves_on_the_socket_it_already_holds():
    """Releasing the claim would reopen the window it exists to close."""
    core = (
        PRODUCTION / "personal-brain-mcp" / "src" / "personal_brain"
        / "mcp_core.py"
    ).read_text(encoding="utf-8")
    assert "claimed_socket" in core
    assert "uvicorn.Server(config).run(sockets=[claimed])" in core


def test_the_app_and_the_shell_share_one_claim():
    """Two starters with two locks is two brains."""
    wrapper = (PRODUCTION / "tools" / "brainwrap.py").read_text(encoding="utf-8")
    assert "archhub-brain-daemon-start.lock" in wrapper
    assert "archhub-brain-daemon-start.lock" in LAUNCHER, (
        "the app must take the SAME claim the shell wrapper takes"
    )


def test_the_app_claims_before_it_spawns():
    tree = ast.parse(LAUNCHER)
    claim = LAUNCHER.index("if not _claim_brain_start():")
    spawn = LAUNCHER.index('_sp.Popen([exe, "-m", "personal_brain.server"')
    assert claim < spawn
    assert tree is not None


def test_the_claim_outlives_a_slow_boot():
    """Released after ten seconds, it would let the next tick start another."""
    body = LAUNCHER[LAUNCHER.index("if not _claim_brain_start():"):]
    body = body[:body.index("def _replace_a_wedged_brain")] if (
        "def _replace_a_wedged_brain" in body
    ) else body[:4000]
    released = body.index("_release_brain_start_claim()")
    alive = body.index("if _alive():")
    assert alive < released, (
        "the claim is released only once the brain actually answers"
    )
    assert "The claim is NOT released here" in body


def test_an_abandoned_claim_is_taken_over():
    """A starter killed mid-boot must not leave the brain unstartable."""
    assert "_BRAIN_START_CLAIM_SECONDS" in LAUNCHER
    block = LAUNCHER[LAUNCHER.index("def _claim_brain_start"):]
    block = block[:block.index("def _release_brain_start_claim")]
    assert "path.unlink()" in block
    assert "O_CREAT | os.O_EXCL" in block
