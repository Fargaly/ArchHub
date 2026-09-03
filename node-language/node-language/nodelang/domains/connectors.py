"""Universal connector/host catalog expressed entirely in the one node table.

Connector identity, capabilities, endpoint/configuration, observed health, and
execution plans are open groups assembled from parameter nodes. Relationships
between those groups are relation-role nodes; this module keeps no registry.
An execution effect is present for inspection, but is frozen by default and
therefore cannot mutate an external sink without an explicit audited unfreeze.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..core import Store, relation_sources, relation_targets


_CATALOG_MARKER = "node-native-connector-catalog/v1"
DEFAULT_HEALTH_STATES = ("live", "loaded_dead", "missing", "unauthorized")
_SECRET_WORDS = frozenset({
    "credential", "credentials", "password", "secret", "token",
    "private", "apikey", "api_key", "access_token", "refresh_token",
})
_SECRET_VALUE_PREFIXES = ("sk-", "ghp_", "github_pat_", "bearer ")


def _text(value: Any, label: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _field_words(name: Any) -> set[str]:
    text = str(name).casefold()
    words = {word for word in re.split(r"[^a-z0-9]+", text) if word}
    words.add(text)
    return words


def _assert_no_secret_value(name: str, value: Any) -> None:
    if _field_words(name) & _SECRET_WORDS:
        raise ValueError(
            "configuration field %r may contain a secret; use a secret_ref node" % name
        )
    if isinstance(value, Mapping):
        for child_name, child_value in value.items():
            _assert_no_secret_value(str(child_name), child_value)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_no_secret_value(name, child)
    elif isinstance(value, str) and value.casefold().startswith(_SECRET_VALUE_PREFIXES):
        raise ValueError("configuration contains a probable raw secret")


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add(
        "param", title, floor={"op": "value", "value": value}, actor=actor
    )


def _record_group(
    store: Store,
    title: str,
    values: Mapping[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    fields = {
        str(name): _param(store, "%s: %s" % (title, name), value, actor)
        for name, value in values.items()
    }
    return _record_group_from_nodes(store, title, fields, actor=actor)


def _record_group_from_nodes(
    store: Store,
    title: str,
    fields: Mapping[str, str],
    *,
    actor: str,
    local_nodes: Iterable[str] = (),
) -> dict[str, Any]:
    field_nodes = dict(fields)
    for field_name, node_id in field_nodes.items():
        if node_id not in store.nodes:
            raise KeyError("record field %s is not in the one table" % field_name)
    keys = list(field_nodes)
    keys_param = _param(store, "%s: record keys" % title, keys, actor)
    record = store.add(
        "op",
        "%s record" % title,
        floor={"op": "merge", "fn": "record", "keys": {"$param": "keys"}},
        params={"keys": keys_param},
        actor=actor,
    )
    wires = [
        store.wire(node_id, record, title="%s -> %s" % (name, title), actor=actor)
        for name, node_id in field_nodes.items()
    ]
    exposed_params = {}
    reference_params = []
    for name, node_id in field_nodes.items():
        if store.nodes[node_id]["kind"] == "param":
            exposed_params[name] = node_id
        else:
            reference = store.add(
                "param", "%s: %s reference" % (title, name),
                floor={"op": "reference", "target": node_id}, actor=actor,
            )
            exposed_params[name] = reference
            reference_params.append(reference)
    owned = list(local_nodes) or list(field_nodes.values())
    group = store.add(
        "group",
        title,
        inner=list(dict.fromkeys(
            owned + reference_params + [keys_param, record] + wires
        )),
        params=exposed_params,
        actor=actor,
    )
    return {
        "group": group,
        "record": record,
        "fields": field_nodes,
        "params": exposed_params,
        "keys": keys_param,
        "wires": wires,
    }


def _capability_group(
    store: Store, title: str, capabilities: Iterable[Any], *, actor: str
) -> dict[str, Any]:
    values = [_text(value, "capability") for value in capabilities]
    if not values:
        raise ValueError("a connector needs at least one capability")
    if len(values) != len(set(values)):
        raise ValueError("connector capabilities must be unique")
    fields = {
        "capability:%03d" % index: _param(
            store, "%s: capability %03d" % (title, index), value, actor
        )
        for index, value in enumerate(values)
    }
    assembler = store.add(
        "op", "%s list" % title, floor={"op": "merge", "fn": "list"}, actor=actor
    )
    wires = [
        store.wire(node_id, assembler, title="Expose capability", actor=actor)
        for node_id in fields.values()
    ]
    group = store.add(
        "group", title,
        inner=list(fields.values()) + [assembler] + wires,
        params=fields,
        actor=actor,
    )
    return {
        "group": group,
        "record": assembler,
        "fields": fields,
        "wires": wires,
    }


def _health_group(
    store: Store,
    title: str,
    observation: Mapping[str, Any],
    enabled_param: str,
    health_policy: str,
    *,
    actor: str,
) -> dict[str, Any]:
    values = {
        "state": "loaded_dead",
        "observed_at": "",
        "evidence": "not observed",
        "latency_ms": None,
    }
    values.update(dict(observation))
    state = str(values["state"]).strip().casefold()
    policy = store.nodes[health_policy]
    allowed = store.pull(policy["params"]["allowed_states"])
    if state not in allowed:
        raise ValueError("health state must be one of %s" % ", ".join(allowed))
    values["state"] = state
    if state == store.pull(policy["params"]["live_state"]) and (
        not str(values["observed_at"]).strip() or not str(values["evidence"]).strip()
    ):
        raise ValueError("live health requires observed_at and evidence")

    health = _record_group(store, title, values, actor=actor)
    empty_literal = store.add(
        "value", "Non-empty requirement", floor={"op": "value", "value": ""},
        actor=actor,
    )
    true_literal = store.add(
        "value", "Enabled requirement", floor={"op": "value", "value": True},
        actor=actor,
    )
    checks = {}
    check_specs = (
        ("state", health["fields"]["state"], policy["params"]["live_state"], "=="),
        ("evidence", health["fields"]["evidence"], empty_literal, "!="),
        ("observed_at", health["fields"]["observed_at"], empty_literal, "!="),
        ("enabled", enabled_param, true_literal, "=="),
    )
    check_wires = []
    for name, left, right, comparison in check_specs:
        check = store.add(
            "op", "%s check" % name,
            floor={"op": "compare", "cmp": comparison}, actor=actor,
        )
        check_wires.extend([
            store.wire(left, check, actor=actor),
            store.wire(right, check, actor=actor),
        ])
        checks[name] = check
    available = store.add(
        "op", "Connector available",
        floor={"op": "math", "fn": "*"}, actor=actor,
    )
    availability_wires = [
        store.wire(check, available, title="Availability condition", actor=actor)
        for check in checks.values()
    ]
    health_inner = store.open(health["group"])
    store.edit(
        health["group"], ["body", "inner"],
        health_inner + [health_policy, empty_literal, true_literal]
        + list(checks.values()) + check_wires + [available] + availability_wires,
        actor=actor,
    )
    health.update({
        "available": available,
        "checks": checks,
        "availability_wires": availability_wires,
    })
    return health


def _link_part(
    store: Store, part_id: str, connector_id: str, port_id: str, *, actor: str
) -> str:
    return store.relation([
        {"role": "source", "direction": "out", "node_id": part_id,
         "port_id": "value", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": connector_id,
         "port_id": port_id, "cardinality": "one"},
    ], title="Connector exposes %s" % port_id, actor=actor)


def create_connector_catalog(
    store: Store, title: str = "Connector / Host Catalog", *,
    actor: str = "connectors-domain",
) -> str:
    marker = _param(store, "catalog_type", _CATALOG_MARKER, actor)
    return store.add(
        "group", title, inner=[marker], params={"catalog_type": marker}, actor=actor
    )


def create_health_policy(
    store: Store,
    states: Iterable[str] = DEFAULT_HEALTH_STATES,
    *,
    live_state: str = "live",
    actor: str = "connectors-domain",
) -> str:
    """Create the editable status vocabulary used by connector probes."""
    allowed = [str(state).strip().casefold() for state in states]
    if not allowed or any(not state for state in allowed) or len(set(allowed)) != len(allowed):
        raise ValueError("connector health states must be unique non-empty strings")
    live = str(live_state).strip().casefold()
    if live not in allowed:
        raise ValueError("live_state must be included in connector health states")
    allowed_param = _param(store, "allowed_states", allowed, actor)
    live_param = _param(store, "live_state", live, actor)
    return store.add(
        "group", "Connector health policy", inner=[allowed_param, live_param],
        params={"allowed_states": allowed_param, "live_state": live_param}, actor=actor,
    )


def _require_catalog(store: Store, catalog_id: str) -> dict[str, Any]:
    catalog = store.nodes.get(catalog_id)
    if not catalog or catalog["kind"] != "group":
        raise ValueError("connector catalog must be a group in the one table")
    marker = catalog["params"].get("catalog_type")
    if marker is None or store.pull(marker) != _CATALOG_MARKER:
        raise ValueError("node %s is not a connector catalog" % catalog_id)
    return catalog


def registered_connector_ids(store: Store, catalog_id: str) -> list[str]:
    """Resolve catalog membership only from explicit relation nodes."""
    catalog = _require_catalog(store, catalog_id)
    connector_ids = []
    for relation_id in store.open(catalog_id):
        relation = store.nodes.get(relation_id)
        if not relation or relation["kind"] != "wire":
            continue
        if not any(
            endpoint.get("node_id") == catalog_id
            and endpoint.get("port_id") == "connectors"
            for endpoint in relation_targets(store.nodes, relation)
        ):
            continue
        connector_ids.extend(
            endpoint["node_id"] for endpoint in relation_sources(store.nodes, relation)
        )
    return connector_ids


def register_connector(
    store: Store, catalog_id: str, connector_id: str, *,
    actor: str = "connectors-domain",
) -> str:
    catalog = _require_catalog(store, catalog_id)
    connector = store.nodes.get(connector_id)
    if not connector or connector["kind"] != "group":
        raise ValueError("connector must be an open group in the one table")
    if connector_id in registered_connector_ids(store, catalog_id):
        raise ValueError("connector is already registered")
    relation = store.relation([
        {"role": "source", "direction": "out", "node_id": connector_id,
         "port_id": "connector", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": catalog_id,
         "port_id": "connectors", "cardinality": "many"},
    ], title="Connector catalog membership", actor=actor)
    store.edit(
        catalog_id, ["body", "inner"], list(store.open(catalog_id)) + [relation],
        actor=actor,
    )
    return relation


def connector_parts(store: Store, connector_id: str) -> dict[str, str]:
    """Resolve exposed parts from the connector's actual relation incidence."""
    connector = store.nodes.get(connector_id)
    if not connector or connector["kind"] != "group":
        raise ValueError("connector must be an open group")
    parts = {}
    for relation_id in connector["relations"]:
        relation = store.nodes.get(relation_id)
        if not relation or relation["kind"] != "wire":
            continue
        target = next((
            endpoint for endpoint in relation_targets(store.nodes, relation)
            if endpoint.get("node_id") == connector_id
        ), None)
        if target is None or target.get("port_id") == "connectors":
            continue
        sources = relation_sources(store.nodes, relation)
        if len(sources) == 1:
            parts[str(target["port_id"])] = sources[0]["node_id"]
    return parts


