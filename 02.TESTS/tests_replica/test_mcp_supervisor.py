"""The connector's supervisor keeps the agent's pipe open when the connector dies (an install, a crash).

Fixture child: a stdlib stdio MCP server that answers with its pid. No live agent, Workshop or install.
"""
import json
import os
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
        # The connector received this call and ended before answering: it may have taken effect.
        assert lost["error"]["data"] == {"archhub": "possibly_committed", "safe_to_retry": False}
        assert "may already have taken effect" in lost["error"]["message"] and "call again" not in lost["error"]["message"]
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
        # Either it never reached a connector (unstarted, safe to retry) or it was written into one that then
        # ended without answering (possibly committed): the supervisor never claims more than it knows.
        data = busy["error"]["data"]
        assert data in ({"archhub": "unstarted", "safe_to_retry": True},
                        {"archhub": "possibly_committed", "safe_to_retry": False})
        assert ("restarting" in busy["error"]["message"]) is data["safe_to_retry"]
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


def test_an_install_closes_the_connector_and_it_comes_back_after_without_the_agent_reconnecting(tmp_path):
    # Setup writes .archhub-installing for the length of an install: the supervisor (outside the install, holding
    # none of its files) closes its connector so no install file is in use, then starts it again and replays.
    fixture = tmp_path / "fixture.py"
    fixture.write_text(FIXTURE, encoding="utf-8")
    marker = tmp_path / ".archhub-installing"
    code = ("import os,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
            "from nodelang.mcp_supervisor import Supervisor;"
            "sys.exit(Supervisor(sys.argv[3:],dict(os.environ),sys.stdin.buffer,sys.stdout.buffer,pause=Path(sys.argv[2])).run())")
    proc = subprocess.Popen([sys.executable, "-I", "-c", code, str(APP), str(marker), sys.executable, "-I", str(fixture)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        _init(proc)
        before = _call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}, 2)["result"]["content"][0]["text"]
        marker.write_text("build")
        time.sleep(2.5)
        assert "restarting" in _call(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call"}, 3)["error"]["message"]
        marker.unlink()
        for attempt in range(40):
            reply = _call(proc, {"jsonrpc": "2.0", "id": 10 + attempt, "method": "tools/call"}, 10 + attempt)
            if "result" in reply:
                break
            time.sleep(0.5)
        assert reply["result"]["content"][0]["text"] != before   # a new connector, same agent pipe
        assert proc.poll() is None
    finally:
        proc.stdin.close()
        proc.wait(10)


SLOW_FIXTURE = textwrap.dedent("""
    import json, os, sys, time
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        if m["method"] == "slow":
            time.sleep(m["params"]["seconds"])
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "f", "version": "1"}} \\
            if m["method"] == "initialize" else {"content": [{"type": "text", "text": str(os.getpid())}]}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}) + "\\n")
        sys.stdout.flush()
""")


def _supervised(tmp_path):
    fixture = tmp_path / "slow_fixture.py"
    fixture.write_text(SLOW_FIXTURE, encoding="utf-8")
    marker, report = tmp_path / ".archhub-installing", tmp_path / "connectors" / "supervisor.json"
    code = ("import os,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
            "from nodelang.mcp_supervisor import Supervisor;"
            "sys.exit(Supervisor(sys.argv[4:],dict(os.environ),sys.stdin.buffer,sys.stdout.buffer,"
            "pause=Path(sys.argv[2]),report=Path(sys.argv[3])).run())")
    proc = subprocess.Popen([sys.executable, "-I", "-c", code, str(APP), str(marker), str(report),
                             sys.executable, "-I", str(fixture)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return proc, marker, report


def _report(report, want=None, field="pending"):
    """The supervisor's call report; with `want`, wait (bounded) until it says so."""
    value = None
    for _ in range(100):
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            value = data if field is None else data[field]
            if want is None or value == want:
                return value
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    raise AssertionError("call report never read %r (last %r)" % (want, value))


def test_an_install_lets_the_call_in_flight_finish_before_the_swap(tmp_path):
    """UPDATERWORKS: Setup's marker no longer cuts a running agent call; the swap waits for its answer."""
    proc, marker, report = _supervised(tmp_path)
    try:
        before = _init(proc)["result"]
        assert before and _report(report, 0) == 0
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 5, "method": "slow", "params": {"seconds": 6}}) + "\n").encode())
        proc.stdin.flush()
        assert _report(report, 1) == 1                    # the updater sees the call in flight
        marker.write_text("build")                        # Setup starts while the call runs
        assert _report(report, {"pending": 1, "admission": "closed", "attempt": None}, None)  # admission closed before any idle report
        late = _call(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call"}, 6)  # arrives during the drain
        assert late["error"]["data"] == {"archhub": "unstarted", "safe_to_retry": True}
        answered = _call(proc, {"jsonrpc": "2.0", "id": 7, "method": "noop"}, 5, timeout=30)
        assert "result" in answered                       # the call in flight got its real answer, not -32603
        assert _report(report, {"pending": 0, "admission": "closed", "attempt": None}, None)  # proven idle
        time.sleep(2.0)                                   # Setup is still copying; the drained connector is swapped
        marker.unlink()
        for attempt in range(40):
            reply = _call(proc, {"jsonrpc": "2.0", "id": 20 + attempt, "method": "tools/call"}, 20 + attempt)
            if "result" in reply:
                break
            time.sleep(0.5)
        assert reply["result"]["content"][0]["text"] != answered["result"]["content"][0]["text"]  # swapped
        assert _report(report, {"pending": 0, "admission": "open", "attempt": None}, None) and proc.poll() is None
    finally:
        proc.stdin.close()
        proc.wait(10)
    assert not report.exists()                            # an ended supervisor reports nothing


def test_an_idle_connector_is_swapped_at_once_and_reports_no_calls(tmp_path):
    proc, marker, report = _supervised(tmp_path)
    try:
        first = _call(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, 1)
        assert first["result"] and _report(report, 0) == 0
        pid = _call(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}, 2)["result"]["content"][0]["text"]
        marker.write_text("build")
        time.sleep(2.5)
        marker.unlink()
        for attempt in range(40):
            reply = _call(proc, {"jsonrpc": "2.0", "id": 10 + attempt, "method": "tools/call"}, 10 + attempt)
            if "result" in reply:
                break
            time.sleep(0.5)
        assert reply["result"]["content"][0]["text"] != pid
    finally:
        proc.stdin.close()
        proc.wait(10)

