"""Court: an agent keeps its own inbox across application restarts.

Founder complaint 2026-09-28: after the app is reinstalled or restarted an agent
can no longer read or answer messages other agents sent it. Live session 717:
the pinned owner differed from the current owner, reads failed with "native
agent client or owner binding changed", rebind was refused with "conditional
native enrollment requires effect reconciliation" because one expired permit
had no receipt, and recovery after a second owner change said "custody changed".

These courts drive the real application server on a persistent scratch graph
through two restarts, the real native session owner and the real MCP control.
Only OS process death is substituted (all servers share the court process).
"""
import hashlib
import os
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
TARGET = "70.HANDOFFS/court-inbox/target.txt"
PLANNED = b"planned content\n"


def _start(root, **options):
    (root / "ws").mkdir(exist_ok=True)
    return ApplicationServer(
        enable_machine_transport=True, machine_descriptor_path=root / "runtime.json",
        machine_key_provider=KEY, universal_workspace_root=root / "ws",
        universal_state_path=root / "graph.sqlite3", **options).start()


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("inbox-template")
    _start(root).close()
    return root


class World:
    def __init__(self, template, root, **options):
        shutil.copytree(template, root)
        self.root = root
        self.server = _start(root, **options)
        self.bind_calls = []

    def restart(self, root=None):
        """Owner replacement: a new application process on the same graph."""
        self.server.close()
        self.server = _start(root or self.root)

    def owner(self, external="court-717"):
        calls = self.bind_calls

        class Counted(UniversalRuntimeClient):
            def bind_agent_session(self, **kwargs):
                calls.append((external, kwargs.get("expected_agent_session")))
                return super().bind_agent_session(**kwargs)

        owner = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": external},
                                   descriptor_path=self.root / "runtime.json", key_provider=KEY,
                                   client_factory=Counted)
        return owner, _OwnedWorkshopClient(owner, owner.connect())

    def send(self, actor, text, key):
        peer = UniversalRuntimeClient(self.root / "runtime.json", KEY)
        peer.bind_agent_session(runtime="codex", external_session_id="court-peer-" + key)
        return InstalledWorkshopCoordinationClient(peer).call(
            "send_message", {"target": actor, "message": text, "idempotency_key": key})

    def legacy_permit(self, actor, name, *, issued_at, content=PLANNED):
        """A graph-held permit as issued before SPEC 3.3 moved new permits to records."""
        store = self.server.universal_store
        protocol = self.server.universal_registry.cde_write_authority_protocol
        snap = store.snapshot()
        root = "court:legacy-cde-permit:" + name
        values = cde._permit_values(
            runtime="claude", agent_session_root=actor, work_root="court:work",
            container_root="court:container", container_id="GM.nodes.court",
            container_digest="a" * 64, operation="write_file", path=TARGET,
            content_digest=hashlib.sha256(content).hexdigest(), request_id="court-request-" + name,
            nonce="court-nonce-" + name, authority_revision=snap.revision,
            issued_at=issued_at, expires_at=issued_at + 60.0)
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

    def target(self, data, *, mtime):
        path = self.root / "ws" / TARGET
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)
            os.utime(path, (mtime, mtime))
        os.utime(path.parent, (mtime, mtime))
        return path

    def close(self):
        self.server.close()


@pytest.fixture
def world(template, tmp_path):
    made = World(template, tmp_path / "app")
    try:
        yield made
    finally:
        made.close()


def _fingerprints(owner):
    status = owner.owner_status()
    return status["pinned"]["fingerprint"], status["current"]["fingerprint"]


def _stale(world, actor, name="717", data=b"old content\n"):
    issued = time.time() - 120.0
    world.target(data, mtime=issued - 60.0)
    return world.legacy_permit(actor, name, issued_at=issued)


def _messages(result):
    return [entry["summary"] for entry in result["entries"]]


def _reconciled(record, state):
    assert record["outcome"] == "reconciled-no-replay"
    assert record["execution_history"] == "unknown"
    assert "does not show whether this permit wrote" in record["evidence_limits"]
    assert record["observed_state"] == state
    # Current state is never turned into an execution receipt either way.
    assert not {"applied", "not-applied"} & {str(value) for value in record.values()}


