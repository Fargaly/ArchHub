"""Universal external-resource adapters built from the one node primitive.

Files, repositories, daemons, databases, providers, and publication hosts are
payload locations, not parallel control planes. Each adapter keeps identity,
schema, policy, ports, health evidence, lineage, and effects in the graph.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..core import Store
from ..laws_relation import attach_payload, build_payload_envelope


_SECRET_WORDS = frozenset({
    "password", "secret", "token", "credential", "private_key", "api_key",
    "access_key", "refresh_token", "client_secret",
})
_SECRET_PREFIXES = ("sk-", "ghp_", "github_pat_", "bearer ", "xoxb-")


DEFAULT_RESOURCES = (
    {
        "id": "governance-standard", "title": "Workspace governance authority",
        "resource_type": "urn:archhub:resource:governance-document",
        "locator": "workspace://00.GOVERNANCE/WORKSPACE-STANDARD.md",
        "privacy_tier": "T1 INTERNAL", "lifecycle": "PRODUCTION",
        "schema_ref": "urn:archhub:schema:workspace-standard", "schema_version": "1",
        "read_enabled": True, "write_enabled": True, "founder_only": True,
        "probe": {"mode": "resource", "expected": "file"},
        "ports": ({"id": "rules", "direction": "out", "logical_type": "text/markdown"},),
    },
    {
        "id": "public-repository", "title": "Public product repository",
        "resource_type": "urn:archhub:resource:repository",
        "locator": "workspace://10.PRODUCT",
        "privacy_tier": "T0 PUBLIC", "lifecycle": "WIP",
        "schema_ref": "urn:archhub:schema:git-repository", "schema_version": "1",
        "read_enabled": True, "write_enabled": True, "founder_only": True,
        "probe": {"mode": "resource", "expected": "directory"},
        "ports": (
            {"id": "tree", "direction": "out", "logical_type": "urn:archhub:git:tree"},
            {"id": "change", "direction": "in", "logical_type": "urn:archhub:git:change"},
        ),
    },
    {
        "id": "grand-map-authority", "title": "Grand Map authority",
        "resource_type": "urn:archhub:resource:graph-authority",
        "locator": "authority://grand-map", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "WIP", "schema_ref": "urn:archhub:schema:grand-map",
        "schema_version": "1", "read_enabled": True, "write_enabled": True,
        "founder_only": True, "probe": {"mode": "resource", "expected": "file"},
        "ports": ({"id": "graph", "direction": "out", "logical_type": "urn:archhub:node-graph"},),
    },
    {
        "id": "brain-daemon", "title": "Brain daemon",
        "resource_type": "urn:archhub:resource:coordination-service",
        "locator": "http://127.0.0.1:8473/mcp", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "DEPLOYED", "schema_ref": "urn:archhub:schema:mcp",
        "schema_version": "2025-03-26", "read_enabled": True, "write_enabled": True,
        "founder_only": True, "probe": {
            "mode": "resource", "timeout": 2.0, "method": "POST", "status": 200,
            "headers": {"Accept": "application/json, text/event-stream"},
            "json": {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "brain.health", "arguments": {}}},
            "contains": "\"result\"",
        },
        "ports": (
            {"id": "memory", "direction": "out", "logical_type": "urn:archhub:brain:record"},
            {"id": "governed-work", "direction": "out", "logical_type": "urn:archhub:work-leaf"},
            {"id": "report", "direction": "in", "logical_type": "urn:archhub:run-report"},
        ),
    },
    {
        "id": "application-runtime", "title": "Application runtime",
        "resource_type": "urn:archhub:resource:graph-runtime",
        "locator": "http://127.0.0.1:8482/api/state", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "DEPLOYED", "schema_ref": "urn:archhub:schema:node-graph-api",
        "schema_version": "1", "read_enabled": True, "write_enabled": True,
        "founder_only": True, "probe": {"mode": "resource", "timeout": 2.0},
        "ports": (
            {"id": "projection", "direction": "out", "logical_type": "urn:archhub:ui-projection"},
            {"id": "mutation", "direction": "in", "logical_type": "urn:archhub:graph-operation"},
        ),
    },
    {
        "id": "identity-database", "title": "User identity database",
        "resource_type": "urn:archhub:resource:identity-database",
        "locator": "https://archhub-cloud.fly.dev/readyz", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "WIP", "schema_ref": "urn:archhub:schema:identity",
        "schema_version": "1", "read_enabled": True, "write_enabled": False,
        "founder_only": True, "probe": {
            "mode": "resource", "timeout": 5.0,
            "response_path": ["capabilities", "database", "ok"],
            "expected_value": True,
        },
        "ports": (
            {"id": "identity", "direction": "out", "logical_type": "urn:archhub:identity"},
            {"id": "account-change", "direction": "in", "logical_type": "urn:archhub:identity-change"},
        ),
    },
    {
        "id": "application-database", "title": "Application database",
        "resource_type": "urn:archhub:resource:database",
        "locator": "https://archhub-cloud.fly.dev/readyz", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "WIP", "schema_ref": "urn:archhub:schema:application-data",
        "schema_version": "1", "read_enabled": True, "write_enabled": False,
        "founder_only": True, "probe": {
            "mode": "resource", "timeout": 5.0,
            "response_path": ["capabilities", "database", "ok"],
            "expected_value": True,
        },
        "ports": ({"id": "records", "direction": "out", "logical_type": "urn:archhub:record"},),
    },
    {
        "id": "object-storage", "title": "Object storage",
        "resource_type": "urn:archhub:resource:content-store",
        "locator": "https://archhub-cloud.fly.dev/readyz", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "WIP", "schema_ref": "urn:archhub:schema:content-descriptor",
        "schema_version": "1", "read_enabled": True, "write_enabled": False,
        "founder_only": True, "probe": {
            "mode": "resource", "timeout": 5.0,
            "response_path": ["capabilities", "persistent_storage", "ok"],
            "expected_value": True,
        },
        "ports": ({"id": "content", "direction": "out", "logical_type": "urn:archhub:content-reference"},),
    },
    {
        "id": "billing-provider", "title": "Billing provider",
        "resource_type": "urn:archhub:resource:payment-provider",
        "locator": "https://archhub-cloud.fly.dev/readyz", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "WIP", "schema_ref": "urn:archhub:schema:billing-event",
        "schema_version": "1", "read_enabled": True, "write_enabled": False,
        "founder_only": True, "probe": {
            "mode": "resource", "timeout": 5.0,
            "response_path": ["capabilities", "billing", "ok"],
            "expected_value": True,
        },
        "ports": ({"id": "billing-event", "direction": "out", "logical_type": "urn:archhub:billing-event"},),
    },
    {
        "id": "email-provider", "title": "Transactional email provider",
        "resource_type": "urn:archhub:resource:messaging-provider",
        "locator": "https://archhub-cloud.fly.dev/readyz", "privacy_tier": "T1 INTERNAL",
        "lifecycle": "WIP", "schema_ref": "urn:archhub:schema:message",
        "schema_version": "1", "read_enabled": True, "write_enabled": False,
        "founder_only": True, "probe": {
            "mode": "resource", "timeout": 5.0,
            "response_path": ["capabilities", "email", "ok"],
            "expected_value": True,
        },
        "ports": ({"id": "message", "direction": "in", "logical_type": "urn:archhub:message"},),
    },
    {
        "id": "website-publication", "title": "Public website publication",
        "resource_type": "urn:archhub:resource:publication-host",
        "locator": "https://archhub.io/", "privacy_tier": "T0 PUBLIC",
        "lifecycle": "DEPLOYED", "schema_ref": "urn:archhub:schema:website-publication",
        "schema_version": "1", "read_enabled": True, "write_enabled": False,
        "founder_only": True, "probe": {
            "mode": "resource", "timeout": 5.0, "contains": "<title>ArchHub",
        },
        "ports": ({"id": "site", "direction": "out", "logical_type": "text/html"},),
    },
)


def _reject_raw_secrets(value: Any, path: str = "resource") -> None:
    if isinstance(value, Mapping):
        for raw_name, item in value.items():
            name = str(raw_name).casefold().replace("-", "_")
            child = "%s.%s" % (path, raw_name)
            secret_field = any(word in name for word in _SECRET_WORDS)
            if secret_field and not (name.endswith("_ref") and str(item).startswith("op://")):
                raise ValueError("%s may contain a raw secret; use an op:// secret_ref" % child)
            _reject_raw_secrets(item, child)
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _reject_raw_secrets(item, "%s[%d]" % (path, index))
    elif isinstance(value, str) and value.casefold().startswith(_SECRET_PREFIXES):
        raise ValueError("%s contains a probable raw secret" % path)


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add("param", title, floor={"op": "value", "value": value}, actor=actor)


def _record(store: Store, title: str, values: Mapping[str, Any], actor: str) -> dict[str, Any]:
    fields = {name: _param(store, "%s: %s" % (title, name), value, actor)
              for name, value in values.items()}
    record = store.add("op", "%s record" % title,
                       floor={"op": "merge", "fn": "record", "keys": list(fields)}, actor=actor)
    wires = [store.wire(node_id, record, title="%s field" % name, actor=actor)
             for name, node_id in fields.items()]
    group = store.add("group", title, inner=list(fields.values()) + [record],
                      params=fields, actor=actor)
    return {"group": group, "record": record, "fields": fields, "wires": wires}


def _normalize(raw: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(raw)
    required = {
        "id", "title", "resource_type", "locator", "privacy_tier", "lifecycle",
        "schema_ref", "schema_version", "read_enabled", "write_enabled",
        "founder_only", "probe", "ports",
    }
    if set(item) != required:
        raise ValueError("resource fields must be exactly %r" % sorted(required))
    _reject_raw_secrets(item)
    item["id"] = str(item["id"]).strip()
    item["title"] = str(item["title"]).strip()
    item["locator"] = str(item["locator"]).strip()
    if not item["id"] or not item["title"] or not item["locator"]:
        raise ValueError("resource id, title, and locator are required")
    ports = [dict(port) for port in item["ports"]]
    port_ids = [str(port.get("id") or "").strip() for port in ports]
    if not port_ids or any(not port_id for port_id in port_ids) or len(port_ids) != len(set(port_ids)):
        raise ValueError("resource ports need unique non-empty ids")
    item["ports"] = ports
    return item


def _build_resource(store: Store, raw: Mapping[str, Any], actor: str) -> dict[str, Any]:
    item = _normalize(raw)
    definition = _record(store, "%s / Identity" % item["title"], {
        "resource_id": item["id"], "title": item["title"],
        "resource_type": item["resource_type"], "locator": item["locator"],
    }, actor)
    schema = _record(store, "%s / Schema" % item["title"], {
        "schema_ref": item["schema_ref"], "schema_version": item["schema_version"],
    }, actor)
    policy = _record(store, "%s / Policy" % item["title"], {
        "privacy_tier": item["privacy_tier"], "lifecycle": item["lifecycle"],
        "read_enabled": bool(item["read_enabled"]),
        "write_enabled": bool(item["write_enabled"]),
        "founder_only": bool(item["founder_only"]),
    }, actor)

    ports = {
        port["id"]: _param(store, "%s / Port: %s" % (item["title"], port["id"]), port, actor)
        for port in item["ports"]
    }
    port_group = store.add("group", "%s / Ports" % item["title"],
                           inner=list(ports.values()), params=ports, actor=actor)

    probe_spec = dict(item["probe"])
    probe_spec.pop("mode", None)
    probe_spec["locator"] = item["locator"]
    probe = store.add("op", "%s / Live resource probe" % item["title"],
                      floor={"op": "probe", "kind": "resource", "spec": probe_spec}, actor=actor)
    health_ok = store.add("op", "%s / Health truth" % item["title"],
                          floor={"op": "probe_ok", "probe": probe}, actor=actor)
    authority_signal = _param(store, "%s / Founder authority signal" % item["title"], False, actor)
    read_gate = store.add("op", "%s / Read gate" % item["title"],
                          floor={"op": "math", "fn": "*"}, actor=actor)
    write_gate = store.add("op", "%s / Write gate" % item["title"],
                           floor={"op": "math", "fn": "*"}, actor=actor)
    gate_wires = [
        store.wire(policy["fields"]["read_enabled"], read_gate, actor=actor),
        store.wire(health_ok, read_gate, actor=actor),
        store.wire(policy["fields"]["write_enabled"], write_gate, actor=actor),
        store.wire(health_ok, write_gate, actor=actor),
        store.wire(authority_signal, write_gate, actor=actor),
    ]
    controls = store.add(
        "group", "%s / Controls" % item["title"],
        inner=[probe, health_ok, authority_signal, read_gate, write_gate],
        params={"authority_signal": authority_signal}, actor=actor,
    )

    plan = _record(store, "%s / Write plan" % item["title"], {
        "resource_id": item["id"], "operation": "write",
        "payload_ref": "", "schema_ref": item["schema_ref"],
    }, actor)
    target_param = store.add("param", "%s / Effect target" % item["title"],
                             floor={"op": "reference", "target": definition["fields"]["locator"]}, actor=actor)
    change_param = store.add("param", "%s / Effect change" % item["title"],
                             floor={"op": "reference", "target": plan["record"]}, actor=actor)
    effect = store.add(
        "op", "%s / Frozen external effect" % item["title"],
        floor={"op": "effect", "target": {"$param": "target"},
               "change": {"$param": "change"}},
        params={"target": target_param, "change": change_param}, frozen=True, actor=actor,
    )
    write_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": plan["record"],
         "port_id": "plan", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": effect,
         "port_id": "change", "cardinality": "one"},
    ], title="%s / Governed write path" % item["title"],
        stages=[{"role": "gate", "mode": "guard", "node_id": write_gate}], actor=actor)
    effects = store.add(
        "group", "%s / Effects" % item["title"],
        inner=[plan["group"], target_param, change_param, effect, write_relation], actor=actor,
    )

    lineage = _record(store, "%s / Lineage" % item["title"], {
        "authority": "graph-control/external-payload",
        "source_locator": item["locator"], "adapter_version": "resource-adapter-v1",
    }, actor)
    exposed_computed = {
        "health": health_ok, "read_gate": read_gate, "write_gate": write_gate,
    }
    computed_params = {
        name: store.add("param", "%s / Exposed %s" % (item["title"], name),
                        floor={"op": "reference", "target": node_id}, actor=actor)
        for name, node_id in exposed_computed.items()
    }
    adapter_params = {
        "resource_id": definition["fields"]["resource_id"],
        "resource_type": definition["fields"]["resource_type"],
        "locator": definition["fields"]["locator"],
        "privacy_tier": policy["fields"]["privacy_tier"],
        "lifecycle": policy["fields"]["lifecycle"],
    }
    adapter_params.update(computed_params)
    adapter_params.update({"port:%s" % name: node_id for name, node_id in ports.items()})
    adapter = store.add(
        "group", item["title"],
        inner=[definition["group"], schema["group"], policy["group"], port_group,
               controls, effects, lineage["group"]] + list(computed_params.values()),
        params=adapter_params, actor=actor,
    )
    return {
        "adapter": adapter, "definition": definition, "schema": schema,
        "policy": policy, "ports": ports, "port_group": port_group,
        "probe": probe, "health_ok": health_ok, "authority_signal": authority_signal,
        "read_gate": read_gate, "write_gate": write_gate, "gate_wires": gate_wires,
        "plan": plan, "effect": effect, "write_relation": write_relation,
        "effects": effects, "lineage": lineage, "resource_type": item["resource_type"],
        "schema_ref": item["schema_ref"], "locator": item["locator"],
    }


def build_resource_domain(
    store: Store, *, resources: Iterable[Mapping[str, Any]] = DEFAULT_RESOURCES,
    actor: str = "resource-domain",
) -> dict[str, Any]:
    normalized = [_normalize(raw) for raw in resources]
    ids = [item["id"] for item in normalized]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("resource ids must be unique and non-empty")
    built = {item["id"]: _build_resource(store, item, actor) for item in normalized}
    readiness = store.add("op", "External resource readiness",
                          floor={"op": "math", "fn": "avg"}, actor=actor)
    readiness_wires = [store.wire(item["health_ok"], readiness, actor=actor)
                       for item in built.values()]
    authority = _param(store, "Resource control authority", "ArchHub operating graph", actor)
    readiness_param = store.add(
        "param", "External resource readiness reference",
        floor={"op": "reference", "target": readiness}, actor=actor,
    )
    session = store.add(
        "session", "External resources",
        inner=[authority] + [item["adapter"] for item in built.values()]
        + [readiness, readiness_param],
        params={"authority": authority, "readiness": readiness_param}, actor=actor,
    )
    return {"session": session, "resources": built, "readiness": readiness,
            "readiness_wires": readiness_wires, "authority": authority,
            "connections": []}


def bind_resource_authority(store: Store, resource: Mapping[str, Any], authority_node: str,
                            actor: str = "resource-authority") -> str:
    """Make founder authority flow through an explicit relation into the gate."""
    if authority_node not in store.nodes:
        raise KeyError("authority node is not in the graph")
    signal = resource["authority_signal"]
    store.edit(signal, ["body", "floor"], {"op": "copy"}, actor=actor)
    return store.relation([
        {"role": "source", "direction": "out", "node_id": authority_node,
         "port_id": "verdict", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": signal,
         "port_id": "authority", "cardinality": "one"},
    ], title="Founder authority controls external resource", actor=actor)


def connect_resource(
    store: Store, domain: Mapping[str, Any], resource_id: str, target_node: str, *,
    target_port: str, actor: str = "resource-integration",
) -> str:
    """Connect a resource adapter to a graph consumer with an open payload envelope."""
    resource = domain["resources"][resource_id]
    relation = store.relation([
        {"role": "source", "direction": "out", "node_id": resource["adapter"],
         "port_id": "resource", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": target_node,
         "port_id": target_port, "cardinality": "one"},
    ], title="%s supplies %s" % (resource_id, target_port), actor=actor)
    envelope = build_payload_envelope(store, {
        "logical_type": resource["resource_type"],
        "schema_ref": resource["schema_ref"], "mode": "reference",
        "value_ref": resource["adapter"], "source_locator": resource["locator"],
    }, title="%s payload" % resource_id, actor=actor)
    attach_payload(store, relation, envelope, actor=actor)
    domain["connections"].append(relation)
    return relation


def resource_status(store: Store, domain: Mapping[str, Any], resource_id: str) -> dict[str, Any]:
    resource = domain["resources"][resource_id]
    evidence = store.pull(resource["probe"])
    if not evidence.get("ok"):
        status = "offline"
    elif bool(store.pull(resource["write_gate"])):
        status = "writable"
    elif bool(store.pull(resource["read_gate"])):
        status = "readable"
    else:
        status = "blocked"
    return {"resource_id": resource_id, "status": status, "evidence": evidence}


__all__ = [
    "DEFAULT_RESOURCES", "bind_resource_authority", "build_resource_domain",
    "connect_resource", "resource_status",
]