def _in_flight_during_drain(tmp_path, seen):
    """An in-process supervisor with call 5 in flight and the updater's drain request for attempt A."""
    import io
    from types import SimpleNamespace
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from nodelang.mcp_supervisor import Supervisor

    report = tmp_path / "connectors" / "1.json"

    class Agent:  # the agent's pipe: records the receipt on disk at the moment each line reaches the agent
        def write(self, data):
            seen.append((json.loads(data), json.loads(report.read_text(encoding="utf-8"))))

        def flush(self):
            pass

    supervisor = Supervisor([], {}, None, Agent(), report=report)
    supervisor.pending.add(5)
    report.parent.mkdir(parents=True)
    (report.parent / "drain-request.json").write_text(json.dumps({"attempt": "A"}), encoding="utf-8")
    supervisor._publish()
    assert json.loads(report.read_text(encoding="utf-8")) == {"pending": 1, "admission": "closed", "attempt": "A"}
    supervisor.child = object()  # another connector is current, so this pump only relays its answer and returns
    answer = SimpleNamespace(stdout=io.BytesIO(b'{"jsonrpc":"2.0","id":5,"result":{}}\n'), wait=lambda: 0)
    return supervisor, report, answer


def test_the_answer_to_the_call_in_flight_writes_the_idle_receipt_before_the_agent_sees_it(tmp_path):
    """Codex v5: no sleep, no polling loop; the decrement itself publishes the acknowledgement."""
    seen = []
    supervisor, _, answer = _in_flight_during_drain(tmp_path, seen)
    supervisor._pump(answer)  # the call in flight is released
    assert seen == [({"jsonrpc": "2.0", "id": 5, "result": {}}, {"pending": 0, "admission": "closed", "attempt": "A"})]