def test_expired_unreceipted_permit_blocks_writes_not_reads_until_reconciled(world):
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    permit = _stale(world, actor)
    world.send(actor, "please review the plan", "court-msg-1")
    world.restart()
    pinned, current = _fingerprints(owner)

    inbox = control.call("read_messages", {"limit": 20})
    assert "please review the plan" in _messages(inbox)
    assert inbox["access"] == "read-only" and inbox["agent_session"] == actor

    with pytest.raises(MachineTransportError, match="effect reconciliation"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    with pytest.raises(MachineTransportError, match="not bound"):
        control.call("send_message", {"target": actor, "message": "x", "idempotency_key": "w1"})
    reader = owner.inbox_reader()
    with pytest.raises(MachineTransportError, match="Replies and file changes are paused"):
        reader.call("send_message", {"target": actor, "message": "x", "idempotency_key": "w1"})
    with pytest.raises(MachineTransportError, match="read-only"):
        reader._client.request("POST", "/api/universal/workshop", {
            "category": "note", "text": "x", "refs": [], "evidence": [], "recipients": [actor],
            "reply_to": None, "idempotency_key": "w2", "created_at": None})
    assert "please review the plan" in _messages(control.call("read_messages", {"limit": 20}))

    revision = world.server.universal_store.revision
    settled = owner.settle_effect(expected_owner=current, permit=permit, settlement="reconciled")
    _reconciled(settled, "differs-from-permitted-content")
    assert settled["settled_by"] == "actor"
    assert world.server.universal_store.revision == revision  # a record, not a graph revision

    owner.recover_rebind_owner(expected_failed_owner=current, expected_current_owner=current)
    owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    assert owner.owner_status()["recovery_required"] is False
    sent = control.call("send_message", {"target": actor, "message": "reviewed", "idempotency_key": "r1"})
    assert sent["ok"] is True
    assert "reviewed" in _messages(control.call("read_messages", {"limit": 20}))


def test_owner_replaced_twice_recovers_without_guessing(world, monkeypatch):
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    permit = _stale(world, actor)
    world.restart()
    pinned, second = _fingerprints(owner)
    with pytest.raises(MachineTransportError, match="effect reconciliation"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=second)
    world.restart()
    third = owner.owner_status()["current"]["fingerprint"]

    # The retired owner must be proven gone; a live one keeps the attempt retained.
    # (Before the fix this refused forever with "custody changed".)
    with pytest.raises(MachineTransportError, match="still present"):
        owner.recover_rebind_owner(expected_failed_owner=second, expected_current_owner=third)
    assert owner.state == "uncertain"
    failed = owner.owner_status().get("failed_attempt") or {}
    assert failed.get("owner_fingerprint") == second and failed.get("superseded") is True
    monkeypatch.setattr(NativeAgentSession, "_require_retired_owner_process", staticmethod(lambda d: None))
    with pytest.raises(MachineTransportError, match="custody changed"):
        owner.recover_rebind_owner(expected_failed_owner=third, expected_current_owner=third)
    recovered = owner.recover_rebind_owner(expected_failed_owner=second, expected_current_owner=third)
    assert recovered["continuation_outcome"] == "owner-retired" and recovered["state"] == "bound"

    owner.settle_effect(expected_owner=third, permit=permit, settlement="reconciled")
    owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=third)
    assert owner.owner_status()["agent_session"] == actor
    assert control.call("send_message", {"target": actor, "message": "back", "idempotency_key": "b1"})["ok"]


