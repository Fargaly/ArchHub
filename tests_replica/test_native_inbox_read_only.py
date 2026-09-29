"""Court: an agent keeps reading its own inbox after the application restarts.

Live session 717 (2026-09-28): after an owner change, reads failed with "native
agent client or owner binding changed" while rebind stayed refused because one
expired permit had no receipt. Reads must survive; writes stay refused.
Real application server on a persistent scratch graph, real native owner and
MCP control; nothing is substituted.
"""
import hashlib
import shutil
import time

import pytest

from nodelang import cell_cde_authority as cde
from nodelang import commit_intent
from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_protocols import compose_relation_cells, prepare_append_relation_member
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.installed_workshop_coordination import InstalledWorkshopCoordinationClient
from nodelang.native_agent_mcp import _OwnedWorkshopClient
from nodelang.native_agent_session import NativeAgentSession

KEY = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"n" * 32)


def _start(root):
    (root / "ws").mkdir(exist_ok=True)
    return ApplicationServer(
        enable_machine_transport=True, machine_descriptor_path=root / "runtime.json",
        machine_key_provider=KEY, universal_workspace_root=root / "ws",
        universal_state_path=root / "graph.sqlite3").start()


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("inbox-read-template")
    _start(root).close()
    return root


class World:
    def __init__(self, template, root):
        shutil.copytree(template, root)
        self.root = root
        self.server = _start(root)

    def restart(self, root=None):
        self.server.close()
        self.server = _start(root or self.root)

    def owner(self, external="court-717"):
        owner = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": external},
                                   descriptor_path=self.root / "runtime.json", key_provider=KEY)
        return owner, _OwnedWorkshopClient(owner, owner.connect())

    def send(self, actor, text, key):
        peer = UniversalRuntimeClient(self.root / "runtime.json", KEY)
        peer.bind_agent_session(runtime="codex", external_session_id="court-peer-" + key)
        return InstalledWorkshopCoordinationClient(peer).call(
            "send_message", {"target": actor, "message": text, "idempotency_key": key})

    def legacy_permit(self, actor, name):
        """An expired graph-held permit with no receipt, as in the live graph."""
        store = self.server.universal_store
        protocol = self.server.universal_registry.cde_write_authority_protocol
        snap = store.snapshot()
        root = "court:legacy-cde-permit:" + name
        issued = time.time() - 120.0
        values = cde._permit_values(
            runtime="claude", agent_session_root=actor, work_root="court:work",
            container_root="court:container", container_id="GM.nodes.court",
            container_digest="a" * 64, operation="write_file", path="70.HANDOFFS/court/target.txt",
            content_digest=hashlib.sha256(b"x").hexdigest(), request_id="court-request-" + name,
            nonce="court-nonce-" + name, authority_revision=snap.revision,
            issued_at=issued, expires_at=issued + 60.0)
        terminals = [cde._terminal("%s:%s" % (root, key), value) for key, value in values.items()]
        envelope = cde._terminal(root + ":signature", "court legacy signature")
        relation = compose_relation_cells(
            tuple((protocol.role(key), "%s:%s" % (root, key)) for key in values)
            + ((protocol.role("signature-envelope"), envelope.id),
               (protocol.role("state"), protocol.states["active"])), relation_id=root)
        append = prepare_append_relation_member(
            snap, protocol.root_id, protocol.role("permit-member"), root, budget=100_000)
        with commit_intent.declare(commit_intent.MIGRATION, actor="court", reason="legacy permit fixture"):
            store.commit(snap.revision, create=(*terminals, envelope, *relation.cells, *append.create),
                         replace=tuple(append.replace))
        return root


@pytest.fixture
def world(template, tmp_path):
    made = World(template, tmp_path / "app")
    try:
        yield made
    finally:
        made.server.close()


def _messages(result):
    return [entry["summary"] for entry in result["entries"]]


