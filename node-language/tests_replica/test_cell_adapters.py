"""Security court for released adapters and exact user consent."""
import inspect
import pickle
import time

import pytest

from nodelang.cell_adapters import (
    UserConsentBroker,
    UserConsentDenied,
    UserConsentHandle,
    authorize_adapter_invocation,
    build_authorized_adapter_evidence,
    bootstrap_adapter_protocol,
    build_adapter_catalog,
    build_adapter_definition,
    build_permission_request,
    extend_adapter_catalog,
    grant_permission,
    read_permission,
    release_adapter_definition,
    revoke_permission,
    verify_adapter_catalog,
    verify_released_adapter,
)
from nodelang.cell_state_machine import (
    bootstrap_state_machine_protocol,
    build_evidence,
    build_state_machine,
    build_transition,
    read_state_machine,
    transition_machine,
)
from nodelang.cell_protocols import compose_relation_cells
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


@pytest.fixture()
def admitted():
    store = CellStore()
    protocol = bootstrap_adapter_protocol(store)
    user = Cell("user:founder", NULL_CELL_ID, NULL_CELL_ID, b"Founder")
    store.commit(store.revision, create=(user,))
    built = build_adapter_definition(
        store,
        protocol,
        adapter_id="adapter:fixture",
        name="Fixture storage boundary",
        actions=("read", "write"),
        locations=("file:///allowed/project", "file:///allowed/export"),
        datatypes=("T0-PUBLIC", "T1-INTERNAL"),
        evidence="adapter fixture court",
    )
    release_adapter_definition(store, protocol, built.root_id)
    catalog = build_adapter_catalog(
        store, protocol, (built.root_id,), catalog_id="adapter:catalog"
    )
    adapter = verify_released_adapter(store.snapshot(), protocol, built.root_id)
    return store, protocol, built, adapter, catalog, user.id


def _request(admitted, *, request_id="permission:fixture", expiry=None):
    store, protocol, built, adapter, catalog, user = admitted
    request = build_permission_request(
        store,
        protocol,
        catalog,
        request_id=request_id,
        adapter_root=built.root_id,
        user_root=user,
        action_roots=(adapter.action_roots[0],),
        location_roots=(adapter.location_roots[0],),
        datatype_roots=(adapter.datatype_roots[0],),
        expires_at=time.time() + 60 if expiry is None else expiry,
        max_invocations=2,
    )
    return request


def test_empty_allowlist_is_valid_and_denies_unknown_adapter():
    store = CellStore()
    protocol = bootstrap_adapter_protocol(store)
    catalog = build_adapter_catalog(store, protocol, catalog_id="empty-adapters")
    assert verify_adapter_catalog(
        store.snapshot(), protocol, catalog
    ).adapter_roots == ()
    user = Cell("user", NULL_CELL_ID, NULL_CELL_ID, b"User")
    store.commit(store.revision, create=(user,))
    with pytest.raises(InvalidCell, match="outside the allowlist"):
        build_permission_request(
            store, protocol, catalog,
            request_id="denied", adapter_root=protocol.root_id,
            user_root=user.id, action_roots=(protocol.root_id,),
            location_roots=(protocol.root_id,),
            datatype_roots=(protocol.root_id,),
            expires_at=time.time() + 60, max_invocations=1,
        )


def test_adapter_catalog_append_preserves_identity_and_digest():
    store = CellStore()
    protocol = bootstrap_adapter_protocol(store)
    first = build_adapter_definition(
        store,
        protocol,
        adapter_id="adapter:first",
        name="First",
        actions=("read",),
        locations=("local:first",),
        datatypes=("text",),
        evidence="first adapter court",
    )
    release_adapter_definition(store, protocol, first.root_id)
    catalog_root = build_adapter_catalog(
        store, protocol, (first.root_id,), catalog_id="adapter:catalog"
    )
    old_members = verify_adapter_catalog(
        store.snapshot(), protocol, catalog_root
    ).adapter_roots
    second = build_adapter_definition(
        store,
        protocol,
        adapter_id="adapter:second",
        name="Second",
        actions=("write",),
        locations=("local:second",),
        datatypes=("text",),
        evidence="second adapter court",
    )
    release_adapter_definition(store, protocol, second.root_id)

    migrated = extend_adapter_catalog(
        store, protocol, catalog_root, (first.root_id, second.root_id)
    )

    assert old_members == (first.root_id,)
    assert migrated.adapter_roots == (first.root_id, second.root_id)
    assert verify_adapter_catalog(
        store.snapshot(), protocol, catalog_root
    ).adapter_roots == migrated.adapter_roots