@pytest.mark.parametrize("case", ["written-with-crlf", "restored-with-old-mtime", "identical-before-permit"])
def test_matching_content_is_current_state_never_an_execution_receipt(world, case):
    """Ping review: a restore keeps an old mtime and the content may predate the
    permit, so matching content proves only what is there now."""
    owner, _control = world.owner()
    actor = owner.owner_status()["agent_session"]
    issued = time.time() - 120.0
    if case == "identical-before-permit":
        world.target(PLANNED, mtime=issued - 60.0)
    else:
        world.target(None, mtime=issued - 60.0)
    permit = world.legacy_permit(actor, case, issued_at=issued)
    if case == "written-with-crlf":
        world.target(PLANNED.replace(b"\n", b"\r\n"), mtime=issued + 5.0)
    elif case == "restored-with-old-mtime":
        world.target(PLANNED, mtime=issued - 3600.0)  # a copy that kept its old timestamp
    world.restart()
    _pinned, current = _fingerprints(owner)
    settled = owner.settle_effect(expected_owner=current, permit=permit, settlement="reconciled")
    _reconciled(settled, "holds-permitted-content-crlf" if case == "written-with-crlf"
                else "holds-permitted-content")
    for refused in ("applied", "not-applied"):
        with pytest.raises(MachineTransportError, match="outcome is invalid"):
            owner.settle_effect(expected_owner=current, permit=permit, settlement=refused)


