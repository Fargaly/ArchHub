"""Node-native cloud services, deployment, synchronization, and queues.

The Grand Map cloud leaves are represented as open generic groups in the one
node table.  Endpoint, health, authorization, queue, and plan fields are
parameter nodes.  Relationships and execution guards are relation nodes.
External deploy/sync effects are inspectable dry-runs and frozen by default.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..core import Store


HEALTH_STATES = ("online", "offline", "degraded", "unauthorized", "unknown")
_AUTHORITY = "Grand Map / cloud"
_SECRET_WORDS = frozenset({
    "password", "secret", "token", "credential", "private_key", "api_key",
    "access_key", "refresh_token", "client_secret",
})
_SECRET_PREFIXES = ("sk-", "ghp_", "github_pat_", "bearer ", "xoxb-")


GRAND_MAP_CLOUD_SERVICES = (
    {
        "id": "cloud_fly_app", "title": "Cloud application host", "role": "host",
        "endpoint": {"transport": "https", "address": "https://archhub-cloud.fly.dev", "enabled": True, "timeout_ms": 5000},
        "configuration": {"app": "archhub-cloud", "primary_region": "ord", "scale_mode": "scale-to-zero"},
    },
    {
        "id": "cloud_persistent_db", "title": "Persistent database", "role": "persistence",
        "endpoint": {"transport": "volume", "address": "/data", "enabled": True, "timeout_ms": 5000},
        "configuration": {"engine": "sqlite", "mount": "/data", "replication_plan": "portable"},
    },
    {
        "id": "cloud_healthz", "title": "Health endpoint", "role": "health",
        "endpoint": {"transport": "https", "address": "/healthz", "enabled": True, "timeout_ms": 5000},
        "configuration": {"interval_seconds": 30, "grace_seconds": 10},
    },
    {
        "id": "cloud_auth", "title": "Authentication service", "role": "identity",
        "endpoint": {"transport": "https", "address": "/v1/auth", "enabled": True, "timeout_ms": 8000},
        "configuration": {"magic_link_ttl_seconds": 300, "verification": "jwks-rs256", "scope": "cloud-routes"},
    },
    {
        "id": "cloud_llm_proxy", "title": "Model proxy", "role": "proxy",
        "endpoint": {"transport": "https", "address": "/v1/chat/completions", "enabled": True, "timeout_ms": 60000},
        "configuration": {"stream": "sse", "route_on": "model-prefix", "billing_unit": "turn"},
    },
    {
        "id": "cloud_quota", "title": "Quota gate", "role": "gate",
        "endpoint": {"transport": "internal", "address": "quota://request", "enabled": True, "timeout_ms": 1000},
        "configuration": {"check_point": "request-start", "increment": "final-response", "over_limit_status": 402},
    },
    {
        "id": "cloud_brain_replica", "title": "Brain replica", "role": "replica",
        "endpoint": {"transport": "https", "address": "/v1/brain/sync", "enabled": True, "timeout_ms": 15000},
        "configuration": {"scopes": ["user", "firm", "community"], "merge": "hlc-last-writer-wins", "protected_value_handling": "references-only"},
    },
    {
        "id": "cloud_brain_portal", "title": "Brain portal", "role": "portal",
        "endpoint": {"transport": "https", "address": "https://archhub.io/brain", "enabled": True, "timeout_ms": 8000},
        "configuration": {"view": "tiered-facts", "read_only": True},
    },
    {
        "id": "cloud_release_updater", "title": "Release updater", "role": "updater",
        "endpoint": {"transport": "https", "address": "release://signed", "enabled": True, "timeout_ms": 30000},
        "configuration": {"mode": "prompt", "cooldown_seconds": 21600, "signature_required": True},
    },
    {
        "id": "cloud_email_sender", "title": "Transactional email", "role": "messaging",
        "endpoint": {"transport": "https", "address": "email://transactional", "enabled": True, "timeout_ms": 10000},
        "configuration": {"templates": ["magic-link", "welcome"], "failure_mode": "explicit-error", "from_domain": "archhub.io"},
    },
    {
        "id": "cloud_dns", "title": "DNS and mail routing", "role": "routing",
        "endpoint": {"transport": "dns", "address": "archhub.io", "enabled": True, "timeout_ms": 5000},
        "configuration": {"web_target": "archhub-web", "api_target": "archhub-cloud.fly.dev"},
    },
    {
        "id": "cloud_billing", "title": "Billing and plans", "role": "billing",
        "endpoint": {"transport": "https", "address": "/v1/billing/webhook", "enabled": True, "timeout_ms": 10000},
        "configuration": {"providers": ["stripe", "polar"], "sync_fields": ["plan", "period_end", "message_limit"]},
    },
    {
        "id": "nl_cloud_central_home", "title": "Central cloud graph", "role": "central-cde",
        "endpoint": {"transport": "https", "address": "/v1/graph/sync", "enabled": True, "timeout_ms": 15000},
        "configuration": {"syncs": ["central-graph", "brain-replica"], "persistence": "node-id"},
    },
)


GRAND_MAP_SERVICE_RELATIONS = (
    ("cloud_fly_app", "cloud_persistent_db"),
    ("cloud_fly_app", "cloud_healthz"),
    ("cloud_fly_app", "cloud_auth"),
    ("cloud_auth", "cloud_persistent_db"),
    ("cloud_auth", "cloud_email_sender"),
    ("cloud_auth", "cloud_llm_proxy"),
    ("cloud_llm_proxy", "cloud_quota"),
    ("cloud_quota", "cloud_persistent_db"),
    ("cloud_quota", "cloud_billing"),
    ("cloud_billing", "cloud_persistent_db"),
    ("cloud_brain_replica", "cloud_persistent_db"),
    ("cloud_brain_replica", "cloud_brain_portal"),
    ("cloud_dns", "cloud_fly_app"),
    ("cloud_dns", "cloud_email_sender"),
    ("nl_cloud_central_home", "cloud_fly_app"),
)


DEFAULT_QUEUES = (
    {"id": "brain-sync-queue", "title": "Brain sync queue", "state": "idle", "pending": 0, "failed": 0, "last_event_at": ""},
)


DEFAULT_SYNCS = (
    {
        "id": "cloud_sync_client", "title": "Desktop and cloud sync",
        "source_service": "nl_cloud_central_home", "target_service": "cloud_brain_replica",
        "queue": "brain-sync-queue", "direction": "bidirectional",
        "offline_mode": "cached", "idempotency_key": "cloud-sync-client-v1",
        "authorized": False, "auth_evidence": "", "auth_observed_at": "",
    },
)


DEFAULT_DEPLOYMENTS = (
    {
        "id": "cloud_deploy_pipeline", "title": "Cloud deployment",
        "target_service": "cloud_fly_app", "artifact_ref": "release://archhub-cloud",
        "environment": "production", "idempotency_key": "cloud-deploy-pipeline-v1",
        "approved": False, "approved_by": "", "approved_at": "",
    },
)


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    clean = str(value).strip()
    if not clean and not allow_empty:
        raise ValueError("%s must be a non-empty string" % label)
    return clean


def _reject_raw_secrets(value: Any, path: str = "cloud") -> None:
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
        raise ValueError("%s contains a probable raw secret; use an op:// secret_ref" % path)


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add("param", title, floor={"op": "value", "value": value}, actor=actor)


def _reference_param(store: Store, title: str, target: str, actor: str) -> str:
    return store.add("param", title, floor={"op": "reference", "target": target}, actor=actor)


def _record_group(
    store: Store, title: str, values: Mapping[str, Any], *, actor: str,
) -> dict[str, Any]:
    fields = {
        str(name): _param(store, "%s: %s" % (title, name), value, actor)
        for name, value in values.items()
    }
    record = store.add(
        "op", "%s record" % title,
        floor={"op": "merge", "fn": "record", "keys": list(fields)}, actor=actor,
    )
    wires = [
        store.wire(node_id, record, title="%s -> record" % name, actor=actor)
        for name, node_id in fields.items()
    ]
    group = store.add(
        "group", title, inner=list(fields.values()) + [record], params=fields, actor=actor,
    )
    return {"group": group, "record": record, "fields": fields, "wires": wires}


def _record_from_nodes(
    store: Store, title: str, fields: Mapping[str, str], *, actor: str,
) -> dict[str, Any]:
    record = store.add(
        "op", "%s record" % title,
        floor={"op": "merge", "fn": "record", "keys": list(fields)}, actor=actor,
    )
    wires = [
        store.wire(node_id, record, title="%s -> plan" % name, actor=actor)
        for name, node_id in fields.items()
    ]
    refs = {
        name: _reference_param(store, "%s: %s" % (title, name), node_id, actor)
        for name, node_id in fields.items()
    }
    group = store.add(
        "group", title,
        inner=list(fields.values()) + list(refs.values()) + [record],
        params=refs, actor=actor,
    )
    return {"group": group, "record": record, "fields": dict(fields), "params": refs, "wires": wires}


def _compare(
    store: Store, title: str, left: str, right: str, comparison: str, actor: str,
) -> tuple[str, list[str]]:
    node = store.add("op", title, floor={"op": "compare", "cmp": comparison}, actor=actor)
    wires = [store.wire(left, node, actor=actor), store.wire(right, node, actor=actor)]
    return node, wires


def _all_gate(store: Store, title: str, conditions: Iterable[str], actor: str) -> tuple[str, list[str]]:
    condition_ids = list(conditions)
    if not condition_ids:
        raise ValueError("a visible gate needs at least one condition")
    gate = store.add("op", title, floor={"op": "math", "fn": "*"}, actor=actor)
    wires = [store.wire(node_id, gate, title="Gate condition", actor=actor) for node_id in condition_ids]
    return gate, wires


def _health_group(
    store: Store, service_id: str, raw: Mapping[str, Any], enabled: str, actor: str,
) -> dict[str, Any]:
    values = {"state": "unknown", "observed_at": "", "evidence": "", "latency_ms": None}
    values.update(dict(raw or {}))
    state = str(values["state"]).strip().casefold()
    if state not in HEALTH_STATES:
        raise ValueError("health state must be one of %s" % ", ".join(HEALTH_STATES))
    values["state"] = state
    if state == "online" and (not str(values["observed_at"]).strip() or not str(values["evidence"]).strip()):
        raise ValueError("online health requires timestamped evidence")
    health = _record_group(store, "%s / Health evidence" % service_id, values, actor=actor)
    online = _param(store, "Required state: online", "online", actor)
    empty = _param(store, "Required evidence: non-empty", "", actor)
    true = _param(store, "Required endpoint state: enabled", True, actor)
    state_ok, state_wires = _compare(store, "Observed online", health["fields"]["state"], online, "==", actor)
    time_ok, time_wires = _compare(store, "Observation timestamp present", health["fields"]["observed_at"], empty, "!=", actor)
    evidence_ok, evidence_wires = _compare(store, "Health evidence present", health["fields"]["evidence"], empty, "!=", actor)
    enabled_ok, enabled_wires = _compare(store, "Endpoint enabled", enabled, true, "==", actor)
    available, gate_wires = _all_gate(store, "Service health gate", [state_ok, time_ok, evidence_ok, enabled_ok], actor)
    inner = store.open(health["group"])
    store.edit(
        health["group"], ["body", "inner"],
        inner + [online, empty, true, state_ok, time_ok, evidence_ok, enabled_ok, available],
        actor=actor,
    )
    health.update({
        "available": available,
        "conditions": {"state": state_ok, "time": time_ok, "evidence": evidence_ok, "enabled": enabled_ok},
        "gate_wires": state_wires + time_wires + evidence_wires + enabled_wires + gate_wires,
    })
    return health


def _authorization_group(
    store: Store, service_id: str, capability_ref: str, raw: Mapping[str, Any], actor: str,
) -> dict[str, Any]:
    reference = _text(capability_ref, "authentication capability reference")
    if not reference.startswith("op://"):
        raise ValueError("authentication capability references must use op:// URIs")
    capability = store.add(
        "secret_ref", "%s / Authentication capability" % service_id,
        floor={"op": "secret_ref", "ref": reference}, actor=actor,
    )
    values = {"authorized": False, "observed_at": "", "evidence": ""}
    values.update(dict(raw or {}))
    if bool(values["authorized"]) and (
        not str(values["observed_at"]).strip() or not str(values["evidence"]).strip()
    ):
        raise ValueError("authorized state requires timestamped evidence")
    auth = _record_group(store, "%s / Authorization evidence" % service_id, values, actor=actor)
    capability_param = _reference_param(store, "Authentication capability reference", capability, actor)
    true = _param(store, "Required authorization state", True, actor)
    empty = _param(store, "Required authorization evidence", "", actor)
    authorized_ok, authorized_wires = _compare(store, "Authorized", auth["fields"]["authorized"], true, "==", actor)
    time_ok, time_wires = _compare(store, "Authorization timestamp present", auth["fields"]["observed_at"], empty, "!=", actor)
    evidence_ok, evidence_wires = _compare(store, "Authorization evidence present", auth["fields"]["evidence"], empty, "!=", actor)
    allowed, gate_wires = _all_gate(store, "Authorization gate", [authorized_ok, time_ok, evidence_ok], actor)
    group = store.add(
        "group", "%s / Authentication" % service_id,
        inner=[capability, capability_param, auth["group"], true, empty, authorized_ok, time_ok, evidence_ok, allowed],
        params={"capability_ref": capability_param}, actor=actor,
    )
    return {
        "group": group, "capability": capability, "capability_param": capability_param,
        "evidence": auth, "allowed": allowed,
        "gate_wires": authorized_wires + time_wires + evidence_wires + gate_wires,
    }


def _service_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    allowed = {"id", "title", "role", "endpoint", "configuration", "health", "auth_capability_ref", "authorization"}
    missing = sorted({"id", "title", "role", "endpoint"} - set(record))
    unknown = sorted(set(record) - allowed)
    if missing or unknown:
        raise ValueError("cloud service fields mismatch; missing=%r unknown=%r" % (missing, unknown))
    service_id = _text(record["id"], "service id")
    endpoint = dict(record["endpoint"])
    endpoint.setdefault("transport", "custom")
    endpoint.setdefault("address", "")
    endpoint.setdefault("enabled", True)
    endpoint.setdefault("timeout_ms", 8000)
    _reject_raw_secrets(record)
    return {
        "id": service_id,
        "title": _text(record["title"], "service title"),
        "role": _text(record["role"], "service role"),
        "endpoint": endpoint,
        "configuration": dict(record.get("configuration") or {}),
        "health": dict(record.get("health") or {}),
        "auth_capability_ref": record.get("auth_capability_ref") or "op://archhub/cloud/%s" % service_id,
        "authorization": dict(record.get("authorization") or {}),
    }


def _build_service(store: Store, raw: Mapping[str, Any], actor: str) -> dict[str, Any]:
    record = _service_record(raw)
    service_id = record["id"]
    definition = _record_group(
        store, "%s / Definition" % record["title"],
        {"id": service_id, "title": record["title"], "role": record["role"], "authority_source": _AUTHORITY},
        actor=actor,
    )
    endpoint = _record_group(store, "%s / Endpoint" % record["title"], record["endpoint"], actor=actor)
    configuration = _record_group(store, "%s / Configuration" % record["title"], record["configuration"], actor=actor)
    health = _health_group(store, service_id, record["health"], endpoint["fields"]["enabled"], actor)
    auth = _authorization_group(store, service_id, record["auth_capability_ref"], record["authorization"], actor)
    ready, ready_wires = _all_gate(store, "%s / Readiness gate" % record["title"], [health["available"], auth["allowed"]], actor)
    plan = _record_from_nodes(
        store, "%s / Execution plan" % record["title"],
        {
            "definition": definition["record"], "endpoint": endpoint["record"],
            "configuration": configuration["record"], "health": health["record"],
            "authorized": auth["allowed"], "ready": ready,
        }, actor=actor,
    )
    effect_change = _reference_param(store, "%s / Effect plan" % record["title"], plan["record"], actor)
    effect = store.add(
        "op", "%s / Frozen service effect" % record["title"],
        floor={"op": "effect", "target": "cloud-service:%s" % service_id, "change": {"$param": "change"}},
        params={"change": effect_change}, frozen=True, actor=actor,
    )
    effect_group = store.add(
        "group", "%s / Execution gate" % record["title"],
        inner=[ready, effect_change, effect], params={"change": effect_change}, actor=actor,
    )
    parts = {
        "definition": definition["group"], "endpoint": endpoint["group"],
        "configuration": configuration["group"], "health": health["group"],
        "authentication": auth["group"], "execution_plan": plan["group"],
        "execution_effect": effect_group,
    }
    service = store.add("group", record["title"], inner=list(parts.values()), actor=actor)
    part_relations = {
        name: store.relation([
            {"role": "source", "direction": "out", "node_id": part, "port_id": "value", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": service, "port_id": name, "cardinality": "one"},
        ], title="Service exposes %s" % name, actor=actor)
        for name, part in parts.items()
    }
    effect_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": plan["group"], "port_id": "plan", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": effect, "port_id": "change", "cardinality": "one"},
    ], title="Readiness-gated service execution", stages=[{"role": "gate", "mode": "guard", "node_id": ready}], actor=actor)
    return {
        "service": service, "parts": parts, "part_relations": part_relations,
        "definition": definition, "endpoint": endpoint, "configuration": configuration,
        "health": health, "authorization": auth, "ready": ready, "ready_wires": ready_wires,
        "plan": plan, "effect": effect, "effect_group": effect_group,
        "effect_relation": effect_relation,
    }


def _queue_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    required = {"id", "title", "state", "pending", "failed", "last_event_at"}
    if set(record) != required:
        raise ValueError("queue fields must be exactly %r" % sorted(required))
    pending = int(record["pending"])
    failed = int(record["failed"])
    if pending < 0 or failed < 0:
        raise ValueError("queue counts must be non-negative")
    return {
        "id": _text(record["id"], "queue id"), "title": _text(record["title"], "queue title"),
        "state": _text(record["state"], "queue state"), "pending": pending,
        "failed": failed, "last_event_at": str(record["last_event_at"]),
    }


def _gated_effect(
    store: Store, title: str, target: str, plan: str, gate: str, actor: str,
) -> tuple[str, str, str]:
    change = _reference_param(store, "%s / Change" % title, plan, actor)
    effect = store.add(
        "op", "%s / Frozen effect" % title,
        floor={"op": "effect", "target": target, "change": {"$param": "change"}},
        params={"change": change}, frozen=True, actor=actor,
    )
    relation = store.relation([
        {"role": "source", "direction": "out", "node_id": plan, "port_id": "plan", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": effect, "port_id": "change", "cardinality": "one"},
    ], title="%s guarded execution" % title, stages=[{"role": "gate", "mode": "guard", "node_id": gate}], actor=actor)
    return effect, change, relation


def _idempotency_gate(store: Store, key_param: str, actor: str) -> tuple[str, list[str]]:
    empty = _param(store, "Idempotency key must be present", "", actor)
    gate, wires = _compare(store, "Idempotency key present", key_param, empty, "!=", actor)
    return gate, [empty] + wires


def _build_deployment(
    store: Store, raw: Mapping[str, Any], services: Mapping[str, dict[str, Any]], actor: str,
) -> dict[str, Any]:
    record = dict(raw)
    required = {"id", "title", "target_service", "artifact_ref", "environment", "idempotency_key", "approved", "approved_by", "approved_at"}
    if set(record) != required:
        raise ValueError("deployment fields must be exactly %r" % sorted(required))
    _reject_raw_secrets(record)
    deploy_id = _text(record["id"], "deployment id")
    target = _text(record["target_service"], "deployment target")
    if target not in services:
        raise ValueError("deployment references unknown service %r" % target)
    values = dict(record)
    values["id"] = deploy_id
    values["target_service"] = target
    fields = _record_group(store, "Deployment: %s" % record["title"], values, actor=actor)
    true = _param(store, "Deployment approval required", True, actor)
    approval, approval_wires = _compare(store, "Deployment approved", fields["fields"]["approved"], true, "==", actor)
    idempotency, idempotency_nodes = _idempotency_gate(store, fields["fields"]["idempotency_key"], actor)
    gate, gate_wires = _all_gate(store, "Deployment gate", [services[target]["ready"], approval, idempotency], actor)
    plan = _record_from_nodes(store, "Deployment execution plan", {"deployment": fields["record"], "target_ready": services[target]["ready"], "gate": gate}, actor=actor)
    effect, change, effect_relation = _gated_effect(store, "Deployment: %s" % deploy_id, "cloud-deployment:%s" % deploy_id, plan["record"], gate, actor)
    group = store.add(
        "group", "Deployment: %s" % record["title"],
        inner=[fields["group"], true, approval, idempotency, gate, plan["group"], change, effect], actor=actor,
    )
    target_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": group, "port_id": "deployment", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": services[target]["service"], "port_id": "deployment", "cardinality": "many"},
    ], title="Deployment targets service", actor=actor)
    return {
        "group": group, "fields": fields, "approval": approval, "idempotency": idempotency,
        "gate": gate, "plan": plan, "effect": effect, "effect_relation": effect_relation,
        "target_relation": target_relation,
        "gate_wires": approval_wires + idempotency_nodes + gate_wires,
    }


def _build_sync(
    store: Store, raw: Mapping[str, Any], services: Mapping[str, dict[str, Any]],
    queues: Mapping[str, dict[str, Any]], actor: str,
) -> dict[str, Any]:
    record = dict(raw)
    required = {"id", "title", "source_service", "target_service", "queue", "direction", "offline_mode", "idempotency_key", "authorized", "auth_evidence", "auth_observed_at"}
    if set(record) != required:
        raise ValueError("sync fields must be exactly %r" % sorted(required))
    _reject_raw_secrets(record)
    sync_id = _text(record["id"], "sync id")
    source = _text(record["source_service"], "sync source")
    target = _text(record["target_service"], "sync target")
    queue_id = _text(record["queue"], "sync queue")
    if source not in services or target not in services or queue_id not in queues:
        raise ValueError("sync references an unknown service or queue")
    values = dict(record)
    values["id"] = sync_id
    fields = _record_group(store, "Sync: %s" % record["title"], values, actor=actor)
    true = _param(store, "Sync authorization required", True, actor)
    empty = _param(store, "Sync evidence required", "", actor)
    authorized, authorized_wires = _compare(store, "Sync authorized", fields["fields"]["authorized"], true, "==", actor)
    auth_evidence, evidence_wires = _compare(store, "Sync authorization evidence present", fields["fields"]["auth_evidence"], empty, "!=", actor)
    auth_time, time_wires = _compare(store, "Sync authorization timestamp present", fields["fields"]["auth_observed_at"], empty, "!=", actor)
    idempotency, idempotency_nodes = _idempotency_gate(store, fields["fields"]["idempotency_key"], actor)
    gate, gate_wires = _all_gate(
        store, "Sync gate",
        [services[source]["ready"], services[target]["ready"], authorized, auth_evidence, auth_time, idempotency], actor,
    )
    plan = _record_from_nodes(
        store, "Sync execution plan",
        {"sync": fields["record"], "queue": queues[queue_id]["record"], "source_ready": services[source]["ready"], "target_ready": services[target]["ready"], "gate": gate},
        actor=actor,
    )
    effect, change, effect_relation = _gated_effect(store, "Sync: %s" % sync_id, "cloud-sync:%s" % sync_id, plan["record"], gate, actor)
    group = store.add(
        "group", "Sync: %s" % record["title"],
        inner=[fields["group"], true, empty, authorized, auth_evidence, auth_time, idempotency, gate, plan["group"], change, effect], actor=actor,
    )
    source_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": services[source]["service"], "port_id": "changes", "cardinality": "many"},
        {"role": "target", "direction": "in", "node_id": group, "port_id": "source", "cardinality": "one"},
    ], title="Sync source", actor=actor)
    target_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": group, "port_id": "changes", "cardinality": "many"},
        {"role": "target", "direction": "in", "node_id": services[target]["service"], "port_id": "sync", "cardinality": "many"},
    ], title="Sync target", actor=actor)
    queue_relation = store.relation([
        {"role": "source", "direction": "out", "node_id": queues[queue_id]["group"], "port_id": "queued", "cardinality": "many"},
        {"role": "target", "direction": "in", "node_id": group, "port_id": "queue", "cardinality": "one"},
    ], title="Sync queue", actor=actor)
    return {
        "group": group, "fields": fields, "authorized": authorized,
        "authorization_evidence": auth_evidence, "authorization_time": auth_time,
        "idempotency": idempotency, "gate": gate, "plan": plan, "effect": effect,
        "effect_relation": effect_relation, "source_relation": source_relation,
        "target_relation": target_relation, "queue_relation": queue_relation,
        "gate_wires": authorized_wires + evidence_wires + time_wires + idempotency_nodes + gate_wires,
    }


def build_cloud_domain(
    store: Store, *,
    services: Iterable[Mapping[str, Any]] = GRAND_MAP_CLOUD_SERVICES,
    queues: Iterable[Mapping[str, Any]] = DEFAULT_QUEUES,
    syncs: Iterable[Mapping[str, Any]] = DEFAULT_SYNCS,
    deployments: Iterable[Mapping[str, Any]] = DEFAULT_DEPLOYMENTS,
    actor: str = "cloud-domain",
) -> dict[str, Any]:
    """Build the Grand Map cloud domain entirely in the supplied Store."""
    raw_services = [dict(item) for item in services]
    raw_queues = [dict(item) for item in queues]
    raw_syncs = [dict(item) for item in syncs]
    raw_deployments = [dict(item) for item in deployments]
    _reject_raw_secrets({"services": raw_services, "queues": raw_queues, "syncs": raw_syncs, "deployments": raw_deployments})

    service_records = [_service_record(item) for item in raw_services]
    service_ids = [record["id"] for record in service_records]
    if not service_ids or len(service_ids) != len(set(service_ids)):
        raise ValueError("cloud service ids must be unique and non-empty")
    service_nodes = {record["id"]: _build_service(store, record, actor) for record in service_records}

    queue_records = [_queue_record(item) for item in raw_queues]
    queue_ids = [record["id"] for record in queue_records]
    if len(queue_ids) != len(set(queue_ids)):
        raise ValueError("cloud queue ids must be unique")
    queue_nodes = {
        record["id"]: _record_group(store, "Queue: %s" % record["title"], record, actor=actor)
        for record in queue_records
    }

    sync_nodes: dict[str, dict[str, Any]] = {}
    for raw in raw_syncs:
        sync_id = _text(raw.get("id"), "sync id")
        if sync_id in sync_nodes:
            raise ValueError("cloud sync ids must be unique")
        sync_nodes[sync_id] = _build_sync(store, raw, service_nodes, queue_nodes, actor)

    deployment_nodes: dict[str, dict[str, Any]] = {}
    for raw in raw_deployments:
        deploy_id = _text(raw.get("id"), "deployment id")
        if deploy_id in deployment_nodes:
            raise ValueError("cloud deployment ids must be unique")
        deployment_nodes[deploy_id] = _build_deployment(store, raw, service_nodes, actor)

    service_relations: dict[str, str] = {}
    for source, target in GRAND_MAP_SERVICE_RELATIONS:
        if source not in service_nodes or target not in service_nodes:
            continue
        relation = store.relation([
            {"role": "source", "direction": "out", "node_id": service_nodes[source]["service"], "port_id": "service", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": service_nodes[target]["service"], "port_id": "dependency", "cardinality": "many"},
        ], title="Grand Map: %s -> %s" % (source, target), actor=actor)
        service_relations["%s->%s" % (source, target)] = relation

    authority = _param(store, "Cloud authority source", _AUTHORITY, actor)
    session = store.add(
        "session", "Cloud domain",
        inner=[authority]
        + [item["service"] for item in service_nodes.values()]
        + [item["group"] for item in queue_nodes.values()]
        + [item["group"] for item in sync_nodes.values()]
        + [item["group"] for item in deployment_nodes.values()]
        + list(service_relations.values()),
        params={"authority_source": authority}, actor=actor,
    )
    return {
        "session": session, "authority": authority, "services": service_nodes,
        "queues": queue_nodes, "syncs": sync_nodes, "deployments": deployment_nodes,
        "service_relations": service_relations,
    }


def observe_service_health(
    store: Store, domain: Mapping[str, Any], service_id: str, state: str, *,
    observed_at: str = "", evidence: str = "", latency_ms: float | None = None,
    actor: str = "cloud-observer",
) -> str:
    normalized = str(state).strip().casefold()
    if normalized not in HEALTH_STATES:
        raise ValueError("health state must be one of %s" % ", ".join(HEALTH_STATES))
    if normalized == "online" and (not str(observed_at).strip() or not str(evidence).strip()):
        raise ValueError("online health requires timestamped evidence")
    service = domain["services"][service_id]
    fields = service["health"]["fields"]
    for name, value in {
        "state": normalized, "observed_at": str(observed_at),
        "evidence": str(evidence), "latency_ms": latency_ms,
    }.items():
        store.edit(fields[name], ["body", "floor", "value"], value, actor=actor)
    return service_status(store, domain, service_id)


def set_service_authorization(
    store: Store, domain: Mapping[str, Any], service_id: str, authorized: bool, *,
    observed_at: str = "", evidence: str = "", actor: str = "cloud-auth-observer",
) -> str:
    if authorized and (not str(observed_at).strip() or not str(evidence).strip()):
        raise ValueError("authorized state requires timestamped evidence")
    fields = domain["services"][service_id]["authorization"]["evidence"]["fields"]
    for name, value in {
        "authorized": bool(authorized), "observed_at": str(observed_at), "evidence": str(evidence),
    }.items():
        store.edit(fields[name], ["body", "floor", "value"], value, actor=actor)
    return service_status(store, domain, service_id)


def service_status(store: Store, domain: Mapping[str, Any], service_id: str) -> str:
    service = domain["services"][service_id]
    state = str(store.pull(service["health"]["fields"]["state"]))
    if state != "online":
        return state
    if not bool(store.pull(service["health"]["available"])):
        return "offline"
    if not bool(store.pull(service["authorization"]["allowed"])):
        return "unauthorized"
    return "online"


__all__ = [
    "DEFAULT_DEPLOYMENTS", "DEFAULT_QUEUES", "DEFAULT_SYNCS",
    "GRAND_MAP_CLOUD_SERVICES", "GRAND_MAP_SERVICE_RELATIONS", "HEALTH_STATES",
    "build_cloud_domain", "observe_service_health", "service_status",
    "set_service_authorization",
]