def test_reads_survive_an_owner_change_while_writes_stay_blocked(world):
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    world.legacy_permit(actor, "717")
    world.send(actor, "please review the plan", "court-msg-1")
    world.restart()
    status = owner.owner_status()
    pinned, current = status["pinned"]["fingerprint"], status["current"]["fingerprint"]

    inbox = control.call("read_messages", {"limit": 20})
    assert "please review the plan" in _messages(inbox)
    assert inbox["access"] == "read-only" and inbox["agent_session"] == actor
    one = inbox["entries"][-1]
    assert control.call("read_message", {"message_id": one["message_id"],
                                         "sequence": one["sequence"]})["access"] == "read-only"

    with pytest.raises(MachineTransportError, match="effect reconciliation"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    with pytest.raises(MachineTransportError, match="not bound"):
        control.call("send_message", {"target": actor, "message": "x", "idempotency_key": "w1"})
    reader = owner.inbox_reader()
    with pytest.raises(MachineTransportError, match="Replies and file changes are paused"):
        reader.call("send_message", {"target": actor, "message": "x", "idempotency_key": "w1"})
    for method, path, body in (
            ("POST", "/api/universal/workshop", {
                "category": "note", "text": "x", "refs": [], "evidence": [], "recipients": [actor],
                "reply_to": None, "idempotency_key": "w2", "created_at": None}),
            ("POST", "/api/universal/cde-write-permit", {
                "operation": "write_file", "path": "70.HANDOFFS/court/target.txt",
                "content_digest": "b" * 64, "request_id": "r", "nonce": "n"})):
        with pytest.raises(MachineTransportError, match="read-only"):
            reader._client.request(method, path, body)
    # Reading stays available after the refused rebind left the owner uncertain.
    assert owner.state == "uncertain"
    assert "please review the plan" in _messages(control.call("read_messages", {"limit": 20}))


def test_foreign_actor_or_other_instance_cannot_read(world, tmp_path, template):
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    world.owner("court-other")
    world.restart()
    with pytest.raises(MachineTransportError, match="does not match expected actor"):
        UniversalRuntimeClient(world.root / "runtime.json", KEY).open_native_inbox_read(
            runtime="claude", external_session_id="court-other", expected_agent_session=actor)
    shutil.copytree(template, tmp_path / "elsewhere")
    world.restart(tmp_path / "elsewhere")
    shutil.copyfile(tmp_path / "elsewhere" / "runtime.json", world.root / "runtime.json")
    with pytest.raises(MachineTransportError, match="another application instance"):
        control.call("read_messages", {"limit": 5})


def test_recovery_server_reads_inbox_before_activation(monkeypatch):
    from types import SimpleNamespace as NS
    from nodelang import native_agent_mcp as mcp
    from nodelang.native_resume_guard import NativeResumeGuard
    calls = []
    reader = NS(call=lambda method, values: calls.append((method, values)) or {"access": "read-only"})
    owner = NS(owner_status=lambda: {"state": "uncertain"}, needs_inbox_recovery=lambda: True,
               inbox_reader=lambda: reader)
    monkeypatch.setattr(NativeResumeGuard, "recover", lambda self: {"status": "recovery_required"})
    server, activate = mcp.build_recovery_server(owner)
    assert activate()["status"] == "recovery_required"
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert tools["coordination.read_messages"].fn(limit=5)["access"] == "read-only"
    assert calls == [("read_messages", {"limit": 5, "before": None})]
    assert "coordination.send_message" not in tools


def _replayed_capability(world, reader):
    """A client on the current owner carrying a capability issued earlier."""
    old = reader._client
    stale = UniversalRuntimeClient(world.root / "runtime.json", KEY)
    stale.agent_session_root = old.agent_session_root
    stale._agent_session_token = old._agent_session_token
    stale._agent_session_capability_id = old._agent_session_capability_id
    stale._agent_session_expires_at = old._agent_session_expires_at
    stale._agent_session_access = "recovery-read"
    return stale


def test_owner_changed_twice_reads_continue_and_old_capability_dies(world):
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    world.legacy_permit(actor, "717")
    world.send(actor, "first message", "court-twice-1")
    world.restart()
    status = owner.owner_status()
    assert "first message" in _messages(control.call("read_messages", {"limit": 20}))
    earlier = owner.inbox_reader()
    space = earlier._descriptor.workshop_root
    with pytest.raises(MachineTransportError, match="effect reconciliation"):
        owner.rebind_owner(expected_old_owner=status["pinned"]["fingerprint"],
                           expected_new_owner=status["current"]["fingerprint"])
    world.restart()  # the owner changes a second time
    world.send(actor, "second message", "court-twice-2")
    inbox = control.call("read_messages", {"limit": 20})
    assert {"first message", "second message"} <= set(_messages(inbox))
    assert inbox["access"] == "read-only" and inbox["agent_session"] == actor
    assert owner.inbox_reader() is not earlier
    with pytest.raises(MachineTransportError, match="unknown"):
        _replayed_capability(world, earlier).request(
            "GET", "/api/universal/deliberation", {"space": space, "limit": 5})

    # The capability is pinned to the OS process that received it.
    current = owner.inbox_reader()
    held = world.server._machine_agent_recovery_capabilities[current._client._agent_session_capability_id]
    genuine = dict(held["enrollment_peer"])
    held["enrollment_peer"] = {**genuine, "pid": genuine["pid"] + 1}
    with pytest.raises(MachineTransportError, match="read-only"):
        current.call("read_messages", {"limit": 5})
    held["enrollment_peer"] = genuine
    assert "second message" in _messages(current.call("read_messages", {"limit": 20}))


def test_recovered_reads_see_only_what_the_actor_may_see(world):
    """Space reads run under the application context with the actor as principal
    (read_all is false, participation is required), exactly as the full session."""
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    other, _other_control = world.owner("court-other")
    other_actor = other.owner_status()["agent_session"]
    world.legacy_permit(actor, "717")
    world.send(actor, "for this agent", "court-private-1")
    world.send(other_actor, "private to the other agent", "court-private-2")
    before_restart = _messages(control.call("read_messages", {"limit": 50}))
    world.restart()
    inbox = control.call("read_messages", {"limit": 50})
    seen = _messages(inbox)
    assert inbox["access"] == "read-only"
    assert "for this agent" in seen
    assert "private to the other agent" not in seen
    assert seen == before_restart  # the same view the full session had, no wider


def test_a_recovered_reader_never_reads_an_older_ledger_space(tmp_path):
    """Ping BLOCK 2026-09-28: older graph-ledger spaces return every entry, for
    every recipient, under the application context. A recovered reader must be
    refused at the server, whatever client it uses."""
    import json
    from nodelang.cell_deliberation import read_deliberation_space
    descriptor = tmp_path / "legacy-runtime.json"
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                               machine_key_provider=KEY).start()
    try:
        space = server.universal_registry.workshop_root
        assert read_deliberation_space(server.universal_store.snapshot(),
            server.universal_registry.deliberation_protocol, space).content_store_root is None
        agent = UniversalRuntimeClient(descriptor, KEY)
        agent.bind_agent_session(runtime="claude", external_session_id="court-legacy-a")
        other = UniversalRuntimeClient(descriptor, KEY)
        other.bind_agent_session(runtime="claude", external_session_id="court-legacy-b")
        peer = UniversalRuntimeClient(descriptor, KEY)
        peer.bind_agent_session(runtime="codex", external_session_id="court-legacy-peer")
        peer.request("POST", "/api/universal/workshop", {
            "category": "note", "text": "private to the other agent", "refs": [], "evidence": [],
            "recipients": [other.agent_session_root], "reply_to": None,
            "idempotency_key": "court-legacy-1", "created_at": None})
        reader = UniversalRuntimeClient(descriptor, KEY)  # a raw client, no wrapper checks
        reader.open_native_inbox_read(runtime="claude", external_session_id="court-legacy-a",
                                      expected_agent_session=agent.agent_session_root)
        for path, body in (("/api/universal/deliberation", {"space": space, "limit": 50}),
                           ("/api/universal/workshop", {})):
            try:
                result = reader.request("GET", path, body)
            except MachineTransportError as exc:
                assert "older conversation" in str(exc)
            else:
                pytest.fail("%s returned the older space to a recovered reader; other recipient "
                            "visible: %s" % (path, "private to the other agent" in json.dumps(result)))
    finally:
        server.close()