def test_a_file_changing_while_checked_is_refused_and_stays_unresolved(world, monkeypatch):
    import os
    import pathlib
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    permit = _stale(world, actor)
    world.restart()
    pinned, current = _fingerprints(owner)
    original = pathlib.Path.read_bytes

    def racing(self):
        data = original(self)
        if self.name == "target.txt":
            os.utime(self, (time.time(), time.time()))  # another writer touches it mid-read
        return data

    monkeypatch.setattr(pathlib.Path, "read_bytes", racing)
    with pytest.raises(MachineTransportError, match="changed while it was being checked"):
        owner.settle_effect(expected_owner=current, permit=permit, settlement="reconciled")
    monkeypatch.setattr(pathlib.Path, "read_bytes", original)
    with pytest.raises(MachineTransportError, match="effect reconciliation"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    assert control.call("read_messages", {"limit": 5})["access"] == "read-only"


def test_foreign_actor_or_other_instance_is_refused(world, tmp_path, template):
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    permit = _stale(world, actor)
    other, _other_control = world.owner("court-other")
    world.restart()
    _pinned, current = _fingerprints(owner)

    with pytest.raises(MachineTransportError, match="another agent"):
        other.settle_effect(expected_owner=current, permit=permit, settlement="reconciled")
    stranger = UniversalRuntimeClient(world.root / "runtime.json", KEY)
    with pytest.raises(MachineTransportError, match="does not match expected actor"):
        stranger.settle_native_effect(runtime="claude", external_session_id="court-other",
                                      expected_agent_session=actor, permit=permit, settlement="reconciled")
    with pytest.raises(MachineTransportError, match="does not match expected actor"):
        UniversalRuntimeClient(world.root / "runtime.json", KEY).open_native_inbox_read(
            runtime="claude", external_session_id="court-other", expected_agent_session=actor)

    shutil.copytree(template, tmp_path / "elsewhere")
    world.restart(tmp_path / "elsewhere")
    shutil.copyfile(tmp_path / "elsewhere" / "runtime.json", world.root / "runtime.json")
    with pytest.raises(MachineTransportError, match="another application instance"):
        control.call("read_messages", {"limit": 5})
    with pytest.raises(MachineTransportError, match="instance changed"):
        owner.settle_effect(expected_owner=owner.owner_status()["current"]["fingerprint"],
                            permit=permit, settlement="reconciled")


def test_nothing_is_replayed(world):
    from nodelang.cell_authorization import AuthorizationDenied
    from nodelang.native_inbox_recovery import refuse_reconciled_replay
    owner, control = world.owner()
    actor = owner.owner_status()["agent_session"]
    permit = _stale(world, actor)
    world.send(actor, "one message", "court-once")
    world.restart()
    pinned, current = _fingerprints(owner)
    with pytest.raises(MachineTransportError):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    for _ in range(3):
        control.call("read_messages", {"limit": 20})
    first = owner.settle_effect(expected_owner=current, permit=permit, settlement="reconciled")
    again = owner.settle_effect(expected_owner=current, permit=permit, settlement="reconciled")
    assert first["already_settled"] is False and again["already_settled"] is True
    assert {key: again[key] for key in first if key != "already_settled"} == {
        key: first[key] for key in first if key != "already_settled"}
    # A retry of the same reconciled operation is refused ...
    with pytest.raises(AuthorizationDenied, match="not retried automatically"):
        refuse_reconciled_replay(world.server, actor, "court:work", "court-request-717")
    # ... but a fresh, separately admitted request writing the same content is not replay.
    refuse_reconciled_replay(world.server, actor, "court:work", "court-request-fresh")
    assert first["content_digest"] == hashlib.sha256(PLANNED).hexdigest()
    owner.recover_rebind_owner(expected_failed_owner=current, expected_current_owner=current)
    owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    assert world.bind_calls == [("court-717", None), ("court-717", actor), ("court-717", actor)]
    assert _messages(control.call("read_messages", {"limit": 20})).count("one message") == 1


def test_recovery_server_reads_inbox_before_activation(monkeypatch):
    from types import SimpleNamespace as NS
    from nodelang import native_agent_mcp as mcp
    from nodelang.native_resume_guard import NativeResumeGuard
    calls = []
    reader = NS(call=lambda method, values: calls.append((method, values)) or {"access": "read-only"})
    owner = NS(owner_status=lambda: {"state": "uncertain"}, needs_inbox_recovery=lambda: True,
               inbox_reader=lambda: reader,
               settle_effect=lambda **kwargs: calls.append(("settle", kwargs)) or {"outcome": "reconciled-no-replay"})
    monkeypatch.setattr(NativeResumeGuard, "recover", lambda self: {"status": "recovery_required"})
    server, activate = mcp.build_recovery_server(owner)
    assert activate()["status"] == "recovery_required"
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert tools["coordination.read_messages"].fn(limit=5)["access"] == "read-only"
    tools["native.owner_settle_effect"].fn(expected_owner="f", permit="p", settlement="reconciled")
    assert calls == [("read_messages", {"limit": 5, "before": None}),
                     ("settle", {"expected_owner": "f", "permit": "p", "settlement": "reconciled"})]
    assert "coordination.send_message" not in tools


def test_an_idle_agent_keeps_its_session_past_the_lease(template, tmp_path):
    """Live cause (d): an idle owner became "runtime Agent Session is unknown"."""
    from nodelang import native_agent_mcp as mcp
    world = World(template, tmp_path / "app", machine_session_lifetime_seconds=20.0)
    try:
        owner = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": "court-idle"},
                                   descriptor_path=world.root / "runtime.json", key_provider=KEY)
        server = mcp.build_server(session=owner)
        actor = owner.owner_status()["agent_session"]
        world.send(actor, "are you there", "court-idle-1")
        revision = world.server.universal_store.revision
        time.sleep(30.0)  # idle for longer than the whole lease
        assert world.server.universal_store.revision == revision  # renewal is no graph write
        tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
        inbox = tools["coordination.read_messages"].fn(limit=20)
        assert "are you there" in _messages(inbox)
        assert owner.owner_status()["recovery_required"] is False
        owner.close()
    finally:
        world.close()


