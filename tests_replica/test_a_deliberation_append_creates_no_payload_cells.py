"""A deliberation append records a decision. Its payload is not the graph.

Measured 2026-09-28 on the founder's newest closed backup
(20260928-1228-b21c5c3): 2,661,115 of 6,708,218 head Cells -- 39.7% -- were
`app:deliberation-payload:*` ValueGraph Cells, one tree per ledger entry,
written by POST /api/universal/deliberation. The head keeps every Cell it is
given (CellStore.commit creates and replaces; nothing removes), so each one
is paid on every boot from then on.

SPEC 3.3 (founder, 2026-09-22): per-event evidence and audit history live in
bounded indexed records in the same primary database, referenced by their
graph-owned owner, never as a new composition per event.

This court holds the outcome, not a mechanism: an append adds the entry's
own bounded composition and nothing that grows with what it carries. The
2.66M Cells already written stay as legacy evidence; a key first written
as a ValueGraph still replays and reads back exactly as before.
"""
from __future__ import annotations

import hashlib

import pytest

import nodelang.runtime_presence_lease_storage as record_storage
from nodelang import commit_intent
from nodelang.application_server import ApplicationServer
from nodelang.cell_deliberation import (
    append_deliberation_entry,
    append_deliberation_value_entry,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider


PAYLOAD_PREFIX = "app:deliberation-payload"
RECORD_STORE = "app:deliberation-record-store:v1"


@pytest.fixture(scope="module")
def memory_server():
    server = ApplicationServer()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture(scope="module")
def file_server(tmp_path_factory):
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    server = ApplicationServer(
        universal_state_path=tmp_path_factory.mktemp("ledger") / "graph.sqlite3",
        universal_key_provider=provider,
        enable_machine_transport=False,
        enable_universal_cloud_gateway=False,
        live_watch=False,
    ).start()
    try:
        yield server
    finally:
        server.close()


@pytest.fixture(params=["memory_server", "file_server"])
def either_server(request):
    return request.getfixturevalue(request.param)


@pytest.fixture(params=["memory", "file"])
def fresh_server(request, tmp_path):
    """A graph whose only payload records are the ones this test writes."""
    if request.param == "memory":
        server = ApplicationServer()
    else:
        provider = MemorySigningKeyProvider(
            "archhub.local.relationship-authority", b"r" * 32
        )
        provider.add_key("archhub.local.court-attestation", b"c" * 32)
        server = ApplicationServer(
            universal_state_path=tmp_path / "graph.sqlite3",
            universal_key_provider=provider,
            enable_machine_transport=False,
            enable_universal_cloud_gateway=False,
            live_watch=False,
        ).start()
    try:
        yield server
    finally:
        server.close()


def _route(server, method, body):
    return server.dispatch_universal_machine_route(
        {"method": method, "path": "/api/universal/deliberation", "body": body}
    )


def _body(server, key, payload):
    registry = server.universal_registry
    return {
        "space": registry.brain_control_ledger_root,
        "category": registry.brain_control_category_roots["run-report"],
        "summary": "Run report " + key,
        "payload": payload,
        "idempotency_key": key,
        "created_at": "2026-09-28T12:00:00+00:00",
    }


def _append(server, key, payload):
    return _route(server, "POST", _body(server, key, payload))


def _read(server, root):
    listed = _route(server, "GET", {
        "space": server.universal_registry.brain_control_ledger_root,
        "limit": 500,
    })
    [entry] = [row for row in listed["entries"] if row["root"] == root]
    return entry


def _cells(server):
    return set(server.universal_store.snapshot().cells)


def _report(items):
    return {
        "owner": "founder",
        "checks": [
            {"name": "check-%03d" % index, "green": index % 3 != 0}
            for index in range(items)
        ],
    }


def _payload_root(server, key):
    space = server.universal_registry.brain_control_ledger_root
    return PAYLOAD_PREFIX + ":" + hashlib.sha256(
        (space + "\0" + key).encode("utf-8")
    ).hexdigest()


def test_an_append_writes_no_payload_cells(either_server):
    before = _cells(either_server)

    _append(either_server, "court:no-payload-cells", _report(20))

    written = _cells(either_server) - before
    assert written, "the ledger entry itself is still a graph composition"
    assert not [cell for cell in written if cell.startswith(PAYLOAD_PREFIX)]


def test_what_an_append_writes_does_not_grow_with_its_payload(memory_server):
    _append(memory_server, "court:warm-up", _report(1))
    before = _cells(memory_server)
    _append(memory_server, "court:small", _report(1))
    small = _cells(memory_server) - before

    before = _cells(memory_server)
    _append(memory_server, "court:large", _report(20))
    large = _cells(memory_server) - before

    assert len(large) == len(small)


def test_the_payload_still_reads_back_whole(either_server):
    payload = _report(10)
    created = _append(either_server, "court:reads-back", payload)

    entry = _read(either_server, created["root"])

    assert entry["payload"] == payload
    assert entry["idempotency_key"] == "court:reads-back"
    # The entry itself states where what it carried lives.
    assert entry["reference_roots"] == [RECORD_STORE]
    assert "payload_expired" not in entry


def test_a_replay_writes_nothing_and_a_reused_key_writes_nothing(either_server):
    payload = _report(5)
    first = _append(either_server, "court:replay", payload)
    before, revision = _cells(either_server), either_server.universal_store.revision

    again = _append(either_server, "court:replay", payload)

    assert again["root"] == first["root"]
    assert again["payload_root"] == first["payload_root"]
    assert either_server.universal_store.revision == revision
    assert _cells(either_server) == before

    with pytest.raises(Exception, match="reused for another value"):
        _append(either_server, "court:replay", _report(6))
    assert either_server.universal_store.revision == revision
    assert _cells(either_server) == before
    assert _read(either_server, first["root"])["payload"] == payload


def test_true_one_and_one_point_zero_are_three_different_values(either_server):
    _append(either_server, "court:scalar-types", {"green": True})
    revision = either_server.universal_store.revision

    for changed in ({"green": 1}, {"green": 1.0}):
        with pytest.raises(Exception, match="reused for another value"):
            _append(either_server, "court:scalar-types", changed)

    assert either_server.universal_store.revision == revision


def test_a_key_first_written_as_a_value_graph_still_replays(either_server):
    registry = either_server.universal_registry
    key, payload = "court:legacy-value-graph", _report(3)
    body = _body(either_server, key, payload)
    # Written the way the old build wrote every payload, as a declared action.
    with commit_intent.declare(
        commit_intent.USER_ACTION, actor="court",
        reason="an entry written while payloads were ValueGraphs",
    ):
        legacy, legacy_root, _ = append_deliberation_value_entry(
            either_server.universal_store,
            registry.deliberation_protocol,
            registry.value_graph_protocol,
            space_root=body["space"],
            actor_root=registry.authorization.subject_root,
            category_root=body["category"],
            content=body["summary"],
            payload=payload,
            payload_root=_payload_root(either_server, key),
            idempotency_key=key,
            created_at=body["created_at"],
            authorization_protocol=registry.authorization.protocol,
            authentication_broker=registry.authorization.broker,
            authentication_context=registry.authorization.session.context(),
        )
    before, revision = _cells(either_server), either_server.universal_store.revision

    again = _append(either_server, key, payload)

    assert again["root"] == legacy.root_id
    assert again["payload_root"] == legacy_root
    assert either_server.universal_store.revision == revision
    assert _cells(either_server) == before
    assert _read(either_server, legacy.root_id)["payload"] == payload


def test_a_retry_after_a_failed_commit_carries_its_own_value(either_server):
    """A record no committed entry references is not yet anyone's evidence."""
    key = "court:orphaned-record"
    body = _body(either_server, key, {"attempt": 1})
    records = either_server._ownership_record_storage()
    records.put_record(
        "deliberation-payload",
        _payload_root(either_server, key),
        owner_root=either_server.universal_registry.authorization.subject_root,
        state="recorded",
        payload={"space": body["space"], "category": body["category"],
                 "entry": "never-committed", "value": {"attempt": 1}},
        authority_revision=either_server.universal_store.revision,
        updated_at=0.0,
        create_only=True,
    )

    created = _append(either_server, key, {"attempt": 2})

    assert _read(either_server, created["root"])["payload"] == {"attempt": 2}


def test_a_retired_payload_reads_as_expired_never_as_null(fresh_server, monkeypatch):
    """SPEC 3.6: purged content is reported as expired, not an empty read."""
    first = _append(fresh_server, "court:retired", {"attempt": "first"})
    # The record kind's bound, lowered so the next append retires the oldest.
    monkeypatch.setattr(record_storage, "_OPERATIONAL_RECORD_LIMIT", 1)
    second = _append(fresh_server, "court:kept", {"attempt": "second"})

    retired = _read(fresh_server, first["root"])
    kept = _read(fresh_server, second["root"])

    assert retired["payload"] is None
    assert retired["payload_expired"] is True
    assert kept["payload"] == {"attempt": "second"}
    assert "payload_expired" not in kept
    revision = fresh_server.universal_store.revision
    with pytest.raises(Exception, match="expired"):
        _append(fresh_server, "court:retired", {"attempt": "first"})
    assert fresh_server.universal_store.revision == revision


def test_an_entry_that_carried_nothing_never_reads_as_expired(either_server):
    registry = either_server.universal_registry
    body = _body(either_server, "court:text-only", None)
    with commit_intent.declare(
        commit_intent.USER_ACTION, actor="court",
        reason="a ledger entry that carries no payload",
    ):
        entry = append_deliberation_entry(
            either_server.universal_store,
            registry.deliberation_protocol,
            space_root=body["space"],
            actor_root=registry.authorization.subject_root,
            category_root=body["category"],
            content="Text only",
            idempotency_key="court:text-only",
            created_at=body["created_at"],
            authorization_protocol=registry.authorization.protocol,
            authentication_broker=registry.authorization.broker,
            authentication_context=registry.authorization.session.context(),
        )

    read = _read(either_server, entry.root_id)

    assert read["payload"] is None
    assert "payload_expired" not in read


def _record(server, key):
    return server._ownership_record_storage().get_record(
        "deliberation-payload", _payload_root(server, key)
    )


def test_a_payload_over_the_record_bound_is_refused_plainly(either_server):
    """A reader receives at most 64 KiB of any payload; storing a megabyte
    only fills the record table. The refusal says what to do instead."""
    before, revision = _cells(either_server), either_server.universal_store.revision

    with pytest.raises(Exception, match=r"over the \d+-byte bound; record a summary"):
        _append(either_server, "court:too-large", {"report": "x" * (300 * 1024)})

    assert either_server.universal_store.revision == revision
    assert _cells(either_server) == before
    assert _record(either_server, "court:too-large") is None


def test_a_payload_inside_the_bound_is_kept_whole(either_server):
    payload = {"report": "y" * (200 * 1024)}
    created = _append(either_server, "court:inside-bound", payload)

    assert _record(either_server, "court:inside-bound")["payload"]["value"] == payload
    # The read projects it; the record keeps every byte.
    assert _read(either_server, created["root"])["payload_truncated"] is True


def test_a_record_naming_another_entry_is_an_integrity_failure_not_expired(either_server):
    key = "court:integrity"
    created = _append(either_server, key, {"attempt": 1})
    held = _record(either_server, key)
    either_server._ownership_record_storage().put_record(
        "deliberation-payload",
        _payload_root(either_server, key),
        owner_root=held["owner_root"],
        state="recorded",
        payload={**held["payload"], "entry": "someone-else"},
        authority_revision=either_server.universal_store.revision,
        updated_at=held["updated_at"],
        expected_generation=held["generation"],
    )

    read = _read(either_server, created["root"])

    assert read["payload"] is None
    assert read["payload_integrity_failed"] is True
    assert "payload_expired" not in read
    revision = either_server.universal_store.revision
    with pytest.raises(Exception, match="integrity"):
        _append(either_server, key, {"attempt": 1})
    assert either_server.universal_store.revision == revision

