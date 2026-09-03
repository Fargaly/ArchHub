"""Node-native agents, tasks, assignment, and governed execution.

The module adds no orchestration engine beside :class:`nodelang.core.Store`.
Agents and tasks are open groups assembled from parameter nodes. Assignment is
an open score graph. The selected agent is materialized as an ordinary relation
endpoint only by ``refresh_assignment`` so rewiring remains explicit and
audited. Execution travels through a task-to-result relation whose stages are a
visible safety gate and a frozen effect group.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from ..core import NO_VALUE, Store, relation_sources
from ..laws_relation import rewire_endpoint


DEFAULT_AGENTS = (
    {
        "id": "agent-general",
        "title": "General agent",
        "capabilities": ["code", "research"],
        "capacity": 5.0,
        "enabled": True,
    },
    {
        "id": "agent-specialist",
        "title": "Specialist agent",
        "capabilities": ["code", "review"],
        "capacity": 4.0,
        "enabled": True,
    },
)

DEFAULT_TASKS = (
    {
        "id": "task-build",
        "title": "Build governed work",
        "required_capability": "code",
        "priority": 1.0,
        "write_capable": True,
        "cde_scope": "10.PRODUCT/13.NODE-LANGUAGE",
        "approved": False,
        "brain_connected": False,
        "hooks_ready": False,
    },
)

_AGENT_FIELDS = frozenset({"id", "title", "capabilities", "capacity", "enabled"})
_TASK_FIELDS = frozenset({
    "id", "title", "required_capability", "priority", "write_capable",
    "cde_scope", "approved", "brain_connected", "hooks_ready",
})


def _identifier(value: Any, label: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _number(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("%s must be a finite non-negative number" % label)
    return number


def _exact_fields(record: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    keys = set(record)
    missing = sorted(allowed - keys)
    unknown = sorted(keys - allowed)
    if missing or unknown:
        raise ValueError(
            "%s fields mismatch; missing=%r unknown=%r" % (label, missing, unknown)
        )


def _agent_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _AGENT_FIELDS, "agent")
    capabilities = record["capabilities"]
    if isinstance(capabilities, (str, bytes)) or not isinstance(capabilities, Iterable):
        raise ValueError("agent capabilities must be an iterable")
    capabilities = [_identifier(value, "agent capability") for value in capabilities]
    if len(capabilities) != len(set(capabilities)):
        raise ValueError("agent capabilities contain duplicates")
    return {
        "id": _identifier(record["id"], "agent id"),
        "title": _identifier(record["title"], "agent title"),
        "capabilities": capabilities,
        "capacity": _number(record["capacity"], "agent capacity"),
        "enabled": bool(record["enabled"]),
    }


def _task_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _TASK_FIELDS, "task")
    return {
        "id": _identifier(record["id"], "task id"),
        "title": _identifier(record["title"], "task title"),
        "required_capability": _identifier(
            record["required_capability"], "required capability"
        ),
        "priority": _number(record["priority"], "task priority"),
        "write_capable": bool(record["write_capable"]),
        "cde_scope": str(record["cde_scope"]).strip(),
        "approved": bool(record["approved"]),
        "brain_connected": bool(record["brain_connected"]),
        "hooks_ready": bool(record["hooks_ready"]),
    }


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add(
        "param", title, floor={"op": "value", "value": value}, actor=actor
    )


def _op(
    store: Store,
    title: str,
    floor: Mapping[str, Any],
    sources: Iterable[str],
    inner: list[str],
    actor: str,
) -> str:
    node = store.add("op", title, floor=dict(floor), actor=actor)
    for source in sources:
        store.wire(source, node, actor=actor)
    inner.append(node)
    return node


def _record_group(
    store: Store,
    title: str,
    record: Mapping[str, Any],
    actor: str,
) -> tuple[str, str, dict[str, str]]:
    """Build one open record entirely from editable parameter nodes."""
    params = {
        name: _param(store, "%s: %s" % (title, name), value, actor)
        for name, value in record.items()
    }
    inner = list(params.values())
    assembled = _op(
        store,
        "Assemble %s" % title,
        {"op": "merge", "fn": "record", "keys": list(record)},
        params.values(),
        inner,
        actor,
    )
    group = store.add(
        "group", title, inner=inner, params=params, actor=actor
    )
    return group, assembled, params


def _field(
    store: Store,
    source: str,
    path: str,
    title: str,
    inner: list[str],
    actor: str,
) -> str:
    return _op(
        store, title, {"op": "field", "path": [path]}, [source], inner, actor
    )


def _source_endpoint_param(store: Store, relation_id: str) -> str:
    relation = store.nodes[relation_id]
    sources = relation_sources(store.nodes, relation)
    if len(sources) != 1:
        raise ValueError("assignment relation must have exactly one source")
    return str(sources[0]["endpoint_param"])


def build_orchestration_domain(
    store: Store,
    *,
    agents: Iterable[Mapping[str, Any]] = DEFAULT_AGENTS,
    tasks: Iterable[Mapping[str, Any]] = DEFAULT_TASKS,
    minimum_capacity: float = 1.0,
    actor: str = "orchestration-domain",
) -> dict[str, Any]:
    """Build inspectable assignment and gated execution in the one table."""
    agent_records = [_agent_record(raw) for raw in agents]
    task_records = [_task_record(raw) for raw in tasks]
    if not agent_records:
        raise ValueError("orchestration needs at least one agent")
    if not task_records:
        raise ValueError("orchestration needs at least one task")
    agent_order = [record["id"] for record in agent_records]
    task_order = [record["id"] for record in task_records]
    if len(agent_order) != len(set(agent_order)):
        raise ValueError("agent ids must be unique")
    if len(task_order) != len(set(task_order)):
        raise ValueError("task ids must be unique")
    minimum_capacity = _number(minimum_capacity, "minimum capacity")

    agent_groups: dict[str, str] = {}
    agent_records_nodes: dict[str, str] = {}
    agent_params: dict[str, dict[str, str]] = {}
    for record in agent_records:
        key = record["id"]
        group, assembled, params = _record_group(
            store, "Agent: %s" % record["title"], record, actor
        )
        agent_groups[key] = group
        agent_records_nodes[key] = assembled
        agent_params[key] = params

    task_groups: dict[str, str] = {}
    task_records_nodes: dict[str, str] = {}
    task_params: dict[str, dict[str, str]] = {}
    for record in task_records:
        key = record["id"]
        group, assembled, params = _record_group(
            store, "Task: %s" % record["title"], record, actor
        )
        task_groups[key] = group
        task_records_nodes[key] = assembled
        task_params[key] = params

    minimum_capacity_param = _param(
        store, "Minimum agent capacity", minimum_capacity, actor
    )
    true_node = store.add(
        "value", "True", floor={"op": "value", "value": True}, actor=actor
    )
    false_node = store.add(
        "value", "False", floor={"op": "value", "value": False}, actor=actor
    )
    empty_node = store.add(
        "value", "Empty value", floor={"op": "value", "value": ""}, actor=actor
    )
    unassigned_reason = _param(store, "Unassigned reason", "no eligible agent", actor)
    unassigned_group = store.add(
        "group", "Unassigned", inner=[unassigned_reason],
        params={"reason": unassigned_reason}, actor=actor,
    )

    assignment_groups: dict[str, str] = {}
    selected_candidates: dict[str, str] = {}
    candidate_nodes: dict[str, dict[str, str]] = {}
    assignment_relations: dict[str, str] = {}
    assignment_source_params: dict[str, str] = {}
    assignment_current_nodes: dict[str, str] = {}
    governance_groups: dict[str, str] = {}
    task_gate_relations: dict[str, str] = {}
    safety_nodes: dict[str, str] = {}
    execution_groups: dict[str, str] = {}
    effect_nodes: dict[str, str] = {}
    result_nodes: dict[str, str] = {}
    task_result_relations: dict[str, str] = {}

    for task_key in task_order:
        assignment_inner: list[str] = []
        per_agent: dict[str, str] = {}
        for agent_key in agent_order:
            capabilities = agent_params[agent_key]["capabilities"]
            enabled = agent_params[agent_key]["enabled"]
            capacity = agent_params[agent_key]["capacity"]
            capability_ok = _op(
                store, "%s can perform %s" % (agent_key, task_key),
                {"op": "compare", "cmp": "contains"},
                [capabilities, task_params[task_key]["required_capability"]],
                assignment_inner, actor,
            )
            enabled_ok = _op(
                store, "%s is enabled" % agent_key,
                {"op": "compare", "cmp": "=="},
                [enabled, true_node], assignment_inner, actor,
            )
            capacity_ok = _op(
                store, "%s has capacity" % agent_key,
                {"op": "compare", "cmp": ">="},
                [capacity, minimum_capacity_param], assignment_inner, actor,
            )
            eligible = _op(
                store, "%s eligibility for %s" % (agent_key, task_key),
                {"op": "math", "fn": "*"},
                [capability_ok, enabled_ok, capacity_ok], assignment_inner, actor,
            )
            score = _op(
                store, "%s score for %s" % (agent_key, task_key),
                {"op": "math", "fn": "*"},
                [eligible, capacity], assignment_inner, actor,
            )
            agent_node = _param(
                store, "%s node identity" % agent_key, agent_groups[agent_key], actor
            )
            assignment_inner.append(agent_node)
            candidate = _op(
                store, "%s candidate for %s" % (agent_key, task_key),
                {"op": "merge", "fn": "record", "keys": [
                    "agent_id", "agent_node", "task_id", "eligible", "score",
                ]},
                [agent_params[agent_key]["id"], agent_node,
                 task_params[task_key]["id"], eligible, score],
                assignment_inner, actor,
            )
            per_agent[agent_key] = candidate
        candidate_nodes[task_key] = per_agent
        candidates = _op(
            store, "Assignment candidates for %s" % task_key,
            {"op": "merge", "fn": "list"},
            [per_agent[key] for key in agent_order], assignment_inner, actor,
        )
        selected = _op(
            store, "Selected agent for %s" % task_key,
            {
                "op": "reduce", "mode": "argmax", "key_path": "score",
                "where_path": "eligible",
                "default": {
                    "agent_id": None, "agent_node": None, "task_id": task_key,
                    "eligible": False, "score": None,
                },
            },
            [candidates], assignment_inner, actor,
        )
        selected_candidates[task_key] = selected
        selected_value = store.pull(selected)
        selected_source = selected_value.get("agent_node") or unassigned_group
        assignment_relation = store.relation([
            {
                "role": "source", "direction": "out", "node_id": selected_source,
                "port_id": "agent", "cardinality": "one",
            },
            {
                "role": "target", "direction": "in", "node_id": task_groups[task_key],
                "port_id": "assignee", "cardinality": "one",
            },
        ], title="Agent assigned to task", actor=actor)
        assignment_relations[task_key] = assignment_relation
        source_param = _source_endpoint_param(store, assignment_relation)
        assignment_source_params[task_key] = source_param
        assignment_inner.append(assignment_relation)
        assignment_group = store.add(
            "group", "Assignment: %s" % task_key,
            inner=assignment_inner, actor=actor,
        )
        assignment_groups[task_key] = assignment_group

        governance_inner: list[str] = []
        selected_agent_node = _field(
            store, selected, "agent_node", "Policy-selected agent node",
            governance_inner, actor,
        )
        assigned_agent_node = _field(
            store, source_param, "node_id", "Wired agent node",
            governance_inner, actor,
        )
        assignment_current = _op(
            store, "Assignment wire matches policy",
            {"op": "compare", "cmp": "=="},
            [assigned_agent_node, selected_agent_node], governance_inner, actor,
        )
        assignment_current_nodes[task_key] = assignment_current
        scope_present = _op(
            store, "CDE scope is defined",
            {"op": "compare", "cmp": "!="},
            [task_params[task_key]["cde_scope"], empty_node], governance_inner, actor,
        )
        not_write = _op(
            store, "Task is read-only",
            {"op": "compare", "cmp": "=="},
            [task_params[task_key]["write_capable"], false_node], governance_inner, actor,
        )
        write_requirements = _op(
            store, "Write requirements satisfied",
            {"op": "math", "fn": "*"},
            [task_params[task_key]["approved"],
             task_params[task_key]["brain_connected"],
             task_params[task_key]["hooks_ready"], scope_present],
            governance_inner, actor,
        )
        read_or_governed_write = _op(
            store, "Read-only or governed write",
            {"op": "math", "fn": "max"},
            [not_write, write_requirements], governance_inner, actor,
        )
        safe = _op(
            store, "Task is safe to execute",
            {"op": "math", "fn": "*"},
            [assignment_current, read_or_governed_write], governance_inner, actor,
        )
        safety_nodes[task_key] = safe
        governance_group = store.add(
            "group", "Execution governance: %s" % task_key,
            inner=governance_inner, actor=actor,
        )
        governance_groups[task_key] = governance_group
        task_gate_relation = store.relation([
            {
                "role": "source", "direction": "out",
                "node_id": task_groups[task_key], "port_id": "governance-request",
                "cardinality": "one",
            },
            {
                "role": "target", "direction": "in",
                "node_id": governance_group, "port_id": "gate",
                "cardinality": "one",
            },
        ], title="Task governed by visible gate", actor=actor)
        task_gate_relations[task_key] = task_gate_relation

        payload = store.add(
            "param", "Execution payload",
            floor={"op": "reference", "target": task_records_nodes[task_key]},
            actor=actor,
        )
        effect = store.add(
            "op", "Frozen execution effect: %s" % task_key,
            floor={"op": "effect", "payload": {"$param": "payload"}},
            params={"payload": payload}, frozen=True, actor=actor,
        )
        effect_nodes[task_key] = effect
        execution_group = store.add(
            "group", "Execution: %s" % task_key,
            inner=[payload, effect], params={"payload": payload}, actor=actor,
        )
        execution_groups[task_key] = execution_group
        result = store.add(
            "op", "Result: %s" % task_key,
            floor={"op": "merge", "fn": "list"}, actor=actor,
        )
        result_nodes[task_key] = result
        task_result_relation = store.relation([
            {
                "role": "source", "direction": "out",
                "node_id": task_groups[task_key], "port_id": "execution-request",
                "cardinality": "one",
            },
            {
                "role": "target", "direction": "in",
                "node_id": result, "port_id": "result",
                "cardinality": "one",
            },
        ], title="Task produces governed result", stages=[
            {"role": "gate", "mode": "guard", "node_id": governance_group},
            {"role": "execution", "mode": "map", "node_id": execution_group},
        ], actor=actor)
        task_result_relations[task_key] = task_result_relation

    policy_group = store.add(
        "group", "Orchestration policy",
        inner=[minimum_capacity_param, true_node, false_node, empty_node],
        params={"minimum_capacity": minimum_capacity_param}, actor=actor,
    )
    session = store.add(
        "session", "Orchestration Domain",
        inner=(list(agent_groups.values()) + list(task_groups.values()) +
               [policy_group, unassigned_group] +
               list(assignment_groups.values()) +
               list(governance_groups.values()) +
               list(execution_groups.values()) + list(result_nodes.values()) +
               list(task_result_relations.values())),
        actor=actor,
    )
    return {
        "session": session,
        "agents": agent_groups,
        "agent_records": agent_records_nodes,
        "agent_params": agent_params,
        "agent_order": agent_order,
        "tasks": task_groups,
        "task_records": task_records_nodes,
        "task_params": task_params,
        "task_order": task_order,
        "policy_group": policy_group,
        "minimum_capacity": minimum_capacity_param,
        "unassigned": unassigned_group,
        "assignment_groups": assignment_groups,
        "candidate_nodes": candidate_nodes,
        "selected_candidates": selected_candidates,
        "assignment_relations": assignment_relations,
        "assignment_source_params": assignment_source_params,
        "assignment_current_nodes": assignment_current_nodes,
        "governance_groups": governance_groups,
        "task_gate_relations": task_gate_relations,
        "safety_nodes": safety_nodes,
        "execution_groups": execution_groups,
        "effect_nodes": effect_nodes,
        "result_nodes": result_nodes,
        "task_result_relations": task_result_relations,
    }


def selected_assignment(
    store: Store, domain: Mapping[str, Any], task_id: str
) -> dict[str, Any]:
    """Read the visible assignment decision; no policy lives in this helper."""
    selected = store.pull(str(domain["selected_candidates"][task_id]))
    if not isinstance(selected, dict):
        raise ValueError("assignment decision did not produce a record")
    return dict(selected)


def refresh_assignment(
    store: Store,
    domain: Mapping[str, Any],
    task_id: str,
    *,
    actor: str = "orchestration-domain",
) -> str:
    """Explicitly rewire the agent-to-task relation to the visible winner."""
    selected = selected_assignment(store, domain, task_id)
    source = selected.get("agent_node") or domain["unassigned"]
    return rewire_endpoint(
        store,
        str(domain["assignment_relations"][task_id]),
        str(domain["assignment_source_params"][task_id]),
        node_id=str(source),
        actor=actor,
    )


def set_agent_parameter(
    store: Store,
    domain: Mapping[str, Any],
    agent_id: str,
    name: str,
    value: Any,
    *,
    actor: str = "orchestration-domain",
) -> str:
    params = domain["agent_params"][agent_id]
    if name not in params:
        raise KeyError("unknown agent parameter %r" % name)
    if name == "capacity":
        value = _number(value, "agent capacity")
    elif name == "enabled":
        value = bool(value)
    return store.edit(params[name], ["body", "floor", "value"], value, actor=actor)


def set_task_parameter(
    store: Store,
    domain: Mapping[str, Any],
    task_id: str,
    name: str,
    value: Any,
    *,
    actor: str = "orchestration-domain",
) -> str:
    params = domain["task_params"][task_id]
    if name not in params:
        raise KeyError("unknown task parameter %r" % name)
    if name == "priority":
        value = _number(value, "task priority")
    elif name in {"write_capable", "approved", "brain_connected", "hooks_ready"}:
        value = bool(value)
    elif name in {"id", "title", "required_capability"}:
        value = _identifier(value, "task %s" % name)
    elif name == "cde_scope":
        value = str(value).strip()
    return store.edit(params[name], ["body", "floor", "value"], value, actor=actor)


def execution_result(
    store: Store, domain: Mapping[str, Any], task_id: str
) -> list[Any]:
    """Pull the governed result. A blocked relation yields an empty list."""
    result = store.pull(str(domain["result_nodes"][task_id]))
    if result is NO_VALUE:
        return []
    if not isinstance(result, list):
        raise ValueError("execution result node did not produce a list")
    return result


__all__ = [
    "DEFAULT_AGENTS",
    "DEFAULT_TASKS",
    "build_orchestration_domain",
    "selected_assignment",
    "refresh_assignment",
    "set_agent_parameter",
    "set_task_parameter",
    "execution_result",
]
