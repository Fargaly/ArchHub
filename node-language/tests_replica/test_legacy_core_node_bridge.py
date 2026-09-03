"""Legacy host/doc/chat core nodes must map to Cell execution boundaries."""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodelang.cell_adapters import (  # noqa: E402
    UserConsentBroker,
    bootstrap_adapter_protocol,
    build_permission_request,
    grant_permission,
    verify_adapter_catalog,
)
from nodelang.cell_baboom_connector_execution import (  # noqa: E402
    bootstrap_baboom_connector_execution_protocol,
    create_connector_delegation,
    create_connector_execution_grant,
    create_connector_execution_receipt,
    read_connector_execution_receipt,
)
from nodelang.cell_baboom_model_execution import (  # noqa: E402
    bootstrap_baboom_model_execution_protocol,
    create_model_delegation,
    create_model_execution_grant,
    create_model_execution_receipt,
    read_model_execution_receipt,
)
from nodelang.cell_legacy_core_nodes import (  # noqa: E402
    DOC_FAMILIES,
    HOST_FAMILIES,
    build_legacy_core_node_authority,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID  # noqa: E402
import nodelang.cell_legacy_core_nodes as bridge_module  # noqa: E402


def _terminal(store: CellStore, root: str) -> None:
    store.commit(
        store.revision,
        create=(Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("utf-8")),),
    )


def _world():
    store = CellStore()
    adapters = bootstrap_adapter_protocol(store, prefix="legacy-core:test:adapter")
    connectors = bootstrap_baboom_connector_execution_protocol(
        store, prefix="legacy-core:test:connector"
    )
    models = bootstrap_baboom_model_execution_protocol(
        store, prefix="legacy-core:test:model"
    )
    authority = build_legacy_core_node_authority(
        store, adapters, connectors, models
    )
    for root in ("user:founder", "session:founder", "work:leaf"):
        _terminal(store, root)
    return store, adapters, connectors, models, authority


def _grant_permission(store, adapters, catalog_root, provider, *, request_id):
    expires_at = time.time() + 120
    permission = build_permission_request(
        store,
        adapters,
        catalog_root,
        request_id=request_id,
        adapter_root=provider.adapter_root,
        user_root="user:founder",
        action_roots=(provider.action_root,),
        location_roots=(provider.location_root,),
        datatype_roots=(provider.datatype_roots[0],),
        expires_at=expires_at,
        max_invocations=1,
    )
    consent = UserConsentBroker()
    grant_permission(
        store,
        adapters,
        catalog_root,
        permission,
        consent,
        consent.mint_from_user_gesture(permission, "user:founder"),
    )
    return permission, expires_at


def test_legacy_core_node_families_publish_exact_cell_providers():
    store, adapters, _connectors, _models, authority = _world()
    connector_catalog = verify_adapter_catalog(
        store.snapshot(), adapters, authority.connector_catalog_root
    )
    model_catalog = verify_adapter_catalog(
        store.snapshot(), adapters, authority.model_catalog_root
    )

    assert set(authority.host_providers) == set(HOST_FAMILIES)
    assert set(authority.document_providers) == set(DOC_FAMILIES)
    assert len(connector_catalog.adapter_roots) == (
        len(HOST_FAMILIES) + len(DOC_FAMILIES)
    )
    assert model_catalog.adapter_roots == (
        authority.conversation_provider.adapter_root,
    )
    assert authority.host_providers["revit"].operation == "host.revit.dispatch"
    assert authority.document_providers["ifc"].operation == "document.ifc.read"


