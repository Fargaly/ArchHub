"""Security court for the universal cell's unavoidable host boundary."""
import pickle
import time

import pytest

from nodelang.capabilities import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityHandle,
    CapabilityPolicy,
    read_capability_events,
    read_capability_grant,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _store_with_request():
    store = CellStore()
    store.commit(store.revision, create=[
        Cell("request", NULL_CELL_ID, NULL_CELL_ID, b"opaque request"),
        Cell("authority", NULL_CELL_ID, NULL_CELL_ID, b"governed authority"),
        Cell("result", NULL_CELL_ID, NULL_CELL_ID, b"opaque result"),
        Cell("session", NULL_CELL_ID, NULL_CELL_ID, b"runtime session"),
        Cell("device", NULL_CELL_ID, NULL_CELL_ID, b"runtime device"),
    ])
    return store


def _policy(*, max_invocations=10, expires_at=None):
    return CapabilityPolicy(
        policy_id="policy:fixture",
        request_roots=frozenset({"request"}),
        authority_roots=frozenset({"authority"}),
        expires_at=time.time() + 60 if expires_at is None else expires_at,
        max_invocations=max_invocations,
    )


def test_capability_is_unforgeable_runtime_possession_not_atom_text():
    store = _store_with_request()
    broker = CapabilityBroker()
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: "result", _policy()
    )
    assert broker.invoke(handle, store.snapshot(), "request", "authority") == "result"

    forged_text = Cell(
        "forged", NULL_CELL_ID, NULL_CELL_ID, repr(handle).encode("utf-8")
    )
    store.commit(store.revision, create=[forged_text])
    with pytest.raises(CapabilityDenied):
        broker.invoke(store.read("forged").atom, store.snapshot(), "request", "authority")


def test_live_handle_cannot_be_serialized_into_graph_or_pickle():
    broker = CapabilityBroker()
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: request_root, _policy()
    )
    with pytest.raises(TypeError):
        pickle.dumps(handle)
    with pytest.raises(TypeError):
        Cell("bad", NULL_CELL_ID, NULL_CELL_ID, handle)


def test_constructor_cannot_mint_a_handle_and_other_broker_rejects_it():
    broker = CapabilityBroker()
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: request_root, _policy()
    )
    with pytest.raises(CapabilityDenied):
        CapabilityHandle(object())
    with pytest.raises(CapabilityDenied):
        CapabilityBroker().invoke(
            handle, _store_with_request().snapshot(), "request", "authority"
        )


def test_revocation_is_immediate_and_auditable_without_secret_material():
    store = _store_with_request()
    broker = CapabilityBroker()
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: "result", _policy()
    )
    assert broker.invoke(handle, store.snapshot(), "request", "authority") == "result"
    broker.revoke(handle)
    with pytest.raises(CapabilityDenied):
        broker.invoke(handle, store.snapshot(), "request", "authority")
    events = broker.audit()
    assert [event.outcome for event in events] == ["allowed", "denied"]
    assert all(event.handle_fingerprint for event in events)
    assert repr(handle) not in repr(events)


def test_scope_expiry_and_use_budget_are_deny_by_default():
    store = _store_with_request()
    broker = CapabilityBroker()
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: "result",
        _policy(max_invocations=1),
    )
    assert broker.invoke(
        handle, store.snapshot(), "request", "authority"
    ) == "result"
    with pytest.raises(CapabilityDenied, match="budget-exhausted"):
        broker.invoke(handle, store.snapshot(), "request", "authority")

    expired = broker.mint(
        lambda snapshot, request_root, authority_root: "result",
        _policy(expires_at=time.time() - 1),
    )
    with pytest.raises(CapabilityDenied, match="expired"):
        broker.invoke(expired, store.snapshot(), "request", "authority")

    scoped = broker.mint(
        lambda snapshot, request_root, authority_root: "result", _policy()
    )
    with pytest.raises(CapabilityDenied, match="request-out-of-scope"):
        broker.invoke(scoped, store.snapshot(), "result", "authority")
    with pytest.raises(CapabilityDenied, match="authority-out-of-scope"):
        broker.invoke(scoped, store.snapshot(), "request", "result")
    assert [event.reason for event in broker.audit()][-4:] == [
        "budget-exhausted", "expired", "request-out-of-scope",
        "authority-out-of-scope",
    ]


