"""Court (fix 5): the launcher starts the existing Brain supervisor when the Brain is silent.

Founder report 2026-09-23: nothing answered on 127.0.0.1:8473 since 09-21 and the application
never started the Brain again. The launcher now asks once per start (off the boot path, never
in a verification run) and starts only `personal_brain.service supervise`. The ambient
suspension marker brain/ambient-runtime.suspended is read and reported, never removed: the
Brain server keeps ambient services paused under it and still serves /mcp.
No process is spawned here: the spawn is a fixture that records its argv.
"""
import ast
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[1] / "launch_archhub_test.py"


def test_the_launcher_starts_the_brain_only_for_the_announced_runtime():
    source = LAUNCHER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    guarded = [node for node in tree.body if isinstance(node, ast.If)
               and "_announced_active is not None" in ast.unparse(node.test)
               and "_ensure_brain" in ast.unparse(node)]
    assert guarded, "the launcher never starts the Brain supervisor"
    assert "ensure_brain_supervisor" in source


class _Process:
    def __init__(self, code=None):
        self.pid, self._code = 4242, code

    def poll(self):
        return self._code


def _brain_dir(tmp_path, *, suspended=True, heartbeat=None):
    brain = tmp_path / "ArchHub" / "brain"
    brain.mkdir(parents=True)
    if suspended:
        (brain / "ambient-runtime.suspended").write_text("Operator pause", encoding="utf-8")
    if heartbeat is not None:
        (brain / "brain-supervisor.heartbeat").write_text(str(heartbeat), encoding="utf-8")
    return brain


def test_a_silent_brain_gets_its_supervisor_and_the_pause_marker_stays(tmp_path):
    from nodelang.brain_supervisor_start import ensure_brain_supervisor
    brain = _brain_dir(tmp_path, suspended=True, heartbeat=1000.0)
    spawned = []
    outcome = ensure_brain_supervisor(probe=lambda port: False, local_appdata=tmp_path,
        spawn=lambda argv, cwd: spawned.append((argv, cwd)) or _Process(), python="pythonw.exe",
        now=lambda: 2000.0, settle_seconds=0)
    assert outcome["action"] == "started" and outcome["ambient_suspended"] is True, outcome
    assert spawned == [(["pythonw.exe", "-m", "personal_brain.service", "supervise", "--port", "8473"], brain)]
    assert (brain / "ambient-runtime.suspended").read_text(encoding="utf-8") == "Operator pause"


@pytest.mark.parametrize("case", ["answers", "supervisor-alive"])
def test_nothing_is_started_beside_a_live_brain_or_supervisor(tmp_path, case):
    from nodelang.brain_supervisor_start import ensure_brain_supervisor
    _brain_dir(tmp_path, suspended=False, heartbeat=1990.0)
    spawned = []
    outcome = ensure_brain_supervisor(probe=lambda port: case == "answers", local_appdata=tmp_path,
        spawn=lambda argv, cwd: spawned.append(argv) or _Process(), python="pythonw.exe",
        now=lambda: 2000.0, settle_seconds=0)
    assert outcome["action"] == "none" and spawned == [], outcome


def test_a_supervisor_that_exits_at_once_is_reported_not_started(tmp_path):
    from nodelang.brain_supervisor_start import ensure_brain_supervisor
    _brain_dir(tmp_path, suspended=False)
    outcome = ensure_brain_supervisor(probe=lambda port: False, local_appdata=tmp_path,
        spawn=lambda argv, cwd: _Process(code=1), python="pythonw.exe", settle_seconds=0)
    assert outcome["action"] == "not started" and "code 1" in outcome["reason"], outcome


def test_health_is_the_brain_health_call_on_mcp():
    from nodelang.brain_supervisor_start import brain_answers
    asked = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            asked.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}'
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert brain_answers(server.server_address[1], timeout=5) is True
    finally:
        server.shutdown(); server.server_close()
    assert asked[0][0] == "/mcp" and asked[0][1]["params"]["name"] == "brain.health"
    assert brain_answers(server.server_address[1], timeout=1) is False, "a closed port is silent"
