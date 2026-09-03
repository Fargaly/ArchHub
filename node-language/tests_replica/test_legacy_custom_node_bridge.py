"""Legacy custom-node behavior must cross Universal Cell adapter authority."""
from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodelang.cell_adapters import (
    UserConsentBroker,
    build_authorized_adapter_evidence,
    grant_permission,
    verify_adapter_catalog,
    verify_released_adapter,
)
from nodelang.cell_legacy_custom_nodes import (
    authorize_legacy_custom_node_invocation,
    bootstrap_legacy_custom_node_protocol,
    build_legacy_custom_node_execution_request,
)
from nodelang.cell_protocols import read_relation
from nodelang.cell_state_machine import (
    bootstrap_state_machine_protocol,
    build_state_machine,
    build_transition,
    read_state_machine,
    transition_machine,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell
import nodelang.cell_legacy_custom_nodes as bridge_module


def _store():
    store = CellStore()
    custom = bootstrap_legacy_custom_node_protocol(store)
    from nodelang.cell_adapters import bootstrap_adapter_protocol

    adapters = bootstrap_adapter_protocol(store, prefix="test:adapter")
    store.commit(
        store.revision,
        create=(Cell("user:founder", NULL_CELL_ID, NULL_CELL_ID, b"Founder"),),
    )
    return store, custom, adapters


def _spec():
    return {
        "type": "founder.rank_facades",
        "category": "decision",
        "display_name": "Rank Facades",
        "inputs": [{"name": "options", "type": "list"}],
        "outputs": [{"name": "ranking", "type": "list"}],
        "impl": {
            "kind": "python",
            "safe_mode": True,
            "code": (
                "def execute(config, inputs, ctx):\n"
                "    return {'ranking': inputs.get('options', [])}\n"
            ),
        },
    }


def _bridge(store, custom, adapters, **kwargs):
    return build_legacy_custom_node_execution_request(
        store,
        custom,
        adapters,
        spec=_spec(),
        user_root="user:founder",
        request_id=kwargs.pop("request_id", "permission:custom-node"),
        expires_at=kwargs.pop("expires_at", time.time() + 60),
        max_invocations=kwargs.pop("max_invocations", 1),
        **kwargs,
    )


def test_custom_node_spec_becomes_exact_released_adapter_permission():
    store, custom, adapters = _store()
    bridge = _bridge(store, custom, adapters)
    snapshot = store.snapshot()

    adapter = verify_released_adapter(snapshot, adapters, bridge.adapter_root)
    catalog = verify_adapter_catalog(snapshot, adapters, bridge.catalog_root)
    capability = read_relation(snapshot, bridge.capability_root, budget=100_000)

    assert catalog.adapter_roots == (bridge.adapter_root,)
    assert adapter.location_roots == (bridge.capability_root,)
    assert bridge.spec_root in {member.participant_id for member in capability}
    assert bridge.spec_digest.encode("ascii") == snapshot.cells[
        bridge.spec_digest_root
    ].atom

    with pytest.raises(InvalidCell, match="not granted"):
        authorize_legacy_custom_node_invocation(
            snapshot, adapters, bridge, invocation_count=0
        )


def test_custom_node_invocation_requires_one_use_user_consent_and_exact_bounds():
    store, custom, adapters = _store()
    bridge = _bridge(store, custom, adapters, max_invocations=2)
    broker = UserConsentBroker()
    grant_permission(
        store,
        adapters,
        bridge.catalog_root,
        bridge.permission_root,
        broker,
        broker.mint_from_user_gesture(bridge.permission_root, bridge.user_root),
    )

    granted = authorize_legacy_custom_node_invocation(
        store.snapshot(), adapters, bridge, invocation_count=0
    )
    assert granted.root_id == bridge.permission_root

    wrong = replace(bridge, datatype_root=adapters.root_id)
    with pytest.raises(InvalidCell, match="denies datatype"):
        authorize_legacy_custom_node_invocation(
            store.snapshot(), adapters, wrong, invocation_count=0
        )
    with pytest.raises(InvalidCell, match="budget is exhausted"):
        authorize_legacy_custom_node_invocation(
            store.snapshot(), adapters, bridge, invocation_count=2
        )


def test_custom_node_adapter_release_drifts_when_spec_graph_changes():
    store, custom, adapters = _store()
    bridge = _bridge(store, custom, adapters)
    broker = UserConsentBroker()
    grant_permission(
        store,
        adapters,
        bridge.catalog_root,
        bridge.permission_root,
        broker,
        broker.mint_from_user_gesture(bridge.permission_root, bridge.user_root),
    )
    spec_cell = store.read(bridge.spec_root)
    store.commit(
        store.revision,
        replace=(Cell(spec_cell.id, spec_cell.link0, spec_cell.link1, b"{}"),),
    )

    with pytest.raises(InvalidCell, match="adapter has drifted"):
        authorize_legacy_custom_node_invocation(
            store.snapshot(), adapters, bridge, invocation_count=0
        )


def test_authorized_custom_node_evidence_can_cross_operational_gate():
    store, custom, adapters = _store()
    bridge = _bridge(store, custom, adapters)
    broker = UserConsentBroker()
    grant_permission(
        store,
        adapters,
        bridge.catalog_root,
        bridge.permission_root,
        broker,
        broker.mint_from_user_gesture(bridge.permission_root, bridge.user_root),
    )
    operational = bootstrap_state_machine_protocol(
        store, prefix="custom-node:operational"
    )
    store.commit(
        store.revision,
        create=(
            Cell("state:pending", NULL_CELL_ID, NULL_CELL_ID, b"Pending"),
            Cell("state:committed", NULL_CELL_ID, NULL_CELL_ID, b"Committed"),
            Cell("event:commit", NULL_CELL_ID, NULL_CELL_ID, b"Commit"),
            Cell(
                "evidence-type:custom-node-receipt",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"Custom node receipt",
            ),
            Cell("actor:founder", NULL_CELL_ID, NULL_CELL_ID, b"Founder"),
        ),
    )
    transition = build_transition(
        store,
        operational,
        transition_id="custom-node:transition:commit",
        from_state_root="state:pending",
        to_state_root="state:committed",
        event_root="event:commit",
        required_evidence_type_roots=("evidence-type:custom-node-receipt",),
    )
    machine = build_state_machine(
        store,
        operational,
        machine_id="custom-node:machine",
        state_roots=("state:pending", "state:committed"),
        transition_roots=(transition,),
        initial_state_root="state:pending",
    )
    evidence = build_authorized_adapter_evidence(
        store,
        adapters,
        bridge.catalog_root,
        bridge.permission_root,
        operational,
        adapter_root=bridge.adapter_root,
        user_root=bridge.user_root,
        action_root=bridge.action_root,
        location_root=bridge.location_root,
        datatype_root=bridge.datatype_root,
        invocation_count=0,
        evidence_id="evidence:custom-node:authorized",
        evidence_type_root="evidence-type:custom-node-receipt",
        payload=b'{"status":"ok","outputs":["ranking"]}',
    )

    transition_machine(
        store,
        operational,
        machine,
        event_root="event:commit",
        expected_state_root="state:pending",
        actor_root="actor:founder",
        evidence_roots=(evidence,),
        trusted_issuer_roots=(bridge.adapter_root,),
    )

    assert read_state_machine(
        store.snapshot(), operational, machine
    ).current_state_root == "state:committed"


def test_legacy_custom_node_bridge_does_not_execute_legacy_code():
    source = inspect.getsource(bridge_module)
    for forbidden in (
        "exec(",
        "eval(",
        "run_op(",
        ".complete(",
        "subprocess",
        "open(",
    ):
        assert forbidden not in source
