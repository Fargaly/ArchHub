"""Court: the native MCP updates itself without the client reconnecting (founder order 2026-09-30).

After an install, agents' native MCP processes kept running day-old code until
someone reconnected them by hand. The client now talks to a stable launcher that
runs the native owner as a worker. On a new BUILD_ID, while nothing is in flight
or uncertain, the same actor moves to a worker running the new code; the client's
pipes and process never change, and nothing it sent is replayed.

Part 1 drives the real launcher over real OS pipes against a scripted worker (a
subprocess speaking the same newline-delimited JSON-RPC), so every swap, deferral
and non-replay is observable. Part 2 runs the real application server: the
worker's handoff release, then the same actor continued by a new worker.
"""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

import pytest

from nodelang import native_mcp_launcher as launcher_module
from nodelang.native_mcp_launcher import HANDOFF_TOOL, Launcher

ACTOR = "app:agent-session:runtime:" + "a" * 32

WORKER = r'''
import json, os, sys, threading
state_path, log_path, release_path = os.environ["FAKE_STATE"], os.environ["FAKE_LOG"], os.environ["FAKE_RELEASE"]
if os.path.exists(os.environ["FAKE_REFUSE"]):
    # A refused first connection, as the real owner reports it, then the process ends.
    sys.stderr.write("nodelang.application_machine_transport.MachineResponseError: runtime Agent Session identity is already bound; renew it instead\n")
    sys.stderr.flush()
    sys.exit(1)
pid, args = os.getpid(), sys.argv[1:]
lock = threading.Lock()
def log(message):
    with lock, open(log_path, "a", encoding="utf-8") as out:
        out.write(json.dumps({"pid": pid, "args": args, "message": message}) + "\n")
def reply(ident, result):
    with lock:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}) + "\n")
        sys.stdout.flush()
def text(value):
    return {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
def owner():
    with open(state_path, encoding="utf-8") as source:
        return json.load(source)
def call(ident, name):
    if name == "slow":
        while not os.path.exists(release_path):
            threading.Event().wait(0.05)
        return reply(ident, text({"pid": pid}))
    if name == "native.owner_status":
        return reply(ident, text(owner()))
    if name == "native.owner_inspect_effects":
        return reply(ident, text({"effects": {"pending_permits": owner().get("permits", []), "truncated": False}}))
    if name == "native.handoff_release":
        return reply(ident, text({"released": True, "agent_session": owner()["agent_session"]}))
    return reply(ident, text({"pid": pid, "args": args}))
for line in sys.stdin:
    message = json.loads(line)
    log(message)
    method, ident = message.get("method"), message.get("id")
    if method == "initialize":
        reply(ident, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": True}},
                      "serverInfo": {"name": "worker", "version": str(pid)}})
    elif method == "tools/list":
        reply(ident, {"tools": [{"name": n} for n in ("native.owner_status", "native.handoff_release", "echo", "slow")]})
    elif method == "tools/call":
        threading.Thread(target=call, args=(ident, message["params"]["name"]), daemon=True).start()
'''


def _owner(**changes):
    same = {"instance_digest": "i" * 64}
    return {"state": "bound", "agent_session": ACTOR, "rebind_pending": False, "failed_attempt": None,
            "current_error": None, "pinned": {**same, "runtime_id": "r1", "fingerprint": "f" * 64},
            "current": {**same, "runtime_id": "r1", "fingerprint": "f" * 64}, **changes}


