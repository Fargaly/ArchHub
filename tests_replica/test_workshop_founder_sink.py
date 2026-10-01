"""Courts: the founder's Workshop sink (plan B, S3a, W4a) admits only the founder and writes nothing on refusal.

BABOOM's tell becomes one founder note in the general Workshop's conversation content,
addressed to one existing participant. These courts run a real owner with its machine
pipe (memory key, descriptor in tmp_path), two runtime Agent Sessions bound over that
pipe, and the Workshop bound to conversation content in tmp_path. Every refusal is
checked against the graph revision and the stored history: both unchanged.
"""
import hashlib
import json
import sqlite3

import pytest

from nodelang.application_machine_transport import UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_authorization import AuthorizationDenied, RefusedWithoutEffect
from nodelang.cell_deliberation import read_deliberation_space
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.workshop_founder_sink import founder_tell
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance


def _bind_content(server, path):
    from nodelang.conversation_content import prepare_empty_content_binding
    from nodelang.conversation_history import ConversationHistoryStore
    registry, store = server.universal_registry, server.universal_store
    server.conversation_content._path = path
    adopted = prepare_empty_content_binding(store.snapshot(), registry.deliberation_protocol,
        application_root=registry.application_root, space_root=registry.workshop_root)
    with ConversationHistoryStore(path, instance_id=adopted.binding.instance_id) as history:
        history.ensure_conversation(registry.workshop_root)
        history.initialize_retention()
    store.commit(adopted.expected_revision, create=adopted.create, replace=adopted.replace)


@pytest.fixture
def owner(tmp_path):
    descriptor = tmp_path / "founder-sink-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"f" * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
        machine_key_provider=provider, universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance).start()
    try:
        agents = [UniversalRuntimeClient(descriptor, provider).bind_agent_session(
            runtime=runtime, external_session_id="founder-sink-" + runtime)["agent_session"]
            for runtime in ("codex", "claude")]
        yield server, agents, tmp_path / "founder-sink-history.sqlite3"
    finally:
        server.close()


def _founder_context(server):
    return server.universal_registry.authorization.session.context()


def _context_for(server, subject_root):
    """A live authenticated context whose subject is not the founder (same tenant and assurance)."""
    authority = server.universal_registry.authorization
    return authority.broker.mint_authenticated_context(subject_root,
        tenant_root=authority.session.tenant_root, assurance_root=authority.session.assurance_root)