def test_the_live_restart_state_rebinds_the_same_actor(template, tmp_path, monkeypatch):
    """Live 14:51 state (session 717): state=uncertain, generation 1, rebind_pending,
    lease_expired, same instance_digest, different runtime_id; recover answered
    "custody changed" and every write stayed refused."""
    world = World(template, tmp_path / "app", machine_session_lifetime_seconds=20.0)
    try:
        owner, control = world.owner()
        actor = owner.owner_status()["agent_session"]
        permit = _stale(world, actor)
        first = owner.owner_status()["current"]["fingerprint"]
        time.sleep(22.0)  # the lease runs out while the agent is idle
        with pytest.raises(MachineTransportError, match="effect reconciliation"):
            owner.rebind_owner(expected_old_owner=first, expected_new_owner=first)
        world.restart()  # the app restarts: a new runtime on the same instance
        status = owner.owner_status()
        assert (status["state"], status["generation"], status["rebind_pending"],
                status["lease_expired"], status["recovery_required"]) == ("uncertain", 1, True, True, True)
        assert status["pinned"]["instance_digest"] == status["current"]["instance_digest"]
        assert status["pinned"]["runtime_id"] != status["current"]["runtime_id"]
        assert status["pinned"]["fingerprint"] == first
        current = status["current"]["fingerprint"]

        # The failed attempt went to the retired runtime; its process is gone.
        monkeypatch.setattr(NativeAgentSession, "_require_retired_owner_process", staticmethod(lambda d: None))
        recovered = owner.recover_rebind_owner(expected_failed_owner=first, expected_current_owner=current)
        assert recovered["continuation_outcome"] == "owner-retired"
        owner.settle_effect(expected_owner=current, permit=permit, settlement="reconciled")
        owner.rebind_owner(expected_old_owner=first, expected_new_owner=current)
        final = owner.owner_status()
        assert final["agent_session"] == actor and final["recovery_required"] is False
        assert control.call("send_message", {"target": actor, "message": "back after restart",
                                             "idempotency_key": "court-live-1"})["ok"] is True
    finally:
        world.close()


def _kept_owner(template, tmp_path, external):
    from nodelang import native_agent_mcp as mcp
    world = World(template, tmp_path / "app", machine_session_lifetime_seconds=20.0)
    owner = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": external},
                               descriptor_path=world.root / "runtime.json", key_provider=KEY)
    mcp.build_server(session=owner)  # starts the lease keeper
    return world, owner


def _still_renewed(owner):
    time.sleep(30.0)  # longer than the whole lease
    status = owner.owner_status()
    assert status["lease_expired"] is False and status["recovery_required"] is False
    with owner.bound_client() as client:
        assert client.request("GET", "/api/universal/workshop", {})["agent_session"] == status["agent_session"]


def test_a_refused_close_keeps_renewing_the_lease(template, tmp_path):
    """Ping review: a refused close stopped the keeper and idle expiry returned."""
    world, owner = _kept_owner(template, tmp_path, "court-keeper-refused")
    try:
        with owner.bound_client():
            with pytest.raises(MachineTransportError, match="active operation"):
                owner.close()
        assert owner.state == "bound"
        _still_renewed(owner)
    finally:
        world.close()


def test_a_retained_release_keeps_renewing_the_lease(template, tmp_path):
    world, owner = _kept_owner(template, tmp_path, "court-keeper-retained")
    try:
        client = owner.require_client()
        real = client._request_once

        def lost(method, path, body, **kwargs):
            if path == "/api/universal/agent-session-release":
                raise MachineTransportError("release reply lost")
            return real(method, path, body, **kwargs)

        client._request_once = lost
        with pytest.raises(MachineTransportError, match="reply lost"):
            owner.close()
        assert owner.state == "release-uncertain"
        retained = owner.close()  # exact status recovery: the release never happened
        assert retained["retained"] is True and owner.state == "bound"
        client._request_once = real
        _still_renewed(owner)
    finally:
        world.close()


