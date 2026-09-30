"""Court: a stuck native owner always has one supported way back (2026-09-30).

Live session 717 (MCP PID 73812, started 2026-09-28 09:43): state "uncertain",
rebind_pending, recovery_required, lease_expired and no failed_attempt field.
owner_rebind refused ("unavailable or uncertain") and owner_recover refused
("custody changed"). That process imports the checkout as it stood on 09-26,
and nothing in owner_status could say so. On the current code three states
still had no way out:

1. a continuation whose receipt expired (the application answers "unknown");
2. an attempt that never left the process (it read no owner, so it has no
   fingerprint to recover with);
3. a restarted process holding the exact actor (--expected-actor) on a runtime
   with no Session Link configured, which could never activate, and whose
   refused-before-enrollment connection could never be reopened.

Recovery keeps the exact actor and every unresolved effect. It never reports
"not enrolled" without the application's own receipt, never replays a tool and
never retries by itself. Only the passage of time and OS process death are
substituted: every server shares this court process.
"""
import json
import os
from pathlib import Path
import re
import time

import pytest

from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
from nodelang.installed_workshop_coordination import InstalledWorkshopCoordinationClient
from nodelang.native_agent_session import NativeAgentSession
from tests_replica.test_native_inbox_recovery import KEY, World, _fingerprints, _messages, _stale, _start

EXTERNAL = "court-717"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("owner-recovery-template")
    _start(root).close()
    return root


@pytest.fixture
def world(template, tmp_path):
    made = World(template, tmp_path / "app")
    try:
        yield made
    finally:
        made.close()


def _lose_next_continuation_reply(monkeypatch):
    """The application issues the capability; its reply never arrives."""
    original = UniversalRuntimeClient._accept_agent_session_result
    lose = {"once": True}

    def accept(self, result, expected_agent_session=None):
        if lose["once"] and expected_agent_session is not None:
            lose["once"] = False
            raise MachineTransportError("injected reply loss after the capability was issued")
        return original(self, result, expected_agent_session)

    monkeypatch.setattr(UniversalRuntimeClient, "_accept_agent_session_result", accept)


def _receipts_expire(world):
    """Ten minutes pass: the application forgets every continuation outcome."""
    for held in world.server._machine_agent_continuation_receipts.values():
        held["until"] = time.time() - 1.0


def _lease_expires(world, actor):
    """The capability's lease runs out: the process that held it is gone."""
    world.server._machine_agent_sessions[actor]["expires_at"] = time.time() - 1.0


def _live_capabilities(world, actor):
    return sum(1 for root, binding in world.server._machine_agent_sessions.items()
               if root == actor and binding["expires_at"] > time.time())


def _counting(calls):
    class Counted(UniversalRuntimeClient):
        def bind_agent_session(self, **kwargs):
            calls.append(kwargs.get("expected_agent_session"))
            return super().bind_agent_session(**kwargs)
    return Counted