def test_request_cannot_exceed_released_adapter_bounds(admitted):
    store, protocol, built, adapter, catalog, user = admitted
    with pytest.raises(InvalidCell, match="location exceeds"):
        build_permission_request(
            store, protocol, catalog,
            request_id="permission:too-broad", adapter_root=built.root_id,
            user_root=user, action_roots=(adapter.action_roots[0],),
            location_roots=(protocol.root_id,),
            datatype_roots=(adapter.datatype_roots[0],),
            expires_at=time.time() + 60, max_invocations=1,
        )


def test_permission_cannot_be_granted_by_graph_text_or_forged_handle(admitted):
    request = _request(admitted)
    store, protocol, _, _, catalog, user = admitted
    broker = UserConsentBroker()
    with pytest.raises(UserConsentDenied):
        UserConsentHandle(object())
    with pytest.raises(UserConsentDenied, match="unknown"):
        grant_permission(
            store, protocol, catalog, request, broker, b"approved=true"
        )
    handle = broker.mint_from_user_gesture(request, user)
    with pytest.raises(TypeError):
        pickle.dumps(handle)
    grant_permission(store, protocol, catalog, request, broker, handle)
    with pytest.raises(UserConsentDenied, match="already used"):
        broker.consume(handle, request, user)


def test_grant_is_exact_rechecked_and_budgeted(admitted):
    request = _request(admitted)
    store, protocol, built, adapter, catalog, user = admitted
    broker = UserConsentBroker()
    grant_permission(
        store, protocol, catalog, request, broker,
        broker.mint_from_user_gesture(request, user),
    )
    permission = authorize_adapter_invocation(
        store.snapshot(), protocol, catalog, request,
        adapter_root=built.root_id, user_root=user,
        action_root=adapter.action_roots[0],
        location_root=adapter.location_roots[0],
        datatype_root=adapter.datatype_roots[0], invocation_count=0,
    )
    assert permission.root_id == request
    with pytest.raises(InvalidCell, match="denies action"):
        authorize_adapter_invocation(
            store.snapshot(), protocol, catalog, request,
            adapter_root=built.root_id, user_root=user,
            action_root=adapter.action_roots[1],
            location_root=adapter.location_roots[0],
            datatype_root=adapter.datatype_roots[0], invocation_count=0,
        )
    with pytest.raises(InvalidCell, match="budget is exhausted"):
        authorize_adapter_invocation(
            store.snapshot(), protocol, catalog, request,
            adapter_root=built.root_id, user_root=user,
            action_root=adapter.action_roots[0],
            location_root=adapter.location_roots[0],
            datatype_root=adapter.datatype_roots[0], invocation_count=2,
        )


def test_permission_drift_expiry_and_revocation_fail_closed(admitted):
    request = _request(admitted)
    store, protocol, built, adapter, catalog, user = admitted
    broker = UserConsentBroker()
    grant_permission(
        store, protocol, catalog, request, broker,
        broker.mint_from_user_gesture(request, user),
    )
    permission = read_permission(store.snapshot(), protocol, request)
    expires = store.read(permission.expires_at_root)
    store.commit(store.revision, replace=(Cell(
        expires.id, expires.link0, expires.link1,
        repr(time.time() + 3600).encode("ascii"),
    ),))
    with pytest.raises(InvalidCell, match="permission has drifted"):
        authorize_adapter_invocation(
            store.snapshot(), protocol, catalog, request,
            adapter_root=built.root_id, user_root=user,
            action_root=adapter.action_roots[0],
            location_root=adapter.location_roots[0],
            datatype_root=adapter.datatype_roots[0], invocation_count=0,
        )
    store.commit(store.revision, replace=(expires,))
    expires_at = float(expires.atom.decode("ascii"))
    with pytest.raises(InvalidCell, match="expired"):
        authorize_adapter_invocation(
            store.snapshot(), protocol, catalog, request,
            adapter_root=built.root_id, user_root=user,
            action_root=adapter.action_roots[0],
            location_root=adapter.location_roots[0],
            datatype_root=adapter.datatype_roots[0], invocation_count=0,
            now=expires_at,
        )
    revoke_permission(store, protocol, request)
    with pytest.raises(InvalidCell, match="not granted"):
        authorize_adapter_invocation(
            store.snapshot(), protocol, catalog, request,
            adapter_root=built.root_id, user_root=user,
            action_root=adapter.action_roots[0],
            location_root=adapter.location_roots[0],
            datatype_root=adapter.datatype_roots[0], invocation_count=0,
        )


