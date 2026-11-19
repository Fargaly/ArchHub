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