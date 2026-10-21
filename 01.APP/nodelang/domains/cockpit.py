"""Founder Cockpit as an open, governed node graph.

The Cockpit is not a privileged Python dashboard. Its identity gate, command
intake, keyword evidence, routing, read capabilities, write previews, kill
switches, destructive effects, and audit cursor are ordinary nodes connected
by authoritative relations. Python in this module is only a construction and
boundary adapter over those graph-owned policies.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..core import NO_VALUE, Store
from ..laws_relation import append_stage, rewire_endpoint


DEFAULT_ROUTES = (
    {"id": "read", "title": "Read system state", "keywords": ["show", "read", "status", "check"]},
    {"id": "users", "title": "Inspect users", "keywords": ["user", "member", "account"]},
    {"id": "metrics", "title": "Inspect live metrics", "keywords": ["metric", "revenue", "usage"]},
    {"id": "write", "title": "Preview a governed write", "keywords": ["write", "change", "update"]},
    {"id": "purge", "title": "Purge test users", "keywords": ["purge", "delete test user"]},
    {"id": "kill", "title": "Change a kill switch", "keywords": ["kill switch", "disable", "stop"]},
    {"id": "self_extend", "title": "Direct self-extension", "keywords": ["build", "extend", "implement"]},
)

DEFAULT_SECRET_MARKERS = (
    "password", "passwd", "api_key", "apikey", "access_token",
    "refresh_token", "private_key", "authorization: bearer", "secret=",
)


def _text(value: Any, label: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add("param", title, floor={"op": "value", "value": value}, actor=actor)


def _reference_param(store: Store, title: str, target: str, actor: str) -> str:
    if target not in store.nodes:
        raise KeyError("reference target %r is not in the one table" % target)
    return store.add(
        "param", title, floor={"op": "reference", "target": target}, actor=actor
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
    values: Mapping[str, Any],
    actor: str,
) -> tuple[str, str, dict[str, str]]:
    params = {
        name: _param(store, "%s: %s" % (title, name), value, actor)
        for name, value in values.items()
    }
    inner = list(params.values())
    record = _op(
        store,
        "Assemble %s" % title,
        {"op": "merge", "fn": "record", "keys": list(values)},
        params.values(),
        inner,
        actor,
    )
    group = store.add("group", title, inner=inner, params=params, actor=actor)
    return group, record, params


def _relation_source_param(store: Store, relation_id: str) -> str:
    relation = store.nodes[relation_id]
    names = sorted(name for name in relation["params"] if name.startswith("endpoint:"))
    for name in names:
        pid = relation["params"][name]
        endpoint = store.pull(pid)
        if endpoint.get("role") == "source" or endpoint.get("direction") in (
            "out", "read", "source"
        ):
            return pid
    raise ValueError("relation has no source endpoint parameter")


def build_cockpit_domain(
    store: Store,
    *,
    founder_id: str = "founder",
    role: str = "owner",
    identity_verified: bool = False,
    founder_enabled: bool = True,
    routes: Iterable[Mapping[str, Any]] = DEFAULT_ROUTES,
    secret_markers: Iterable[str] = DEFAULT_SECRET_MARKERS,
    source_nodes: Mapping[str, str] | None = None,
    self_extension_node: str | None = None,
    actor: str = "cockpit-domain",
) -> dict[str, Any]:
    """Build the operational Founder Cockpit in the existing one-table store."""
    source_nodes = dict(source_nodes or {})
    for name, node_id in source_nodes.items():
        if node_id not in store.nodes:
            raise KeyError("Cockpit source %s=%r is not in the one table" % (name, node_id))
    if self_extension_node is not None and self_extension_node not in store.nodes:
        raise KeyError("self-extension node is not in the one table")

    route_records = []
    for raw in routes:
        record = dict(raw)
        if set(record) != {"id", "title", "keywords"}:
            raise ValueError("route fields must be id, title, and keywords")
        keywords = [_text(item, "route keyword") for item in record["keywords"]]
        if not keywords:
            raise ValueError("route needs at least one keyword")
        route_records.append({
            "id": _text(record["id"], "route id"),
            "title": _text(record["title"], "route title"),
            "keywords": keywords,
        })
    route_ids = [record["id"] for record in route_records]
    if not route_records or len(route_ids) != len(set(route_ids)):
        raise ValueError("route ids must be present and unique")
    markers = [_text(item, "secret marker").casefold() for item in secret_markers]
    if not markers or len(markers) != len(set(markers)):
        raise ValueError("secret markers must be present and unique")

    all_relations: list[str] = []
    identity_group, identity_record, identity_params = _record_group(
        store,
        "Founder identity evidence",
        {
            "founder_id": _text(founder_id, "founder id"),
            "role": _text(role, "role"),
            "verified": bool(identity_verified),
            "enabled": bool(founder_enabled),
        },
        actor,
    )
    expected_role = _param(store, "Founder role policy", "owner", actor)
    true_node = store.add("value", "True", floor={"op": "value", "value": True}, actor=actor)
    gate_inner = [identity_group, expected_role, true_node]
    role_gate = _op(
        store, "Founder role gate", {"op": "compare", "cmp": "=="},
        [identity_params["role"], expected_role], gate_inner, actor,
    )
    verified_gate = _op(
        store, "Verified identity gate", {"op": "compare", "cmp": "=="},
        [identity_params["verified"], true_node], gate_inner, actor,
    )
    enabled_gate = _op(
        store, "Founder flag gate", {"op": "compare", "cmp": "=="},
        [identity_params["enabled"], true_node], gate_inner, actor,
    )
    founder_gate = _op(
        store, "Founder-only verdict", {"op": "math", "fn": "*"},
        [role_gate, verified_gate, enabled_gate], gate_inner, actor,
    )
    founder_gate_group = store.add(
        "group", "Founder-only gate", inner=gate_inner,
        params={"expected_role": expected_role}, actor=actor,
    )

    command = _param(store, "Cockpit command", "show system status", actor)
    submitted_by = _param(store, "Cockpit command submitted by", founder_id, actor)
    submitted_at = _param(store, "Cockpit command submitted at", "", actor)
    redacted = _param(store, "Cockpit command was withheld", False, actor)
    redaction_reason = _param(store, "Cockpit redaction reason", "", actor)

    redactor_inner = [command, redacted, redaction_reason]
    marker_params = []
    marker_checks = []
    for index, marker in enumerate(markers):
        marker_param = _param(store, "Secret marker %03d" % index, marker, actor)
        marker_params.append(marker_param)
        marker_checks.append(_op(
            store, "Command contains secret marker %03d" % index,
            {"op": "compare", "cmp": "icontains"},
            [command, marker_param], redactor_inner, actor,
        ))
    secret_hits = _op(
        store, "Secret marker hits", {"op": "math", "fn": "+"},
        marker_checks, redactor_inner, actor,
    )
    zero_node = store.add("value", "Zero", floor={"op": "value", "value": 0}, actor=actor)
    command_safe = _op(
        store, "Command is safe to persist", {"op": "compare", "cmp": "=="},
        [secret_hits, zero_node], redactor_inner, actor,
    )
    redactor_group = store.add(
        "group", "Secret redactor and withholding gate", inner=redactor_inner,
        params={
            "command": command,
            "redacted": redacted,
            "reason": redaction_reason,
            **{"marker:%03d" % index: pid for index, pid in enumerate(marker_params)},
        },
        actor=actor,
    )

    route_groups: dict[str, str] = {}
    route_scores: dict[str, str] = {}
    route_params: dict[str, dict[str, str]] = {}
    candidate_records: list[str] = []
    router_inner: list[str] = [redactor_group]
    for order, record in enumerate(route_records):
        params = {
            "id": _param(store, "Route id", record["id"], actor),
            "title": _param(store, "Route title", record["title"], actor),
            "order": _param(store, "Route order", order, actor),
        }
        checks = []
        route_inner = list(params.values())
        for index, keyword in enumerate(record["keywords"]):
            keyword_param = _param(
                store, "%s keyword %03d" % (record["title"], index), keyword, actor
            )
            params["keyword:%03d" % index] = keyword_param
            route_inner.append(keyword_param)
            checks.append(_op(
                store, "%s keyword match %03d" % (record["title"], index),
                {"op": "compare", "cmp": "icontains"},
                [command, keyword_param], route_inner, actor,
            ))
        score = _op(
            store, "%s route score" % record["title"],
            {"op": "math", "fn": "max"}, checks, route_inner, actor,
        )
        score_number = _op(
            store, "%s route score number" % record["title"],
            {"op": "math", "fn": "*"}, [score, true_node], route_inner, actor,
        )
        candidate = _op(
            store, "%s route candidate" % record["title"],
            {"op": "merge", "fn": "record", "keys": ["id", "title", "score", "order"]},
            [params["id"], params["title"], score_number, params["order"]],
            route_inner, actor,
        )
        group = store.add(
            "group", "Route: %s" % record["title"], inner=route_inner,
            params=params, actor=actor,
        )
        route_groups[record["id"]] = group
        route_scores[record["id"]] = score_number
        route_params[record["id"]] = params
        candidate_records.append(candidate)
        router_inner.append(group)
    candidates = _op(
        store, "Cockpit route candidates", {"op": "merge", "fn": "list"},
        candidate_records, router_inner, actor,
    )
    selected_candidate = _op(
        store, "Selected Cockpit route",
        {"op": "reduce", "mode": "argmax", "key_path": "score", "default": {}},
        [candidates], router_inner, actor,
    )
    selected_route = _op(
        store, "Selected Cockpit route id", {"op": "field", "path": "id", "default": "read"},
        [selected_candidate], router_inner, actor,
    )
    router_group = store.add("group", "Offline keyword router", inner=router_inner, actor=actor)

    capability_groups: dict[str, str] = {}
    capability_records: dict[str, str] = {}
    capability_params: dict[str, dict[str, str]] = {}
    dispatch_relations: dict[str, str] = {}
    dispatch_source_params: dict[str, str] = {}
    for route in route_records:
        key = route["id"]
        group, record, params = _record_group(
            store,
            "Cockpit capability: %s" % route["title"],
            {
                "id": key,
                "title": route["title"],
                "mode": "read" if key in {"read", "users", "metrics"} else "write-preview",
                "target_ref": "node://%s" % source_nodes.get(key, "unbound"),
            },
            actor,
        )
        capability_groups[key] = group
        capability_records[key] = record
        capability_params[key] = params
        relation = store.relation([
            {"role": "source", "direction": "out", "node_id": selected_route,
             "port_id": "route", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": group,
             "port_id": "command", "cardinality": "one"},
        ], title="Cockpit dispatch: %s" % key, actor=actor)
        append_stage(store, relation, route_scores[key], mode="guard", actor=actor)
        dispatch_relations[key] = relation
        dispatch_source_params[key] = _relation_source_param(store, relation)
        all_relations.append(relation)

    read_tools_group = store.add(
        "group", "Read tools run immediately",
        inner=[capability_groups[key] for key in ("read", "users", "metrics")
               if key in capability_groups],
        actor=actor,
    )

    source_groups: dict[str, str] = {}
    source_relations: dict[str, str] = {}
    for name, node_id in source_nodes.items():
        source_ref = _reference_param(store, "%s live source" % name, node_id, actor)
        source_groups[name] = store.add(
            "group", "Cockpit live source: %s" % name,
            inner=[source_ref], params={"source": source_ref}, actor=actor,
        )
        source_relations[name] = store.relation([
            {"role": "source", "direction": "out", "node_id": node_id,
             "port_id": "live_state", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": source_groups[name],
             "port_id": name, "cardinality": "one"},
        ], title="%s reaches Founder Cockpit" % name, actor=actor)
        all_relations.append(source_relations[name])
    user_view = store.add(
        "group", "User database view",
        inner=[source_groups[name] for name in source_groups if "user" in name], actor=actor,
    )
    live_metrics = store.add(
        "group", "Live metrics panel",
        inner=[source_groups[name] for name in source_groups if "metric" in name or name in {
            "brain", "hooks", "governance", "grand_map", "revenue"
        }], actor=actor,
    )

    write_target = _param(store, "Write preview target", "", actor)
    write_change = _param(store, "Write preview change", {}, actor)
    write_approved = _param(store, "Write preview approved", False, actor)
    write_approver = _param(store, "Write preview approver", "", actor)
    write_inner = [write_target, write_change, write_approved, write_approver]
    approval_gate = _op(
        store, "Write preview approval gate", {"op": "compare", "cmp": "=="},
        [write_approved, true_node], write_inner, actor,
    )
    write_effect = store.add(
        "op", "Cockpit governed write effect",
        floor={"op": "effect", "target": {"$param": "target"},
               "change": {"$param": "change"}},
        params={"target": write_target, "change": write_change},
        frozen=True, actor=actor,
    )
    write_inner.append(write_effect)
    write_preview_group = store.add(
        "group", "Gated-write preview card", inner=write_inner,
        params={"target": write_target, "change": write_change,
                "approved": write_approved, "approver": write_approver}, actor=actor,
    )
    write_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": command,
         "port_id": "intent", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": write_effect,
         "port_id": "effect", "cardinality": "one"},
    ], title="Cockpit command reaches governed write", actor=actor)
    for gate in (command_safe, founder_gate, approval_gate):
        append_stage(store, write_relation, gate, mode="guard", actor=actor)
    append_stage(store, write_relation, write_effect, mode="map", actor=actor)
    all_relations.append(write_relation)

    purge_armed = _param(store, "Purge test users armed", False, actor)
    purge_scope = _param(store, "Purge test users scope", "test-only", actor)
    purge_inner = [purge_armed, purge_scope]
    purge_gate = _op(
        store, "Purge is armed", {"op": "compare", "cmp": "=="},
        [purge_armed, true_node], purge_inner, actor,
    )
    purge_effect = store.add(
        "op", "Purge test users effect",
        floor={"op": "effect", "payload": {"$param": "scope"}},
        params={"scope": purge_scope}, frozen=True, actor=actor,
    )
    purge_inner.append(purge_effect)
    purge_group = store.add(
        "group", "Purge test users", inner=purge_inner,
        params={"armed": purge_armed, "scope": purge_scope}, actor=actor,
    )

    kill_enabled = _param(store, "Global kill switch enabled", False, actor)
    kill_reason = _param(store, "Global kill switch reason", "", actor)
    kill_inner = [kill_enabled, kill_reason]
    kill_effect = store.add(
        "op", "Kill switch effect",
        floor={"op": "effect", "target": "runtime.enabled",
               "change": {"$param": "enabled"}},
        params={"enabled": kill_enabled}, frozen=True, actor=actor,
    )
    kill_inner.append(kill_effect)
    kill_switch_group = store.add(
        "group", "Kill switches and Founder flags", inner=kill_inner,
        params={"enabled": kill_enabled, "reason": kill_reason}, actor=actor,
    )

    destructive_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": purge_group,
         "port_id": "request", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": purge_effect,
         "port_id": "effect", "cardinality": "one"},
    ], title="Founder-gated purge relation", actor=actor)
    append_stage(store, destructive_relation, founder_gate, mode="guard", actor=actor)
    append_stage(store, destructive_relation, purge_gate, mode="guard", actor=actor)
    all_relations.append(destructive_relation)

    withheld_group = store.add(
        "group", "Withheld actions - founder hands only",
        inner=[purge_group, kill_switch_group, write_preview_group], actor=actor,
    )
    audit_sequence = _param(store, "Cockpit audit sequence", 0, actor)
    audit_event = _param(store, "Cockpit last audit event", {}, actor)
    audit_group = store.add(
        "group", "Cockpit audit log", inner=[audit_sequence, audit_event],
        params={"sequence": audit_sequence, "last_event": audit_event}, actor=actor,
    )

    direct_agent_inner = [router_group, read_tools_group, write_preview_group]
    direct_agent_relation = None
    if self_extension_node is not None:
        direct_agent_relation = store.relation([
            {"role": "source", "direction": "out", "node_id": router_group,
             "port_id": "direct", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": self_extension_node,
             "port_id": "proposal", "cardinality": "one"},
        ], title="Cockpit directs self-extension through an explicit wire", actor=actor)
        append_stage(store, direct_agent_relation, founder_gate, mode="guard", actor=actor)
        direct_agent_inner.append(direct_agent_relation)
        all_relations.append(direct_agent_relation)
    direct_agent_group = store.add(
        "group", "Cockpit agent reason-tool-observe loop",
        inner=direct_agent_inner, actor=actor,
    )

    surface_group = store.add(
        "group", "Cockpit first surface authority",
        inner=[founder_gate_group, direct_agent_group, user_view, live_metrics,
               withheld_group, audit_group], actor=actor,
    )
    session_params = {
        "lifecycle": _param(store, "Cockpit lifecycle", "WIP", actor),
        "surface": _reference_param(store, "Cockpit surface", surface_group, actor),
        "command": command,
        "submitted_by": submitted_by,
        "submitted_at": submitted_at,
        "redacted": redacted,
        "redaction_reason": redaction_reason,
        "redactor": _reference_param(store, "Cockpit redactor", redactor_group, actor),
        "selected_route": _reference_param(
            store, "Cockpit selected route", selected_route, actor),
        "audit_sequence": audit_sequence,
        "audit_event": audit_event,
    }
    session = store.add(
        "session", "Founder Cockpit domain",
        inner=[identity_group, founder_gate_group, redactor_group, router_group,
               read_tools_group, user_view, live_metrics, write_preview_group,
               purge_group, kill_switch_group, withheld_group, audit_group,
               direct_agent_group, surface_group] + all_relations,
        params=session_params,
        actor=actor,
    )

    return {
        "session": session,
        "surface": surface_group,
        "identity": identity_group,
        "identity_record": identity_record,
        "identity_params": identity_params,
        "founder_gate": founder_gate_group,
        "founder_verdict": founder_gate,
        "command": command,
        "submitted_by": submitted_by,
        "submitted_at": submitted_at,
        "redacted": redacted,
        "redaction_reason": redaction_reason,
        "redactor": redactor_group,
        "command_safe": command_safe,
        "routes": route_groups,
        "route_scores": route_scores,
        "route_params": route_params,
        "router": router_group,
        "selected_candidate": selected_candidate,
        "selected_route": selected_route,
        "capabilities": capability_groups,
        "capability_records": capability_records,
        "capability_params": capability_params,
        "dispatch_relations": dispatch_relations,
        "dispatch_source_params": dispatch_source_params,
        "read_tools": read_tools_group,
        "source_groups": source_groups,
        "source_relations": source_relations,
        "user_view": user_view,
        "live_metrics": live_metrics,
        "write_preview": write_preview_group,
        "write_effect": write_effect,
        "write_relation": write_relation,
        "write_params": {
            "target": write_target, "change": write_change,
            "approved": write_approved, "approver": write_approver,
        },
        "purge": purge_group,
        "purge_effect": purge_effect,
        "purge_params": {"armed": purge_armed, "scope": purge_scope},
        "kill_switches": kill_switch_group,
        "kill_effect": kill_effect,
        "kill_params": {"enabled": kill_enabled, "reason": kill_reason},
        "withheld": withheld_group,
        "audit": audit_group,
        "audit_params": {"sequence": audit_sequence, "last_event": audit_event},
        "agent_loop": direct_agent_group,
        "direct_agent_relation": direct_agent_relation,
        "relations": all_relations,
    }


def submit_cockpit_command(
    store: Store,
    domain: Mapping[str, Any],
    command: Any,
    *,
    submitted_by: str = "founder",
    submitted_at: str = "",
    actor: str = "cockpit-boundary",
) -> dict[str, Any]:
    """Persist a safe command or a redacted placeholder using graph-owned markers."""
    raw = str(command)
    redactor = store.nodes[domain["redactor"]]
    markers = [
        str(store.pull(pid)).casefold()
        for name, pid in sorted(redactor["params"].items())
        if name.startswith("marker:")
    ]
    matched = [marker for marker in markers if marker in raw.casefold()]
    safe_value = "[REDACTED BY COCKPIT POLICY]" if matched else raw
    store.edit(domain["command"], ["body", "floor", "value"], safe_value, actor=actor)
    store.edit(domain["submitted_by"], ["body", "floor", "value"], str(submitted_by), actor=actor)
    store.edit(domain["submitted_at"], ["body", "floor", "value"], str(submitted_at), actor=actor)
    store.edit(domain["redacted"], ["body", "floor", "value"], bool(matched), actor=actor)
    store.edit(
        domain["redaction_reason"], ["body", "floor", "value"],
        "secret-shaped input withheld" if matched else "", actor=actor,
    )
    route = store.pull(domain["selected_route"])
    record_cockpit_event(
        store, domain,
        {"event": "command_submitted", "route": route, "redacted": bool(matched)},
        actor=actor,
    )
    return {"route": route, "redacted": bool(matched), "value": safe_value}


def record_cockpit_event(
    store: Store,
    domain: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    actor: str = "cockpit",
) -> int:
    """Advance the graph audit cursor; Store history is the append-only log."""
    sequence = int(store.pull(domain["audit_params"]["sequence"])) + 1
    store.edit(
        domain["audit_params"]["sequence"], ["body", "floor", "value"], sequence,
        actor=actor,
    )
    store.edit(
        domain["audit_params"]["last_event"], ["body", "floor", "value"],
        dict(event), actor=actor,
    )
    return sequence


def set_founder_evidence(
    store: Store,
    domain: Mapping[str, Any],
    *,
    role: str | None = None,
    verified: bool | None = None,
    enabled: bool | None = None,
    actor: str = "identity-boundary",
) -> None:
    values = {"role": role, "verified": verified, "enabled": enabled}
    for name, value in values.items():
        if value is None:
            continue
        store.edit(
            domain["identity_params"][name], ["body", "floor", "value"], value,
            actor=actor,
        )


def rewire_dispatch(
    store: Store,
    domain: Mapping[str, Any],
    route_id: str,
    source_node: str,
    *,
    actor: str = "founder",
) -> str:
    """Expose dispatch as the relation endpoint it actually is."""
    relation = domain["dispatch_relations"][route_id]
    endpoint = domain["dispatch_source_params"][route_id]
    return rewire_endpoint(store, relation, endpoint, node_id=source_node, actor=actor)


def cockpit_write_preview(store: Store, domain: Mapping[str, Any]) -> Any:
    return store.pull(domain["write_relation"])


__all__ = [
    "DEFAULT_ROUTES", "DEFAULT_SECRET_MARKERS", "build_cockpit_domain",
    "cockpit_write_preview", "record_cockpit_event", "rewire_dispatch",
    "set_founder_evidence", "submit_cockpit_command",
]