def test_adapter_gate_has_no_filesystem_api_database_or_bim_dispatch():
    source = inspect.getsource(authorize_adapter_invocation).lower()
    for forbidden in ('"filesystem"', '"api"', '"database"', '"geometry"', '"bim"'):
        assert forbidden not in source


def test_adapter_can_admit_and_digest_an_external_graph_capability():
    store = CellStore()
    protocol = bootstrap_adapter_protocol(store, prefix="capability-adapter")
    store.commit(store.revision, create=(
        Cell("dimension:provider", NULL_CELL_ID, NULL_CELL_ID, b"provider"),
        Cell("dimension:model", NULL_CELL_ID, NULL_CELL_ID, b"model"),
        Cell("provider:exact", NULL_CELL_ID, NULL_CELL_ID, b"provider-a"),
        Cell("model:exact", NULL_CELL_ID, NULL_CELL_ID, b"model-a@sha256:1"),
    ))
    capability = compose_relation_cells((
        ("dimension:provider", "provider:exact"),
        ("dimension:model", "model:exact"),
    ), relation_id="capability:model:exact")
    store.commit(store.revision, create=capability.cells)
    adapter = build_adapter_definition(
        store,
        protocol,
        adapter_id="adapter:graph-capability",
        name="Exact model boundary",
        actions=("propose",),
        locations=(),
        location_roots=(capability.build.root_id,),
        datatypes=("proposal",),
        evidence="graph capability court",
    )
    release_adapter_definition(store, protocol, adapter.root_id)
    projected = verify_released_adapter(
        store.snapshot(), protocol, adapter.root_id
    )
    assert projected.location_roots == (capability.build.root_id,)

    model = store.read("model:exact")
    store.commit(store.revision, replace=(Cell(
        model.id, model.link0, model.link1, b"model-b@sha256:2"
    ),))
    with pytest.raises(InvalidCell, match="adapter has drifted"):
        verify_released_adapter(store.snapshot(), protocol, adapter.root_id)


def test_only_exactly_authorized_adapter_evidence_crosses_operational_gate(admitted):
    request = _request(admitted)
    store, protocol, built, adapter, catalog, user = admitted
    consent = UserConsentBroker()
    grant_permission(
        store, protocol, catalog, request, consent,
        consent.mint_from_user_gesture(request, user),
    )
    operational = bootstrap_state_machine_protocol(
        store, prefix="operational"
    )
    roots = {
        "state:pending": b"Pending",
        "state:committed": b"Committed",
        "event:commit": b"Commit",
        "evidence-type:adapter-confirmation": b"Adapter confirmation",
        "actor": b"Actor",
    }
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
        for root, atom in roots.items()
    ))
    transition = build_transition(
        store, operational, transition_id="operational:commit",
        from_state_root="state:pending", to_state_root="state:committed",
        event_root="event:commit",
        required_evidence_type_roots=("evidence-type:adapter-confirmation",),
    )
    machine = build_state_machine(
        store, operational, machine_id="operational:machine",
        state_roots=("state:pending", "state:committed"),
        transition_roots=(transition,), initial_state_root="state:pending",
    )
    forged = build_evidence(
        store, operational, evidence_id="evidence:forged",
        evidence_type_root="evidence-type:adapter-confirmation",
        payload=b"committed", issuer_root=user,
    )
    with pytest.raises(InvalidCell, match="issuer is not trusted"):
        transition_machine(
            store, operational, machine,
            event_root="event:commit", expected_state_root="state:pending",
            actor_root="actor", evidence_roots=(forged,),
            trusted_issuer_roots=(built.root_id,),
        )

    evidence = build_authorized_adapter_evidence(
        store, protocol, catalog, request, operational,
        adapter_root=built.root_id, user_root=user,
        action_root=adapter.action_roots[0],
        location_root=adapter.location_roots[0],
        datatype_root=adapter.datatype_roots[0], invocation_count=0,
        evidence_id="evidence:authorized",
        evidence_type_root="evidence-type:adapter-confirmation",
        payload=b"committed",
    )
    transition_machine(
        store, operational, machine,
        event_root="event:commit", expected_state_root="state:pending",
        actor_root="actor", evidence_roots=(evidence,),
        trusted_issuer_roots=(built.root_id,),
    )
    assert read_state_machine(
        store.snapshot(), operational, machine
    ).current_state_root == "state:committed"
