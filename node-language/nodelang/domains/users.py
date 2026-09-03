"""Node-native users, identity, roles, entitlements, and ownership.

The graph is the authority. Profiles, policies, authentication evidence, and
assignments are open groups in ``Store.nodes``. Authentication material never
enters the graph: only external ``op://`` capability references are accepted.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..core import Store, relation_sources
from ..laws_relation import rewire_endpoint


PRIVACY_LEVELS = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "SECRET": 3,
}

DEFAULT_ROLES = (
    {
        "id": "owner",
        "title": "Owner",
        "rank": 3,
        "privacy_clearance": 3,
        "permissions": ["manage", "invite", "transfer", "read", "write"],
    },
    {
        "id": "admin",
        "title": "Administrator",
        "rank": 2,
        "privacy_clearance": 2,
        "permissions": ["manage", "invite", "read", "write"],
    },
    {
        "id": "member",
        "title": "Member",
        "rank": 1,
        "privacy_clearance": 1,
        "permissions": ["read", "write"],
    },
)

DEFAULT_ENTITLEMENTS = (
    {
        "id": "workspace",
        "title": "Workspace access",
        "enabled": True,
        "source": "firm-plan",
        "expires_at": "",
    },
)

_ROLE_FIELDS = frozenset(
    {"id", "title", "rank", "privacy_clearance", "permissions"}
)
_ENTITLEMENT_FIELDS = frozenset(
    {"id", "title", "enabled", "source", "expires_at"}
)
_USER_FIELDS = frozenset(
    {"id", "display_name", "email", "role", "entitlements", "auth"}
)
_AUTH_FIELDS = frozenset({"capability_ref", "evidence"})
_EVIDENCE_FIELDS = frozenset(
    {"provider", "method", "verified", "verified_at", "subject_ref"}
)
_SESSION_FIELDS = frozenset({"id", "title", "owner", "privacy_scope"})
_SECRET_WORDS = (
    "password", "passwd", "secret", "credential", "api_key", "apikey",
    "access_token", "refresh_token", "id_token", "private_key",
    "code_verifier", "authorization",
)


def _identifier(value: Any, label: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _exact_fields(record: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    keys = set(record)
    missing = sorted(allowed - keys)
    unknown = sorted(keys - allowed)
    if missing or unknown:
        raise ValueError(
            "%s fields mismatch; missing=%r unknown=%r" % (label, missing, unknown)
        )


def _reject_raw_secrets(value: Any, path: str = "input") -> None:
    """Reject credential-shaped values before any node can be created."""
    if isinstance(value, Mapping):
        for raw_name, item in value.items():
            name = str(raw_name).casefold().replace("-", "_")
            child_path = "%s.%s" % (path, raw_name)
            if any(word in name for word in _SECRET_WORDS):
                if not (name.endswith("_ref") and str(item).startswith("op://")):
                    raise ValueError(
                        "%s may contain a raw credential; use an op:// capability reference"
                        % child_path
                    )
            _reject_raw_secrets(item, child_path)
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _reject_raw_secrets(item, "%s[%d]" % (path, index))


def _privacy_level(
    value: Any, label: str = "privacy scope",
    levels: Mapping[str, int] = PRIVACY_LEVELS,
) -> int:
    if isinstance(value, str):
        key = value.strip().upper()
        if key not in levels:
            raise ValueError("%s must be one of %s" % (label, ", ".join(levels)))
        return int(levels[key])
    level = int(value)
    if level not in levels.values():
        raise ValueError("%s must match a privacy policy level" % label)
    return level


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add(
        "param", title, floor={"op": "value", "value": value}, actor=actor
    )


def _reference_param(store: Store, title: str, target: str, actor: str) -> str:
    return store.add(
        "param", title, floor={"op": "reference", "target": target}, actor=actor
    )


def _record_group(
    store: Store,
    title: str,
    values: Mapping[str, Any],
    *,
    terminal_field: str | None = None,
    actor: str,
) -> tuple[str, dict[str, str]]:
    """Build an open parameter record; optionally expose one field as its value."""
    params = {name: _param(store, name, value, actor) for name, value in values.items()}
    record = store.add(
        "op", "%s record" % title,
        floor={"op": "merge", "fn": "record", "keys": list(params)},
        actor=actor,
    )
    wires = [
        store.wire(param_id, record, title="%s -> %s" % (name, title), actor=actor)
        for name, param_id in params.items()
    ]
    # Relations remain first-class nodes and are discoverable from every
    # participant's ``relations`` list. Keeping them outside ``inner`` avoids
    # making the relation values additional computational outputs of the group.
    inner = list(params.values()) + [record]
    if terminal_field is not None:
        terminal = store.add(
            "op", "%s / %s" % (title, terminal_field),
            floor={"op": "field", "path": terminal_field}, actor=actor,
        )
        terminal_wire = store.wire(
            record, terminal,
            title="%s exposes %s" % (title, terminal_field), actor=actor,
        )
        inner.append(terminal)
    group = store.add("group", title, inner=inner, params=params, actor=actor)
    return group, params


def create_privacy_policy(
    store: Store,
    levels: Mapping[str, int] = PRIVACY_LEVELS,
    *,
    actor: str = "users-domain",
) -> str:
    """Create the editable privacy vocabulary used by role/session gates."""
    normalized = {str(name).strip().upper(): int(value)
                  for name, value in dict(levels).items()}
    if not normalized or any(not name for name in normalized):
        raise ValueError("privacy policy names must be non-empty")
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("privacy policy levels must be unique")
    params = {name: _param(store, "privacy level: " + name, value, actor)
              for name, value in normalized.items()}
    return store.add(
        "group", "Privacy Policy", inner=list(params.values()), params=params, actor=actor
    )


def _role_record(raw: Mapping[str, Any], levels: Mapping[str, int]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _ROLE_FIELDS, "role")
    permissions = record["permissions"]
    if isinstance(permissions, (str, bytes)) or not isinstance(permissions, Iterable):
        raise ValueError("role permissions must be an iterable")
    permissions = [_identifier(item, "permission") for item in permissions]
    if len(permissions) != len(set(permissions)):
        raise ValueError("role permissions contain duplicates")
    rank = int(record["rank"])
    if rank < 0:
        raise ValueError("role rank must be non-negative")
    return {
        "id": _identifier(record["id"], "role id"),
        "title": _identifier(record["title"], "role title"),
        "rank": rank,
        "privacy_clearance": _privacy_level(
            record["privacy_clearance"], "role privacy clearance", levels
        ),
        "permissions": permissions,
    }


def _entitlement_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _ENTITLEMENT_FIELDS, "entitlement")
    return {
        "id": _identifier(record["id"], "entitlement id"),
        "title": _identifier(record["title"], "entitlement title"),
        "enabled": bool(record["enabled"]),
        "source": _identifier(record["source"], "entitlement source"),
        "expires_at": str(record["expires_at"]),
    }


def _auth_group(
    store: Store, user_id: str, raw: Mapping[str, Any], actor: str
) -> tuple[str, str, dict[str, str]]:
    auth = dict(raw)
    _exact_fields(auth, _AUTH_FIELDS, "authentication")
    _reject_raw_secrets(auth, "authentication")
    capability_ref = _identifier(auth["capability_ref"], "auth capability reference")
    if not capability_ref.startswith("op://"):
        raise ValueError("auth capability reference must start with op://")
    evidence = dict(auth["evidence"])
    _exact_fields(evidence, _EVIDENCE_FIELDS, "authentication evidence")
    capability = store.add(
        "secret_ref", "External authentication capability",
        floor={"op": "secret_ref", "ref": capability_ref}, actor=actor,
    )
    capability_param = _reference_param(
        store, "capability_ref", capability, actor
    )
    evidence_group, evidence_params = _record_group(
        store,
        "Authentication evidence: %s" % user_id,
        {
            "provider": str(evidence["provider"]),
            "method": str(evidence["method"]),
            "verified": bool(evidence["verified"]),
            "verified_at": str(evidence["verified_at"]),
            "subject_ref": str(evidence["subject_ref"]),
        },
        actor=actor,
    )
    group = store.add(
        "group", "Authentication: %s" % user_id,
        inner=[capability, capability_param, evidence_group],
        params={"capability_ref": capability_param}, actor=actor,
    )
    return group, capability, evidence_params


def _source_endpoint_param(store: Store, relation_id: str, port_id: str) -> str:
    endpoints = store.endpoints(relation_id)
    matching = [
        endpoint for endpoint in endpoints
        if endpoint.get("role") == "source" and endpoint.get("port_id") == port_id
    ]
    if len(matching) != 1:
        raise ValueError(
            "relation %s needs exactly one %s source" % (relation_id, port_id)
        )
    return str(matching[0]["endpoint_param"])


def build_users_domain(
    store: Store,
    *,
    users: Iterable[Mapping[str, Any]],
    sessions: Iterable[Mapping[str, Any]] = (),
    roles: Iterable[Mapping[str, Any]] = DEFAULT_ROLES,
    entitlements: Iterable[Mapping[str, Any]] = DEFAULT_ENTITLEMENTS,
    firm: Mapping[str, Any] | None = None,
    actor: str = "users-domain",
) -> dict[str, Any]:
    """Build the users domain entirely in the supplied one-table store."""
    raw_users = [dict(item) for item in users]
    raw_sessions = [dict(item) for item in sessions]
    raw_roles = [dict(item) for item in roles]
    raw_entitlements = [dict(item) for item in entitlements]
    _reject_raw_secrets(
        {"users": raw_users, "sessions": raw_sessions,
         "roles": raw_roles, "entitlements": raw_entitlements}
    )
    privacy_policy = create_privacy_policy(store, actor=actor)
    privacy_levels = {
        name: int(store.pull(param_id))
        for name, param_id in store.nodes[privacy_policy]["params"].items()
    }

    role_records = [_role_record(item, privacy_levels) for item in raw_roles]
    if len({item["id"] for item in role_records}) != len(role_records):
        raise ValueError("role ids must be unique")
    role_groups: dict[str, str] = {}
    role_params: dict[str, dict[str, str]] = {}
    for record in role_records:
        group, params = _record_group(
            store, "Role: %s" % record["title"], record,
            terminal_field="privacy_clearance", actor=actor,
        )
        role_groups[record["id"]] = group
        role_params[record["id"]] = params

    entitlement_records = [_entitlement_record(item) for item in raw_entitlements]
    if len({item["id"] for item in entitlement_records}) != len(entitlement_records):
        raise ValueError("entitlement ids must be unique")
    entitlement_groups: dict[str, str] = {}
    entitlement_params: dict[str, dict[str, str]] = {}
    for record in entitlement_records:
        group, params = _record_group(
            store, "Entitlement: %s" % record["title"], record,
            terminal_field="enabled", actor=actor,
        )
        entitlement_groups[record["id"]] = group
        entitlement_params[record["id"]] = params

    firm_values = {
        "id": "primary-firm",
        "name": "Primary firm",
        "plan": "studio",
        "seat_limit": 5,
    }
    if firm is not None:
        firm_values.update(dict(firm))
    firm_values["id"] = _identifier(firm_values["id"], "firm id")
    firm_values["name"] = _identifier(firm_values["name"], "firm name")
    firm_values["seat_limit"] = int(firm_values["seat_limit"])
    if firm_values["seat_limit"] < 1:
        raise ValueError("firm seat_limit must be positive")
    firm_group, firm_params = _record_group(
        store, "Firm: %s" % firm_values["name"], firm_values, actor=actor
    )

    user_groups: dict[str, str] = {}
    profile_groups: dict[str, str] = {}
    profile_params: dict[str, dict[str, str]] = {}
    auth_groups: dict[str, str] = {}
    auth_capabilities: dict[str, str] = {}
    auth_evidence_params: dict[str, dict[str, str]] = {}
    role_relations: dict[str, str] = {}
    membership_relations: dict[str, str] = {}
    entitlement_relations: dict[str, dict[str, str]] = {}

    for raw in raw_users:
        _exact_fields(raw, _USER_FIELDS, "user")
        user_id = _identifier(raw["id"], "user id")
        if user_id in user_groups:
            raise ValueError("user ids must be unique")
        role_id = _identifier(raw["role"], "user role")
        if role_id not in role_groups:
            raise ValueError("unknown role %r" % role_id)
        entitlement_ids = [_identifier(item, "user entitlement")
                           for item in raw["entitlements"]]
        unknown = sorted(set(entitlement_ids) - set(entitlement_groups))
        if unknown:
            raise ValueError("unknown entitlements %r" % unknown)

        profile, params = _record_group(
            store,
            "Profile: %s" % user_id,
            {
                "id": user_id,
                "display_name": str(raw["display_name"]),
                "email": str(raw["email"]).strip().casefold(),
            },
            actor=actor,
        )
        auth, capability, evidence_params = _auth_group(
            store, user_id, dict(raw["auth"]), actor
        )
        profile_ref = _reference_param(store, "profile", profile, actor)
        auth_ref = _reference_param(store, "authentication", auth, actor)
        user = store.add(
            "group", "User: %s" % user_id,
            inner=[profile, auth, profile_ref, auth_ref],
            params={"profile": profile_ref, "authentication": auth_ref}, actor=actor,
        )
        user_groups[user_id] = user
        profile_groups[user_id] = profile
        profile_params[user_id] = params
        auth_groups[user_id] = auth
        auth_capabilities[user_id] = capability
        auth_evidence_params[user_id] = evidence_params

        role_relation = store.relation([
            {"role": "source", "direction": "out", "node_id": role_groups[role_id],
             "port_id": "role", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": user,
             "port_id": "role_assignment", "cardinality": "one"},
        ], title="Role assignment: %s" % user_id, actor=actor)
        role_relations[user_id] = role_relation

        membership_relations[user_id] = store.relation([
            {"role": "source", "direction": "out", "node_id": user,
             "port_id": "member", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": firm_group,
             "port_id": "members", "cardinality": "many"},
        ], title="Firm membership: %s" % user_id, actor=actor)

        entitlement_relations[user_id] = {}
        for entitlement_id in entitlement_ids:
            entitlement_relations[user_id][entitlement_id] = store.relation([
                {"role": "source", "direction": "out",
                 "node_id": entitlement_groups[entitlement_id],
                 "port_id": "entitlement", "cardinality": "one"},
                {"role": "target", "direction": "in", "node_id": user,
                 "port_id": "entitlements", "cardinality": "many"},
            ], title="Entitlement assignment: %s / %s" % (user_id, entitlement_id),
               actor=actor)

    session_groups: dict[str, str] = {}
    session_params: dict[str, dict[str, str]] = {}
    ownership_relations: dict[str, str] = {}
    privacy_gates: dict[str, str] = {}
    privacy_compare_nodes: dict[str, str] = {}
    privacy_relations: dict[str, tuple[str, str]] = {}

    for raw in raw_sessions:
        _exact_fields(raw, _SESSION_FIELDS, "session")
        session_id = _identifier(raw["id"], "session id")
        if session_id in session_groups:
            raise ValueError("session ids must be unique")
        owner_id = _identifier(raw["owner"], "session owner")
        if owner_id not in user_groups:
            raise ValueError("unknown session owner %r" % owner_id)
        privacy_level = _privacy_level(raw["privacy_scope"], levels=privacy_levels)
        params = {
            "id": _param(store, "id", session_id, actor),
            "privacy_scope": _param(store, "privacy_scope", privacy_level, actor),
        }
        session = store.add(
            "session", str(raw["title"]),
            inner=list(params.values()), params=params, actor=actor,
        )
        session_groups[session_id] = session
        session_params[session_id] = params
        ownership_relations[session_id] = store.relation([
            {"role": "source", "direction": "out", "node_id": user_groups[owner_id],
             "port_id": "owner", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": session,
             "port_id": "owned_session", "cardinality": "one"},
        ], title="Session ownership: %s" % session_id, actor=actor)

        role_relation = role_relations[owner_id]
        compare = store.add(
            "op", "Privacy gate decision: %s" % session_id,
            floor={"op": "compare", "cmp": ">="}, actor=actor,
        )
        clearance_wire = store.relation([
            {"role": "source", "direction": "out", "node_id": role_relation,
             "port_id": "assigned_clearance", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": compare,
             "port_id": "clearance", "cardinality": "one"},
        ], title="Assigned role supplies privacy clearance", actor=actor)
        scope_wire = store.relation([
            {"role": "source", "direction": "out",
             "node_id": params["privacy_scope"], "port_id": "required_level",
             "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": compare,
             "port_id": "required_level", "cardinality": "one"},
        ], title="Session supplies required privacy level", actor=actor)
        gate = store.add(
            "group", "Privacy gate: %s" % session_id,
            inner=[compare], actor=actor,
        )
        privacy_compare_nodes[session_id] = compare
        privacy_gates[session_id] = gate
        privacy_relations[session_id] = (clearance_wire, scope_wire)

    domain_inner = (
        [privacy_policy] + list(role_groups.values()) + list(entitlement_groups.values()) + [firm_group] +
        list(user_groups.values()) + list(role_relations.values()) +
        list(membership_relations.values()) +
        [relation for assignments in entitlement_relations.values()
         for relation in assignments.values()] +
        list(session_groups.values()) + list(ownership_relations.values()) +
        list(privacy_gates.values())
    )
    domain_session = store.add(
        "session", "Users and Identity Domain", inner=domain_inner, actor=actor
    )
    return {
        "session": domain_session,
        "privacy_policy": privacy_policy,
        "roles": role_groups,
        "role_params": role_params,
        "entitlements": entitlement_groups,
        "entitlement_params": entitlement_params,
        "firm": firm_group,
        "firm_params": firm_params,
        "users": user_groups,
        "profiles": profile_groups,
        "profile_params": profile_params,
        "auth_groups": auth_groups,
        "auth_capabilities": auth_capabilities,
        "auth_evidence_params": auth_evidence_params,
        "role_relations": role_relations,
        "membership_relations": membership_relations,
        "entitlement_relations": entitlement_relations,
        "sessions": session_groups,
        "session_params": session_params,
        "ownership_relations": ownership_relations,
        "privacy_gates": privacy_gates,
        "privacy_compare_nodes": privacy_compare_nodes,
        "privacy_relations": privacy_relations,
    }


def assigned_role(store: Store, domain: Mapping[str, Any], user_id: str) -> str:
    relation_id = str(domain["role_relations"][user_id])
    sources = relation_sources(store.nodes, store.nodes[relation_id])
    if len(sources) != 1:
        raise ValueError("user %s does not have exactly one role" % user_id)
    role_node = sources[0]["node_id"]
    for role_id, node_id in domain["roles"].items():
        if node_id == role_node:
            return str(role_id)
    raise ValueError("role relation points outside the domain role groups")


def rewire_role(
    store: Store, domain: Mapping[str, Any], user_id: str, role_id: str,
    *, actor: str = "users-domain",
) -> str:
    if role_id not in domain["roles"]:
        raise KeyError("unknown role %r" % role_id)
    relation_id = str(domain["role_relations"][user_id])
    endpoint = _source_endpoint_param(store, relation_id, "role")
    return rewire_endpoint(
        store, relation_id, endpoint, node_id=str(domain["roles"][role_id]), actor=actor
    )


def session_owner(store: Store, domain: Mapping[str, Any], session_id: str) -> str:
    relation_id = str(domain["ownership_relations"][session_id])
    sources = relation_sources(store.nodes, store.nodes[relation_id])
    if len(sources) != 1:
        raise ValueError("session %s does not have exactly one owner" % session_id)
    owner_node = sources[0]["node_id"]
    for user_id, node_id in domain["users"].items():
        if node_id == owner_node:
            return str(user_id)
    raise ValueError("ownership relation points outside the domain users")


def rewire_session_owner(
    store: Store, domain: Mapping[str, Any], session_id: str, user_id: str,
    *, actor: str = "users-domain",
) -> str:
    if user_id not in domain["users"]:
        raise KeyError("unknown user %r" % user_id)
    relation_id = str(domain["ownership_relations"][session_id])
    endpoint = _source_endpoint_param(store, relation_id, "owner")
    return rewire_endpoint(
        store, relation_id, endpoint, node_id=str(domain["users"][user_id]), actor=actor
    )


def privacy_allowed(store: Store, domain: Mapping[str, Any], session_id: str) -> bool:
    return bool(store.pull(str(domain["privacy_gates"][session_id])))


def set_profile_parameter(
    store: Store, domain: Mapping[str, Any], user_id: str, name: str, value: Any,
    *, actor: str = "users-domain",
) -> str:
    if name not in domain["profile_params"][user_id]:
        raise KeyError("unknown profile parameter %r" % name)
    if name == "id":
        value = _identifier(value, "user id")
    elif name == "email":
        value = str(value).strip().casefold()
    return store.edit(
        str(domain["profile_params"][user_id][name]),
        ["body", "floor", "value"], value, actor=actor,
    )


def set_role_parameter(
    store: Store, domain: Mapping[str, Any], role_id: str, name: str, value: Any,
    *, actor: str = "users-domain",
) -> str:
    if name not in domain["role_params"][role_id]:
        raise KeyError("unknown role parameter %r" % name)
    if name == "privacy_clearance":
        policy = store.nodes[domain["privacy_policy"]]
        levels = {key: int(store.pull(pid)) for key, pid in policy["params"].items()}
        value = _privacy_level(value, "role privacy clearance", levels)
    elif name == "rank":
        value = int(value)
        if value < 0:
            raise ValueError("role rank must be non-negative")
    return store.edit(
        str(domain["role_params"][role_id][name]),
        ["body", "floor", "value"], value, actor=actor,
    )


def set_entitlement_parameter(
    store: Store, domain: Mapping[str, Any], entitlement_id: str,
    name: str, value: Any, *, actor: str = "users-domain",
) -> str:
    if name not in domain["entitlement_params"][entitlement_id]:
        raise KeyError("unknown entitlement parameter %r" % name)
    if name == "enabled":
        value = bool(value)
    return store.edit(
        str(domain["entitlement_params"][entitlement_id][name]),
        ["body", "floor", "value"], value, actor=actor,
    )


__all__ = [
    "PRIVACY_LEVELS",
    "DEFAULT_ROLES",
    "DEFAULT_ENTITLEMENTS",
    "build_users_domain",
    "create_privacy_policy",
    "assigned_role",
    "rewire_role",
    "session_owner",
    "rewire_session_owner",
    "privacy_allowed",
    "set_profile_parameter",
    "set_role_parameter",
    "set_entitlement_parameter",
]
