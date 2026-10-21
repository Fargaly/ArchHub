"""Local HTTP adapter that interprets the node-native Cloud domain.

The HTTP server is a host-boundary shim. Route definitions, payload schemas,
data sources, gates, dispatch effects, evidence, and results live in the one
``Store.nodes`` table. The shim discovers them by reading nodes and relations;
it owns no parallel route or service registry.
"""
from __future__ import annotations

import copy
import gzip
import json
import os
import threading
import time
from collections import Counter
from collections.abc import Mapping, MutableMapping
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

from .core import Store, relation_sources, relation_stages, relation_targets, validate_store
from .http_server import QuietThreadingHTTPServer
from .laws_effect import apply_effect, dry_run


RUNTIME_FORMAT = "archhub-cloud-runtime-v1"
MAX_REQUEST_BYTES = 1024 * 1024
_ACTOR = "cloud-runtime"
_SECRET_WORDS = frozenset({
    "password", "passwd", "secret", "token", "credential", "api_key",
    "apikey", "access_key", "private_key", "client_secret", "code_verifier",
})
_SECRET_PREFIXES = ("sk-", "ghp_", "github_pat_", "bearer ", "xoxb-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _param(store: Store, title: str, value, actor: str = _ACTOR) -> str:
    return store.add("param", title, floor={"op": "value", "value": value}, actor=actor)


def _ref(store: Store, title: str, target: str, actor: str = _ACTOR) -> str:
    return store.add("param", title, floor={"op": "reference", "target": target}, actor=actor)


def _record(store: Store, title: str, values: Mapping[str, object],
            *, references: bool = False, actor: str = _ACTOR) -> dict[str, object]:
    fields = {
        str(name): (_ref(store, "%s: %s" % (title, name), str(value), actor)
                    if references else
                    _param(store, "%s: %s" % (title, name), copy.deepcopy(value), actor))
        for name, value in values.items()
    }
    result = store.add(
        "op", "%s record" % title,
        floor={"op": "merge", "fn": "record", "keys": list(fields)}, actor=actor,
    )
    wires = [store.wire(pid, result, title="%s -> record" % name, actor=actor)
             for name, pid in fields.items()]
    group = store.add("group", title, inner=list(fields.values()) + [result],
                      params=fields, actor=actor)
    return {"group": group, "record": result, "fields": fields, "wires": wires}


def _route(store: Store, *, method: str, path: str, operation: str,
           source: str, payload: Mapping[str, object] | None = None) -> dict[str, str]:
    method_param = _param(store, "Runtime route method", method.upper())
    path_param = _param(store, "Runtime route path", path)
    operation_param = _param(store, "Runtime route operation", operation)
    enabled = _param(store, "Runtime route enabled", True)
    required_enabled = _param(store, "Runtime route requires enabled", True)
    gate = store.add("op", "Runtime route enabled gate",
                     floor={"op": "compare", "cmp": "=="}, actor=_ACTOR)
    store.wire(enabled, gate, title="Route enabled", actor=_ACTOR)
    store.wire(required_enabled, gate, title="Required route state", actor=_ACTOR)
    payload_group = _record(store, "Payload schema: %s %s" % (method, path),
                            payload or {})["group"]
    route = store.add(
        "group", "%s %s" % (method.upper(), path),
        inner=[method_param, path_param, operation_param, enabled,
               required_enabled, gate, payload_group],
        params={
            "runtime_route_method": method_param,
            "runtime_route_path": path_param,
            "runtime_operation": operation_param,
            "runtime_route_enabled": enabled,
            "runtime_route_gate": _ref(store, "Runtime route gate", gate),
            "runtime_payload_schema": _ref(store, "Runtime payload schema", payload_group),
        }, actor=_ACTOR,
    )
    relation = store.relation([
        {"role": "source", "direction": "out", "node_id": source,
         "port_id": "response_source", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": route,
         "port_id": "request", "cardinality": "many"},
    ], title="Runtime route source", stages=[
        {"role": "gate", "mode": "guard", "node_id": gate}
    ], actor=_ACTOR)
    return {"route": route, "gate": gate, "relation": relation,
            "enabled": enabled, "payload": str(payload_group)}


def _service_status_nodes(store: Store, cloud: Mapping[str, object]) -> str:
    statuses = []
    for service_id, service in cloud["services"].items():
        definition = service["definition"]["fields"]
        endpoint = service["endpoint"]["fields"]
        health = service["health"]["fields"]
        authorization = service["authorization"]["evidence"]["fields"]
        status = _record(store, "Runtime service status: %s" % service_id, {
            "id": definition["id"], "title": definition["title"],
            "role": definition["role"], "transport": endpoint["transport"],
            "address": endpoint["address"], "enabled": endpoint["enabled"],
            "health": health["state"], "health_observed_at": health["observed_at"],
            "health_evidence": health["evidence"],
            "authorized": authorization["authorized"],
            "authorization_observed_at": authorization["observed_at"],
            "authorization_evidence": authorization["evidence"],
            "ready": service["ready"],
        }, references=True)["group"]
        statuses.append(status)
    return store.add("group", "Cloud runtime service status index", inner=statuses,
                     actor=_ACTOR)


def _auth_status_nodes(store: Store, users: Mapping[str, object] | None) -> str:
    statuses = []
    if users:
        for user_id, fields in users["auth_evidence_params"].items():
            values = {"user_id": users["profile_params"][user_id]["id"], **fields}
            statuses.append(_record(store, "Runtime auth status: %s" % user_id,
                                    values, references=True)["group"])
    if not statuses:
        statuses.append(_record(store, "Runtime auth status unavailable", {
            "status": "not-wired", "verified": False,
            "evidence": "Users domain is not connected to this runtime",
        })["group"])
    return store.add("group", "Cloud runtime authentication status index",
                     inner=statuses, actor=_ACTOR)


def _monetization_status_nodes(store: Store,
                               monetization: Mapping[str, object] | None) -> tuple[str, str]:
    if not monetization:
        missing = _record(store, "Runtime monetization status unavailable", {
            "status": "not-wired", "evidence": "Monetization domain is not connected",
        })["group"]
        return missing, missing
    quota_values = {
        "plan": monetization["subscription_params"]["plan_id"],
        "allowed": monetization["quota_gate"],
        "usage": monetization["usage_record"],
    }
    quota_values.update({"remaining:%s" % name: node_id
                         for name, node_id in monetization["remaining"].items()})
    quota = _record(store, "Runtime quota status", quota_values,
                    references=True)["group"]
    billing = _record(store, "Runtime billing status", {
        "subscription": monetization["subscription_value"],
        "approval_gate": monetization["approval_gate"],
        "idempotency_gate": monetization["idempotency_gate"],
        "privacy_gate": monetization["privacy_gate"],
        "account": monetization["account_chip_value"],
        "net_revenue": monetization["net_revenue"],
    }, references=True)["group"]
    return quota, billing


def _community_status_nodes(store: Store,
                            community: Mapping[str, object] | None) -> str:
    if not community:
        return _record(store, "Runtime community status unavailable", {
            "status": "not-wired", "evidence": "Community domain is not connected",
        })["group"]
    values = {"community": community["community_record"],
              "invitation_allowed": community["invite_gate"]}
    values.update({"peer:%s" % peer_id: gate
                   for peer_id, gate in community["sync_gates"].items()})
    return _record(store, "Runtime community status", values,
                   references=True)["group"]


def build_cloud_runtime_nodes(
    store: Store, cloud: Mapping[str, object], *,
    users: Mapping[str, object] | None = None,
    monetization: Mapping[str, object] | None = None,
    community: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the HTTP adapter as nodes and explicit relations."""
    service_index = _service_status_nodes(store, cloud)
    auth_index = _auth_status_nodes(store, users)
    quota_status, billing_status = _monetization_status_nodes(store, monetization)
    community_status = _community_status_nodes(store, community)
    local_status = _record(store, "Cloud runtime local listener evidence", {
        "online": False, "host": "", "port": 0, "observed_at": "",
        "evidence": "listener has not started",
    })
    graph_source = store.add("group", "Cloud runtime graph-state source",
                             inner=[cloud["session"]], actor=_ACTOR)
    dispatch_source = store.add("group", "Cloud runtime effect-dispatch source",
                                inner=[cloud["session"]], actor=_ACTOR)
    routes = [
        _route(store, method="GET", path="/health", operation="health",
               source=local_status["group"]),
        _route(store, method="GET", path="/v1/services", operation="services",
               source=service_index),
        _route(store, method="GET", path="/v1/services/{service_id}",
               operation="service", source=service_index),
        _route(store, method="GET", path="/v1/graph/state", operation="graph",
               source=graph_source),
        _route(store, method="GET", path="/v1/auth/status", operation="auth",
               source=auth_index),
        _route(store, method="GET", path="/v1/quota/status", operation="quota",
               source=quota_status),
        _route(store, method="GET", path="/v1/billing/status", operation="billing",
               source=billing_status),
        _route(store, method="GET", path="/v1/community/status", operation="community",
               source=community_status),
        _route(store, method="POST", path="/v1/effects/dispatch", operation="dispatch",
               source=dispatch_source, payload={
                   "target": "cloud-deployment:... or cloud-sync:...",
                   "idempotency_key": "must match the graph plan",
                   "capability_ref": "op:// reference only",
                   "evidence_node": "existing Cloud graph node id",
                   "actor": "audited actor name",
               }),
    ]
    cloud_ref = _ref(store, "Cloud runtime authority", cloud["session"])
    runtime = store.add(
        "session", "Cloud HTTP Runtime",
        inner=[cloud_ref, service_index, auth_index, quota_status, billing_status,
               community_status, local_status["group"], graph_source,
               dispatch_source] + [item["route"] for item in routes]
              + [item["relation"] for item in routes],
        params={"cloud_session": cloud_ref,
                "listener_online": local_status["fields"]["online"],
                "listener_host": local_status["fields"]["host"],
                "listener_port": local_status["fields"]["port"],
                "listener_observed_at": local_status["fields"]["observed_at"],
                "listener_evidence": local_status["fields"]["evidence"]},
        actor=_ACTOR,
    )
    validate_store(store)
    return {"session": runtime, "routes": routes, "service_index": service_index,
            "auth_index": auth_index, "quota": quota_status, "billing": billing_status,
            "community": community_status, "listener": local_status["group"]}


def _reject_raw_credentials(value, path: str = "request") -> None:
    if isinstance(value, Mapping):
        for raw_name, item in value.items():
            name = str(raw_name).casefold().replace("-", "_")
            child = "%s.%s" % (path, raw_name)
            if any(word in name for word in _SECRET_WORDS):
                if not (name.endswith("_ref") and str(item).startswith("op://")):
                    raise ValueError("%s may contain a raw credential" % child)
            _reject_raw_credentials(item, child)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_raw_credentials(item, "%s[%d]" % (path, index))
    elif isinstance(value, str) and value.casefold().startswith(_SECRET_PREFIXES):
        raise ValueError("%s contains a probable raw credential" % path)


def _reference_target(store: Store, param_id: str) -> str:
    floor = store.nodes[param_id]["body"].get("floor", {})
    if floor.get("op") != "reference" or floor.get("target") not in store.nodes:
        raise ValueError("runtime reference parameter is invalid")
    return str(floor["target"])


def _deep_members(store: Store, root: str) -> set[str]:
    found: set[str] = set()
    pending = [root]
    while pending:
        node_id = pending.pop()
        if node_id in found or node_id not in store.nodes:
            continue
        found.add(node_id)
        node = store.nodes[node_id]
        pending.extend(node["params"].values())
        pending.extend(node["relations"])
        pending.extend(node["body"].get("inner", []))
    return found


def _group_value(store: Store, group_id: str) -> dict[str, object]:
    return {name: copy.deepcopy(store.pull(param_id))
            for name, param_id in store.nodes[group_id]["params"].items()
            if not name.startswith("runtime_")}


class _GraphSink(MutableMapping):
    """Mutable effect sink whose values are parameter nodes, not hidden state."""

    def __init__(self, store: Store, target_param: str, value_param: str):
        self.store = store
        self.target_param = target_param
        self.value_param = value_param

    def _field(self, key):
        if self.store.pull(self.target_param) != key:
            raise KeyError(key)
        return self.value_param

    def __getitem__(self, key):
        return self.store.pull(self._field(key))

    def __setitem__(self, key, value):
        self.store.edit(self._field(key), ["body", "floor", "value"],
                        copy.deepcopy(value), actor=_ACTOR)

    def __delitem__(self, key):
        self.store.edit(self._field(key), ["body", "floor", "value"], None,
                        actor=_ACTOR)

    def __iter__(self):
        yield self.store.pull(self.target_param)

    def __len__(self):
        return 1

    def __contains__(self, key):
        try:
            value = self._field(key)
        except KeyError:
            return False
        return self.store.pull(value) is not None


class CloudRuntime:
    """Threaded local HTTP lifecycle over a node-native Cloud graph."""

    def __init__(self, store: Store, cloud: Mapping[str, object] | None = None,
                 *, users: Mapping[str, object] | None = None,
                 monetization: Mapping[str, object] | None = None,
                 community: Mapping[str, object] | None = None,
                 host: str = "127.0.0.1", port: int = 0,
                 state_path: str | os.PathLike | None = None,
                 on_mutation=None):
        self.store = store
        self.state_path = Path(state_path).resolve() if state_path else None
        self.lock = threading.RLock()
        self.on_mutation = on_mutation
        existing = self._runtime_sessions()
        if existing:
            if cloud is not None:
                raise ValueError("Cloud HTTP Runtime already exists in this Store")
            self.session = existing[0]
        else:
            if cloud is None:
                raise ValueError("cloud domain handles are required for a new runtime")
            self.session = str(build_cloud_runtime_nodes(
                store, cloud, users=users, monetization=monetization,
                community=community)["session"])
        self.httpd = QuietThreadingHTTPServer((host, port), self._handler())
        self.thread: threading.Thread | None = None

    @classmethod
    def load(cls, path: str | os.PathLike, *, host: str = "127.0.0.1",
             port: int = 0) -> "CloudRuntime":
        source = Path(path).resolve()
        with gzip.open(source, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        if payload.get("format") != RUNTIME_FORMAT:
            raise ValueError("not an ArchHub Cloud runtime snapshot")
        store = Store.load(payload["nodes"])
        validate_store(store)
        return cls(store, host=host, port=port, state_path=source)

    def _runtime_sessions(self) -> list[str]:
        return [node_id for node_id, node in self.store.nodes.items()
                if node["kind"] == "session" and node["title"] == "Cloud HTTP Runtime"]

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return "http://%s:%d" % (host, port)

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                return

            def _write(self, status: int, payload: Mapping[str, object]):
                raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length > MAX_REQUEST_BYTES:
                    raise ValueError("request body exceeds the runtime limit")
                raw = self.rfile.read(length) if length else b"{}"
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("JSON request body must be an object")
                return value

            def do_GET(self):
                owner._serve(self, "GET", None)

            def do_POST(self):
                try:
                    body = self._body()
                except Exception as exc:
                    self._write(400, {"ok": False, "error": str(exc)})
                    return
                owner._serve(self, "POST", body)

        return Handler

    def _routes(self):
        for node in self.store.nodes.values():
            params = node["params"]
            required = {"runtime_route_method", "runtime_route_path", "runtime_operation"}
            if node["kind"] == "group" and required <= set(params):
                yield node

    @staticmethod
    def _match(template: str, path: str) -> dict[str, str] | None:
        expected = template.strip("/").split("/") if template != "/" else []
        actual = path.strip("/").split("/") if path != "/" else []
        if len(expected) != len(actual):
            return None
        values = {}
        for wanted, got in zip(expected, actual):
            if wanted.startswith("{") and wanted.endswith("}"):
                values[wanted[1:-1]] = got
            elif wanted != got:
                return None
        return values

    def _find_route(self, method: str, path: str):
        for route in self._routes():
            params = route["params"]
            if self.store.pull(params["runtime_route_method"]) != method:
                continue
            matched = self._match(str(self.store.pull(params["runtime_route_path"])), path)
            if matched is not None:
                return route, matched
        return None, {}

    def _route_source(self, route: Mapping[str, object]) -> str:
        for relation_id in route["relations"]:
            relation = self.store.nodes[relation_id]
            if relation["kind"] != "wire":
                continue
            if not any(item.get("node_id") == route["id"]
                       for item in relation_targets(self.store.nodes, relation)):
                continue
            sources = relation_sources(self.store.nodes, relation)
            if sources:
                return str(sources[0]["node_id"])
        raise ValueError("runtime route has no wired response source")

    def _append_exchange(self, route: Mapping[str, object], method: str, path: str,
                         payload: Mapping[str, object], status: int,
                         response: Mapping[str, object]) -> None:
        request_payload = _record(self.store, "Runtime request payload", payload)
        request = _record(self.store, "Runtime HTTP request", {
            "method": method, "path": path, "received_at": _now(),
        })
        request_group = self.store.add(
            "group", "Runtime request: %s %s" % (method, path),
            inner=[request_payload["group"], request["group"]], actor=_ACTOR)
        self.store.relation([
            {"role": "source", "direction": "out", "node_id": route["id"],
             "port_id": "route", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": request_group,
             "port_id": "request", "cardinality": "many"},
        ], title="Route received request", actor=_ACTOR)
        result = _record(self.store, "Runtime HTTP result", {
            "status": status, "ok": bool(response.get("ok")),
            "body": copy.deepcopy(response), "completed_at": _now(),
        })
        self.store.relation([
            {"role": "source", "direction": "out", "node_id": request_group,
             "port_id": "request", "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": result["group"],
             "port_id": "result", "cardinality": "one"},
        ], title="Request produced result", actor=_ACTOR)
        runtime = self.store.nodes[self.session]
        self.store.edit(self.session, ["body", "inner"],
                        runtime["body"]["inner"] + [request_group, result["group"]],
                        actor=_ACTOR)

    def _serve(self, handler, method: str, payload: Mapping[str, object] | None):
        path = urlsplit(handler.path).path
        with self.lock:
            route, variables = self._find_route(method, path)
            if route is None:
                handler._write(404, {"ok": False, "error": "route not found"})
                return
            safe_payload = dict(payload or {})
            try:
                _reject_raw_credentials(safe_payload)
                gate = _reference_target(self.store, route["params"]["runtime_route_gate"])
                if not bool(self.store.pull(gate)):
                    status, response = 503, {"ok": False, "error": "route gate is closed"}
                else:
                    operation = str(self.store.pull(route["params"]["runtime_operation"]))
                    status, response = self._execute(operation, self._route_source(route),
                                                     variables, safe_payload)
            except PermissionError as exc:
                status, response = 403, {"ok": False, "error": str(exc)}
            except (KeyError, ValueError) as exc:
                status, response = 400, {"ok": False, "error": str(exc)}
            # Credential-shaped payloads are deliberately not persisted.
            persisted = safe_payload if status != 400 or "credential" not in response.get("error", "") else {}
            self._append_exchange(route, method, path, persisted, status, response)
            validate_store(self.store)
            self.flush()
            self._notify_mutation()
        handler._write(status, response)

    def _execute(self, operation: str, source: str, variables: Mapping[str, str],
                 payload: Mapping[str, object]):
        if operation == "health":
            listener = _group_value(self.store, source)
            return 200, {"ok": True, "adapter": listener,
                         "external_cloud": "not inferred from local listener"}
        if operation == "services":
            services = [self._service_value(child)
                        for child in self.store.nodes[source]["body"]["inner"]]
            return 200, {"ok": True, "services": services}
        if operation == "service":
            service_id = variables["service_id"]
            for child in self.store.nodes[source]["body"]["inner"]:
                value = self._service_value(child)
                if value.get("id") == service_id:
                    return 200, {"ok": True, "service": value}
            return 404, {"ok": False, "error": "service not found"}
        if operation in {"auth", "quota", "billing", "community"}:
            node = self.store.nodes[source]
            if operation == "auth":
                value = [_group_value(self.store, child) for child in node["body"]["inner"]]
            else:
                value = _group_value(self.store, source)
            return 200, {"ok": True, operation: value}
        if operation == "graph":
            counts = Counter(node["kind"] for node in self.store.nodes.values())
            return 200, {"ok": True, "graph": {
                "valid": validate_store(self.store), "nodes": len(self.store.nodes),
                "kinds": dict(sorted(counts.items())), "cloud_source": source,
                "runtime": self.session,
            }}
        if operation == "dispatch":
            return 200, {"ok": True, "dispatch": self._dispatch(payload)}
        raise ValueError("unsupported runtime operation %r" % operation)

    def _service_value(self, group_id: str) -> dict[str, object]:
        value = _group_value(self.store, group_id)
        if value.get("health") != "online":
            value["status"] = value.get("health", "unknown")
        elif not value.get("ready"):
            value["status"] = "unauthorized" if not value.get("authorized") else "offline"
        else:
            value["status"] = "online"
        return value

    @staticmethod
    def _nested_key(value, name: str):
        if isinstance(value, Mapping):
            if name in value:
                return value[name]
            for child in value.values():
                found = CloudRuntime._nested_key(child, name)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = CloudRuntime._nested_key(child, name)
                if found is not None:
                    return found
        return None

    def _cloud_session(self) -> str:
        return _reference_target(self.store,
                                 self.store.nodes[self.session]["params"]["cloud_session"])

    def _dispatch(self, payload: Mapping[str, object]) -> dict[str, object]:
        required = {"target", "idempotency_key", "capability_ref", "evidence_node", "actor"}
        if set(payload) != required:
            raise ValueError("dispatch fields must be exactly %r" % sorted(required))
        target = str(payload["target"])
        if not target.startswith(("cloud-deployment:", "cloud-sync:")):
            raise ValueError("only Cloud deployment and sync effects can be dispatched")
        capability = str(payload["capability_ref"])
        if not capability.startswith("op://"):
            raise ValueError("capability_ref must be an op:// reference")
        actor = str(payload["actor"]).strip()
        if not actor:
            raise ValueError("dispatch actor must be non-empty")
        cloud_members = _deep_members(self.store, self._cloud_session())
        capabilities = {self.store.pull(node_id) for node_id in cloud_members
                        if self.store.nodes[node_id]["kind"] == "secret_ref"}
        if capability not in capabilities:
            raise PermissionError("capability reference is not wired into the Cloud authority")
        evidence_node = str(payload["evidence_node"])
        if evidence_node not in cloud_members or not self.store.pull(evidence_node):
            raise PermissionError("dispatch evidence node is missing, empty, or outside Cloud")
        matches = []
        for node_id in cloud_members:
            node = self.store.nodes[node_id]
            floor = node["body"].get("floor", {})
            if floor.get("op") == "effect" and floor.get("target") == target:
                matches.append(node_id)
        if len(matches) != 1:
            raise ValueError("dispatch target resolves to %d Cloud effects" % len(matches))
        effect = matches[0]
        if not self.store.nodes[effect]["meta"].get("frozen"):
            raise PermissionError("effect must be frozen before a runtime dispatch")
        guard_relations = []
        for relation_id in self.store.nodes[effect]["relations"]:
            relation = self.store.nodes[relation_id]
            if any(item.get("node_id") == effect
                   for item in relation_targets(self.store.nodes, relation)):
                stages = [stage for stage in relation_stages(self.store.nodes, relation)
                          if stage.get("mode") == "guard"]
                if stages:
                    guard_relations.extend(stages)
        if not guard_relations or not all(bool(self.store.pull(stage["node_id"]))
                                          for stage in guard_relations):
            raise PermissionError("Cloud effect relation gate is closed")
        plan = dry_run(self.store, effect)
        expected_key = self._nested_key(plan, "idempotency_key")
        if not expected_key or str(payload["idempotency_key"]) != str(expected_key):
            raise PermissionError("idempotency key does not match the graph plan")
        sinks = [node for node in self.store.nodes.values()
                 if node["kind"] == "group"
                 and {"runtime_effect_target", "runtime_effect_value"}
                 <= set(node["params"])
                 and self.store.pull(node["params"]["runtime_effect_target"]) == target]
        if len(sinks) > 1:
            raise ValueError("Cloud effect has more than one authoritative runtime sink")
        if sinks:
            sink_group = sinks[0]["id"]
            target_param = sinks[0]["params"]["runtime_effect_target"]
            value_param = sinks[0]["params"]["runtime_effect_value"]
        else:
            target_param = _param(self.store, "Runtime effect target", target)
            value_param = _param(self.store, "Runtime effect value", None)
            sink_group = self.store.add(
                "group", "Runtime dispatch sink: %s" % target,
                inner=[target_param, value_param],
                params={"runtime_effect_target": target_param,
                        "runtime_effect_value": value_param}, actor=actor)
            relation = self.store.relation([
                {"role": "source", "direction": "out", "node_id": effect,
                 "port_id": "effect", "cardinality": "one"},
                {"role": "target", "direction": "in", "node_id": sink_group,
                 "port_id": "result", "cardinality": "one"},
            ], title="Cloud effect produced runtime result", stages=guard_relations,
               actor=actor)
            self.store.edit(self.session, ["body", "inner"],
                            self.store.nodes[self.session]["body"]["inner"]
                            + [sink_group, relation], actor=actor)
        self.store.apply_op({"op": "unfreeze", "id": effect, "actor": actor})
        try:
            result = apply_effect(
                self.store, effect,
                _GraphSink(self.store, target_param, value_param), actor=actor,
            )
        finally:
            self.store.apply_op({"op": "freeze", "id": effect, "actor": actor})
        return {"effect": effect, "target": target, "result_node": sink_group,
                "fired": result["fired"], "idempotent": result["idempotent"]}

    def flush(self):
        if self.state_path is None:
            return None
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": RUNTIME_FORMAT, "saved_at": time.time(),
                   "nodes": self.store.dump()}
        temp = self.state_path.with_name(self.state_path.name + ".tmp")
        with gzip.open(temp, "wt", encoding="utf-8", compresslevel=1) as stream:
            json.dump(payload, stream, separators=(",", ":"))
        os.replace(temp, self.state_path)
        return self.state_path

    def _notify_mutation(self) -> None:
        if self.on_mutation is not None:
            self.on_mutation()

    def start(self) -> "CloudRuntime":
        if self.thread is not None:
            return self
        host, port = self.httpd.server_address[:2]
        for name, value in {
            "listener_online": True, "listener_host": host, "listener_port": port,
            "listener_observed_at": _now(),
            "listener_evidence": "ThreadingHTTPServer socket bound locally",
        }.items():
            self.store.edit(self.store.nodes[self.session]["params"][name],
                            ["body", "floor", "value"], value, actor=_ACTOR)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       name="archhub-cloud-runtime", daemon=True)
        self.thread.start()
        self.flush()
        self._notify_mutation()
        return self

    def close(self) -> None:
        if self.thread is not None:
            self.httpd.shutdown()
            self.thread.join(timeout=5)
            self.thread = None
        self.httpd.server_close()
        for name, value in {
            "listener_online": False, "listener_observed_at": _now(),
            "listener_evidence": "local listener closed",
        }.items():
            self.store.edit(self.store.nodes[self.session]["params"][name],
                            ["body", "floor", "value"], value, actor=_ACTOR)
        self.flush()
        self._notify_mutation()


__all__ = ["CloudRuntime", "MAX_REQUEST_BYTES", "RUNTIME_FORMAT",
           "build_cloud_runtime_nodes"]