def test_a_receipt_write_windows_refuses_is_written_again_not_lost(tmp_path, monkeypatch):
    """The lost receipt: os.replace refused (the updater was reading the file) and the state was still
    remembered as written, so pending=1 stayed on disk forever."""
    seen = []
    supervisor, report, answer = _in_flight_during_drain(tmp_path, seen)
    replace, refusals = os.replace, [PermissionError(13, "in use")]

    def refused_once(source, target):
        if refusals:
            raise refusals.pop()
        return replace(source, target)

    monkeypatch.setattr(os, "replace", refused_once)
    supervisor._pump(answer)
    assert json.loads(report.read_text(encoding="utf-8"))["pending"] == 1  # that write was refused
    supervisor._publish()  # the report loop's next turn
    assert json.loads(report.read_text(encoding="utf-8")) == {"pending": 0, "admission": "closed", "attempt": "A"}


def test_the_updaters_drain_request_closes_admission_acknowledges_the_attempt_and_reopens(tmp_path):
    """Codex v2: admission closes before the all-clear; a late call is refused unstarted; removing the request
    (refused or deferred attempt) lets calls through again on the same connector."""
    proc, _marker, report = _supervised(tmp_path)
    request = report.parent / "drain-request.json"
    try:
        _init(proc)
        assert _report(report, {"pending": 0, "admission": "open", "attempt": None}, None)
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 5, "method": "slow", "params": {"seconds": 3}}) + "\n").encode())
        proc.stdin.flush()
        assert _report(report, 1) == 1
        request.write_text(json.dumps({"attempt": "A"}), encoding="utf-8")
        assert _report(report, {"pending": 1, "admission": "closed", "attempt": "A"}, None)  # not yet idle
        late = _call(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call"}, 6)
        assert late["error"]["data"] == {"archhub": "unstarted", "safe_to_retry": True}
        assert "result" in _call(proc, {"jsonrpc": "2.0", "id": 7, "method": "noop"}, 5, timeout=30)
        assert _report(report, {"pending": 0, "admission": "closed", "attempt": "A"}, None)  # the acknowledgement
        request.unlink()                                  # the attempt was refused or deferred
        assert _report(report, {"pending": 0, "admission": "open", "attempt": None}, None)
        assert "result" in _call(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/call"}, 8)
    finally:
        proc.stdin.close()
        proc.wait(10)


def test_calls_at_the_stop_step_and_at_setup_entry_are_refused_unstarted(tmp_path):
    """Codex acceptance (receipts 20/21 on 085e99d6): the real apply_staged must keep admission closed from the
    drain through the process stop and Setup entry, and reopen it once Setup has returned."""
    from types import SimpleNamespace
    from nodelang import quiet_update as qu
    from tests_replica.test_update_release_path import _build_output, _installed_app, _local_github

    app = _installed_app(tmp_path / "LOCAL" / "ArchHub", "old", "2026-11-17T16:08:00Z")
    state = tmp_path / "updater-state"
    release = _build_output(tmp_path / "release", "next", "2026-11-17T17:44:00Z")
    assert qu.stage_if_newer(state, app, opener=_local_github(release))["staged"]
    connectors = tmp_path / "LOCAL" / "ArchHub-Runtime" / "connectors"
    fixture = tmp_path / "slow_fixture.py"
    fixture.write_text(SLOW_FIXTURE, encoding="utf-8")
    report = connectors / "4242.json"
    code = ("import os,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
            "from nodelang.mcp_supervisor import Supervisor;"
            "sys.exit(Supervisor(sys.argv[4:],dict(os.environ),sys.stdin.buffer,sys.stdout.buffer,"
            "pause=Path(sys.argv[2]),report=Path(sys.argv[3])).run())")
    proc = subprocess.Popen([sys.executable, "-I", "-c", code, str(APP), str(app / ".archhub-installing"), str(report),
                             sys.executable, "-I", str(fixture)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    calls = []

    def acknowledgements(_directory, attempt):  # the real report of this one live supervisor
        data = json.loads(report.read_text(encoding="utf-8"))
        ok = data == {"pending": 0, "admission": "closed", "attempt": attempt}
        return [] if ok else ["pid 4242: %r" % data]

    def ask(identity):
        calls.append(_call(proc, {"jsonrpc": "2.0", "id": identity, "method": "tools/call"}, identity))

    try:
        _init(proc)
        _report(report, {"pending": 0, "admission": "open", "attempt": None}, None)
        drain = lambda d, a: qu.drain_connectors(d, a, acknowledgements=acknowledgements, sleep=time.sleep, bound=30)
        result = qu.apply_staged(state, app, drain=drain, stop_runtime=lambda _d: ask(20),
                                 runner=lambda argv, **k: ask(21) or SimpleNamespace(returncode=1))
        assert result["applied"] is False                      # this fixture's Setup fails; the order is the point
        for refused in calls:
            assert refused["error"]["data"] == {"archhub": "unstarted", "safe_to_retry": True}, refused
        assert [c["id"] for c in calls] == [20, 21]
        assert not (connectors / qu.DRAIN_REQUEST).exists()  # reopened after Setup returned
        _report(report, {"pending": 0, "admission": "open", "attempt": None}, None)
        assert "result" in _call(proc, {"jsonrpc": "2.0", "id": 22, "method": "tools/call"}, 22)
    finally:
        proc.stdin.close()
        proc.wait(10)


_HOT_RELOAD_SERVER = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    app_root = Path(sys.argv[1])
    tools = json.loads((app_root / "tools_spec.json").read_text(encoding="utf-8"))
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        method = msg.get("method")
        if method == "initialize":
            res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "hot-fixture", "version": "1"}}
        elif method == "tools/list":
            res = {"tools": [{"name": name, "inputSchema": {"type": "object", "properties": {}}} for name in tools]}
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name not in tools:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                                             "error": {"code": -32602, "message": "unknown tool"}}) + "\\n")
                sys.stdout.flush()
                continue
            res = {"content": [{"type": "text", "text": f"{name}:{os.getpid()}"}]}
        else:
            res = {"ok": True}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}) + "\\n")
        sys.stdout.flush()
