"""Legacy self-extension must be visible as governed Cell effect steps."""
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
from nodelang.cell_legacy_self_extension import (  # noqa: E402
    SELF_EXTENSION_STEPS,
    build_legacy_self_extension_authority,
)
from nodelang.universal_cell import Cell, CellStore, InvalidCell, NULL_CELL_ID  # noqa: E402
import nodelang.cell_legacy_self_extension as bridge_module  # noqa: E402


def _terminal(store: CellStore, root: str) -> None:
    store.commit(
        store.revision,
        create=(Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("utf-8")),),
    )


def _world():
    store = CellStore()
    adapters = bootstrap_adapter_protocol(
        store, prefix="legacy-self-extension:test:adapter"
    )
    connectors = bootstrap_baboom_connector_execution_protocol(
        store, prefix="legacy-self-extension:test:connector"
    )
    authority = build_legacy_self_extension_authority(
        store, adapters, connectors
    )
    for root in ("user:founder", "session:founder", "work:self-extension"):
        _terminal(store, root)
    return store, adapters, connectors, authority


def _permission_for(store, adapters, authority, provider, request_id):
    expires_at = time.time() + 120
    permission = build_permission_request(
        store,
        adapters,
        authority.catalog_root,
        request_id=request_id,
        adapter_root=provider.adapter_root,
        user_root="user:founder",
        action_roots=(provider.action_root,),
        location_roots=(provider.location_root,),
        datatype_roots=(provider.datatype_roots[0],),
        expires_at=expires_at,
        max_invocations=1,
    )
    return permission, expires_at


def _grant(store, adapters, authority, permission):
    consent = UserConsentBroker()
    grant_permission(
        store,
        adapters,
        authority.catalog_root,
        permission,
        consent,
        consent.mint_from_user_gesture(permission, "user:founder"),
    )


def test_self_extension_steps_publish_as_exact_adapter_providers():
    store, adapters, _connectors, authority = _world()
    catalog = verify_adapter_catalog(
        store.snapshot(), adapters, authority.catalog_root
    )

    assert tuple(authority.providers) == SELF_EXTENSION_STEPS
    assert len(catalog.adapter_roots) == len(SELF_EXTENSION_STEPS)
    assert authority.providers["build"].operation == "self-extension.build-artifact"
    assert authority.providers["court"].operation == "self-extension.run-court"
    assert authority.providers["learn"].operation == "self-extension.write-learned-fact"


def test_self_extension_build_step_requires_permission_and_redacts_artifact_path():
    store, adapters, connectors, authority = _world()
    provider = authority.providers["build"]
    permission, expires_at = _permission_for(
        store, adapters, authority, provider, "permission:self-extension:build"
    )
    raw_input = b'{"tool":"create_connector","path":"C:/client/secret.py"}'
    input_digest = hashlib.sha256(raw_input).hexdigest()
    delegation = create_connector_delegation(
        store,
        connectors,
        adapters,
        delegation_id="delegation:self-extension:build",
        session_root="session:founder",
        work_root="work:self-extension",
        provider_root=provider.root_id,
        input_digest=input_digest,
        input_bytes=len(raw_input),
        datatype_root=provider.datatype_roots[0],
        permission_root=permission,
        expires_at=expires_at,
    )
    _grant(store, adapters, authority, permission)
    grant = create_connector_execution_grant(
        store,
        connectors,
        adapters,
        grant_id="grant:self-extension:build",
        delegation_root=delegation.root_id,
        session_root="session:founder",
        expires_at=expires_at,
        token_digest=hashlib.sha256(b"build-token").hexdigest(),
    )
    receipt = create_connector_execution_receipt(
        store,
        connectors,
        adapters,
        receipt_id="receipt:self-extension:build",
        delegation_root=delegation.root_id,
        grant_root=grant.root_id,
        provider_root=provider.root_id,
        input_digest=input_digest,
        input_bytes=len(raw_input),
        output_digest=hashlib.sha256(b"artifact digest").hexdigest(),
        output_bytes=15,
        outcome="succeeded",
    )

    assert read_connector_execution_receipt(
        store.snapshot(), connectors, adapters, receipt.root_id
    ).operation == "self-extension.build-artifact"
    assert "C:/client/secret.py" not in repr(store.snapshot().cells)


def test_self_extension_flow_settles_build_court_and_learn_once_each():
    store, adapters, connectors, authority = _world()
    settled = []
    for step in SELF_EXTENSION_STEPS:
        provider = authority.providers[step]
        permission, expires_at = _permission_for(
            store, adapters, authority, provider, "permission:self-extension:%s" % step
        )
        input_digest = hashlib.sha256(("request:" + step).encode("utf-8")).hexdigest()
        delegation = create_connector_delegation(
            store,
            connectors,
            adapters,
            delegation_id="delegation:self-extension:%s" % step,
            session_root="session:founder",
            work_root="work:self-extension",
            provider_root=provider.root_id,
            input_digest=input_digest,
            input_bytes=len(("request:" + step).encode("utf-8")),
            datatype_root=provider.datatype_roots[0],
            permission_root=permission,
            expires_at=expires_at,
        )
        _grant(store, adapters, authority, permission)
        grant = create_connector_execution_grant(
            store,
            connectors,
            adapters,
            grant_id="grant:self-extension:%s" % step,
            delegation_root=delegation.root_id,
            session_root="session:founder",
            expires_at=expires_at,
            token_digest=hashlib.sha256(("token:" + step).encode("utf-8")).hexdigest(),
        )
        receipt = create_connector_execution_receipt(
            store,
            connectors,
            adapters,
            receipt_id="receipt:self-extension:%s" % step,
            delegation_root=delegation.root_id,
            grant_root=grant.root_id,
            provider_root=provider.root_id,
            input_digest=input_digest,
            input_bytes=len(("request:" + step).encode("utf-8")),
            output_digest=hashlib.sha256(("output:" + step).encode("utf-8")).hexdigest(),
            output_bytes=len(("output:" + step).encode("utf-8")),
            outcome="succeeded",
        )
        settled.append(receipt.root_id)
        with pytest.raises(InvalidCell, match="already has a settled receipt"):
            create_connector_execution_receipt(
                store,
                connectors,
                adapters,
                receipt_id="receipt:self-extension:%s:replay" % step,
                delegation_root=delegation.root_id,
                grant_root=grant.root_id,
                provider_root=provider.root_id,
                input_digest=input_digest,
                input_bytes=len(("request:" + step).encode("utf-8")),
                output_digest=hashlib.sha256(b"replay").hexdigest(),
                output_bytes=6,
                outcome="succeeded",
            )

    assert len(settled) == 3


def test_legacy_self_extension_bridge_does_not_execute_build_court_or_brain():
    source = inspect.getsource(bridge_module)
    for forbidden in (
        "build_artifact",
        "court_verify",
        "brain.write",
        "BrainClient",
        "run_to_dry",
        "subprocess",
        "open(",
        "exec(",
    ):
        assert forbidden not in source
