"""Round3 real-owner mailbox courts; synthetic state only."""
import os
from unittest.mock import patch
import pytest
from nodelang.application_machine_transport import MachineResponseError

@pytest.fixture(scope="module")
def mailbox_owner(tmp_path_factory):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    from nodelang.application_machine_transport import UniversalRuntimeClient
    root = tmp_path_factory.mktemp("mailbox-round3")
    environment = {key: str(root) for key in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "HOME", "USERPROFILE")}
    with patch.dict(os.environ, environment):
        local = root / "ArchHub"
        provider = WindowsDpapiSigningKeyProvider(local / "keys/authority-signing-v1.dpapi.json")
        provider.current("archhub.local.universal-runtime-pipe")
        workspace = root / "project"; workspace.mkdir()
        app = ApplicationServer(enable_machine_transport=True, machine_key_provider=provider,
            machine_descriptor_path=local / "active-universal-runtime.json",
            universal_workspace_root=workspace, universal_state_path=root / "graph.sqlite3").start()
        try:
            app.round3_client = UniversalRuntimeClient(local / "active-universal-runtime.json", provider)
            yield app, app.round3_client
        finally:
            app.close()

def call(app, peer, method, body):
    with patch("nodelang.application_machine_transport._read_windows_pipe_peer", return_value=peer):
        return app.round3_client.request("POST" if method == "send" else "GET",
            "/api/universal/agent-mail/" + method, body)

def test_recent_peers_exclude_app_and_old_first_page(mailbox_owner):
    from nodelang.application_machine_transport import MachinePipePeer
    from nodelang.conversation_content import read_content_binding
    from nodelang.baboom_agent_link import list_agents
    app, _ = mailbox_owner
    old = MachinePipePeer(70001, 1700000001, cwd=str(app.universal_workspace_root))
    recent = MachinePipePeer(70002, 1700000002, cwd=str(app.universal_workspace_root))
    call(app, old, "send", {"to": "*", "text": "old"})
    registry = app.universal_registry
    with app.mutation_lock:
        binding = read_content_binding(app.universal_store.snapshot(), registry.deliberation_protocol,
            application_root=registry.application_root, space_root=registry.workshop_root)
        history = app.conversation_content._history_for(binding)
        for index in range(105):
            history.append(registry.workshop_root, author="fixture:old", content="old %s" % index,
                category=registry.workshop_category_roots["note"], idempotency_key="round3-%s" % index)
    sent = call(app, recent, "send", {"to": "*", "text": "recent", "context": {"threadId": "current-session"}})
    call(app, recent, "send", {"to": "*", "text": "latest", "context": {"threadId": "current-session"}})
    app.shared_agent_mail("send", {"to": "*", "text": "builtin"})
    revision = app.universal_store.revision
    peers = app.shared_agent_mail("read", {"since":0})["peers"]
    agents = [{"session_root":row["label"], **row} for row in peers]
    assert [row["session_root"] for row in agents] == [sent["sender_label"]]
    assert agents[0]["sender_key"] == sent["sender_key"]
    assert list_agents(mailbox=app.shared_agent_mail) == []  # fixture peer has no live declaration
    assert app.universal_store.revision == revision

def test_runtime_labels_survive_connector_restart_without_forgery(mailbox_owner):
    from nodelang.application_machine_transport import MachinePipePeer
    app, _ = mailbox_owner
    context = {"threadId": "session-round3"}
    before = call(app, MachinePipePeer(71001, 1700000011, cwd="C:/work/Villas"), "read", {"since": 0, "context": context})
    after = call(app, MachinePipePeer(71002, 1700000012, cwd="C:/work/Villas"), "read", {"since": 0, "context": context})
    other = call(app, MachinePipePeer(71003, 1700000013, cwd="C:/work/Villas"), "read", {"since": 0, "context": {"threadId": "other-session"}})
    assert before["sender_key"] != after["sender_key"]
    assert before["sender_label"] == after["sender_label"]
    assert before["sender_label"].startswith("Codex / Villas / ")
    assert other["sender_label"] != before["sender_label"]
    sent = call(app, MachinePipePeer(71004, 1700000014), "send", {"to": before["sender_label"], "text": "stable address"})
    assert sent["to"] == after["sender_label"]
    with pytest.raises(MachineResponseError, match="arguments are invalid"):
        call(app, MachinePipePeer(71005, 1700000015), "send", {"to": "*", "text": "forged", "sender_label": before["sender_label"]})

