from __future__ import annotations

from nodelang import KINDS, NO_VALUE, Store, relation_sources, relation_targets, validate_store
from nodelang.core import relation_stages
from nodelang.domains.orchestration import (
    build_orchestration_domain,
    execution_result,
    refresh_assignment,
    selected_assignment,
    set_agent_parameter,
    set_task_parameter,
)
from nodelang.laws_relation import rewire_endpoint


def _agent(key: str, capacity: float, capabilities=None, enabled=True):
    return {
        "id": key,
        "title": key.title(),
        "capabilities": list(capabilities or ["code"]),
        "capacity": capacity,
        "enabled": enabled,
    }


def _task(key="build", **overrides):
    task = {
        "id": key,
        "title": key.title(),
        "required_capability": "code",
        "priority": 1.0,
        "write_capable": True,
        "cde_scope": "10.PRODUCT/13.NODE-LANGUAGE",
        "approved": True,
        "brain_connected": True,
        "hooks_ready": True,
    }
    task.update(overrides)
    return task


def _pairs(store: Store) -> set[tuple[str, str]]:
    pairs = set()
    for node in store.nodes.values():
        if node["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, node):
            for target in relation_targets(store.nodes, node):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def test_orchestration_is_open_one_table_groups_params_and_explicit_relations():
    store = Store()
    domain = build_orchestration_domain(
        store, agents=[_agent("alpha", 5), _agent("beta", 4)],
        tasks=[_task()],
    )

    assert validate_store(store) is True
    assert set(node["kind"] for node in store.nodes.values()) <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    for collection in (
        domain["agents"], domain["tasks"], domain["assignment_groups"],
        domain["governance_groups"], domain["execution_groups"],
    ):
        assert all(store.nodes[node_id]["kind"] == "group"
                   for node_id in collection.values())
    for params_by_owner in (domain["agent_params"], domain["task_params"]):
        assert all(store.nodes[param_id]["kind"] == "param"
                   for params in params_by_owner.values()
                   for param_id in params.values())

    pairs = _pairs(store)
    assert (domain["agents"]["alpha"], domain["tasks"]["build"]) in pairs
    assert (domain["tasks"]["build"], domain["governance_groups"]["build"]) in pairs
    assert (domain["tasks"]["build"], domain["result_nodes"]["build"]) in pairs

    assignment = domain["assignment_relations"]["build"]
    assert assignment in store.open(domain["assignment_groups"]["build"])
    assert domain["task_gate_relations"]["build"] in store.nodes[
        domain["governance_groups"]["build"]
    ]["relations"]
    stages = relation_stages(
        store.nodes, store.nodes[domain["task_result_relations"]["build"]]
    )
    assert [(stage["mode"], stage["node_id"]) for stage in stages] == [
        ("guard", domain["governance_groups"]["build"]),
        ("map", domain["execution_groups"]["build"]),
    ]
    assert store.nodes[domain["effect_nodes"]["build"]]["meta"]["frozen"] is True


def test_assignment_is_deterministic_and_ties_follow_declaration_order():
    store = Store()
    domain = build_orchestration_domain(
        store, agents=[_agent("first", 5), _agent("second", 5)],
        tasks=[_task()],
    )

    first = selected_assignment(store, domain, "build")
    second = selected_assignment(store, domain, "build")
    assert first == second
    assert first == {
        "agent_id": "first",
        "agent_node": domain["agents"]["first"],
        "task_id": "build",
        "eligible": 1,
        "score": 5.0,
    }
    source = relation_sources(
        store.nodes, store.nodes[domain["assignment_relations"]["build"]]
    )
    assert [endpoint["node_id"] for endpoint in source] == [domain["agents"]["first"]]
    assert validate_store(store) is True


def test_parameter_change_reselects_but_explicit_refresh_rewires_assignment():
    store = Store()
    domain = build_orchestration_domain(
        store, agents=[_agent("alpha", 5), _agent("beta", 4)],
        tasks=[_task()],
    )
    relation = domain["assignment_relations"]["build"]
    endpoint_param = domain["assignment_source_params"]["build"]

    set_agent_parameter(store, domain, "alpha", "enabled", False, actor="court")
    assert selected_assignment(store, domain, "build")["agent_id"] == "beta"
    assert relation_sources(store.nodes, store.nodes[relation])[0]["node_id"] == (
        domain["agents"]["alpha"]
    )
    assert store.pull(domain["assignment_current_nodes"]["build"]) is False
    assert store.pull(domain["safety_nodes"]["build"]) == 0
    assert store.pull(domain["task_result_relations"]["build"]) is NO_VALUE

    touched = refresh_assignment(store, domain, "build", actor="dispatcher")
    assert touched == endpoint_param
    assert relation_sources(store.nodes, store.nodes[relation])[0]["node_id"] == (
        domain["agents"]["beta"]
    )
    assert store.pull(domain["assignment_current_nodes"]["build"]) is True
    assert store.pull(domain["safety_nodes"]["build"]) == 1

    rewire_endpoint(
        store, relation, endpoint_param,
        node_id=domain["agents"]["alpha"], actor="manual-rewire",
    )
    assert store.pull(domain["assignment_current_nodes"]["build"]) is False
    assert store.pull(domain["safety_nodes"]["build"]) == 0
    assert validate_store(store) is True


def test_unsafe_write_is_blocked_then_visible_gate_allows_only_frozen_plan():
    store = Store()
    domain = build_orchestration_domain(
        store, agents=[_agent("alpha", 5)],
        tasks=[_task(
            cde_scope="", approved=False, brain_connected=False, hooks_ready=False,
        )],
    )
    task_id = "build"
    effect = domain["effect_nodes"][task_id]

    assert store.pull(domain["safety_nodes"][task_id]) == 0
    assert store.pull(domain["task_result_relations"][task_id]) is NO_VALUE
    assert execution_result(store, domain, task_id) == []
    assert store.nodes[effect]["meta"]["frozen"] is True

    set_task_parameter(store, domain, task_id, "cde_scope", "10.PRODUCT/WIP")
    set_task_parameter(store, domain, task_id, "approved", True)
    set_task_parameter(store, domain, task_id, "brain_connected", True)
    set_task_parameter(store, domain, task_id, "hooks_ready", True)
    assert store.pull(domain["safety_nodes"][task_id]) == 1
    assert execution_result(store, domain, task_id) == [{
        "fired": False,
        "dry_run": True,
        "payload": {
            "id": "build",
            "title": "Build",
            "required_capability": "code",
            "priority": 1.0,
            "write_capable": True,
            "cde_scope": "10.PRODUCT/WIP",
            "approved": True,
            "brain_connected": True,
            "hooks_ready": True,
        },
    }]

    store.apply_op({"op": "unfreeze", "id": effect, "actor": "founder"})
    assert execution_result(store, domain, task_id)[0]["fired"] is True
    assert validate_store(store) is True
