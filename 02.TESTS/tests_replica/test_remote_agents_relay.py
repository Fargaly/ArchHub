"""A claimed remote call is gated here, and the caller joins the Workshop by name.

The cloud queues host-effect and workshop-call rows. This PC claims them on the
existing outbound relay. host.exec passes hook_decision.decide() before any
engine runs. A Workshop send is stored as mcp-<client> and a later read of that
mailbox sees the addressed line.

Run: python -m pytest 02.TESTS/tests_replica/test_remote_agents_relay.py -q
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nodelang.cloud_relay import CloudRelay, McpWorkshopAgents


class _Cloud(BaseHTTPRequestHandler):
    tasks, claims, results = [], [], []

    def log_message(self, *_a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/agent-tasks/claim"):
            _Cloud.claims.append(json.loads(raw))
            return self._json({"ok": True, "task": _Cloud.tasks.pop(0) if _Cloud.tasks else None})
        if self.path.endswith("/result"):
            _Cloud.results.append(json.loads(raw))
            return self._json({"ok": True})
        return self._json({"ok": False})


@pytest.fixture
def cloud():
    for held in (_Cloud.tasks, _Cloud.claims, _Cloud.results):
        held[:] = []
    server = HTTPServer(("127.0.0.1", 0), _Cloud)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_port
    server.shutdown()
    server.server_close()


def _env(root, mode):
    """Permissions and hook trace stay in this test directory."""
    settings = root / "ArchHub" / "settings"
    settings.mkdir(parents=True)
    (settings / "permissions.json").write_text(json.dumps({
        "runMode": mode, "tools": {},
    }), encoding="utf-8")
    hook = root / "hook-decision"
    hook.mkdir()
    (root / "tmp").mkdir()
    return {
        "LOCALAPPDATA": str(root),
        "USERPROFILE": str(root),
        "HOME": str(root),
        "TEMP": str(root / "tmp"),
        "TMP": str(root / "tmp"),
        "ARCHHUB_HOOK_STATE": str(hook),
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
    }


def _relay(base, root, mode, **kw):
    return CloudRelay(
        base_url=base, token="t",
        respond=lambda utterance: {},
        execute=lambda utterance: {},
        environment=_env(root, mode),
        **kw,
    )


def _effect(tool="host.exec", args=None):
    return json.dumps({"tool": tool, "args": {} if args is None else args})


def test_a_claimed_host_exec_is_held_while_ask_first(cloud, tmp_path):
    ran = []
    _Cloud.tasks[:] = [{"id": "ask", "kind": "host-effect", "directive": _effect(
        args={"engine": "revit.info", "params": {}})}]
    out = _relay(cloud, tmp_path, "Ask first",
                 host_effect=lambda tool, args: ran.append((tool, args)) or {"ok": True}).poll_once()
    assert out["ok"] is True and ran == []
    body = json.loads(_Cloud.results[-1]["result"])
    assert body["held"] is True and body["verdict"] == "ask" and body["ran"] is False
    assert body["tool"] == "host.exec"


def test_a_claimed_host_exec_runs_when_accept_edits(cloud, tmp_path):
    ran = []
    _Cloud.tasks[:] = [{"id": "allow", "kind": "host-effect", "directive": _effect(
        args={"engine": "revit.info", "params": {"view": "plan"}})}]
    out = _relay(cloud, tmp_path, "Accept edits",
                 host_effect=lambda tool, args: ran.append((tool, dict(args))) or {"ok": True, "ran": True}).poll_once()
    assert out["ok"] is True
    assert ran == [("host.exec", {"engine": "revit.info", "params": {"view": "plan"}})]
    assert json.loads(_Cloud.results[-1]["result"])["ran"] is True


def test_a_claimed_host_exec_refuses_client_data(cloud, tmp_path):
    ran = []
    _Cloud.tasks[:] = [{"id": "priv", "kind": "host-effect", "directive": _effect(
        args={"engine": "revit.info", "params": {"path": r"D:\20.CLIENTS\plan.rvt"}})}]
    out = _relay(cloud, tmp_path, "Accept edits",
                 host_effect=lambda tool, args: ran.append(tool) or {"ok": True}).poll_once()
    assert out["ok"] is False and ran == []
    assert "client-data-going-public" in out["result"]
    assert _Cloud.results[-1]["ok"] is False


def test_a_remote_agent_appears_as_mcp_client_and_its_send_is_readable(cloud, tmp_path):
    mailbox = tmp_path / "workshop" / "messages.sqlite3"
    mailbox.parent.mkdir()
    agents = McpWorkshopAgents(tmp_path / "relay-descriptor.json", None, mailbox_path=mailbox)
    home = tmp_path / "env"
    send = {
        "agent": {"client_id": "notion-1", "client_name": "Notion"},
        "method": "send_message",
        "params": {"id": "sess-9", "text": "hello from notion"},
    }
    _Cloud.tasks[:] = [{"id": "send", "kind": "workshop-call", "directive": json.dumps(send)}]
    relay = _relay(cloud, home, "Accept edits", workshop_caller=agents.call)
    sent = relay.poll_once()
    assert sent["ok"] is True, sent
    posted = json.loads(_Cloud.results[-1]["result"])
    assert posted["agent_runtime"] == "mcp-notion"
    assert posted["to"] == "sess-9"

    read = {
        "agent": {"client_id": "notion-1", "client_name": "Notion"},
        "method": "read_messages",
        "params": {"since": 0},
    }
    _Cloud.tasks[:] = [{"id": "read", "kind": "workshop-call", "directive": json.dumps(read)}]
    got = relay.poll_once()
    assert got["ok"] is True, got
    body = json.loads(_Cloud.results[-1]["result"])
    assert body["agent_runtime"] == "mcp-notion"
    texts = [message.get("content", "") for message in body.get("messages", [])]
    assert any("To sess-9:" in text and "hello from notion" in text for text in texts)
    authors = [message.get("author", "") for message in body.get("messages", [])]
    peers = [peer.get("runtime", "") for peer in body.get("peers", [])]
    assert any(author.startswith("mcp-notion") for author in authors)
    assert "mcp-notion" in peers


def test_the_idle_poll_and_one_effect_round_trip(cloud, tmp_path):
    """One empty claim, the 4 s gap, then one host.exec. The round trip stays under 5 s."""
    ran = []
    relay = _relay(cloud, tmp_path, "Accept edits",
                   host_effect=lambda tool, args: ran.append(tool) or {"ok": True, "label": "ran"})
    try:
        import psutil
        proc = psutil.Process()
        proc.cpu_percent(interval=None)
    except Exception:
        proc = None
    started = time.perf_counter()
    assert relay.poll_once() is None
    time.sleep(4)
    idle_s = time.perf_counter() - started
    cpu = proc.cpu_percent(interval=None) if proc is not None else None
    rss = proc.memory_info().rss if proc is not None else 0
    _Cloud.tasks[:] = [{"id": "rtt", "kind": "host-effect", "directive": _effect(
        args={"engine": "noop", "params": {}})}]
    tick = time.perf_counter()
    out = relay.poll_once()
    rtt = time.perf_counter() - tick
    print("RELAY idle_s=%.3f cpu_percent=%.2f rss_mb=%.1f rtt_s=%.3f" % (
        idle_s, -1 if cpu is None else cpu, rss / 1048576, rtt))
    assert out["ok"] is True and ran == ["host.exec"]
    assert rtt < 5
    assert 4 <= idle_s < 8
    if cpu is not None:
        assert cpu < 50