def test_a_capability_retired_after_admission_is_denied_not_passed(tmp_path, monkeypatch):
    """Ping BLOCK on v3: a capability retired between admission and projection
    made the legacy guard pass. An absent binding must deny, on the deliberation
    route and on the cold and cached Workshop paths."""
    import nodelang.application_server as application_server_module
    descriptor = tmp_path / "race-runtime.json"
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                               machine_key_provider=KEY).start()
    try:
        space = server.universal_registry.workshop_root
        agent = UniversalRuntimeClient(descriptor, KEY)
        agent.bind_agent_session(runtime="claude", external_session_id="court-race-a")
        other = UniversalRuntimeClient(descriptor, KEY)
        other.bind_agent_session(runtime="claude", external_session_id="court-race-b")
        peer = UniversalRuntimeClient(descriptor, KEY)
        peer.bind_agent_session(runtime="codex", external_session_id="court-race-peer")
        peer.request("POST", "/api/universal/workshop", {
            "category": "note", "text": "private to the other agent", "refs": [], "evidence": [],
            "recipients": [other.agent_session_root], "reply_to": None,
            "idempotency_key": "court-race-1", "created_at": None})

        def recovered_reader():
            reader = UniversalRuntimeClient(descriptor, KEY)
            reader.open_native_inbox_read(runtime="claude", external_session_id="court-race-a",
                                          expected_agent_session=agent.agent_session_root)
            return reader

        def refused(reader, path, body):
            try:
                result = reader.request("GET", path, body)
            except MachineTransportError as exc:
                assert "private to the other agent" not in str(exc)
                return
            pytest.fail("%s passed a retired capability; other recipient visible: %s"
                        % (path, "private to the other agent" in str(result)))

        reader = recovered_reader()
        original_space = application_server_module.read_deliberation_space

        def retire_then_read(*args, **kwargs):
            server._machine_agent_recovery_capabilities.pop(reader._agent_session_capability_id, None)
            return original_space(*args, **kwargs)

        monkeypatch.setattr(application_server_module, "read_deliberation_space", retire_then_read)
        refused(reader, "/api/universal/deliberation", {"space": space, "limit": 50})
        reader = recovered_reader()
        refused(reader, "/api/universal/workshop", {})  # cold Workshop path
        monkeypatch.setattr(application_server_module, "read_deliberation_space", original_space)

        agent.request("GET", "/api/universal/workshop", {})  # a full session fills the legacy cache
        reader = recovered_reader()
        original_projection = server._project_universal_machine_workshop

        def retire_then_project(**kwargs):
            server._machine_agent_recovery_capabilities.pop(reader._agent_session_capability_id, None)
            return original_projection(**kwargs)

        monkeypatch.setattr(server, "_project_universal_machine_workshop", retire_then_project)
        refused(reader, "/api/universal/workshop", {})  # cached Workshop path
        monkeypatch.setattr(server, "_project_universal_machine_workshop", original_projection)
        # Direct desktop reads keep working.
        assert server.dispatch_universal_machine_route({
            "method": "GET", "path": "/api/universal/deliberation",
            "body": {"space": space, "limit": 5}})["space"] == space
    finally:
        server.close()