def test_audit_memory_is_bounded_and_contains_no_live_handle():
    store = _store_with_request()
    broker = CapabilityBroker(audit_limit=2)
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: "result",
        _policy(max_invocations=1),
    )
    broker.invoke(handle, store.snapshot(), "request", "authority")
    for _ in range(3):
        with pytest.raises(CapabilityDenied):
            broker.invoke(handle, store.snapshot(), "request", "authority")
    assert len(broker.audit()) == 2
    assert all(event.reason == "budget-exhausted" for event in broker.audit())
    assert repr(handle) not in repr(broker.audit())


def test_cell_backed_capability_grant_and_events_are_visible_graph_facts():
    store = _store_with_request()
    broker = CapabilityBroker(store=store)
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: "result",
        CapabilityPolicy(
            policy_id="policy:graph-backed",
            request_roots=frozenset({"request"}),
            authority_roots=frozenset({"authority"}),
            session_roots=frozenset({"session"}),
            device_roots=frozenset({"device"}),
            data_classes=frozenset({"T1:internal"}),
            expires_at=time.time() + 60,
            max_invocations=2,
        ),
    )
    protocol = broker.protocol
    assert protocol is not None
    grant_root = next(
        root for root in store.snapshot().cells
        if root.startswith("capability-grant:sha256:")
        and root.count(":") == 2
    )
    grant = read_capability_grant(store.snapshot(), protocol, grant_root)
    assert grant.policy_id == "policy:graph-backed"
    assert grant.request_scope_roots == ("request",)
    assert grant.authority_scope_roots == ("authority",)
    assert grant.session_scope_roots == ("session",)
    assert grant.device_scope_roots == ("device",)
    assert grant.data_class_scope == ("T1:internal",)
    assert grant.invocation_count == 0
    assert grant.state_root == protocol.grant_states["active"]
    assert grant.handle_fingerprint_digest != handle.fingerprint

    encoded_atoms = b"\n".join(
        cell.atom for cell in store.snapshot().cells.values()
    )
    assert handle.fingerprint.encode("ascii") not in encoded_atoms
    assert repr(handle).encode("utf-8") not in encoded_atoms

    assert broker.invoke(handle, store.snapshot(), "request", "authority") == "result"
    grant = read_capability_grant(store.snapshot(), protocol, grant_root)
    assert grant.invocation_count == 1
    events = read_capability_events(store.snapshot(), protocol)
    assert [(event.outcome, event.reason) for event in events] == [
        ("allowed", "")
    ]
    assert events[0].grant_root == grant.root_id
    assert events[0].request_root == "request"
    assert events[0].authority_root == "authority"
    assert events[0].result_root == "result"


def test_cell_backed_denial_and_revocation_are_graph_auditable():
    store = _store_with_request()
    broker = CapabilityBroker(store=store)
    handle = broker.mint(
        lambda snapshot, request_root, authority_root: "result",
        _policy(max_invocations=1),
    )
    protocol = broker.protocol
    assert protocol is not None
    grant_root = next(
        root for root in store.snapshot().cells
        if root.startswith("capability-grant:sha256:")
        and root.count(":") == 2
    )

    assert broker.invoke(handle, store.snapshot(), "request", "authority") == "result"
    with pytest.raises(CapabilityDenied, match="budget-exhausted"):
        broker.invoke(handle, store.snapshot(), "request", "authority")
    broker.revoke(handle)
    with pytest.raises(CapabilityDenied, match="revoked"):
        broker.invoke(handle, store.snapshot(), "request", "authority")

    grant = read_capability_grant(store.snapshot(), protocol, grant_root)
    assert grant.state_root == protocol.grant_states["revoked"]
    assert [(event.outcome, event.reason) for event in read_capability_events(
        store.snapshot(), protocol
    )] == [
        ("allowed", ""),
        ("denied", "budget-exhausted"),
        ("denied", "revoked"),
    ]