def _build_connector(
    store: Store, raw: Mapping[str, Any], *, health_policy: str, actor: str
) -> dict[str, Any]:
    definition = dict(raw)
    allowed = {
        "key", "title", "capabilities", "endpoint", "configuration",
        "health", "plan", "secret_refs",
    }
    unknown = sorted(set(definition) - allowed)
    missing = sorted({"key", "title", "capabilities", "endpoint"} - set(definition))
    if unknown or missing:
        raise ValueError(
            "connector fields mismatch; missing=%r unknown=%r" % (missing, unknown)
        )
    key = _text(definition["key"], "connector key")
    title = _text(definition["title"], "connector title")

    endpoint_values = dict(definition["endpoint"])
    endpoint_values.setdefault("transport", "custom")
    endpoint_values.setdefault("address", "")
    endpoint_values.setdefault("enabled", True)
    endpoint_values.setdefault("timeout_ms", 8000)
    endpoint_values["transport"] = _text(
        endpoint_values["transport"], "endpoint transport"
    )
    for name, value in endpoint_values.items():
        _assert_no_secret_value(str(name), value)

    configuration_values = dict(definition.get("configuration") or {})
    for name, value in configuration_values.items():
        _assert_no_secret_value(str(name), value)

    definition_part = _record_group(
        store, "%s / Definition" % title,
        {"key": key, "title": title}, actor=actor,
    )
    capabilities_part = _capability_group(
        store, "%s / Capabilities" % title, definition["capabilities"], actor=actor
    )
    endpoint_part = _record_group(
        store, "%s / Endpoint" % title, endpoint_values, actor=actor
    )

    secret_nodes = {}
    config_nodes = {
        name: _param(store, "%s / Configuration: %s" % (title, name), value, actor)
        for name, value in configuration_values.items()
    }
    for name, reference in dict(definition.get("secret_refs") or {}).items():
        clean_name = _text(name, "secret reference name")
        clean_reference = _text(reference, "secret reference")
        if not clean_reference.startswith("op://"):
            raise ValueError("secret references must use op:// URIs")
        secret = store.add(
            "secret_ref", "%s / Secret reference: %s" % (title, clean_name),
            floor={"op": "secret_ref", "ref": clean_reference}, actor=actor,
        )
        secret_nodes[clean_name] = secret
        config_nodes[clean_name] = store.add(
            "param", "%s / Configuration reference: %s" % (title, clean_name),
            floor={"op": "reference", "target": secret}, actor=actor,
        )
    configuration_part = _record_group_from_nodes(
        store, "%s / Configuration" % title, config_nodes,
        local_nodes=list(config_nodes.values()) + list(secret_nodes.values()), actor=actor,
    )
    health_part = _health_group(
        store, "%s / Health observation" % title,
        dict(definition.get("health") or {}),
        endpoint_part["fields"]["enabled"], health_policy, actor=actor,
    )

    plan_values = dict(definition.get("plan") or {})
    selected = plan_values.pop(
        "selected_capability", store.pull(next(iter(capabilities_part["fields"].values())))
    )
    arguments = plan_values.pop("arguments", {})
    mutation = bool(plan_values.pop("mutation", False))
    for name, value in plan_values.items():
        _assert_no_secret_value(str(name), value)
    selected_param = _param(store, "%s / Selected capability" % title, selected, actor)
    arguments_param = _param(store, "%s / Arguments" % title, arguments, actor)
    mutation_param = _param(store, "%s / Mutation requested" % title, mutation, actor)
    extra_plan_params = {
        name: _param(store, "%s / Plan: %s" % (title, name), value, actor)
        for name, value in plan_values.items()
    }
    plan_fields = {
        "connector_key": definition_part["fields"]["key"],
        "selected_capability": selected_param,
        "capabilities": capabilities_part["record"],
        "endpoint": endpoint_part["record"],
        "configuration": configuration_part["record"],
        "arguments": arguments_param,
        "mutation": mutation_param,
        "available": health_part["available"],
    }
    plan_fields.update(extra_plan_params)
    plan_part = _record_group_from_nodes(
        store, "%s / Execution plan" % title, plan_fields,
        local_nodes=[selected_param, arguments_param, mutation_param]
        + list(extra_plan_params.values()), actor=actor,
    )

    effect_change = store.add(
        "param", "%s / Effect plan" % title,
        floor={"op": "reference", "target": plan_part["record"]}, actor=actor,
    )
    effect = store.add(
        "op", "%s / External execution" % title,
        floor={
            "op": "effect",
            "target": "connector:%s" % key,
            "change": {"$param": "change"},
        },
        params={"change": effect_change},
        frozen=True,
        actor=actor,
    )
    effect_group = store.add(
        "group", "%s / Execution gate" % title,
        inner=[effect_change, effect],
        params={"change": effect_change}, actor=actor,
    )

    part_ids = {
        "definition": definition_part["group"],
        "capabilities": capabilities_part["group"],
        "endpoint": endpoint_part["group"],
        "configuration": configuration_part["group"],
        "health": health_part["group"],
        "execution_plan": plan_part["group"],
        "execution_effect": effect_group,
    }
    connector = store.add(
        "group", title, inner=list(part_ids.values()), actor=actor
    )
    part_relations = {
        name: _link_part(store, part_id, connector, name, actor=actor)
        for name, part_id in part_ids.items()
    }
    store.edit(
        connector, ["body", "inner"],
        store.open(connector) + list(part_relations.values()), actor=actor,
    )
    return {
        "key": key,
        "connector": connector,
        "parts": part_ids,
        "part_relations": part_relations,
        "definition": definition_part,
        "capabilities": capabilities_part,
        "endpoint": endpoint_part,
        "configuration": configuration_part,
        "health": health_part,
        "plan": plan_part,
        "effect": effect,
        "effect_group": effect_group,
        "secret_refs": secret_nodes,
        "health_policy": health_policy,
    }


