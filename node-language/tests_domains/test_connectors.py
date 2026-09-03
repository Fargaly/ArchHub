from __future__ import annotations

import pytest

from nodelang import KINDS, Store, relation_sources, relation_targets, validate_store
from nodelang.domains.connectors import (
    build_connectors_domain,
    connector_parts,
    connector_status,
    observe_connector_health,
    registered_connector_ids,
)
from nodelang.laws_effect import FrozenNode, apply_effect, dry_run


def _definition(key="coord-host", address="http://127.0.0.1:9000"):
    return {
        "key": key,
        "title": "Coordination host",
        "capabilities": ["read", "write"],
        "endpoint": {
            "transport": "http",
            "address": address,
            "enabled": True,
            "timeout_ms": 3000,
        },
        "configuration": {"workspace": "WIP", "format": "json"},
        "plan": {
            "selected_capability": "read",
            "arguments": {"query": "levels"},
            "mutation": False,
        },
    }


def _pairs(store: Store) -> set[tuple[str, str]]:
    pairs = set()
    for relation in store.nodes.values():
        if relation["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, relation):
            for target in relation_targets(store.nodes, relation):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def test_connector_catalog_is_one_open_table_with_explicit_relations():
    store = Store()
    domain = build_connectors_domain(store, connectors=[_definition()])
    connector = domain["connectors"]["coord-host"]
    connector_id = connector["connector"]

    assert validate_store(store) is True
    assert set(node["kind"] for node in store.nodes.values()) <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    assert store.nodes[domain["catalog"]]["kind"] == "group"
    assert store.nodes[connector_id]["kind"] == "group"
    assert registered_connector_ids(store, domain["catalog"]) == [connector_id]
    assert connector_parts(store, connector_id) == connector["parts"]

    for part_id in connector["parts"].values():
        assert store.nodes[part_id]["kind"] == "group"
        assert part_id in store.open(connector_id)
    assert all(store.nodes[rid]["kind"] == "wire"
               for rid in connector["part_relations"].values())

    pairs = _pairs(store)
    assert (connector_id, domain["catalog"]) in pairs
    assert (connector["endpoint"]["record"], connector["plan"]["record"]) in pairs
    assert (connector["health"]["available"], connector["plan"]["record"]) in pairs
    assert (connector["capabilities"]["record"], connector["plan"]["record"]) in pairs


def test_endpoint_and_capability_parameter_edits_propagate_into_plan():
    store = Store()
    connector = build_connectors_domain(
        store, connectors=[_definition()]
    )["connectors"]["coord-host"]

    plan_before = store.pull(connector["plan"]["record"])
    assert plan_before["endpoint"]["address"] == "http://127.0.0.1:9000"
    assert plan_before["capabilities"] == ["read", "write"]

    address = connector["endpoint"]["fields"]["address"]
    capability = connector["capabilities"]["fields"]["capability:001"]
    store.edit(address, ["body", "floor", "value"], "pipe://coordination", actor="user")
    store.edit(capability, ["body", "floor", "value"], "stream", actor="user")

    plan_after = store.pull(connector["plan"]["record"])
    assert plan_after["endpoint"]["address"] == "pipe://coordination"
    assert plan_after["capabilities"] == ["read", "stream"]
    assert plan_after != plan_before
    assert validate_store(store) is True


def test_health_is_honestly_disconnected_until_evidence_is_present():
    store = Store()
    connector = build_connectors_domain(
        store, connectors=[_definition()]
    )["connectors"]["coord-host"]
    connector_id = connector["connector"]
    health_fields = connector["health"]["fields"]

    assert connector_status(store, connector_id) == "loaded_dead"
    assert store.pull(connector["health"]["available"]) == 0

    store.edit(
        health_fields["state"], ["body", "floor", "value"], "live",
        actor="user",
    )
    assert connector_status(store, connector_id) == "loaded_dead"

    observe_connector_health(
        store, connector_id, "live",
        observed_at="2026-07-12T12:00:00Z",
        evidence="HTTP 200 from independent health endpoint",
        latency_ms=12.5,
    )
    assert connector_status(store, connector_id) == "live"
    assert store.pull(connector["health"]["available"]) == 1
    assert store.pull(connector["plan"]["record"])["available"] == 1

    enabled = connector["endpoint"]["fields"]["enabled"]
    store.edit(enabled, ["body", "floor", "value"], False, actor="user")
    assert connector_status(store, connector_id) == "loaded_dead"
    assert store.pull(connector["plan"]["record"])["available"] == 0
    assert validate_store(store) is True


def test_four_state_probe_vocabulary_is_an_editable_policy_node():
    store = Store()
    domain = build_connectors_domain(store, connectors=[_definition()])
    policy = domain["health_policy"]
    allowed = store.nodes[policy]["params"]["allowed_states"]
    connector = domain["connectors"]["coord-host"]

    assert store.pull(allowed) == ["live", "loaded_dead", "missing", "unauthorized"]
    observe_connector_health(
        store, connector["connector"], "unauthorized",
        observed_at="2026-07-12T12:00:00Z", evidence="HTTP 401",
    )
    assert connector_status(store, connector["connector"]) == "unauthorized"
    store.edit(allowed, ["body", "floor", "value"],
               ["live", "loaded_dead", "missing", "unauthorized", "degraded"])
    observe_connector_health(
        store, connector["connector"], "degraded",
        observed_at="2026-07-12T12:01:00Z", evidence="slow heartbeat",
    )
    assert connector_status(store, connector["connector"]) == "degraded"
    assert validate_store(store) is True


def test_execution_is_an_open_plan_but_external_mutation_stays_frozen():
    store = Store()
    connector = build_connectors_domain(
        store, connectors=[_definition()]
    )["connectors"]["coord-host"]
    effect = connector["effect"]
    sink = {}

    marker = store.pull(effect)
    assert marker["fired"] is False
    assert marker["dry_run"] is True
    assert marker["plan"]["change"] == store.pull(connector["plan"]["record"])
    assert dry_run(store, effect) == marker["plan"]
    with pytest.raises(FrozenNode):
        apply_effect(store, effect, sink)
    assert sink == {}
    assert store.nodes[effect]["meta"]["frozen"] is True
    assert validate_store(store) is True


def test_raw_secret_configuration_is_rejected_but_reference_nodes_are_allowed():
    store = Store()
    raw = _definition()
    raw["configuration"]["api_token"] = "not-allowed"
    with pytest.raises(ValueError, match="secret_ref"):
        build_connectors_domain(store, connectors=[raw])

    safe = _definition()
    safe["secret_refs"] = {"credential": "op://archhub/connectors/coord-host"}
    domain = build_connectors_domain(Store(), connectors=[safe])
    connector = domain["connectors"]["coord-host"]
    assert connector["secret_refs"]