class Client:
    """The MCP client's side of real OS pipes, with the launcher serving the other side."""

    def __init__(self, tmp_path, owner, refuse=False):
        self.install = tmp_path / "install"
        self.install.mkdir()
        (self.install / "BUILD_ID").write_text("build-1", encoding="utf-8")
        self.state, self.log, self.release = tmp_path / "owner.json", tmp_path / "worker.log", tmp_path / "release"
        self.refuse = tmp_path / "refuse"
        if refuse:
            self.refuse.write_text("refuse", encoding="utf-8")
        self.set_owner(owner)
        script = tmp_path / "worker.py"
        script.write_text(WORKER, encoding="utf-8")
        to_launcher_r, to_launcher_w = os.pipe()
        from_launcher_r, from_launcher_w = os.pipe()
        self._send = os.fdopen(to_launcher_w, "wb")
        self._recv = os.fdopen(from_launcher_r, "rb")
        env = dict(os.environ, FAKE_STATE=str(self.state), FAKE_LOG=str(self.log), FAKE_RELEASE=str(self.release),
                   FAKE_REFUSE=str(self.refuse))
        self.launcher = Launcher(self.install, client_in=os.fdopen(to_launcher_r, "rb"),
                                 client_out=os.fdopen(from_launcher_w, "wb"),
                                 worker_argv=lambda extra: [sys.executable, str(script), *extra],
                                 check_seconds=0.1, environment=env)
        self.thread = threading.Thread(target=self.launcher.serve, daemon=True)
        self.thread.start()
        self.inbox = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.next_id = 0

    def set_owner(self, owner):
        self.state.write_text(json.dumps(owner), encoding="utf-8")

    def _read(self):
        for raw in iter(self._recv.readline, b""):
            self.inbox.put(json.loads(raw))

    def send(self, message):
        self._send.write(json.dumps(message).encode() + b"\n")
        self._send.flush()

    def request(self, method, params=None, *, wait=True):
        self.next_id += 1
        ident = self.next_id
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        return self.answer(ident) if wait else ident

    def answer(self, ident, timeout=20.0):
        deadline = time.monotonic() + timeout
        held = []
        try:
            while time.monotonic() < deadline:
                try:
                    message = self.inbox.get(timeout=0.1)
                except queue.Empty:
                    continue
                if message.get("id") == ident:
                    return message
                held.append(message)
        finally:
            for message in held:
                self.inbox.put(message)
        raise AssertionError("no answer to %s" % ident)

    def notification(self, method, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            if message.get("method") == method:
                return message
            self.inbox.put(message)
            time.sleep(0.02)
        raise AssertionError("no %s" % method)

    def tool(self, name, **arguments):
        answer = self.request("tools/call", {"name": name, "arguments": arguments})
        return json.loads(answer["result"]["content"][0]["text"])

    def start(self):
        assert "result" in self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                       "clientInfo": {"name": "court", "version": "1"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def worker_messages(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def close(self):
        self._send.close()
        self.thread.join(timeout=20)


@pytest.fixture
def client(tmp_path):
    made = Client(tmp_path, _owner())
    try:
        yield made
    finally:
        made.close()


def test_an_idle_owner_moves_to_new_code_as_the_same_actor_on_the_same_pipes(client):
    client.start()
    names = [tool["name"] for tool in client.request("tools/list")["result"]["tools"]]
    assert HANDOFF_TOOL not in names and "echo" in names          # the handoff is never the agent's
    before = client.tool("echo")
    (client.install / "BUILD_ID").write_text("build-2", encoding="utf-8")
    client.notification("notifications/tools/list_changed")
    after = client.tool("echo")
    assert after["pid"] != before["pid"] and after["args"] == ["--expected-actor", ACTOR]
    status = client.tool("native.owner_status")["self_update"]
    assert (status["state"], status["build"], status["swaps"]) == ("current", "build-2", 1)
    refused = client.request("tools/call", {"name": HANDOFF_TOOL, "arguments": {}})
    assert refused["error"]["message"] == "Unknown tool"
    # Nothing the client sent before the swap reached the new worker; it saw only
    # the launcher's private replay of initialize.
    new = [row["message"] for row in client.worker_messages() if row["pid"] == after["pid"]]
    assert new[0]["method"] == "initialize" and str(new[0]["id"]).startswith("archhub-launcher:")
    assert not any(message.get("id") in (1, 2, 3) for message in new)
    old = [row["message"] for row in client.worker_messages() if row["pid"] == before["pid"]]
    assert any((message.get("params") or {}).get("name") == HANDOFF_TOOL for message in old)


def test_a_call_in_flight_defers_the_update_and_is_never_replayed(client):
    client.start()
    first = client.tool("echo")["pid"]
    slow = client.request("tools/call", {"name": "slow", "arguments": {}}, wait=False)
    (client.install / "BUILD_ID").write_text("build-2", encoding="utf-8")
    time.sleep(1.0)
    assert client.launcher.status["state"] == "deferred"
    assert client.launcher.status["reason"] == "a call is in flight"
    assert client.launcher.status["swaps"] == 0
    client.release.write_text("go", encoding="utf-8")
    assert json.loads(client.answer(slow)["result"]["content"][0]["text"])["pid"] == first   # the old code answered it
    client.notification("notifications/tools/list_changed")
    second = client.tool("echo")["pid"]
    assert second != first
    assert not any((row["message"].get("params") or {}).get("name") == "slow"
                   for row in client.worker_messages() if row["pid"] == second)


def test_an_uncertain_owner_defers_and_says_why(client):
    client.start()
    first = client.tool("echo")["pid"]
    client.set_owner(_owner(failed_attempt={"kind": "rebind", "request_sent": True}))
    (client.install / "BUILD_ID").write_text("build-2", encoding="utf-8")
    time.sleep(1.0)
    status = client.tool("native.owner_status")["self_update"]
    assert status["state"] == "deferred" and "unresolved" in status["reason"]
    assert client.tool("echo")["pid"] == first
    client.set_owner(_owner(permits=[{"permit": "p1"}]))
    time.sleep(1.0)
    assert "permit is unresolved" in client.launcher.status["reason"] and client.tool("echo")["pid"] == first
    client.set_owner(_owner())
    client.notification("notifications/tools/list_changed")
    assert client.tool("echo")["pid"] != first


def test_after_an_application_restart_no_release_is_needed(client):
    """The old capability ended with the old application: continue without a release."""
    client.start()
    first = client.tool("echo")["pid"]
    client.set_owner(_owner(current={"instance_digest": "i" * 64, "runtime_id": "r2", "fingerprint": "e" * 64}))
    (client.install / "BUILD_ID").write_text("build-2", encoding="utf-8")
    client.notification("notifications/tools/list_changed")
    assert client.tool("echo")["pid"] != first
    old = [row["message"] for row in client.worker_messages() if row["pid"] == first]
    assert not any((message.get("params") or {}).get("name") == HANDOFF_TOOL for message in old)


def test_a_refused_start_never_ends_the_connection_and_the_next_call_connects(tmp_path):
    """Live 1cefae13: the owner's first connection was refused ("already bound"), the
    owner exited, and the whole connector died with it while the client still showed
    it connected. The host now stays, says why, and the next call connects."""
    client = Client(tmp_path, _owner(), refuse=True)
    try:
        answer = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "court", "version": "1"}})
        assert answer["result"]["capabilities"]["tools"]["listChanged"] is True
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = [tool["name"] for tool in client.request("tools/list")["result"]["tools"]]
        assert listed == ["native.owner_status"]
        refused = client.request("tools/call", {"name": "echo", "arguments": {}})["result"]
        why = json.loads(refused["content"][0]["text"])
        assert refused["isError"] is True and why["connected"] is False
        assert "already bound" in why["reason"] and "next call" in why["next"]
        assert client.thread.is_alive()                            # the connection never ended
        client.refuse.unlink()
        after = client.tool("echo")                                # the next call starts a new owner
        client.notification("notifications/tools/list_changed")
        assert client.thread.is_alive() and client.launcher._down is None
        new = [row["message"] for row in client.worker_messages() if row["pid"] == after["pid"]]
        assert new[0]["method"] == "initialize" and str(new[0]["id"]).startswith("archhub-launcher:")
    finally:
        client.close()