""")


def _isolated_env(tmp_path):
    """Build an isolated subprocess environment pointing state and profile roots into tmp_path."""
    env = dict(os.environ)
    env["ARCHHUB_TEST_STATE_DIR"] = str(tmp_path / "state")
    env["LOCALAPPDATA"] = str(tmp_path / "local")
    env["APPDATA"] = str(tmp_path / "roaming")
    env["USERPROFILE"] = str(tmp_path / "home")
    return env


def _next_msg(proc, timeout=15):
    """Read the next JSON-RPC line from proc.stdout via one shared reader queue per process."""
    import queue
    import threading
    if not hasattr(proc, "_msg_q"):
        lines = queue.Queue()

        def _reader():
            for raw in iter(proc.stdout.readline, b""):
                lines.put(raw)
            lines.put(None)

        proc._msg_q = lines
        threading.Thread(target=_reader, daemon=True).start()
    try:
        raw = proc._msg_q.get(timeout=timeout)
    except queue.Empty:
        raise AssertionError("timed out waiting for connector stdout")
    if not raw:
        raise AssertionError("connector stdout closed early")
    return json.loads(raw)


def _qcall(proc, message, want_id=None, timeout=15):
    """Send message to proc.stdin and read from the shared queue until want_id arrives."""
    proc.stdin.write((json.dumps(message) + "\n").encode())
    proc.stdin.flush()
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.05, deadline - time.time())
        reply = _next_msg(proc, timeout=remaining)
        if want_id is None or reply.get("id") == want_id:
            return reply
    raise AssertionError(f"no reply for id={want_id!r}")


def _qinit(proc, timeout=15):
    """Initialize proc using the shared stdout reader queue."""
    reply = _qcall(
        proc,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "court", "version": "1"}}},
        1,
        timeout=timeout,
    )
    proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    proc.stdin.flush()
    return reply


def _read_until(proc, predicate, timeout=15):
    """Read JSON-RPC messages from proc's shared stdout queue until predicate(msg) is True."""
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        remaining = max(0.05, deadline - time.time())
        msg = _next_msg(proc, timeout=remaining)
        seen.append(msg)
        if predicate(msg):
            return msg, seen
    raise AssertionError(f"timed out waiting for message (seen={seen!r})")