def test_owner_status_names_the_process_and_the_code_it_runs(world, monkeypatch, tmp_path):
    import shutil
    import nodelang.native_agent_session as native
    owner, _ = world.owner(EXTERNAL)
    status = owner.owner_status()
    process = status["process"]
    assert process["pid"] == os.getpid()
    assert process["module_origin"] == str(Path(native.__file__).resolve().parent)
    assert re.fullmatch(r"[0-9a-f]{64}", process["disk_digest_at_import"])
    assert process["disk_digest_now"] == process["disk_digest_at_import"]
    assert process["disk_changed_since_import"] is False
    # Never a token or a payload.
    assert owner._client._agent_session_token not in json.dumps(status)
    # A checkout edited after import is named even when size and mtime are unchanged:
    # the files are hashed every time, never trusted by their stat.
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for name in native._CODE_FILES:
        shutil.copy2(Path(native.__file__).parent / name, checkout / name)
    monkeypatch.setattr(native, "_IMPORT_SNAPSHOT", {"origin": str(checkout),
        "digest": native._code_digest(checkout), "revision": None})
    assert owner.owner_status()["process"]["disk_changed_since_import"] is False
    edited = checkout / "native_agent_session.py"
    stat, data = edited.stat(), bytearray(edited.read_bytes())
    data[-2] = ord("#") if data[-2] != ord("#") else ord(" ")
    edited.write_bytes(bytes(data))
    os.utime(edited, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert edited.stat().st_size == stat.st_size and edited.stat().st_mtime_ns == stat.st_mtime_ns
    assert owner.owner_status()["process"]["disk_changed_since_import"] is True


def test_an_expired_receipt_is_classified_and_the_same_actor_continues(world, monkeypatch):
    owner, control = world.owner(EXTERNAL)
    actor = owner.owner_status()["agent_session"]
    world.send(actor, "before the restart", "court-a1")
    world.restart()
    pinned, current = _fingerprints(owner)
    _lose_next_continuation_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="injected reply loss"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    _receipts_expire(world)

    recover = lambda: owner.recover_rebind_owner(expected_failed_owner=current, expected_current_owner=current)
    candidate, sent = owner._rebind_candidate, list(world.bind_calls)

    def refused_and_kept(match):
        # Negative evidence: each refusal keeps the exact attempt and sends nothing.
        with pytest.raises(MachineTransportError, match=match):
            recover()
        status = owner.owner_status()
        assert (status["state"], status["rebind_pending"]) == ("uncertain", True)
        assert owner._rebind_candidate is candidate and world.bind_calls == sent
        return status["failed_attempt"]

    # The lost capability is still live: wait for it, never mint a second one.
    failed = refused_and_kept("Recover again after its lease expires")
    assert failed["owner_fingerprint"] == current and failed["request_sent"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", failed["request_id"])
    with pytest.raises(MachineTransportError, match="unavailable or uncertain"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    # Held by another OS process instead: never taken over, only named.
    mine = dict(world.server._machine_agent_sessions[actor]["enrollment_peer"])
    world.server._machine_agent_sessions[actor]["enrollment_peer"] = {"pid": mine["pid"] + 1, "created_at": 0.0}
    assert refused_and_kept("another process holds a live capability") == failed
    world.server._machine_agent_sessions[actor]["enrollment_peer"] = mine

    _lease_expires(world, actor)
    # An operation still in flight for this actor also waits.
    world.server._machine_agent_active_requests[actor] = 1
    assert refused_and_kept("still in flight") == failed
    del world.server._machine_agent_active_requests[actor]
    settled = recover()
    assert (settled["state"], settled["continuation_outcome"], settled["historical_attempt_outcome"],
            settled["binding_status"], settled["next"]) == (
        "bound", "unknown", "unknown", "expired", "native.owner_rebind")
    assert settled["agent_session"] == actor and settled["failed_attempt"] is None

    owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    final = owner.owner_status()
    assert final["agent_session"] == actor and final["recovery_required"] is False
    # The admitted tool succeeds ...
    assert control.call("send_message", {"target": actor, "message": "after recovery",
                                         "idempotency_key": "court-a2"})["ok"] is True
    # ... the control refusal stays denied, and nothing ran twice.
    with pytest.raises(MachineTransportError, match="custody changed"):
        recover()
    assert world.bind_calls == [(EXTERNAL, None), (EXTERNAL, actor), (EXTERNAL, actor)]
    assert _live_capabilities(world, actor) == 1
    assert _messages(control.call("read_messages", {"limit": 20})).count("before the restart") == 1


def test_a_first_connection_with_an_unknown_outcome_refuses_until_nothing_is_live(world, monkeypatch):
    owner, control = world.owner(EXTERNAL)
    actor = owner.owner_status()["agent_session"]
    _lease_expires(world, actor)  # the old process is gone
    current = owner.owner_status()["current"]["fingerprint"]
    calls = []
    fresh = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": EXTERNAL},
                               descriptor_path=world.root / "runtime.json", key_provider=KEY,
                               client_factory=_counting(calls), expected_agent_session=actor)
    _lose_next_continuation_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="injected reply loss"):
        fresh.connect(expected_owner=current)
    _receipts_expire(world)
    client, sent = fresh._client, list(calls)
    failed = fresh.owner_status()["failed_attempt"]
    assert (failed["kind"], failed["request_sent"]) == ("connection", True)

    def refused_and_kept(match):
        with pytest.raises(MachineTransportError, match=match):
            fresh.recover_connection(expected_owner=current)
        assert fresh.state == "uncertain" and fresh._client is client and calls == sent
        assert fresh.owner_status()["failed_attempt"] == failed

    refused_and_kept("Recover again after its lease expires")
    mine = dict(world.server._machine_agent_sessions[actor]["enrollment_peer"])
    world.server._machine_agent_sessions[actor]["enrollment_peer"] = {"pid": mine["pid"] + 1, "created_at": 0.0}
    refused_and_kept("another process holds a live capability")
    world.server._machine_agent_sessions[actor]["enrollment_peer"] = mine
    _lease_expires(world, actor)
    world.server._machine_agent_active_requests[actor] = 1
    refused_and_kept("still in flight")
    del world.server._machine_agent_active_requests[actor]

    reopened = fresh.recover_connection(expected_owner=current)
    assert (reopened["state"], reopened["connection_outcome"], reopened["historical_attempt_outcome"]) == (
        "unbound", "unknown", "unknown")
    fresh.connect(expected_owner=current)
    assert fresh.owner_status()["agent_session"] == actor and calls == [actor, actor]


def test_unresolved_and_truncated_permits_stay_and_block_the_next_execution(world, monkeypatch):
    owner, control = world.owner(EXTERNAL)
    actor = owner.owner_status()["agent_session"]
    world.restart()
    pinned, current = _fingerprints(owner)
    _lose_next_continuation_reply(monkeypatch)
    with pytest.raises(MachineTransportError, match="injected reply loss"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    # Seventeen stale permits: more than one bounded page, so the page is truncated.
    permits = [_stale(world, actor, name="717-%02d" % n) for n in range(17)]
    _receipts_expire(world)
    _lease_expires(world, actor)

    settled = owner.recover_rebind_owner(expected_failed_owner=current, expected_current_owner=current)
    assert (settled["state"], settled["continuation_outcome"], settled["unresolved_effects"],
            settled["next"]) == ("bound", "unknown", True, "native.owner_settle_effect")
    page = owner.inspect_enrollment(expected_owner=current, projection="effects")["effects"]
    assert page["truncated"] is True and len(page["pending_permits"]) == 16   # retained, not dropped
    assert set(permits) >= {row["permit"] for row in page["pending_permits"]}
    # The next execution stays blocked while any permit is unresolved.
    with pytest.raises(MachineTransportError, match="effect reconciliation"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    with pytest.raises(MachineTransportError):
        control.call("send_message", {"target": actor, "message": "x", "idempotency_key": "court-p1"})
    again = owner.inspect_enrollment(expected_owner=current, projection="effects")["effects"]
    assert again["truncated"] is True and again["pending_permits"] == page["pending_permits"]


def test_the_blocking_permit_is_found_on_the_first_page_behind_other_agents_permits(world):
    """Live 717 after the 12:11 install: rebind refused for "effect reconciliation",
    and inspect_effects answered pending_permits [], truncated true, a new cursor
    every call. A page stopped after 256 registry entries whatever it had found."""
    owner, control = world.owner(EXTERNAL)
    actor = owner.owner_status()["agent_session"]
    other = "app:agent-session:runtime:" + "f" * 32
    issued = time.time() - 120.0
    for n in range(300):  # other agents' permits, registered first
        world.legacy_permit(other, "other-%03d" % n, issued_at=issued)
    mine = _stale(world, actor, name="717-behind")
    world.restart()
    pinned, current = _fingerprints(owner)
    with pytest.raises(MachineTransportError, match="effect reconciliation"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)

    page = owner.inspect_enrollment(expected_owner=current, projection="effects")["effects"]
    assert [row["permit"] for row in page["pending_permits"]] == [mine]
    assert page["truncated"] is False and page["next_cursor"] is None
    # Settle it, and the same actor continues.
    owner.settle_effect(expected_owner=current, permit=mine, settlement="reconciled")
    owner.recover_rebind_owner(expected_failed_owner=current, expected_current_owner=current)
    owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    assert owner.owner_status()["agent_session"] == actor
    empty = owner.inspect_enrollment(expected_owner=current, projection="effects")["effects"]
    assert empty["pending_permits"] == [] and empty["truncated"] is False


def test_an_attempt_that_never_left_the_process_is_named_and_settled(world, monkeypatch):
    import nodelang.native_agent_session as native
    owner, control = world.owner(EXTERNAL)
    actor = owner.owner_status()["agent_session"]
    world.restart()
    pinned, current = _fingerprints(owner)
    original, reads = native._read_descriptor, {"n": 0}

    def read(path, keys):  # the application is mid-restart for the attempt's own read
        reads["n"] += 1
        if reads["n"] == 2:
            raise MachineTransportError("existing runtime descriptor is unavailable")
        return original(path, keys)

    monkeypatch.setattr(native, "_read_descriptor", read)
    with pytest.raises(MachineTransportError, match="unavailable"):
        owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    status = owner.owner_status()
    assert (status["state"], status["rebind_pending"]) == ("uncertain", True)
    assert status["failed_attempt"] == {"kind": "rebind", "owner_fingerprint": current,
                                        "superseded": False, "request_sent": False, "request_id": None}

    recovered = owner.recover_rebind_owner(expected_failed_owner=current, expected_current_owner=current)
    assert (recovered["state"], recovered["continuation_outcome"], recovered["next"]) == (
        "bound", "not-sent", "native.owner_rebind")
    owner.rebind_owner(expected_old_owner=pinned, expected_new_owner=current)
    assert owner.owner_status()["agent_session"] == actor
    assert control.call("send_message", {"target": actor, "message": "back",
                                         "idempotency_key": "court-n1"})["ok"] is True
    with pytest.raises(MachineTransportError, match="custody changed"):
        owner.recover_rebind_owner(expected_failed_owner=current, expected_current_owner=current)
    # The unsent attempt never reached the application.
    assert world.bind_calls == [(EXTERNAL, None), (EXTERNAL, actor)]


def test_a_restarted_process_keeps_the_exact_actor_without_session_link(world):
    from nodelang import native_agent_mcp as mcp
    owner, control = world.owner(EXTERNAL)
    actor = owner.owner_status()["agent_session"]
    world.send(actor, "kept across the handoff", "court-h1")
    permit = _stale(world, actor)
    _lease_expires(world, actor)  # the old MCP process is gone; nothing released it
    current = owner.owner_status()["current"]["fingerprint"]

    calls = []
    fresh = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": EXTERNAL},
                               descriptor_path=world.root / "runtime.json", key_provider=KEY,
                               client_factory=_counting(calls), expected_agent_session=actor)
    server, activate = mcp.build_recovery_server(fresh)
    tools = lambda: {tool.name: tool for tool in server._tool_manager.list_tools()}

    # The unresolved permit keeps the continuation refused before enrollment.
    first = activate()
    assert (first["status"], first["reason"]) == ("recovery_required", "existing_owner_recovery_unconfirmed")
    assert fresh.state == "uncertain" and calls == [actor]
    tools()["native.owner_settle_effect"].fn(expected_owner=current, permit=permit, settlement="reconciled")
    reopened = tools()["native.connection_recover"].fn(expected_owner=current)
    assert (reopened["state"], reopened["connection_outcome"]) == ("unbound", "not-enrolled")

    assert activate()["status"] == "tools_available"
    status = fresh.owner_status()
    assert status["agent_session"] == actor and status["recovery_required"] is False and fresh._continued
    with fresh.bound_client() as client:
        sent = InstalledWorkshopCoordinationClient(client).call(
            "send_message", {"target": actor, "message": "after the handoff", "idempotency_key": "court-h2"})
    assert sent["ok"] is True
    # Only conditional continuations of the exact actor, never a plain enrollment.
    assert calls == [actor, actor] and _live_capabilities(world, actor) == 1
    with fresh.bound_client() as client:
        inbox = InstalledWorkshopCoordinationClient(client).call("read_messages", {"limit": 20})
    assert _messages(inbox).count("kept across the handoff") == 1

    # Control: a process naming another actor stays refused and issues nothing.
    foreign_calls = []
    foreign = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": EXTERNAL},
                                 descriptor_path=world.root / "runtime.json", key_provider=KEY,
                                 client_factory=_counting(foreign_calls),
                                 expected_agent_session="app:agent-session:runtime:" + "0" * 32)
    _, foreign_activate = mcp.build_recovery_server(foreign)
    assert foreign_activate()["status"] == "recovery_required"
    assert foreign_calls == [] and _live_capabilities(world, actor) == 1
