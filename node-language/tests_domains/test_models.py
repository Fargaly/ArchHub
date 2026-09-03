from __future__ import annotations

from nodelang import KINDS, Store, relation_sources, relation_targets, validate_store
from nodelang.domains.models import (
    build_models_domain,
    route_model,
    set_model_usage,
    set_selection_parameter,
)


def _wire_pairs(store: Store) -> set[tuple[str, str]]:
    pairs = set()
    for node in store.nodes.values():
        if node["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, node):
            for target in relation_targets(store.nodes, node):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def test_models_domain_is_one_table_records_groups_params_and_wires():
    store = Store()
    domain = build_models_domain(store)

    assert validate_store(store) is True
    assert store.nodes[domain["session"]]["kind"] == "session"
    assert store.nodes[domain["policy_group"]]["kind"] == "group"
    assert store.nodes[domain["routing_group"]]["kind"] == "group"
    assert set(node["kind"] for node in store.nodes.values()) <= KINDS
    assert not any(node["kind"] == "secret_ref" for node in store.nodes.values())

    fast_record = store.pull(domain["models"]["model-fast"])
    provider_record = store.pull(domain["providers"]["provider-fast"])
    assert fast_record["capabilities"] == ["text", "embedding"]
    assert provider_record["capabilities"] == ["text", "embedding"]

    for param_id in domain["selection_params"].values():
        assert store.nodes[param_id]["kind"] == "param"
    for usage in domain["usage_params"].values():
        for param_id in usage.values():
            assert store.nodes[param_id]["kind"] == "param"
    for model_node in domain["models"].values():
        assert store.nodes[model_node]["body"]["floor"]["op"] == "merge"
        assert all(store.nodes[param_id]["kind"] == "param"
                   for param_id in store.nodes[model_node]["params"].values())
    assert store.nodes[domain["selected_candidate"]]["body"]["floor"] == {
        "op": "reduce", "mode": "argmax", "key_path": "score",
        "where_path": "eligible", "default": {
            "model_id": None, "provider_id": None, "eligible": False,
            "score": None, "status": "no-match",
        },
    }

    pairs = _wire_pairs(store)
    assert (
        domain["providers"]["provider-fast"],
        domain["provider_bindings"]["model-fast"],
    ) in pairs
    assert (
        domain["score_nodes"]["model-fast"],
        domain["candidate_nodes"]["model-fast"],
    ) in pairs


def test_selection_parameter_edits_change_routing_deterministically():
    store = Store()
    domain = build_models_domain(store)

    assert route_model(store, domain)["model_id"] == "model-fast"

    touched = set_selection_parameter(
        store, domain, "required_capability", "vision", actor="test"
    )
    assert touched == domain["selection_params"]["required_capability"]
    first = route_model(store, domain)
    second = route_model(store, domain)
    assert first == second
    assert first["model_id"] == "model-deep"
    assert first["status"] == "selected"
    assert validate_store(store) is True


def test_weight_and_usage_parameter_edits_recook_scores_and_route():
    store = Store()
    domain = build_models_domain(store)

    assert route_model(store, domain)["model_id"] == "model-fast"
    set_selection_parameter(store, domain, "quality_weight", 30.0)
    deep = route_model(store, domain)
    assert deep["model_id"] == "model-deep"

    score_before = store.pull(domain["score_nodes"]["model-deep"])
    touched = set_model_usage(store, domain, "model-deep", requests=50, actor="meter")
    score_after = store.pull(domain["score_nodes"]["model-deep"])
    assert touched == [domain["usage_params"]["model-deep"]["requests"]]
    assert score_after < score_before
    assert route_model(store, domain)["model_id"] == "model-fast"
    assert validate_store(store) is True


def test_ties_use_declaration_order_and_no_match_is_explicit():
    store = Store()
    domain = build_models_domain(store)
    for name in (
        "quality_weight", "input_cost_weight", "latency_weight",
        "usage_weight", "preference_weight",
    ):
        set_selection_parameter(store, domain, name, 0.0)

    assert route_model(store, domain)["model_id"] == domain["model_order"][0]

    set_selection_parameter(store, domain, "required_capability", "audio")
    assert route_model(store, domain) == {
        "model_id": None,
        "provider_id": None,
        "eligible": False,
        "score": None,
        "status": "no-match",
    }
    assert validate_store(store) is True
