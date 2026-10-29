"""The connector's supervisor keeps the agent's pipe open when the connector dies (an install, a crash).

Fixture child: a stdlib stdio MCP server that answers with its pid. No live agent, Workshop or install.
"""
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "01.APP"

FIXTURE = textwrap.dedent("""
    import json, os, sys
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "f", "version": "1"}} \\
            if m["method"] == "initialize" else {"content": [{"type": "text", "text": str(os.getpid())}]}
        if m["method"] == "die":
            os._exit(3)
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\\n")
        sys.stdout.flush()
""")


def _start(tmp_path, gate=None):
    fixture = tmp_path / "fixture.py"
    fixture.write_text(FIXTURE, encoding="utf-8")
    child = [sys.executable, "-I", str(fixture)]
    if gate:  # the child refuses to start while the gate file exists (a half-done install)
        child = [sys.executable, "-I", "-c",
                 "import os,sys,runpy;os.path.exists(sys.argv[1]) and sys.exit(9);sys.argv=sys.argv[1:];"
                 "runpy.run_path(sys.argv[1],run_name='__main__')", str(gate), str(fixture)]
    code = ("import sys;sys.path.insert(0,sys.argv[1]);from nodelang.mcp_supervisor import supervise;"
            "sys.exit(supervise(sys.argv[2:]))")
    return subprocess.Popen([sys.executable, "-I", "-c", code, str(APP), *child], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _call(proc, message, want_id=None, timeout=30):
    proc.stdin.write((json.dumps(message) + "\n").encode())
    proc.stdin.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        reply = json.loads(proc.stdout.readline())
        if want_id is None or reply.get("id") == want_id:
            return reply
    raise AssertionError("no reply")


def _init(proc):
    reply = _call(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, 1)
    proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    return reply


def test_connector_death_keeps_the_pipe_and_the_next_call_reaches_a_new_connector(tmp_path):
    proc = _start(tmp_path)
    try:
        assert _init(proc)["result"]["serverInfo"]["name"] == "f"
        first = _call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}, 2)["result"]["content"][0]["text"]
        lost = _call(proc, {"jsonrpc": "2.0", "id": 3, "method": "die"}, 3)
        assert "restarting" in lost["error"]["message"]
        for _ in range(40):
            reply = _call(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call"}, 4)
            if "result" in reply:
                break
            time.sleep(0.25)
        assert reply["result"]["content"][0]["text"] != first
        assert proc.poll() is None
    finally:
        proc.stdin.close()
        proc.wait(10)


def test_a_connector_that_cannot_start_yet_answers_restarting_then_comes_up(tmp_path):
    gate = tmp_path / "installing"
    gate.write_text("x")
    proc = _start(tmp_path, gate)
    try:
        proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n')
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        busy = _call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}, 2)
        assert "restarting" in busy["error"]["message"]
        gate.unlink()  # the install finished
        # The agent's own initialize is answered once, by the first connector that comes up.
        assert json.loads(proc.stdout.readline())["id"] == 1
        reply = _call(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call"}, 3)
        assert reply["result"]["content"][0]["text"].isdigit()
    finally:
        proc.stdin.close()
        proc.wait(10)


def test_the_agent_closing_its_pipe_ends_supervisor_and_connector(tmp_path):
    proc = _start(tmp_path)
    _init(proc)
    proc.stdin.close()
    assert proc.wait(15) == 0