def test_an_owner_that_dies_mid_session_is_replaced_on_the_next_call(client):
    import signal
    client.start()
    first = client.tool("echo")["pid"]
    os.kill(first, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while client.launcher._worker.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)                                                # its output has closed
    after = client.tool("echo")
    client.notification("notifications/tools/list_changed")
    assert after["pid"] != first and client.thread.is_alive()


def test_the_native_entry_points_become_the_launcher_unless_they_are_its_worker(monkeypatch):
    import inspect
    from nodelang import clean_coordination_mcp, native_agent_mcp
    for module, name in ((native_agent_mcp, "nodelang.native_agent_mcp"),
                         (clean_coordination_mcp, "nodelang.clean_coordination_mcp")):
        source = inspect.getsource(module).replace("\r\n", "\n")
        entry = source[source.rindex('if __name__ == "__main__":'):]
        assert 'run_entry("%s", main)' % name in entry, module.__name__
    launched, ran = [], []
    monkeypatch.setattr(launcher_module, "launch", launched.append)
    monkeypatch.delenv(launcher_module.LAUNCHER_ENV, raising=False)
    launcher_module.run_entry("nodelang.native_agent_mcp", lambda: ran.append("worker"))
    assert launched == ["nodelang.native_agent_mcp"] and ran == []      # the client's process: the launcher
    monkeypatch.setenv(launcher_module.LAUNCHER_ENV, "1")
    launcher_module.run_entry("nodelang.native_agent_mcp", lambda: ran.append("worker"))
    assert ran == ["worker"] and launched == ["nodelang.native_agent_mcp"]   # its worker: the owner itself
    assert launcher_module.installed_build(Path(launcher_module.__file__).parents[1] / "no-such-install") == ""