def test_the_real_permit_route_refuses_only_a_retry_of_the_reconciled_operation(tmp_path):
    """Ping acceptance gap: through the claimed-Work permit route, the retry of a
    reconciled uncertain operation is refused and a fresh admitted request writing
    the same content is issued."""
    from nodelang import application_server as application_server_module
    from nodelang.cell_signing_authority import LocalEd25519KmsProvider
    from nodelang.native_inbox_recovery import settle_stale_permit
    from nodelang.universal_application import create_universal_governed_work
    from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance
    from tests_replica.workshop_gate_support import open_execution_gate
    workspace = tmp_path / "ws"
    workspace.mkdir()
    descriptor = tmp_path / "replay-runtime.json"
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                               machine_key_provider=KEY, universal_workspace_root=workspace,
                               runtime_compliance_runner=_green_runtime_compliance).start()
    try:
        signer = LocalEd25519KmsProvider(provider_id="court.replay", authority_id="court-replay")
        server.cde_write_signing_provider = signer
        with commit_intent.declare(commit_intent.MIGRATION, actor="app:archhub", reason="court signing key"):
            server.cde_write_signing_descriptor_root = application_server_module._ensure_cde_write_signing_authority(
                server.universal_store, server.universal_registry, signer,
                descriptor_root="court:cde-write-signing-key:v1")
        target = "10.PRODUCT/13.NODE-LANGUAGE/nodelang/court_replay_target.py"
        container = {
            "container_id": "GM.nodes.court-replay", "source_requirement": "court:replay",
            "domain": "nodes", "tier": "T1", "lifecycle_state": "WIP", "suitability_status": "S0",
            "revision": "P01", "owner": "founder", "checker": "court", "allowed_paths": [target],
            "gate_kind": "pytest",
            "gate_spec": {"path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py"},
            "write_grants": [{"path": target, "scope": "exact", "operations": ["apply_patch"]}],
        }
        with commit_intent.declare(commit_intent.USER_ACTION, actor="app:identity:founder", reason="court work"):
            work_root, _wire, _revision = create_universal_governed_work(
                server.universal_store, server.universal_registry, title="Court replay",
                description="court", priority=100, external_key="court:replay",
                structured_references={"cde-container": container}, x=320, y=240)
        open_execution_gate(server, work_root, "replay")
        agent = UniversalRuntimeClient(descriptor, KEY)
        agent.bind_agent_session(runtime="codex", external_session_id="court-replay-agent")
        agent.request("POST", "/api/universal/workshop", {
            "category": "plan", "text": "Exercise the replay boundary.", "refs": [work_root],
            "evidence": [], "recipients": [], "reply_to": None,
            "idempotency_key": "court:replay:plan", "created_at": "2026-09-28T00:00:00+00:00"})
        agent.claim_work(work_root)
        digest = hashlib.sha256(b"same content").hexdigest()
        request = dict(operation="apply_patch", path=target, content_digest=digest)
        old = agent.issue_cde_write_permit(**request, request_id="court-replay-old", nonce="court-replay-old-n")
        settled = settle_stale_permit(server, actor=agent.agent_session_root, permit_root=old["permit"],
                                      settlement="reconciled", settled_by="instance-owner",
                                      now=old["expires_at"] + 1.0)
        assert settled["outcome"] == "reconciled-no-replay" and settled["request_id"] == "court-replay-old"
        with pytest.raises(MachineTransportError, match="not retried automatically"):
            agent.issue_cde_write_permit(**request, request_id="court-replay-old", nonce="court-replay-old-n")
        fresh = agent.issue_cde_write_permit(**request, request_id="court-replay-fresh", nonce="court-replay-fresh-n")
        assert fresh["content_digest"] == digest and fresh["permit"] != old["permit"]
    finally:
        server.close()


def test_a_recovered_reader_is_refused_in_a_conversation_it_is_not_part_of(world):
    """Ping acceptance gap: a second ordinary space made by the product's own
    conversation creation; the recovered non-participant is refused there."""
    from nodelang.workshop_conversation_catalog import create_workshop_conversation
    owner, _control = world.owner()
    actor = owner.owner_status()["agent_session"]
    other, _other_control = world.owner("court-other")
    other_actor = other.owner_status()["agent_session"]
    server, registry = world.server, world.server.universal_registry
    with commit_intent.declare(commit_intent.USER_ACTION, actor="app:identity:founder", reason="court conversation"):
        created = create_workshop_conversation(
            server, authentication_context=registry.authorization.session.context(),
            expected_revision=server.universal_store.revision, title="Court side conversation",
            participant_roots=[registry.authorization.subject_root, other_actor],
            idempotency_key="court-side-conversation")
    space = created["root"]
    assert actor not in created["participant_roots"] and other_actor in created["participant_roots"]
    world.restart()
    body = {"space": space, "limit": 5}
    with pytest.raises(MachineTransportError, match="participant"):
        owner.inbox_reader()._client.request("GET", "/api/universal/deliberation", body)
    assert other.inbox_reader()._client.request("GET", "/api/universal/deliberation", body)["space"] == space