def _state(server, path):
    """Graph revision plus a digest of every stored history row: equal means nothing was written."""
    rows = []
    if path.exists():
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            rows = db.execute("select id, sequence, author, content, recipients, idempotency_key "
                              "from messages order by conversation_id, sequence").fetchall()
    return server.universal_store.revision, len(rows), hashlib.sha256(
        json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def _stored(server, path, key):
    from nodelang.conversation_history import ConversationHistoryStore
    registry = server.universal_registry
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        instance = db.execute("select instance_id from history_identity").fetchone()[0]
    with ConversationHistoryStore(path, instance_id=instance, create=False) as history:
        return history.get_by_idempotency(registry.workshop_root, key,
            principal=registry.authorization.subject_root, read_all=True)


def test_founder_tell_stores_one_note_to_one_participant_and_replay_adds_none(owner, monkeypatch):
    server, (agent_a, agent_b), path = owner
    _bind_content(server, path)
    relayed = []
    monkeypatch.setattr(server.native_recipient_relay, "request",
                        lambda **call: relayed.append(call) or [{"recipient": agent_a, "state": "started"}])
    founder = server.universal_registry.authorization.subject_root
    revision, count, _digest = _state(server, path)

    sent = founder_tell(server, _founder_context(server), target_root=agent_a,
                        text="check the build", idempotency_key="baboom-tell-1")
    assert sent["storage"] == "conversation-content" and sent["target"] == agent_a
    assert sent["native_delivery"] == [{"recipient": agent_a, "state": "started"}]
    stored = _stored(server, path, "baboom-tell-1")
    assert stored["id"] == sent["message_id"] and stored["content"] == "check the build"
    # No promotion: the founder authored it; the agent is only its one recipient.
    assert stored["author"] == founder and list(stored["recipients"]) == [agent_a]
    assert relayed == [{"space_root": server.universal_registry.workshop_root,
                        "message_id": sent["message_id"], "sender_root": founder,
                        "recipient_roots": (agent_a,), "text": "check the build"}]
    after = _state(server, path)
    assert after[0] == revision and after[1] == count + 1   # content only, no graph write

    again = founder_tell(server, _founder_context(server), target_root=agent_a,
                         text="check the build", idempotency_key="baboom-tell-1")
    assert again["message_id"] == sent["message_id"]
    assert _state(server, path) == after                     # replay: 0 duplicates


def test_an_agent_session_caller_is_refused_with_zero_writes(owner):
    server, (agent_a, agent_b), path = owner
    _bind_content(server, path)
    before = _state(server, path)
    agent = _context_for(server, agent_b)
    with pytest.raises(RefusedWithoutEffect, match="Only the founder"):
        founder_tell(server, agent, target_root=agent_a, text="pretend to be the founder",
                     idempotency_key="agent-as-founder")
    with pytest.raises(RefusedWithoutEffect, match="Only the founder"):
        founder_tell(server, agent, target_root=agent_b, text="note to self",
                     idempotency_key="agent-to-self")
    assert _state(server, path) == before


def test_a_non_founder_or_dead_context_is_refused_with_zero_writes(owner):
    server, (agent_a, _agent_b), path = owner
    _bind_content(server, path)
    before = _state(server, path)
    with pytest.raises(RefusedWithoutEffect, match="Only the founder"):
        founder_tell(server, _context_for(server, "app:identity:someone-else"), target_root=agent_a,
                     text="hello", idempotency_key="stranger")
    with pytest.raises(RefusedWithoutEffect, match="live session"):
        founder_tell(server, object(), target_root=agent_a, text="hello", idempotency_key="no-context")
    assert _state(server, path) == before


def test_the_target_must_be_an_existing_workshop_agent(owner):
    server, (agent_a, _agent_b), path = owner
    _bind_content(server, path)
    founder = server.universal_registry.authorization.subject_root
    space = read_deliberation_space(server.universal_store.snapshot(),
        server.universal_registry.deliberation_protocol, server.universal_registry.workshop_root)
    absent = "app:agent-session:runtime:not-in-this-workshop"
    assert agent_a in space.participant_roots and absent not in space.participant_roots
    before = _state(server, path)
    for target in (absent, founder):
        with pytest.raises(RefusedWithoutEffect, match="is not an agent in this Workshop"):
            founder_tell(server, _founder_context(server), target_root=target, text="hello",
                         idempotency_key="target-" + str(len(target)))
    assert _state(server, path) == before


def test_an_unbound_workshop_is_never_written_from_the_sink(owner):
    server, (agent_a, _agent_b), path = owner
    space = read_deliberation_space(server.universal_store.snapshot(),
        server.universal_registry.deliberation_protocol, server.universal_registry.workshop_root)
    if space.content_store_root is not None:
        pytest.skip("this owner bound its Workshop to content at construction")
    before = _state(server, path)
    with pytest.raises(RefusedWithoutEffect, match="not on conversation content"):
        founder_tell(server, _founder_context(server), target_root=agent_a, text="hello",
                     idempotency_key="unbound")
    assert _state(server, path) == before


def _recording_relay(server, monkeypatch):
    relayed = []
    monkeypatch.setattr(server.native_recipient_relay, "request",
                        lambda **call: relayed.append(call) or [])
    return relayed


def test_a_revocation_from_another_thread_waits_until_the_tell_is_done(owner, monkeypatch):
    """Event-ordered: the revoker starts inside the admission window and is held off by the broker
    lock until the append returns; the next tell with that context is a typed no-effect refusal."""
    import threading
    from nodelang import universal_application
    server, (agent_a, _agent_b), path = owner
    _bind_content(server, path)
    relayed = _recording_relay(server, monkeypatch)
    founder = _founder_context(server)
    broker = server.universal_registry.authorization.broker
    order, attempting = [], threading.Event()

    def revoke():
        attempting.set()
        broker.revoke(founder)
        order.append("revoked")
    revoker = threading.Thread(target=revoke, name="founder-sink-revoker")
    real_append = universal_application.append_universal_workshop_entry

    def append_after_revoke_started(*args, **kwargs):
        # The founder passed admission; a revocation now races the append.
        revoker.start()
        assert attempting.wait(5)
        revoker.join(0.5)
        assert revoker.is_alive(), "revocation must not land between admission and the append"
        entry = real_append(*args, **kwargs)
        order.append("appended")
        return entry
    monkeypatch.setattr(universal_application, "append_universal_workshop_entry",
                        append_after_revoke_started)
    sent = founder_tell(server, founder, target_root=agent_a, text="before revoke",
                        idempotency_key="race-1")
    revoker.join(5)
    assert order == ["appended", "revoked"] and len(relayed) == 1
    assert _stored(server, path, "race-1")["id"] == sent["message_id"]
    monkeypatch.setattr(universal_application, "append_universal_workshop_entry", real_append)
    before = _state(server, path)
    with pytest.raises(RefusedWithoutEffect, match="live session"):
        founder_tell(server, founder, target_root=agent_a, text="after revoke", idempotency_key="race-2")
    assert _state(server, path) == before and len(relayed) == 1


def test_a_revocation_inside_the_window_is_a_typed_refusal_at_the_pre_append_boundary(owner, monkeypatch):
    """Event-ordered: the context is revoked after admission resolved it and before the append
    (the broker lock re-enters on this thread); the boundary check refuses with no effect."""
    from nodelang import workshop_founder_sink as sink
    server, (agent_a, _agent_b), path = owner
    _bind_content(server, path)
    relayed = _recording_relay(server, monkeypatch)
    founder = _founder_context(server)
    broker = server.universal_registry.authorization.broker
    real_read = sink.read_deliberation_space
    events = []

    def read_then_revoke(*args, **kwargs):
        events.append("admitted")
        broker.revoke(founder)
        events.append("revoked")
        return real_read(*args, **kwargs)
    monkeypatch.setattr(sink, "read_deliberation_space", read_then_revoke)
    before = _state(server, path)
    with pytest.raises(RefusedWithoutEffect, match="no longer authorized"):
        founder_tell(server, founder, target_root=agent_a, text="revoked in the window",
                     idempotency_key="window-1")
    assert events == ["admitted", "revoked"]
    assert _state(server, path) == before and relayed == []


def test_a_policy_denial_before_the_append_is_a_typed_refusal(owner, monkeypatch):
    from nodelang import cell_authorization
    server, (agent_a, _agent_b), path = owner
    _bind_content(server, path)
    relayed = _recording_relay(server, monkeypatch)

    def deny(*args, **kwargs):
        raise AuthorizationDenied("conversation policy denies this founder note")
    monkeypatch.setattr(cell_authorization, "require_authorization", deny)
    before = _state(server, path)
    with pytest.raises(RefusedWithoutEffect, match="policy denies"):
        founder_tell(server, _founder_context(server), target_root=agent_a, text="denied",
                     idempotency_key="policy-1")
    assert _state(server, path) == before and relayed == []


def test_an_error_after_the_append_is_never_reported_as_no_effect(owner, monkeypatch):
    from nodelang import universal_application
    server, (agent_a, _agent_b), path = owner
    _bind_content(server, path)
    relayed = _recording_relay(server, monkeypatch)
    real_append = universal_application.append_universal_workshop_entry
    for failure in (RuntimeError("lost after the commit"), AuthorizationDenied("denied after the commit")):
        def append_then_fail(*args, failure=failure, **kwargs):
            real_append(*args, **kwargs)
            raise failure
        monkeypatch.setattr(universal_application, "append_universal_workshop_entry", append_then_fail)
        key = "after-" + type(failure).__name__
        with pytest.raises(type(failure)) as raised:
            founder_tell(server, _founder_context(server), target_root=agent_a, text="committed",
                         idempotency_key=key)
        assert type(raised.value) is type(failure)          # never upgraded to RefusedWithoutEffect
        assert _stored(server, path, key)["content"] == "committed"   # the effect exists
    assert relayed == []


def test_an_idempotency_conflict_never_relays_the_new_text(owner, monkeypatch):
    server, (agent_a, agent_b), path = owner
    _bind_content(server, path)
    relayed = _recording_relay(server, monkeypatch)
    sent = founder_tell(server, _founder_context(server), target_root=agent_a, text="first text",
                        idempotency_key="conflict-1")
    assert [call["text"] for call in relayed] == ["first text"]
    after = _state(server, path)
    for target, text in ((agent_a, "second text"), (agent_b, "first text")):
        with pytest.raises(ValueError, match="idempotency conflict"):
            founder_tell(server, _founder_context(server), target_root=target, text=text,
                         idempotency_key="conflict-1")
    assert _state(server, path) == after
    assert [call["text"] for call in relayed] == ["first text"]
    stored = _stored(server, path, "conflict-1")
    assert stored["id"] == sent["message_id"] and stored["content"] == "first text"