def test_the_worker_hands_its_actor_to_new_code(tmp_path, monkeypatch):
    """Part 2, the real application: release, then the same actor continued by a new worker."""
    from nodelang import native_agent_mcp as mcp
    from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
    from nodelang.native_agent_session import NativeAgentSession
    from tests_replica.test_native_inbox_recovery import KEY, World, _start

    template = tmp_path / "template"
    template.mkdir()
    _start(template).close()
    world = World(template, tmp_path / "app")
    try:
        monkeypatch.setenv(launcher_module.LAUNCHER_ENV, "1")
        owner, _control = world.owner("court-launcher")
        actor = owner.owner_status()["agent_session"]
        tools = {tool.name: tool.fn for tool in mcp.build_server(session=owner)._tool_manager.list_tools()}
        calls = []

        class Counted(UniversalRuntimeClient):
            def bind_agent_session(self, **kwargs):
                calls.append(kwargs.get("expected_agent_session"))
                return super().bind_agent_session(**kwargs)

        def new_worker():
            fresh = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": "court-launcher"},
                                       descriptor_path=world.root / "runtime.json", key_provider=KEY,
                                       client_factory=Counted, expected_agent_session=actor)
            return fresh, mcp.build_recovery_server(fresh)[1]

        # While the old worker still holds the capability, new code cannot take the actor.
        early, activate = new_worker()
        assert activate()["status"] == "recovery_required" and calls == [actor]
        released = tools[HANDOFF_TOOL]()
        assert released["released"] is True and released["agent_session"] == actor
        fresh, activate = new_worker()
        assert activate()["status"] == "tools_available"
        assert fresh.owner_status()["agent_session"] == actor and fresh._continued is True
        assert calls == [actor, actor]                          # conditional only, never a new enrollment
        with fresh.bound_client() as client:
            assert client.agent_session_root == actor
        with pytest.raises(MachineTransportError):
            owner.require_client()                               # the old worker holds nothing now
    finally:
        world.close()