def test_pipe_calls_use_verified_scope_and_checkpoint(mailbox_owner, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_authorization import AuthorizationDenied
    app, client = mailbox_owner
    seen = []
    original = ApplicationServer._dispatch_verified_machine_route_scoped
    def observe(owner, request):
        seen.append(request["path"])
        return original(owner, request)
    monkeypatch.setattr(ApplicationServer, "_dispatch_verified_machine_route_scoped", observe)
    baseline = client.request("GET", "/api/universal/agent-mail/read", {"since": 0})
    assert seen == ["/api/universal/agent-mail/read"]
    revision = app.universal_store.revision
    class BrokenCheckpoint:
        def require_healthy(self): raise AuthorizationDenied("round3 checkpoint refused")
    with monkeypatch.context() as changes:
        changes.setattr(app, "universal_checkpoint_guard", BrokenCheckpoint())
        for method, path, body in [("POST", "send", {"to": "*", "text": "must refuse"}), ("GET", "read", {"since": 0})]:
            with pytest.raises(Exception, match="checkpoint refused"):
                client.request(method, "/api/universal/agent-mail/" + path, body)
    def deny_route(*args, **kwargs): raise AuthorizationDenied("round3 route scope refused")
    with monkeypatch.context() as changes:
        changes.setattr(app, "require_universal_http_route", deny_route)
        with pytest.raises(Exception, match="route scope refused"):
            client.request("POST", "/api/universal/agent-mail/send", {"to": "*", "text": "must refuse"})
    assert client.request("GET", "/api/universal/agent-mail/read", {"since": 0})["messages"] == baseline["messages"]
    assert app.universal_store.revision == revision
    with pytest.raises(MachineResponseError, match="authenticated local pipe"):
        call(app, None, "send", {"to": "*", "text": "no peer"})

def test_quota_counts_os_peer_not_metadata_and_reads_still_work(mailbox_owner, monkeypatch):
    from nodelang import installed_workshop_coordination as mailbox
    from nodelang.application_machine_transport import MachinePipePeer
    app, _ = mailbox_owner
    clock = [100.0]
    monkeypatch.setattr(mailbox, "_mailbox_now", lambda: clock[0], raising=False)
    peer = MachinePipePeer(72001, 1700000021)
    for index in range(30):
        call(app, peer, "send", {"to": "*", "text": "quota %s" % index})
    with pytest.raises(Exception, match="30 messages per minute"):
        call(app, peer, "send", {"to": "*", "text": "31", "context": {"threadId": "rotated"}})
    call(app, peer, "read", {"since": 0})
    call(app, MachinePipePeer(72002, 1700000022), "send", {"to": "*", "text": "independent"})
    clock[0] += 60
    call(app, peer, "send", {"to": "*", "text": "new window"})


def test_node_cli_uses_registry_label_and_missing_observer_is_harmless(monkeypatch):
    import sys
    import psutil
    from nodelang.agent_runtime_registry import mailbox_label, _observed_runtime
    from nodelang.application_machine_transport import MachinePipePeer
    class NodeCli:
        def create_time(self): return 1700000031
        def name(self): return "node.exe"
        def cmdline(self): return ["node.exe", "C:/modules/@anthropic-ai/claude-code/cli.js"]
        def parent(self): return None
    peer = MachinePipePeer(73001, 1700000031, cwd="C:/work/Villas")
    _observed_runtime.cache_clear()
    monkeypatch.setattr(psutil, "Process", lambda _pid: NodeCli())
    assert mailbox_label(peer, {})[0] == "Claude Code / Villas / project"
    _observed_runtime.cache_clear()
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert mailbox_label(peer, {})[0] == "Agent / Villas / project"
    _observed_runtime.cache_clear()


def test_disappearing_parent_does_not_fail_message_label(monkeypatch):
    import psutil
    from nodelang.agent_runtime_registry import mailbox_label, _observed_runtime
    from nodelang.application_machine_transport import MachinePipePeer
    class Parent:
        def name(self): return "python.exe"
        def parent(self): return None
    class Connector(Parent):
        calls = 0
        def create_time(self): return 1700000041
        def parent(self):
            self.calls += 1
            return Parent() if self.calls == 1 else None
    connector = Connector()
    _observed_runtime.cache_clear()
    monkeypatch.setattr(psutil, "Process", lambda _pid: connector)
    label, runtime = mailbox_label(MachinePipePeer(74001, 1700000041, cwd="C:/work/Villas"), {})
    assert label == "Agent / Villas / project" and runtime == "mcp"
    _observed_runtime.cache_clear()