def build_connectors_domain(
    store: Store,
    *,
    connectors: Iterable[Mapping[str, Any]] = (),
    actor: str = "connectors-domain",
) -> dict[str, Any]:
    """Build a universal catalog and the supplied connector/host definitions."""
    catalog = create_connector_catalog(store, actor=actor)
    health_policy = create_health_policy(store, actor=actor)
    built = {}
    memberships = {}
    for raw in connectors:
        connector = _build_connector(store, raw, health_policy=health_policy, actor=actor)
        key = connector["key"]
        if key in built:
            raise ValueError("connector keys must be unique: %s" % key)
        built[key] = connector
        memberships[key] = register_connector(
            store, catalog, connector["connector"], actor=actor
        )
    session = store.add(
        "session", "Connectors / Hosts",
        inner=[catalog, health_policy] + [entry["connector"] for entry in built.values()]
        + list(memberships.values()), actor=actor,
    )
    return {
        "session": session,
        "catalog": catalog,
        "health_policy": health_policy,
        "connectors": built,
        "memberships": memberships,
    }


def observe_connector_health(
    store: Store,
    connector_id: str,
    state: str,
    *,
    observed_at: str,
    evidence: str,
    latency_ms: float | None = None,
    actor: str = "connector-observer",
) -> list[str]:
    """Write one explicit observation through audited parameter edits."""
    clean_state = str(state).strip().casefold()
    health_id = connector_parts(store, connector_id).get("health")
    if health_id is None:
        raise ValueError("connector has no health observation relation")
    policy_id = next((nid for nid in store.open(health_id)
                      if store.nodes[nid]["title"] == "Connector health policy"), None)
    if policy_id is None:
        raise ValueError("connector health observation has no policy node")
    policy = store.nodes[policy_id]
    allowed = store.pull(policy["params"]["allowed_states"])
    live_state = store.pull(policy["params"]["live_state"])
    if clean_state not in allowed:
        raise ValueError("health state must be one of %s" % ", ".join(allowed))
    clean_time = str(observed_at).strip()
    clean_evidence = str(evidence).strip()
    if clean_state == live_state and (not clean_time or not clean_evidence):
        raise ValueError("live health requires observed_at and evidence")
    health = store.nodes[health_id]
    values = {
        "state": clean_state,
        "observed_at": clean_time,
        "evidence": clean_evidence,
        "latency_ms": latency_ms,
    }
    order = ("state", "observed_at", "evidence", "latency_ms") \
        if clean_state != live_state else ("observed_at", "evidence", "latency_ms", "state")
    touched = []
    for name in order:
        param_id = health["params"].get(name)
        if param_id is None:
            raise ValueError("health observation is missing %s" % name)
        touched.append(store.edit(
            param_id, ["body", "floor", "value"], values[name], actor=actor
        ))
    return touched


def connector_status(store: Store, connector_id: str) -> str:
    """Project status from the visible health graph; no status registry exists."""
    health_id = connector_parts(store, connector_id).get("health")
    if health_id is None:
        return "missing"
    available = next((
        node_id for node_id in store.open(health_id)
        if store.nodes[node_id]["title"] == "Connector available"
    ), None)
    state_param = store.nodes[health_id]["params"].get("state")
    state = str(store.pull(state_param)) if state_param else "missing"
    return "live" if available is not None and bool(store.pull(available)) \
        else ("loaded_dead" if state == "live" else state)


__all__ = [
    "build_connectors_domain",
    "create_health_policy",
    "DEFAULT_HEALTH_STATES",
    "connector_parts",
    "connector_status",
    "create_connector_catalog",
    "observe_connector_health",
    "register_connector",
    "registered_connector_ids",
]
