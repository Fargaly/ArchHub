"""Node-native model/provider catalog and visible routing policy.

All authority lives in the one table. Providers and models are ordinary value
records, usage and selection controls are parameter nodes, and routing is an
open graph made only from field/compare/math/merge floor primitives and wires.
The small ``route_model`` helper contains no policy: it performs stable argmax
over the candidate records computed by that visible graph.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from ..core import Store


DEFAULT_PROVIDERS = (
    {
        "id": "provider-fast",
        "title": "Fast provider",
        "capabilities": ["text", "embedding"],
        "local": False,
    },
    {
        "id": "provider-deep",
        "title": "Deep provider",
        "capabilities": ["text", "vision", "tool-use"],
        "local": False,
    },
)

DEFAULT_MODELS = (
    {
        "id": "model-fast",
        "title": "Fast model",
        "provider": "provider-fast",
        "capabilities": ["text", "embedding"],
        "max_context": 8192,
        "input_cost": 0.25,
        "output_cost": 0.50,
        "latency_ms": 120.0,
        "quality": 0.72,
        "enabled": True,
    },
    {
        "id": "model-deep",
        "title": "Deep model",
        "provider": "provider-deep",
        "capabilities": ["text", "vision", "tool-use"],
        "max_context": 65536,
        "input_cost": 0.90,
        "output_cost": 1.80,
        "latency_ms": 700.0,
        "quality": 0.94,
        "enabled": True,
    },
)

DEFAULT_POLICY = {
    "required_capability": "text",
    "minimum_context": 1024,
    "maximum_input_cost": 1.0,
    "maximum_latency_ms": 1000.0,
    "preferred_provider": "",
    "base_score": 100.0,
    "quality_weight": 10.0,
    "input_cost_weight": 2.0,
    "latency_weight": 0.005,
    "usage_weight": 0.10,
    "preference_weight": 0.0,
}

_PROVIDER_FIELDS = frozenset({"id", "title", "capabilities", "local"})
_MODEL_FIELDS = frozenset({
    "id", "title", "provider", "capabilities", "max_context",
    "input_cost", "output_cost", "latency_ms", "quality", "enabled",
})
_POLICY_FIELDS = frozenset(DEFAULT_POLICY)
_USAGE_FIELDS = ("requests", "input_tokens", "output_tokens")


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


def _capabilities(value: Any, label: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ValueError("%s must be an iterable of capability names" % label)
    capabilities = [_identifier(item, label) for item in value]
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("%s contains duplicate capabilities" % label)
    return capabilities


def _exact_fields(record: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    keys = set(record)
    unknown = sorted(keys - allowed)
    missing = sorted(allowed - keys)
    if unknown or missing:
        raise ValueError(
            "%s fields mismatch; missing=%r unknown=%r" % (label, missing, unknown)
        )


def _provider_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _PROVIDER_FIELDS, "provider")
    return {
        "id": _identifier(record["id"], "provider id"),
        "title": _identifier(record["title"], "provider title"),
        "capabilities": _capabilities(record["capabilities"], "provider capabilities"),
        "local": bool(record["local"]),
    }


def _model_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    _exact_fields(record, _MODEL_FIELDS, "model")
    quality = _number(record["quality"], "model quality")
    if quality > 1.0:
        raise ValueError("model quality must be between 0 and 1")
    return {
        "id": _identifier(record["id"], "model id"),
        "title": _identifier(record["title"], "model title"),
        "provider": _identifier(record["provider"], "model provider"),
        "capabilities": _capabilities(record["capabilities"], "model capabilities"),
        "max_context": int(_number(record["max_context"], "model max_context")),
        "input_cost": _number(record["input_cost"], "model input_cost"),
        "output_cost": _number(record["output_cost"], "model output_cost"),
        "latency_ms": _number(record["latency_ms"], "model latency_ms"),
        "quality": quality,
        "enabled": bool(record["enabled"]),
    }


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add(
        "param", title, floor={"op": "value", "value": value}, actor=actor
    )


def _record_node(
    store: Store,
    title: str,
    record: Mapping[str, Any],
    actor: str,
) -> tuple[str, dict[str, str]]:
    """Assemble a record visibly from editable parameter nodes."""
    fields = {
        name: _param(store, "%s: %s" % (title, name), value, actor)
        for name, value in record.items()
    }
    node = store.add(
        "op", title,
        floor={"op": "merge", "fn": "record", "keys": list(record)},
        params=fields,
        actor=actor,
    )
    for field_id in fields.values():
        store.wire(field_id, node, title="Assemble %s" % title, actor=actor)
    return node, fields


def _field(store: Store, source: str, path: str, title: str, bag: list[str], actor: str) -> str:
    node = store.add(
        "op", title, floor={"op": "field", "path": [path]}, actor=actor
    )
    store.wire(source, node, title="Read %s" % path, actor=actor)
    bag.append(node)
    return node


def _op(
    store: Store,
    title: str,
    floor: Mapping[str, Any],
    sources: Iterable[str],
    bag: list[str],
    actor: str,
) -> str:
    node = store.add("op", title, floor=dict(floor), actor=actor)
    for source in sources:
        store.wire(source, node, actor=actor)
    bag.append(node)
    return node


def build_models_domain(
    store: Store,
    *,
    providers: Iterable[Mapping[str, Any]] = DEFAULT_PROVIDERS,
    models: Iterable[Mapping[str, Any]] = DEFAULT_MODELS,
    policy: Mapping[str, Any] | None = None,
    actor: str = "models-domain",
) -> dict[str, Any]:
    """Build a provider/model catalog plus an open, deterministic score graph."""
    provider_records = [_provider_record(raw) for raw in providers]
    model_records = [_model_record(raw) for raw in models]
    if not provider_records:
        raise ValueError("models domain needs at least one provider")
    if not model_records:
        raise ValueError("models domain needs at least one model")

    provider_ids = [record["id"] for record in provider_records]
    model_ids = [record["id"] for record in model_records]
    if len(set(provider_ids)) != len(provider_ids):
        raise ValueError("provider ids must be unique")
    if len(set(model_ids)) != len(model_ids):
        raise ValueError("model ids must be unique")
    unknown_providers = sorted({m["provider"] for m in model_records} - set(provider_ids))
    if unknown_providers:
        raise ValueError("models reference unknown providers: %r" % unknown_providers)

    policy_values = dict(DEFAULT_POLICY)
    if policy is not None:
        unknown = sorted(set(policy) - _POLICY_FIELDS)
        if unknown:
            raise ValueError("unknown routing policy fields: %r" % unknown)
        policy_values.update(policy)
    for name in _POLICY_FIELDS - {"required_capability", "preferred_provider"}:
        policy_values[name] = _number(policy_values[name], "policy %s" % name)
    policy_values["required_capability"] = _identifier(
        policy_values["required_capability"], "required capability"
    )
    policy_values["preferred_provider"] = str(policy_values["preferred_provider"]).strip()

    selection_params = {
        name: _param(store, "Selection: %s" % name, policy_values[name], actor)
        for name in DEFAULT_POLICY
    }
    policy_group = store.add(
        "group",
        "Model routing policy",
        inner=list(selection_params.values()),
        actor=actor,
    )

    provider_nodes: dict[str, str] = {}
    provider_capability_nodes: dict[str, str] = {}
    provider_inner: dict[str, list[str]] = {}
    for record in provider_records:
        provider_id = record["id"]
        node, provider_params = _record_node(
            store, "Provider: %s" % record["title"], record, actor
        )
        inner = list(provider_params.values()) + [node]
        capabilities_node = _field(
            store, node, "capabilities", "Provider capabilities: %s" % provider_id,
            inner, actor,
        )
        provider_nodes[provider_id] = node
        provider_capability_nodes[provider_id] = capabilities_node
        provider_inner[provider_id] = inner

    model_nodes: dict[str, str] = {}
    provider_bindings: dict[str, str] = {}
    model_groups: dict[str, str] = {}
    usage_params: dict[str, dict[str, str]] = {}
    score_nodes: dict[str, str] = {}
    eligibility_nodes: dict[str, str] = {}
    candidate_nodes: dict[str, str] = {}

    true_node = store.add(
        "value", "Enabled requirement", floor={"op": "value", "value": True},
        actor=actor,
    )
    routing_inner = [true_node]

    for record in model_records:
        model_id = record["id"]
        provider_id = record["provider"]
        inner: list[str] = []
        model_node, model_params = _record_node(
            store, "Model: %s" % record["title"], record, actor
        )
        inner.extend(model_params.values())
        inner.append(model_node)
        model_nodes[model_id] = model_node
        provider_binding = store.add(
            "param", "Provider node: %s" % model_id,
            floor={"op": "reference", "target": provider_nodes[provider_id]}, actor=actor,
        )
        provider_relation = store.relation([
            {"role": "source", "direction": "out",
             "node_id": provider_nodes[provider_id], "port_id": "provider",
             "cardinality": "one"},
            {"role": "target", "direction": "in",
             "node_id": provider_binding, "port_id": "provider",
             "cardinality": "one"},
        ], title="Provider supplies model", actor=actor)
        provider_bindings[model_id] = provider_binding
        model_node_params = dict(store.nodes[model_node]["params"])
        model_node_params["provider_node"] = provider_binding
        store.edit(model_node, ["params"], model_node_params, actor=actor)
        inner.extend([provider_binding, provider_relation])

        usage = {
            name: _param(store, "Usage %s: %s" % (name, model_id), 0, actor)
            for name in _USAGE_FIELDS
        }
        usage_params[model_id] = usage
        inner.extend(usage.values())

        fields = {
            name: _field(store, model_node, name, "%s: %s" % (model_id, name), inner, actor)
            for name in (
                "id", "provider", "capabilities", "max_context", "input_cost",
                "latency_ms", "quality", "enabled",
            )
        }

        checks = [
            _op(
                store, "%s supports capability" % model_id,
                {"op": "compare", "cmp": "contains"},
                [fields["capabilities"], selection_params["required_capability"]],
                inner, actor,
            ),
            _op(
                store, "%s provider supports capability" % model_id,
                {"op": "compare", "cmp": "contains"},
                [provider_capability_nodes[provider_id], selection_params["required_capability"]],
                inner, actor,
            ),
            _op(
                store, "%s has enough context" % model_id,
                {"op": "compare", "cmp": ">="},
                [fields["max_context"], selection_params["minimum_context"]],
                inner, actor,
            ),
            _op(
                store, "%s is within cost" % model_id,
                {"op": "compare", "cmp": "<="},
                [fields["input_cost"], selection_params["maximum_input_cost"]],
                inner, actor,
            ),
            _op(
                store, "%s is within latency" % model_id,
                {"op": "compare", "cmp": "<="},
                [fields["latency_ms"], selection_params["maximum_latency_ms"]],
                inner, actor,
            ),
            _op(
                store, "%s is enabled" % model_id,
                {"op": "compare", "cmp": "=="},
                [fields["enabled"], true_node],
                inner, actor,
            ),
        ]
        eligible = _op(
            store, "%s eligibility" % model_id, {"op": "math", "fn": "*"},
            checks, inner, actor,
        )
        eligibility_nodes[model_id] = eligible

        quality_term = _op(
            store, "%s quality term" % model_id, {"op": "math", "fn": "*"},
            [fields["quality"], selection_params["quality_weight"]], inner, actor,
        )
        cost_term = _op(
            store, "%s input cost term" % model_id, {"op": "math", "fn": "*"},
            [fields["input_cost"], selection_params["input_cost_weight"]], inner, actor,
        )
        latency_term = _op(
            store, "%s latency term" % model_id, {"op": "math", "fn": "*"},
            [fields["latency_ms"], selection_params["latency_weight"]], inner, actor,
        )
        usage_term = _op(
            store, "%s usage term" % model_id, {"op": "math", "fn": "*"},
            [usage["requests"], selection_params["usage_weight"]], inner, actor,
        )
        preferred = _op(
            store, "%s preferred provider" % model_id,
            {"op": "compare", "cmp": "=="},
            [fields["provider"], selection_params["preferred_provider"]], inner, actor,
        )
        preference_term = _op(
            store, "%s preference term" % model_id, {"op": "math", "fn": "*"},
            [preferred, selection_params["preference_weight"]], inner, actor,
        )
        gross = _op(
            store, "%s gross utility" % model_id, {"op": "math", "fn": "+"},
            [selection_params["base_score"], quality_term, preference_term], inner, actor,
        )
        utility = _op(
            store, "%s utility after penalties" % model_id,
            {"op": "math", "fn": "-"},
            [gross, cost_term, latency_term, usage_term], inner, actor,
        )
        score = _op(
            store, "%s routing score" % model_id, {"op": "math", "fn": "*"},
            [eligible, utility], inner, actor,
        )
        score_nodes[model_id] = score

        candidate = _op(
            store,
            "%s routing candidate" % model_id,
            {"op": "merge", "fn": "record",
             "keys": ["model_id", "provider_id", "eligible", "score"]},
            [fields["id"], fields["provider"], eligible, score],
            inner,
            actor,
        )
        candidate_nodes[model_id] = candidate
        routing_inner.append(candidate)

        model_group = store.add(
            "group", "Model route: %s" % model_id, inner=inner, actor=actor
        )
        model_groups[model_id] = model_group
        provider_inner[provider_id].append(model_group)

    candidates = _op(
        store,
        "Routing candidates in declaration order",
        {"op": "merge", "fn": "list"},
        [candidate_nodes[model_id] for model_id in model_ids],
        routing_inner,
        actor,
    )
    no_match = {
        "model_id": None,
        "provider_id": None,
        "eligible": False,
        "score": None,
        "status": "no-match",
    }
    selected_candidate = _op(
        store,
        "Selected routing candidate",
        {"op": "reduce", "mode": "argmax", "key_path": "score",
         "where_path": "eligible", "default": no_match},
        [candidates],
        routing_inner,
        actor,
    )
    routing_group = store.add(
        "group", "Model routing decision", inner=routing_inner, actor=actor
    )

    provider_groups = {
        provider_id: store.add(
            "group",
            "Provider models: %s" % provider_id,
            inner=provider_inner[provider_id],
            actor=actor,
        )
        for provider_id in provider_ids
    }
    session = store.add(
        "session",
        "Models Domain",
        inner=list(provider_groups.values()) + [policy_group, routing_group],
        actor=actor,
    )
    return {
        "session": session,
        "providers": provider_nodes,
        "provider_groups": provider_groups,
        "models": model_nodes,
        "provider_bindings": provider_bindings,
        "model_groups": model_groups,
        "usage_params": usage_params,
        "selection_params": selection_params,
        "policy_group": policy_group,
        "routing_group": routing_group,
        "eligibility_nodes": eligibility_nodes,
        "score_nodes": score_nodes,
        "candidate_nodes": candidate_nodes,
        "candidates": candidates,
        "selected_candidate": selected_candidate,
        "model_order": list(model_ids),
    }


def route_model(store: Store, domain: Mapping[str, Any]) -> dict[str, Any]:
    """Pull the visible routing decision node; this helper contains no policy."""
    selected = store.pull(str(domain["selected_candidate"]))
    if not isinstance(selected, dict):
        raise ValueError("selected candidate node did not produce a record")
    if selected.get("model_id") is None:
        return dict(selected)
    return dict(selected, status="selected")


def set_selection_parameter(
    store: Store,
    domain: Mapping[str, Any],
    name: str,
    value: Any,
    *,
    actor: str = "models-domain",
) -> str:
    """Edit one visible routing parameter through Store's audited path."""
    params = domain["selection_params"]
    if name not in params:
        raise KeyError("unknown selection parameter %r" % name)
    return store.edit(
        params[name], ["body", "floor", "value"], value, actor=actor
    )


def set_model_usage(
    store: Store,
    domain: Mapping[str, Any],
    model_id: str,
    *,
    requests: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    actor: str = "models-domain",
) -> list[str]:
    """Edit model usage parameters; request count currently drives routing."""
    usage_by_model = domain["usage_params"]
    if model_id not in usage_by_model:
        raise KeyError("unknown model %r" % model_id)
    updates = {
        "requests": requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    touched = []
    for name, value in updates.items():
        if value is None:
            continue
        clean = int(_number(value, "%s %s" % (model_id, name)))
        touched.append(store.edit(
            usage_by_model[model_id][name],
            ["body", "floor", "value"],
            clean,
            actor=actor,
        ))
    return touched


__all__ = [
    "DEFAULT_PROVIDERS",
    "DEFAULT_MODELS",
    "DEFAULT_POLICY",
    "build_models_domain",
    "route_model",
    "set_selection_parameter",
    "set_model_usage",
]