def test_host_provider_delegation_requires_permission_grant_and_redacted_receipt():
    store, adapters, connectors, _models, authority = _world()
    provider = authority.host_providers["revit"]
    permission, expires_at = _grant_permission(
        store,
        adapters,
        authority.connector_catalog_root,
        provider,
        request_id="permission:host:revit",
    )
    raw_input = b'{"action":"open","path":"secret-client-model.rvt"}'
    input_digest = hashlib.sha256(raw_input).hexdigest()
    delegation = create_connector_delegation(
        store,
        connectors,
        adapters,
        delegation_id="delegation:host:revit",
        session_root="session:founder",
        work_root="work:leaf",
        provider_root=provider.root_id,
        input_digest=input_digest,
        input_bytes=len(raw_input),
        datatype_root=provider.datatype_roots[0],
        permission_root=permission,
        expires_at=expires_at,
    )
    grant = create_connector_execution_grant(
        store,
        connectors,
        adapters,
        grant_id="grant:host:revit",
        delegation_root=delegation.root_id,
        session_root="session:founder",
        expires_at=expires_at,
        token_digest=hashlib.sha256(b"host-token").hexdigest(),
    )
    receipt = create_connector_execution_receipt(
        store,
        connectors,
        adapters,
        receipt_id="receipt:host:revit",
        delegation_root=delegation.root_id,
        grant_root=grant.root_id,
        provider_root=provider.root_id,
        input_digest=input_digest,
        input_bytes=len(raw_input),
        output_digest=hashlib.sha256(b"host ok").hexdigest(),
        output_bytes=7,
        outcome="succeeded",
    )

    assert read_connector_execution_receipt(
        store.snapshot(), connectors, adapters, receipt.root_id
    ).operation == "host.revit.dispatch"
    assert "secret-client-model" not in repr(store.snapshot().cells)
    with pytest.raises(InvalidCell, match="already has a settled receipt"):
        create_connector_execution_receipt(
            store,
            connectors,
            adapters,
            receipt_id="receipt:host:revit:replay",
            delegation_root=delegation.root_id,
            grant_root=grant.root_id,
            provider_root=provider.root_id,
            input_digest=input_digest,
            input_bytes=len(raw_input),
            output_digest=hashlib.sha256(b"replay").hexdigest(),
            output_bytes=6,
            outcome="succeeded",
        )


def test_conversation_provider_uses_model_delegation_with_redacted_receipt():
    store, adapters, _connectors, models, authority = _world()
    provider = authority.conversation_provider
    expires_at = time.time() + 120
    permission = build_permission_request(
        store,
        adapters,
        authority.model_catalog_root,
        request_id="permission:conversation",
        adapter_root=provider.adapter_root,
        user_root="user:founder",
        action_roots=(provider.action_root,),
        location_roots=(provider.location_root,),
        datatype_roots=(provider.datatype_roots[0],),
        expires_at=expires_at,
        max_invocations=1,
    )
    input_digest = hashlib.sha256(b"private prompt").hexdigest()
    delegation = create_model_delegation(
        store,
        models,
        adapters,
        delegation_id="delegation:conversation",
        session_root="session:founder",
        work_root="work:leaf",
        provider_root=provider.root_id,
        model="router-auto",
        input_digest=input_digest,
        datatype_root=provider.datatype_roots[0],
        permission_root=permission,
        expires_at=expires_at,
    )
    consent = UserConsentBroker()
    grant_permission(
        store,
        adapters,
        authority.model_catalog_root,
        permission,
        consent,
        consent.mint_from_user_gesture(permission, "user:founder"),
    )
    grant = create_model_execution_grant(
        store,
        models,
        adapters,
        grant_id="grant:conversation",
        delegation_root=delegation.root_id,
        session_root="session:founder",
        expires_at=expires_at,
        token_digest=hashlib.sha256(b"model-token").hexdigest(),
    )
    receipt = create_model_execution_receipt(
        store,
        models,
        adapters,
        receipt_id="receipt:conversation",
        delegation_root=delegation.root_id,
        grant_root=grant.root_id,
        provider_root=provider.root_id,
        model="router-auto",
        input_digest=input_digest,
        output_digest=hashlib.sha256(b"answer").hexdigest(),
        output_bytes=6,
        outcome="succeeded",
    )

    assert read_model_execution_receipt(
        store.snapshot(), models, adapters, receipt.root_id
    ).provider_root == provider.root_id
    assert "private prompt" not in repr(store.snapshot().cells)


def test_legacy_core_node_bridge_does_not_call_host_or_model_runtime():
    source = inspect.getsource(bridge_module)
    for forbidden in (
        "revit_broker",
        "acad_broker",
        "max_broker",
        "ifcopenshell",
        "router.complete",
        "run_op(",
        "exec(",
        "subprocess",
    ):
        assert forbidden not in source
