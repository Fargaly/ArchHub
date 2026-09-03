from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodelang.cell_adapters import (
    UserConsentBroker,
    bootstrap_adapter_protocol,
    build_adapter_catalog,
    build_adapter_definition,
    build_permission_request,
    grant_permission,
    release_adapter_definition,
)
from nodelang.cell_baboom_connector_execution import (
    bootstrap_baboom_connector_execution_protocol,
    create_connector_delegation,
    create_connector_execution_grant,
    create_connector_execution_receipt,
    read_connector_execution_receipt,
    register_connector_provider,
)
from nodelang.cell_protocols import read_relation
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID


def _terminal(store: CellStore, root: str, value: str) -> None:
    snapshot = store.snapshot()
    store.commit(
        snapshot.revision,
        create=(Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8")),),
    )


def _world():
    store = CellStore()
    protocol = bootstrap_baboom_connector_execution_protocol(store)
    adapters = bootstrap_adapter_protocol(store, prefix="court:connector-adapter")
    adapter = build_adapter_definition(
        store,
        adapters,
        adapter_id="court:adapter:teams-meetings",
        name="Court Teams meeting reader",
        actions=("read-calendar",),
        locations=("graph.microsoft.com",),
        datatypes=("internal-metadata", "internal-text"),
        evidence="bounded connector execution with redacted receipts",
    )
    release_adapter_definition(store, adapters, adapter.root_id)
    catalog = build_adapter_catalog(
        store,
        adapters,
        (adapter.root_id,),
        catalog_id="court:connector-adapter:catalog",
    )
    adapter_members = read_relation(store.snapshot(), adapter.root_id, budget=100_000)
    action_root = next(
        member.participant_id
        for member in adapter_members
        if member.role_id == adapters.role("action")
    )
    location_root = next(
        member.participant_id
        for member in adapter_members
        if member.role_id == adapters.role("location")
    )
    datatype_roots = tuple(
        member.participant_id
        for member in adapter_members
        if member.role_id == adapters.role("datatype")
    )
    provider = register_connector_provider(
        store,
        protocol,
        adapters,
        provider_id="court:connector-provider:teams-meetings",
        adapter_root=adapter.root_id,
        action_root=action_root,
        location_root=location_root,
        datatype_roots=datatype_roots,
        operation="teams.list_meetings",
    )
    for root in ("court:founder", "court:session", "court:work"):
        _terminal(store, root, root)
    return store, protocol, adapters, catalog, provider


def test_connector_delegation_requires_exact_permission_and_settles_once():
    store, protocol, adapters, catalog, provider = _world()
    expires_at = time.time() + 120
    permission = build_permission_request(
        store,
        adapters,
        catalog,
        request_id="court:connector-permission",
        adapter_root=provider.adapter_root,
        user_root="court:founder",
        action_roots=(provider.action_root,),
        location_roots=(provider.location_root,),
        datatype_roots=(provider.datatype_roots[0],),
        expires_at=expires_at,
        max_invocations=1,
    )
    raw_input = b'{"limit":5,"meeting":"Confidential design review"}'
    input_digest = hashlib.sha256(raw_input).hexdigest()
    delegation = create_connector_delegation(
        store,
        protocol,
        adapters,
        delegation_id="court:connector-delegation",
        session_root="court:session",
        work_root="court:work",
        provider_root=provider.root_id,
        input_digest=input_digest,
        input_bytes=len(raw_input),
        datatype_root=provider.datatype_roots[0],
        permission_root=permission,
        expires_at=expires_at,
    )
    assert "Confidential design review" not in repr(store.snapshot().cells)
    consent = UserConsentBroker()
    grant_permission(
        store,
        adapters,
        catalog,
        permission,
        consent,
        consent.mint_from_user_gesture(permission, "court:founder"),
    )
    grant = create_connector_execution_grant(
        store,
        protocol,
        adapters,
        grant_id="court:connector-grant",
        delegation_root=delegation.root_id,
        session_root="court:session",
        expires_at=expires_at,
        token_digest=hashlib.sha256(b"unforgeable-connector-token").hexdigest(),
    )
    with pytest.raises(InvalidCell, match="failed connector receipt error code"):
        create_connector_execution_receipt(
            store,
            protocol,
            adapters,
            receipt_id="court:connector-receipt:unsafe-error",
            delegation_root=delegation.root_id,
            grant_root=grant.root_id,
            provider_root=provider.root_id,
            input_digest=input_digest,
            input_bytes=len(raw_input),
            output_digest=hashlib.sha256(b"").hexdigest(),
            output_bytes=0,
            outcome="failed",
            error_code="Confidential design review could not be retrieved",
        )
    receipt = create_connector_execution_receipt(
        store,
        protocol,
        adapters,
        receipt_id="court:connector-receipt",
        delegation_root=delegation.root_id,
        grant_root=grant.root_id,
        provider_root=provider.root_id,
        input_digest=input_digest,
        input_bytes=len(raw_input),
        output_digest=hashlib.sha256(b"two meetings").hexdigest(),
        output_bytes=12,
        outcome="succeeded",
    )
    assert receipt.operation == "teams.list_meetings"
    assert read_connector_execution_receipt(
        store.snapshot(), protocol, adapters, receipt.root_id
    ) == receipt
    with pytest.raises(InvalidCell, match="already has a settled receipt"):
        create_connector_execution_receipt(
            store,
            protocol,
            adapters,
            receipt_id="court:connector-receipt:replay",
            delegation_root=delegation.root_id,
            grant_root=grant.root_id,
            provider_root=provider.root_id,
            input_digest=input_digest,
            input_bytes=len(raw_input),
            output_digest=hashlib.sha256(b"replay").hexdigest(),
            output_bytes=6,
            outcome="succeeded",
        )


def test_connector_delegation_rejects_provider_data_class_drift():
    store, protocol, adapters, catalog, provider = _world()
    expires_at = time.time() + 120
    permission = build_permission_request(
        store,
        adapters,
        catalog,
        request_id="court:connector-permission:drift",
        adapter_root=provider.adapter_root,
        user_root="court:founder",
        action_roots=(provider.action_root,),
        location_roots=(provider.location_root,),
        datatype_roots=(provider.datatype_roots[0],),
        expires_at=expires_at,
        max_invocations=1,
    )
    with pytest.raises(InvalidCell, match="permission binding drifted"):
        create_connector_delegation(
            store,
            protocol,
            adapters,
            delegation_id="court:connector-delegation:drift",
            session_root="court:session",
            work_root="court:work",
            provider_root=provider.root_id,
            input_digest=hashlib.sha256(b"meeting request").hexdigest(),
            input_bytes=15,
            datatype_root=provider.datatype_roots[1],
            permission_root=permission,
            expires_at=expires_at,
        )
