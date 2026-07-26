"""Node-native session catalog built entirely from the one table.

The catalog is a generic group whose children are reference nodes. Session
metadata and lifecycle values are parameter nodes owned by each session. The
module keeps no registry, cache, or domain-specific state outside ``Store``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..core import Store, relation_sources


DEFAULT_LIFECYCLE_STATES = (
    "WIP",
    "SHARED",
    "PRODUCTION",
    "DEPLOYED",
    "ARCHIVE",
)

_CATALOG_MARKER = "node-native-session-catalog/v1"
_POLICY_MARKER = "node-native-lifecycle-policy/v1"
_RESERVED_METADATA = frozenset({"key", "lifecycle", "owner", "description"})


def _value_param(store: Store, name: str, value: Any, *, actor: str) -> str:
    return store.add(
        "param",
        name,
        floor={"op": "value", "value": value},
        actor=actor,
    )


def _require_node(store: Store, node_id: str, kind: str | None = None) -> dict[str, Any]:
    node = store.nodes.get(node_id)
    if node is None:
        raise KeyError("node %r is not in the one table" % node_id)
    if kind is not None and node["kind"] != kind:
        raise ValueError("node %s is kind %r, not %r" % (node_id, node["kind"], kind))
    return node


def _require_catalog(store: Store, catalog_id: str) -> dict[str, Any]:
    catalog = _require_node(store, catalog_id, "group")
    marker_id = catalog["params"].get("catalog_type")
    marker = store.nodes.get(marker_id) if marker_id else None
    floor = marker and marker.get("body", {}).get("floor")
    if not isinstance(floor, dict) or floor.get("op") != "value" \
            or floor.get("value") != _CATALOG_MARKER:
        raise ValueError("node %s is not a session catalog" % catalog_id)
    return catalog


def _clean_key(key: str) -> str:
    value = str(key).strip()
    if not value:
        raise ValueError("session key must be a non-empty string")
    return value


def _require_policy(store: Store, policy_id: str) -> dict[str, Any]:
    policy = _require_node(store, policy_id, "group")
    marker_id = policy["params"].get("policy_type")
    marker = store.nodes.get(marker_id) if marker_id else None
    floor = marker and marker.get("body", {}).get("floor")
    if not isinstance(floor, dict) or floor.get("op") != "value" \
            or floor.get("value") != _POLICY_MARKER:
        raise ValueError("node %s is not a lifecycle policy" % policy_id)
    return policy


def _clean_lifecycle(store: Store, lifecycle: str, policy_id: str) -> str:
    value = str(lifecycle).strip().upper()
    policy = _require_policy(store, policy_id)
    allowed = store.pull(policy["params"]["allowed_states"])
    if not isinstance(allowed, list) or not allowed or any(
            not isinstance(item, str) or not item.strip() for item in allowed):
        raise ValueError("lifecycle policy allowed_states must be a non-empty string list")
    allowed = [item.strip().upper() for item in allowed]
    if value not in allowed:
        raise ValueError(
            "lifecycle must be one of %s, got %r"
            % (", ".join(allowed), lifecycle)
        )
    return value


def create_lifecycle_policy(
    store: Store,
    states: Iterable[str] = DEFAULT_LIFECYCLE_STATES,
    *,
    title: str = "Session lifecycle policy",
    actor: str = "sessions-domain",
) -> str:
    """Create an open, editable lifecycle policy from parameter nodes."""
    allowed = [str(state).strip().upper() for state in states]
    if not allowed or any(not state for state in allowed) or len(set(allowed)) != len(allowed):
        raise ValueError("lifecycle policy states must be unique non-empty strings")
    marker = _value_param(store, "policy_type", _POLICY_MARKER, actor=actor)
    allowed_states = _value_param(store, "allowed_states", allowed, actor=actor)
    return store.add(
        "group", title, inner=[marker, allowed_states],
        params={"policy_type": marker, "allowed_states": allowed_states}, actor=actor,
    )


def create_session_catalog(
    store: Store,
    title: str = "Session Catalog",
    *,
    lifecycle_policy: str | None = None,
    actor: str = "sessions-domain",
) -> str:
    """Create an empty catalog group and return its node id."""
    policy = lifecycle_policy or create_lifecycle_policy(store, actor=actor)
    _require_policy(store, policy)
    catalog_type = _value_param(store, "catalog_type", _CATALOG_MARKER, actor=actor)
    policy_param = store.add(
        "param", "lifecycle_policy",
        floor={"op": "reference", "target": policy}, actor=actor,
    )
    catalog = store.add(
        "group",
        title,
        inner=[catalog_type, policy_param, policy],
        params={"catalog_type": catalog_type, "lifecycle_policy": policy_param},
        actor=actor,
    )
    relation = store.relation([
        {"role": "source", "direction": "out", "node_id": policy,
         "port_id": "allowed_states", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": catalog,
         "port_id": "lifecycle_policy", "cardinality": "one"},
    ], title="Lifecycle policy governs session catalog", actor=actor)
    store.edit(catalog, ["body", "inner"], store.open(catalog) + [relation], actor=actor)
    return catalog


def create_session(
    store: Store,
    key: str,
    title: str,
    *,
    members: Iterable[str] = (),
    lifecycle: str = "WIP",
    owner: str = "",
    description: str = "",
    metadata: Mapping[str, Any] | None = None,
    lifecycle_policy: str | None = None,
    actor: str = "sessions-domain",
) -> str:
    """Create one session node with node-owned metadata parameters."""
    clean_key = _clean_key(key)
    policy = lifecycle_policy or create_lifecycle_policy(store, actor=actor)
    clean_lifecycle = _clean_lifecycle(store, lifecycle, policy)
    member_ids = list(members)
    for member_id in member_ids:
        _require_node(store, member_id)

    extra = dict(metadata or {})
    conflicts = sorted(_RESERVED_METADATA.intersection(extra))
    if conflicts:
        raise ValueError("reserved session metadata keys: %s" % ", ".join(conflicts))
    if any(not isinstance(name, str) or not name.strip() for name in extra):
        raise ValueError("session metadata names must be non-empty strings")

    values = {
        "key": clean_key,
        "lifecycle": clean_lifecycle,
        "owner": str(owner),
        "description": str(description),
    }
    for name in sorted(extra):
        values[name] = extra[name]
    params = {
        name: _value_param(store, name, value, actor=actor)
        for name, value in values.items()
    }
    policy_param = store.add(
        "param", "lifecycle_policy",
        floor={"op": "reference", "target": policy}, actor=actor,
    )
    params["lifecycle_policy"] = policy_param
    session = store.add(
        "session",
        str(title),
        inner=member_ids + list(params.values()) + [policy],
        params=params,
        actor=actor,
    )
    relation = store.relation([
        {"role": "source", "direction": "out", "node_id": policy,
         "port_id": "allowed_states", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": session,
         "port_id": "lifecycle", "cardinality": "one"},
    ], title="Lifecycle policy governs session", actor=actor)
    store.edit(session, ["body", "inner"], store.open(session) + [relation], actor=actor)
    return session


def govern_existing_session(
    store: Store,
    session_id: str,
    key: str,
    *,
    lifecycle: str = "WIP",
    owner: str = "",
    description: str = "",
    lifecycle_policy: str | None = None,
    actor: str = "sessions-domain",
) -> str:
    """Attach visible session metadata and policy wiring to an existing session."""
    session = _require_node(store, session_id, "session")
    policy = lifecycle_policy or create_lifecycle_policy(store, actor=actor)
    clean_lifecycle = _clean_lifecycle(store, lifecycle, policy)
    values = {
        "key": _clean_key(key),
        "lifecycle": clean_lifecycle,
        "owner": str(owner),
        "description": str(description),
    }
    params = dict(session["params"])
    additions = []
    for name, value in values.items():
        if name not in params:
            params[name] = _value_param(store, name, value, actor=actor)
            additions.append(params[name])
    if "lifecycle_policy" not in params:
        params["lifecycle_policy"] = store.add(
            "param", "lifecycle_policy",
            floor={"op": "reference", "target": policy}, actor=actor,
        )
        additions.append(params["lifecycle_policy"])
    store.edit(session_id, ["params"], params, actor=actor)
    relation = store.relation([
        {"role": "source", "direction": "out", "node_id": policy,
         "port_id": "allowed_states", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": session_id,
         "port_id": "lifecycle", "cardinality": "one"},
    ], title="Lifecycle policy governs existing session", actor=actor)
    inner = list(session["body"]["inner"])
    store.edit(session_id, ["body", "inner"],
               list(dict.fromkeys(inner + additions + [policy, relation])), actor=actor)
    return session_id


def registered_session_ids(store: Store, catalog_id: str) -> list[str]:
    """Resolve session participants from explicit membership relations."""
    catalog = _require_catalog(store, catalog_id)
    session_ids: list[str] = []
    for relation_id in catalog["body"]["inner"]:
        relation = store.nodes.get(relation_id)
        if not relation or relation["kind"] != "wire":
            continue
        targets_catalog = any(
            endpoint.get("node_id") == catalog_id and endpoint.get("port_id") == "sessions"
            for endpoint in store.endpoints(relation_id)
        )
        if not targets_catalog:
            continue
        for endpoint in relation_sources(store.nodes, relation):
            session_id = endpoint.get("node_id")
            _require_node(store, session_id, "session")
            session_ids.append(session_id)
    return session_ids


def register_session(
    store: Store,
    catalog_id: str,
    session_id: str,
    *,
    actor: str = "sessions-domain",
) -> str:
    """Register a session by adding a generic reference to the catalog group."""
    catalog = _require_catalog(store, catalog_id)
    session = _require_node(store, session_id, "session")
    if session_id in registered_session_ids(store, catalog_id):
        raise ValueError("session %s is already registered" % session_id)

    key_id = session["params"].get("key")
    if key_id is None:
        raise ValueError("session %s has no key parameter" % session_id)
    key = store.pull(key_id)
    for existing_id in registered_session_ids(store, catalog_id):
        existing = store.nodes[existing_id]
        if store.pull(existing["params"]["key"]) == key:
            raise ValueError("session key %r is already registered" % key)

    reference_id = store.relation([
        {"role": "source", "direction": "out", "node_id": session_id,
         "port_id": "session", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": catalog_id,
         "port_id": "sessions", "cardinality": "many"},
    ], title="Catalog membership: %s" % key, actor=actor)
    store.edit(
        catalog_id,
        ["body", "inner"],
        list(catalog["body"]["inner"]) + [reference_id],
        actor=actor,
    )
    return reference_id


def session_metadata(store: Store, session_id: str) -> dict[str, Any]:
    """Pull all metadata parameters from a session node."""
    session = _require_node(store, session_id, "session")
    return {
        name: store.pull(param_id)
        for name, param_id in session["params"].items()
        if name != "lifecycle_policy"
    }


def set_session_lifecycle(
    store: Store,
    session_id: str,
    lifecycle: str,
    *,
    actor: str = "sessions-domain",
) -> str:
    """Edit the session's lifecycle parameter through the audited store path."""
    session = _require_node(store, session_id, "session")
    lifecycle_id = session["params"].get("lifecycle")
    if lifecycle_id is None:
        raise ValueError("session %s has no lifecycle parameter" % session_id)
    policy_param = session["params"].get("lifecycle_policy")
    if policy_param is None:
        raise ValueError("session %s has no lifecycle policy parameter" % session_id)
    policy_floor = store.nodes[policy_param]["body"]["floor"]
    policy_id = policy_floor.get("target")
    clean_lifecycle = _clean_lifecycle(store, lifecycle, policy_id)
    return store.edit(
        lifecycle_id,
        ["body", "floor", "value"],
        clean_lifecycle,
        actor=actor,
    )


__all__ = [
    "DEFAULT_LIFECYCLE_STATES",
    "create_lifecycle_policy",
    "create_session_catalog",
    "create_session",
    "govern_existing_session",
    "register_session",
    "registered_session_ids",
    "session_metadata",
    "set_session_lifecycle",
]