def _pid_exited(pid, timeout=10):
    """Return True once the given pid is no longer running."""
    import psutil
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            return True
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.1)
    return False


def _stop_proc(proc):
    """Close stdin and force-kill proc if it does not exit within 5 seconds."""
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except OSError:
        pass
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(5)


def test_real_native_mcp_advertises_tools_list_changed(tmp_path):
    """Real native_agent_mcp must advertise capabilities.tools.listChanged=True on initialize."""
    env = dict(_isolated_env(tmp_path), ARCHHUB_MCP_SUPERVISED="1")
    loader = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
              "runpy.run_module('nodelang.native_agent_mcp',run_name='__main__')")
    proc = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", loader, str(APP)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    try:
        reply = _qcall(
            proc,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "court", "version": "1"}}},
            1,
        )
        assert reply["result"]["capabilities"]["tools"]["listChanged"] is True
    finally:
        _stop_proc(proc)


def _start_hot_supervisor(tmp_path, app_root):
    """Launch Supervisor wrapping the hot-reload fixture server inside tmp_path."""
    server = tmp_path / "hot_server.py"
    server.write_text(_HOT_RELOAD_SERVER, encoding="utf-8")
    code = ("import os,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
            "from nodelang.mcp_supervisor import Supervisor;"
            "sys.exit(Supervisor(sys.argv[3:],dict(os.environ),sys.stdin.buffer,"
            "sys.stdout.buffer,pause=Path(sys.argv[2])).run())")
    return subprocess.Popen(
        [sys.executable, "-I", "-c", code, str(APP), str(app_root / ".archhub-installing"),
         sys.executable, "-I", str(server), str(app_root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )


def _tool_names(reply):
    """Extract tool names from a tools/list response."""
    return [tool["name"] for tool in reply["result"]["tools"]]


def test_supervisor_hot_reloads_on_build_id_change_and_serves_new_tools_for_both_client_types(tmp_path):
    """Supervisor reloads on both marker and direct BUILD_ID/.archhub-ready updates for reactive and passive clients."""
    app_root = tmp_path / "app"
    app_root.mkdir()
    (app_root / "BUILD_ID").write_text("build-1\n", encoding="ascii")
    (app_root / "tools_spec.json").write_text(json.dumps(["tool_v1"]), encoding="utf-8")
    proc = _start_hot_supervisor(tmp_path, app_root)
    try:
        init = _qinit(proc)
        assert init["result"]["capabilities"]["tools"]["listChanged"] is True
        assert _tool_names(_qcall(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, 2)) == ["tool_v1"]
        pid1 = int(_qcall(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "tool_v1"}}, 3)["result"]["content"][0]["text"].split(":")[1])

        # Type A client (honors notifications/tools/list_changed) via .archhub-installing + BUILD_ID.
        (app_root / ".archhub-installing").write_text("build-2", encoding="ascii")
        assert _pid_exited(pid1)
        (app_root / "tools_spec.json").write_text(json.dumps(["tool_v1", "tool_v2"]), encoding="utf-8")
        (app_root / "BUILD_ID").write_text("build-2\n", encoding="ascii")
        (app_root / ".archhub-installing").unlink()
        note, _ = _read_until(proc, lambda m: m.get("method") == "notifications/tools/list_changed")
        assert note["method"] == "notifications/tools/list_changed"
        assert _tool_names(_qcall(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, 4)) == ["tool_v1", "tool_v2"]
        pid2 = int(_qcall(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                 "params": {"name": "tool_v2"}}, 5)["result"]["content"][0]["text"].split(":")[1])
        assert pid2 != pid1

        # Type B client (ignores notifications/tools/list_changed) on direct BUILD_ID update without .archhub-installing.
        (app_root / "tools_spec.json").write_text(json.dumps(["tool_v1", "tool_v2", "tool_v3"]), encoding="utf-8")
        (app_root / "BUILD_ID").write_text("build-3\n", encoding="ascii")
        listed = _qcall(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/list"}, 6)
        assert "result" in listed and _tool_names(listed) == ["tool_v1", "tool_v2", "tool_v3"]
        called = _qcall(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "tool_v3"}}, 7)
        assert "result" in called
        pid3 = int(called["result"]["content"][0]["text"].split(":")[1])
        assert pid3 != pid2 and _pid_exited(pid2)

        # Generation change via .archhub-ready after BUILD_ID was already written.
        (app_root / "tools_spec.json").write_text(
            json.dumps(["tool_v1", "tool_v2", "tool_v3", "tool_v4"]), encoding="utf-8")
        (app_root / ".archhub-ready").write_text("venv-v1:build-3:abc\n", encoding="ascii")
        _read_until(proc, lambda m: m.get("method") == "notifications/tools/list_changed")
        listed4 = _qcall(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/list"}, 8)
        assert _tool_names(listed4) == ["tool_v1", "tool_v2", "tool_v3", "tool_v4"]
        assert _pid_exited(pid3)
    finally:
        _stop_proc(proc)


def test_supervised_native_agent_mcp_exits_for_supervisor_respawn_on_build_change(tmp_path):
    """Even under an older supervisor without BUILD_ID watching, native_agent_mcp exits when idle on BUILD_ID change."""
    import shutil
    app_root = tmp_path / "app"
    shutil.copytree(APP / "nodelang", app_root / "nodelang",
                    ignore=shutil.ignore_patterns("__pycache__", "studio", "*.pyc"))
    (app_root / "BUILD_ID").write_text("build-1\n", encoding="ascii")
    try:
        old_supervisor_src = subprocess.run(
            ["git", "show", "a9ce4a95:01.APP/nodelang/mcp_supervisor.py"],
            cwd=APP.parent, capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        old_supervisor_src = (APP / "nodelang" / "mcp_supervisor.py").read_bytes()
    old_supervisor = tmp_path / "old_mcp_supervisor.py"
    old_supervisor.write_bytes(old_supervisor_src)
    env = dict(_isolated_env(tmp_path), ARCHHUB_MCP_SUPERVISED="1")
    loader = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
              "runpy.run_module('nodelang.native_agent_mcp',run_name='__main__')")
    child_cmd = [sys.executable, "-I", "-B", "-c", loader, str(app_root)]
    load = ("import importlib.util,os,sys;from pathlib import Path;"
            "s=importlib.util.spec_from_file_location('old_sup',sys.argv[1]);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "sys.exit(m.Supervisor(sys.argv[3:],dict(os.environ),sys.stdin.buffer,"
            "sys.stdout.buffer,pause=Path(sys.argv[2])).run())")
    proc = subprocess.Popen(
        [sys.executable, "-I", "-c", load, str(old_supervisor), str(app_root / ".archhub-installing"), *child_cmd],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
    )
    try:
        _qinit(proc)
        before = _qcall(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, 2)
        assert "result" in before and before["result"]["tools"]
        # Update BUILD_ID while .archhub-installing and .archhub-ready are both absent.
        (app_root / "BUILD_ID").write_text("build-2\n", encoding="ascii")
        note, _ = _read_until(proc, lambda m: m.get("method") == "notifications/tools/list_changed", timeout=15)
        assert note["method"] == "notifications/tools/list_changed"
        after = _qcall(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, 3)
        assert "result" in after and after["result"]["tools"]
    finally:
        _stop_proc(proc)