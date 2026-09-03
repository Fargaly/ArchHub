"""Node-native plans, entitlements, metering, billing, and revenue.

The Grand Map monetization domain is represented as fifteen open groups joined
by its nineteen authoritative relations. Commercial values and policies are
parameter nodes. Checkout, subscription, and invoice changes are inspectable
plans whose external effects stay frozen behind approval, idempotency, and
privacy guard nodes.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from ..core import Store, relation_sources
from ..laws_effect import apply_effect
from ..laws_relation import rewire_endpoint


DEFAULT_PLANS = (
    {"id": "free", "title": "Free", "monthly_price": 0.0,
     "seat_price": 0.0, "seats": 1, "credits": 50_000,
     "token_limit": 50_000, "node_run_limit": 1_000,
     "connector_call_limit": 100, "byo_key": False,
     "features": ["nodes", "local-sessions"]},
    {"id": "pro", "title": "Pro", "monthly_price": 19.0,
     "seat_price": 19.0, "seats": 1, "credits": 1_000_000,
     "token_limit": 1_000_000, "node_run_limit": 20_000,
     "connector_call_limit": 5_000, "byo_key": True,
     "features": ["nodes", "local-sessions", "cloud-sync", "connectors"]},
    {"id": "firm", "title": "Firm", "monthly_price": 39.0,
     "seat_price": 39.0, "seats": 5, "credits": 5_000_000,
     "token_limit": 5_000_000, "node_run_limit": 100_000,
     "connector_call_limit": 25_000, "byo_key": True,
     "features": ["nodes", "cloud-sync", "connectors", "firm-pooling"]},
)

AUTHORITY_WIRES = (
    ("monetization_plan_catalog", "monetization_entitlements"),
    ("monetization_entitlements", "monetization_quota_gate"),
    ("monetization_entitlements", "monetization_byo_key_gate"),
    ("monetization_usage_meter", "monetization_quota_gate"),
    ("monetization_quota_gate", "monetization_free_llm_key"),
    ("monetization_byo_key_gate", "monetization_free_llm_key"),
    ("monetization_quota_gate", "monetization_upgrade_flow"),
    ("monetization_upgrade_flow", "monetization_stripe_billing"),
    ("monetization_stripe_billing", "monetization_webhook_sync"),
    ("monetization_webhook_sync", "monetization_entitlements"),
    ("monetization_entitlements", "monetization_firm_seats"),
    ("monetization_firm_seats", "monetization_usage_meter"),
    ("monetization_usage_meter", "monetization_account_chip"),
    ("monetization_entitlements", "monetization_account_chip"),
    ("monetization_marketplace_rev", "monetization_revenue_ledger"),
    ("monetization_stripe_billing", "monetization_revenue_ledger"),
    ("monetization_project_billing", "monetization_marketplace_rev"),
    ("monetization_webhook_sync", "monetization_dunning"),
    ("monetization_dunning", "monetization_entitlements"),
)

_PLAN_FIELDS = frozenset(DEFAULT_PLANS[0])
_NUMERIC_PLAN_FIELDS = frozenset({
    "monthly_price", "seat_price", "seats", "credits", "token_limit",
    "node_run_limit", "connector_call_limit",
})
_SECRET_WORDS = frozenset({
    "apikey", "api_key", "credential", "credentials", "password", "secret",
    "token", "private_key", "access_token", "refresh_token",
})
_SECRET_PREFIXES = ("sk-", "rk_", "whsec_", "bearer ", "github_pat_", "ghp_")


def _param(store: Store, title: str, value: Any, actor: str) -> str:
    return store.add("param", title, floor={"op": "value", "value": value}, actor=actor)


def _wire(store: Store, source: str, target: str, title: str, actor: str) -> str:
    return store.wire(source, target, title=title, actor=actor)


def _op(store: Store, title: str, floor: Mapping[str, Any], sources: Iterable[str],
        inner: list[str], relations: list[str], actor: str) -> str:
    node = store.add("op", title, floor=dict(floor), actor=actor)
    inner.append(node)
    for source in sources:
        wire = _wire(store, source, node, "Input to %s" % title, actor)
        relations.append(wire)
        inner.append(wire)
    return node


def _record_group_from_nodes(
    store: Store,
    title: str,
    fields: Mapping[str, str],
    actor: str,
    *,
    local_nodes: Iterable[str] = (),
) -> dict[str, Any]:
    exposed: dict[str, str] = {}
    references: list[str] = []
    for name, node_id in fields.items():
        if node_id not in store.nodes:
            raise KeyError("record field %s is not in the one table" % name)
        if store.nodes[node_id]["kind"] == "param":
            exposed[name] = node_id
        else:
            reference = store.add(
                "param", "%s: %s" % (title, name),
                floor={"op": "reference", "target": node_id}, actor=actor)
            exposed[name] = reference
            references.append(reference)
    keys = list(fields)
    keys_param = _param(store, "%s: record keys" % title, keys, actor)
    record = store.add(
        "op", "%s record" % title,
        floor={"op": "merge", "fn": "record", "keys": {"$param": "keys"}},
        params={"keys": keys_param}, actor=actor)
    wires = [
        _wire(store, exposed[name], record, "%s enters %s" % (name, title), actor)
        for name in keys
    ]
    owned = list(local_nodes) or [node_id for node_id in fields.values()
                                  if store.nodes[node_id]["kind"] == "param"]
    group = store.add(
        "group", title,
        inner=list(dict.fromkeys(owned + references + [keys_param, record] + wires)),
        params=exposed, actor=actor)
    return {"group": group, "record": record, "params": exposed,
            "fields": dict(fields), "wires": wires, "keys": keys_param}


def _record_group(store: Store, title: str, values: Mapping[str, Any], actor: str):
    fields = {name: _param(store, "%s: %s" % (title, name), value, actor)
              for name, value in values.items()}
    return _record_group_from_nodes(
        store, title, fields, actor, local_nodes=fields.values())


def _field(store: Store, source: str, path: str, title: str,
           inner: list[str], relations: list[str], actor: str) -> str:
    return _op(store, title, {"op": "field", "path": [path]}, [source],
               inner, relations, actor)


def _attach_authority(store: Store, group: str, authority_id: str, actor: str) -> str:
    authority = _param(store, "%s: authority id" % store.nodes[group]["title"],
                       authority_id, actor)
    node = store.nodes[group]
    store.edit(group, ["body", "inner"], node["body"]["inner"] + [authority], actor=actor)
    params = dict(store.nodes[group]["params"])
    params["authority_id"] = authority
    store.edit(group, ["params"], params, actor=actor)
    return group


def _assert_no_raw_secrets(value: Any, path: str = "billing configuration") -> None:
    if isinstance(value, Mapping):
        for name, child in value.items():
            normalized = str(name).casefold()
            words = {part for part in re.split(r"[^a-z0-9_]+", normalized) if part}
            if normalized in _SECRET_WORDS or words & _SECRET_WORDS:
                raise ValueError("%s contains a secret field %r; use a secret_ref node"
                                 % (path, name))
            _assert_no_raw_secrets(child, "%s.%s" % (path, name))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_raw_secrets(child, "%s[%d]" % (path, index))
    elif isinstance(value, str) and value.casefold().startswith(_SECRET_PREFIXES):
        raise ValueError("%s contains a probable raw secret" % path)


def _plan_record(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    missing = sorted(_PLAN_FIELDS - set(record))
    unknown = sorted(set(record) - _PLAN_FIELDS)
    if missing or unknown:
        raise ValueError("plan fields mismatch; missing=%r unknown=%r" % (missing, unknown))
    for key in ("id", "title"):
        record[key] = str(record[key]).strip()
        if not record[key]:
            raise ValueError("plan %s must be non-empty" % key)
    for key in _NUMERIC_PLAN_FIELDS:
        record[key] = float(record[key])
        if record[key] < 0:
            raise ValueError("plan %s must be non-negative" % key)
    if record["seats"] < 1:
        raise ValueError("plan seats must be at least one")
    record["byo_key"] = bool(record["byo_key"])
    record["features"] = [str(item).strip() for item in record["features"]]
    if any(not item for item in record["features"]):
        raise ValueError("plan features must be non-empty")
    return record


def _source_endpoint(store: Store, relation_id: str) -> str:
    sources = relation_sources(store.nodes, store.nodes[relation_id])
    if len(sources) != 1:
        raise ValueError("selection relation requires exactly one source")
    return str(sources[0]["endpoint_param"])


def _billing_plan(
    store: Store,
    title: str,
    operation: str,
    account: str,
    selected_plan: str,
    seats: str,
    amount: str,
    currency: str,
    idempotency_key: str,
    privacy_scope: str,
    approval_gate: str,
    idempotency_gate: str,
    privacy_gate: str,
    trigger: str,
    relations: list[str],
    actor: str,
) -> dict[str, Any]:
    action = _param(store, "%s: action" % title, operation, actor)
    mode = _param(store, "%s: mode" % title, "subscription", actor)
    fields = {
        "action": action, "account_id": account, "plan_id": selected_plan,
        "seats": seats, "amount": amount, "currency": currency,
        "mode": mode, "idempotency_key": idempotency_key,
        "privacy_scope": privacy_scope,
    }
    record = _record_group_from_nodes(
        store, title, fields, actor, local_nodes=[action, mode])
    target_inner: list[str] = []
    target = _op(
        store, "%s target" % title,
        {"op": "format", "template": "billing:{}:%s:{}" % operation},
        [account, idempotency_key], target_inner, relations, actor)
    target_ref = store.add(
        "param", "%s: target" % title,
        floor={"op": "reference", "target": target}, actor=actor)
    change_ref = store.add(
        "param", "%s: change" % title,
        floor={"op": "reference", "target": record["record"]}, actor=actor)
    effect = store.add(
        "op", "Frozen %s effect" % title,
        floor={"op": "effect", "target": "billing:pending:%s" % operation,
               "change": {"$param": "change"}},
        params={"target": target_ref, "change": change_ref}, frozen=True, actor=actor)
    result = store.add("op", "%s result" % title,
                       floor={"op": "merge", "fn": "list"}, actor=actor)
    execution = store.relation([
        {"role": "source", "direction": "out", "node_id": trigger,
         "port_id": "request", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": result,
         "port_id": "result", "cardinality": "one"},
    ], title="Guarded %s execution" % title, stages=[
        {"role": "approval", "mode": "guard", "node_id": approval_gate},
        {"role": "idempotency", "mode": "guard", "node_id": idempotency_gate},
        {"role": "privacy", "mode": "guard", "node_id": privacy_gate},
        {"role": "billing-plan", "mode": "map", "node_id": effect},
    ], actor=actor)
    relations.append(execution)
    group = store.add(
        "group", title,
        inner=[record["group"]] + target_inner + [target_ref, change_ref, effect,
                                                   result, execution],
        params={"action": action, "mode": mode, "target": target_ref,
                "change": change_ref}, actor=actor)
    return {"group": group, "record": record["record"], "params": record["params"],
            "target": target, "effect": effect, "result": result,
            "relation": execution}


def build_monetization_domain(
    store: Store,
    *,
    plans: Iterable[Mapping[str, Any]] = DEFAULT_PLANS,
    selected_plan: str = "free",
    account_id: str = "founder",
    grace_percent: float = 10.0,
    billing_configuration: Mapping[str, Any] | None = None,
    actor: str = "monetization-domain",
) -> dict[str, Any]:
    records = [_plan_record(raw) for raw in plans]
    ids = [record["id"] for record in records]
    if not records or len(ids) != len(set(ids)):
        raise ValueError("plans must be non-empty with unique ids")
    if selected_plan not in ids:
        raise ValueError("selected plan is not in the plan catalog")
    account_id = str(account_id).strip()
    if not account_id:
        raise ValueError("account id must be non-empty")
    grace_percent = float(grace_percent)
    if grace_percent < 0:
        raise ValueError("grace percent must be non-negative")
    configuration = {
        "provider": "stripe", "capability_ref": "op://archhub/billing/provider",
        "currency": "usd", "proration": True, "portal_enabled": True,
    }
    configuration.update(dict(billing_configuration or {}))
    _assert_no_raw_secrets(configuration)
    capability_ref = str(configuration.get("capability_ref", ""))
    if not capability_ref.startswith("op://"):
        raise ValueError("billing capability_ref must be an external op:// reference")

    relations: list[str] = []
    plan_groups: dict[str, str] = {}
    plan_records: dict[str, str] = {}
    plan_params: dict[str, dict[str, str]] = {}
    plan_wires: list[str] = []
    for record in records:
        built = _record_group(store, "Plan: %s" % record["title"], record, actor)
        plan_groups[record["id"]] = built["group"]
        plan_records[record["id"]] = built["record"]
        plan_params[record["id"]] = built["params"]
        plan_wires.extend(built["wires"])
        relations.extend(built["wires"])
    catalog_list = store.add("op", "Plan catalog records",
                             floor={"op": "merge", "fn": "list"}, actor=actor)
    catalog_wires = []
    for plan_id in ids:
        wire = _wire(store, plan_records[plan_id], catalog_list,
                     "Plan enters catalog", actor)
        catalog_wires.append(wire)
        relations.append(wire)
    trial_days = _param(store, "Plan catalog: trial days", 14.0, actor)
    catalog = store.add(
        "group", "Plan Catalog",
        inner=list(plan_groups.values()) + [trial_days, catalog_list] + catalog_wires,
        params={"trial_days": trial_days}, actor=actor)
    _attach_authority(store, catalog, "monetization_plan_catalog", actor)

    subscription_built = _record_group(store, "Active subscription", {
        "account_id": account_id, "plan_id": selected_plan, "status": "active",
        "renews_at": "", "seat_count": 1.0,
    }, actor)
    relations.extend(subscription_built["wires"])
    subscription = subscription_built["group"]
    subscription_params = subscription_built["params"]
    selected_record = store.add("op", "Selected plan record",
                                floor={"op": "merge", "fn": "first"}, actor=actor)
    plan_relation = store.relation([
        {"role": "source", "direction": "out",
         "node_id": plan_records[selected_plan], "port_id": "plan", "cardinality": "one"},
        {"role": "target", "direction": "in", "node_id": selected_record,
         "port_id": "selection", "cardinality": "one"},
    ], title="Active subscription selects plan", actor=actor)
    relations.append(plan_relation)
    entitlement_inner: list[str] = [subscription, selected_record, plan_relation]
    selected_fields: dict[str, str] = {}
    for name in ("id", "features", "token_limit", "node_run_limit",
                 "connector_call_limit", "seats", "seat_price", "credits",
                 "byo_key", "monthly_price"):
        selected_fields[name] = _field(
            store, selected_record, name, "Selected plan: %s" % name,
            entitlement_inner, relations, actor)
    entitlement_value = _op(
        store, "Resolved entitlements",
        {"op": "merge", "fn": "record",
         "keys": ["plan_id", "features", "seats", "credits", "byo_key",
                  "token_limit", "node_run_limit", "connector_call_limit"]},
        [selected_fields["id"], selected_fields["features"], selected_fields["seats"],
         selected_fields["credits"], selected_fields["byo_key"],
         selected_fields["token_limit"], selected_fields["node_run_limit"],
         selected_fields["connector_call_limit"]],
        entitlement_inner, relations, actor)
    entitlement_group = store.add("group", "Entitlement Resolver",
                                  inner=entitlement_inner, actor=actor)
    _attach_authority(store, entitlement_group, "monetization_entitlements", actor)

    usage_built = _record_group(store, "Usage Meter", {
        "tokens": 0.0, "node_runs": 0.0, "connector_calls": 0.0,
        "credits": 0.0, "window": "calendar_month", "flush_interval_s": 30.0,
    }, actor)
    relations.extend(usage_built["wires"])
    usage_group = usage_built["group"]
    usage_params = usage_built["params"]
    _attach_authority(store, usage_group, "monetization_usage_meter", actor)

    grace_pct = _param(store, "Quota Gate: grace percent", grace_percent, actor)
    hundred = _param(store, "Quota Gate: percent base", 100.0, actor)
    one = _param(store, "Quota Gate: multiplier base", 1.0, actor)
    quota_inner: list[str] = [grace_pct, hundred, one]
    grace_fraction = _op(store, "Quota grace fraction", {"op": "math", "fn": "/"},
                         [grace_pct, hundred], quota_inner, relations, actor)
    grace_multiplier = _op(store, "Quota grace multiplier", {"op": "math", "fn": "+"},
                           [one, grace_fraction], quota_inner, relations, actor)
    quota_gates: dict[str, str] = {}
    remaining: dict[str, str] = {}
    for usage_name, limit_name in (("tokens", "token_limit"),
                                   ("node_runs", "node_run_limit"),
                                   ("connector_calls", "connector_call_limit"),
                                   ("credits", "credits")):
        effective = _op(store, "Effective %s limit" % usage_name,
                        {"op": "math", "fn": "*"},
                        [selected_fields[limit_name], grace_multiplier],
                        quota_inner, relations, actor)
        quota_gates[usage_name] = _op(
            store, "%s quota gate" % usage_name, {"op": "compare", "cmp": "<="},
            [usage_params[usage_name], effective], quota_inner, relations, actor)
        remaining[usage_name] = _op(
            store, "%s remaining" % usage_name, {"op": "math", "fn": "-"},
            [effective, usage_params[usage_name]], quota_inner, relations, actor)
    quota_gate = _op(store, "Combined quota gate", {"op": "math", "fn": "*"},
                     quota_gates.values(), quota_inner, relations, actor)
    on_exceed = _param(store, "Quota Gate: on exceed", "soft_block", actor)
    reset = _param(store, "Quota Gate: reset", "monthly", actor)
    quota_group = store.add(
        "group", "Quota Gate", inner=quota_inner + [on_exceed, reset],
        params={"grace_pct": grace_pct, "on_exceed": on_exceed, "reset": reset},
        actor=actor)
    _attach_authority(store, quota_group, "monetization_quota_gate", actor)

    true_node = store.add("value", "True", floor={"op": "value", "value": True}, actor=actor)
    false_node = store.add("value", "False", floor={"op": "value", "value": False}, actor=actor)
    zero_node = store.add("value", "Zero", floor={"op": "value", "value": 0.0}, actor=actor)
    byo_inner: list[str] = []
    byo_gate = _op(store, "BYO-key entitlement gate", {"op": "compare", "cmp": "=="},
                   [selected_fields["byo_key"], true_node], byo_inner, relations, actor)
    byo_secret = store.add("secret_ref", "User model credential capability",
                           floor={"op": "secret_ref",
                                  "ref": "op://archhub/models/byo-key"}, actor=actor)
    byo_group = store.add("group", "BYO-Key Gate", inner=byo_inner + [byo_secret], actor=actor)
    _attach_authority(store, byo_group, "monetization_byo_key_gate", actor)

    free_secret = store.add("secret_ref", "Free-tier model credential capability",
                            floor={"op": "secret_ref",
                                   "ref": "op://archhub/models/free-tier"}, actor=actor)
    free_model = _param(store, "Free-Tier LLM Key: model", "cloud-free", actor)
    free_rate = _param(store, "Free-Tier LLM Key: rate limit rpm", 20.0, actor)
    free_group = store.add(
        "group", "Free-Tier LLM Key",
        inner=[free_secret, free_model, free_rate, quota_gate, byo_gate],
        params={"model": free_model, "rate_limit_rpm": free_rate}, actor=actor)
    _attach_authority(store, free_group, "monetization_free_llm_key", actor)

    seat_inner: list[str] = []
    requested_seats = subscription_params["seat_count"]
    seat_delta = _op(store, "Seats above allowance", {"op": "math", "fn": "-"},
                     [requested_seats, selected_fields["seats"]],
                     seat_inner, relations, actor)
    extra_seats = _op(store, "Billable extra seats", {"op": "math", "fn": "max"},
                      [zero_node, seat_delta], seat_inner, relations, actor)
    seat_overage = _op(store, "Seat overage charge", {"op": "math", "fn": "*"},
                       [extra_seats, selected_fields["seat_price"]],
                       seat_inner, relations, actor)
    monthly_total = _op(store, "Monthly total", {"op": "math", "fn": "+"},
                        [selected_fields["monthly_price"], seat_overage],
                        seat_inner, relations, actor)
    credit_pool = _op(store, "Firm credit pool", {"op": "math", "fn": "*"},
                      [selected_fields["credits"], requested_seats],
                      seat_inner, relations, actor)
    seats_record = _record_group_from_nodes(store, "Firm Seats and Pooling", {
        "plan_id": selected_fields["id"], "requested_seats": requested_seats,
        "included_seats": selected_fields["seats"], "extra_seats": extra_seats,
        "seat_price": selected_fields["seat_price"], "monthly_total": monthly_total,
        "credit_pool": credit_pool,
    }, actor, local_nodes=seat_inner)
    firm_group = seats_record["group"]
    _attach_authority(store, firm_group, "monetization_firm_seats", actor)

    quota_hit_inner: list[str] = []
    quota_hit = _op(store, "Quota is exhausted", {"op": "compare", "cmp": "=="},
                    [quota_gate, false_node], quota_hit_inner, relations, actor)
    manual_upgrade = _param(store, "Upgrade Flow: manually requested", False, actor)
    upgrade_requested = _op(
        store, "Upgrade requested", {"op": "math", "fn": "max"},
        [quota_hit, manual_upgrade], quota_hit_inner, relations, actor)
    trigger = _param(store, "Upgrade Flow: trigger", "quota_hit,manual", actor)
    surface = _param(store, "Upgrade Flow: surface", "modal+account_chip", actor)
    highlight = _param(store, "Upgrade Flow: highlighted plan", "pro", actor)
    upgrade_group = store.add(
        "group", "Upgrade Flow",
        inner=quota_hit_inner + [manual_upgrade, trigger, surface, highlight],
        params={"manual_requested": manual_upgrade, "trigger": trigger,
                "surface": surface, "highlight_plan": highlight}, actor=actor)
    _attach_authority(store, upgrade_group, "monetization_upgrade_flow", actor)

    approved = _param(store, "Billing approved", False, actor)
    approver = _param(store, "Billing approver", "", actor)
    approved_at = _param(store, "Billing approved at", "", actor)
    empty = store.add("value", "Empty", floor={"op": "value", "value": ""}, actor=actor)
    approval_inner = [approved, approver, approved_at]
    approval_checks = [
        _op(store, "Billing approval is explicit", {"op": "compare", "cmp": "=="},
            [approved, true_node], approval_inner, relations, actor),
        _op(store, "Billing approver is identified", {"op": "compare", "cmp": "!="},
            [approver, empty], approval_inner, relations, actor),
        _op(store, "Billing approval is timestamped", {"op": "compare", "cmp": "!="},
            [approved_at, empty], approval_inner, relations, actor),
    ]
    approval_gate = _op(store, "Billing approval gate", {"op": "math", "fn": "*"},
                        approval_checks, approval_inner, relations, actor)
    approval_group = store.add(
        "group", "Billing Approval", inner=approval_inner,
        params={"approved": approved, "approver": approver,
                "approved_at": approved_at}, actor=actor)

    idempotency_key = _param(store, "Billing idempotency key", "", actor)
    idempotency_enabled = _param(store, "Billing idempotency enforced", True, actor)
    idempotency_inner = [idempotency_key, idempotency_enabled]
    key_present = _op(store, "Idempotency key is present", {"op": "compare", "cmp": "!="},
                      [idempotency_key, empty], idempotency_inner, relations, actor)
    enforcement_enabled = _op(
        store, "Idempotency enforcement is enabled", {"op": "compare", "cmp": "=="},
        [idempotency_enabled, true_node], idempotency_inner, relations, actor)
    idempotency_gate = _op(
        store, "Billing idempotency gate", {"op": "math", "fn": "*"},
        [key_present, enforcement_enabled], idempotency_inner, relations, actor)
    idempotency_group = store.add(
        "group", "Billing Idempotency", inner=idempotency_inner,
        params={"key": idempotency_key, "enforced": idempotency_enabled}, actor=actor)

    privacy_scope = _param(store, "Billing request privacy scope", "T1 INTERNAL", actor)
    allowed_privacy = _param(store, "Billing allowed privacy scope", "T1 INTERNAL", actor)
    privacy_inner = [privacy_scope, allowed_privacy]
    privacy_gate = _op(store, "Billing privacy gate", {"op": "compare", "cmp": "=="},
                       [privacy_scope, allowed_privacy], privacy_inner, relations, actor)
    privacy_group = store.add(
        "group", "Billing Privacy", inner=privacy_inner,
        params={"request_scope": privacy_scope, "allowed_scope": allowed_privacy},
        actor=actor)

    account_param = _param(store, "Billing account id", account_id, actor)
    currency_param = _param(store, "Billing currency", configuration["currency"], actor)
    provider_config = _record_group(store, "Billing Provider Configuration",
                                    configuration, actor)
    relations.extend(provider_config["wires"])
    provider_secret = store.add(
        "secret_ref", "Billing provider credential capability",
        floor={"op": "secret_ref", "ref": capability_ref}, actor=actor)
    billing_plans = {
        operation: _billing_plan(
            store, title, operation, account_param, selected_fields["id"],
            requested_seats, monthly_total, currency_param, idempotency_key,
            privacy_scope, approval_gate, idempotency_gate, privacy_gate,
            upgrade_requested, relations, actor)
        for operation, title in (
            ("checkout", "Checkout Plan"),
            ("subscription", "Subscription Change Plan"),
            ("invoice", "Invoice Plan"),
        )
    }
    billing_group = store.add(
        "group", "Stripe Billing",
        inner=[provider_config["group"], provider_secret, approval_group,
               idempotency_group, privacy_group] +
              [billing_plans[name]["group"] for name in ("checkout", "subscription", "invoice")],
        params={"account_id": account_param, "currency": currency_param}, actor=actor)
    _attach_authority(store, billing_group, "monetization_stripe_billing", actor)

    webhook = _record_group(store, "Billing Webhook Sync", {
        "events": ["sub.created", "sub.updated", "sub.deleted", "invoice.paid"],
        "signature_valid": False, "retry_on_fail": 3.0, "event": {},
    }, actor)
    relations.extend(webhook["wires"])
    signature_inner: list[str] = []
    signature_gate = _op(
        store, "Webhook signature gate", {"op": "compare", "cmp": "=="},
        [webhook["params"]["signature_valid"], true_node],
        signature_inner, relations, actor)
    store.edit(webhook["group"], ["body", "inner"],
               store.open(webhook["group"]) + signature_inner, actor=actor)
    webhook_group = webhook["group"]
    _attach_authority(store, webhook_group, "monetization_webhook_sync", actor)

    project = _record_group(store, "Project Monetization Node", {
        "model": "per_run|flat|hourly", "markup_pct": 0.0,
        "invoice_to": "client_email",
    }, actor)
    relations.extend(project["wires"])
    project_group = project["group"]
    _attach_authority(store, project_group, "monetization_project_billing", actor)

    marketplace = _record_group(store, "Marketplace Revenue Share", {
        "platform_fee_pct": 20.0, "payout_provider": "stripe_connect",
        "min_payout_usd": 25.0,
    }, actor)
    relations.extend(marketplace["wires"])
    marketplace_group = marketplace["group"]
    _attach_authority(store, marketplace_group, "monetization_marketplace_rev", actor)

    dunning = _record_group(store, "Dunning and Downgrade", {
        "retry_schedule_days": [1, 3, 7], "grace_days": 7.0,
        "on_final_fail": "downgrade_free",
    }, actor)
    relations.extend(dunning["wires"])
    dunning_group = dunning["group"]
    _attach_authority(store, dunning_group, "monetization_dunning", actor)

    revenue = _record_group(store, "Revenue Ledger", {
        "currency_base": "usd", "mrr": 0.0, "payouts": 0.0, "refunds": 0.0,
        "retention_days": 3650.0,
    }, actor)
    relations.extend(revenue["wires"])
    revenue_inner = store.open(revenue["group"])
    net_revenue = _op(store, "Net revenue", {"op": "math", "fn": "-"},
                      [revenue["params"]["mrr"], revenue["params"]["payouts"],
                       revenue["params"]["refunds"]],
                      revenue_inner, relations, actor)
    store.edit(revenue["group"], ["body", "inner"], revenue_inner, actor=actor)
    revenue_group = revenue["group"]
    _attach_authority(store, revenue_group, "monetization_revenue_ledger", actor)

    chip_inner: list[str] = []
    account_chip_value = _op(
        store, "Account and usage chip", {"op": "merge", "fn": "record",
        "keys": ["plan", "monthly_total", "seats", "tokens_remaining",
                 "node_runs_remaining", "connector_calls_remaining",
                 "credits_remaining", "renews_at"]},
        [selected_fields["id"], monthly_total, requested_seats, remaining["tokens"],
         remaining["node_runs"], remaining["connector_calls"], remaining["credits"],
         subscription_params["renews_at"]], chip_inner, relations, actor)
    chip_refresh = _param(store, "Account and Usage Chip: refresh seconds", 60.0, actor)
    chip_action = _param(store, "Account and Usage Chip: click action",
                         "open_settings_account", actor)
    account_chip_group = store.add(
        "group", "Account and Usage Chip", inner=chip_inner + [chip_refresh, chip_action],
        params={"refresh_s": chip_refresh, "click_action": chip_action}, actor=actor)
    _attach_authority(store, account_chip_group, "monetization_account_chip", actor)

    authority_nodes = {
        "monetization_plan_catalog": catalog,
        "monetization_entitlements": entitlement_group,
        "monetization_usage_meter": usage_group,
        "monetization_quota_gate": quota_group,
        "monetization_free_llm_key": free_group,
        "monetization_byo_key_gate": byo_group,
        "monetization_stripe_billing": billing_group,
        "monetization_webhook_sync": webhook_group,
        "monetization_upgrade_flow": upgrade_group,
        "monetization_firm_seats": firm_group,
        "monetization_marketplace_rev": marketplace_group,
        "monetization_project_billing": project_group,
        "monetization_account_chip": account_chip_group,
        "monetization_dunning": dunning_group,
        "monetization_revenue_ledger": revenue_group,
    }
    authority_relations: dict[tuple[str, str], str] = {}
    for source_key, target_key in AUTHORITY_WIRES:
        relation = store.relation([
            {"role": "source", "direction": "out", "node_id": authority_nodes[source_key],
             "port_id": source_key, "cardinality": "one"},
            {"role": "target", "direction": "in", "node_id": authority_nodes[target_key],
             "port_id": target_key, "cardinality": "one"},
        ], title="Grand Map: %s -> %s" % (source_key, target_key), actor=actor)
        authority_relations[(source_key, target_key)] = relation
        relations.append(relation)

    session = store.add(
        "session", "Monetization Domain",
        inner=list(authority_nodes.values()) + list(authority_relations.values()),
        actor=actor)
    return {
        "session": session, "authority_nodes": authority_nodes,
        "authority_relations": authority_relations,
        "plans": plan_groups, "plan_records": plan_records,
        "plan_params": plan_params, "plan_order": ids, "catalog": catalog,
        "subscription": subscription, "subscription_value": subscription_built["record"],
        "subscription_params": subscription_params,
        "selected_plan": selected_record, "plan_relation": plan_relation,
        "plan_source_param": _source_endpoint(store, plan_relation),
        "entitlements": entitlement_group, "entitlement_value": entitlement_value,
        "selected_fields": selected_fields,
        "usage": usage_group, "usage_record": usage_built["record"],
        "usage_params": usage_params, "quota": quota_group,
        "quota_gates": quota_gates, "quota_gate": quota_gate, "remaining": remaining,
        "byo_key": byo_group, "byo_gate": byo_gate,
        "free_key": free_group, "free_secret": free_secret,
        "firm_seats": firm_group, "extra_seats": extra_seats,
        "seat_overage": seat_overage, "monthly_total": monthly_total,
        "credit_pool": credit_pool, "upgrade": upgrade_group,
        "upgrade_requested": upgrade_requested,
        "approval": approval_group, "approval_gate": approval_gate,
        "approval_params": {"approved": approved, "approver": approver,
                            "approved_at": approved_at},
        "idempotency": idempotency_group, "idempotency_gate": idempotency_gate,
        "idempotency_params": {"key": idempotency_key,
                               "enforced": idempotency_enabled},
        "privacy": privacy_group, "privacy_gate": privacy_gate,
        "privacy_params": {"request_scope": privacy_scope,
                           "allowed_scope": allowed_privacy},
        "billing": billing_group, "billing_plans": billing_plans,
        "billing_effects": {name: plan["effect"] for name, plan in billing_plans.items()},
        "billing_effect": billing_plans["checkout"]["effect"],
        "billing_result": billing_plans["checkout"]["result"],
        "billing_relation": billing_plans["checkout"]["relation"],
        "webhook": webhook_group, "webhook_signature_gate": signature_gate,
        "marketplace": marketplace_group, "project_billing": project_group,
        "dunning": dunning_group, "revenue": revenue_group,
        "revenue_params": revenue["params"], "net_revenue": net_revenue,
        "account_chip": account_chip_group, "account_chip_value": account_chip_value,
        "relations": relations,
    }


def select_plan(store: Store, domain: Mapping[str, Any], plan_id: str,
                *, actor: str = "monetization-domain") -> str:
    if plan_id not in domain["plan_records"]:
        raise KeyError("unknown plan %r" % plan_id)
    endpoint = str(domain["plan_source_param"])
    rewire_endpoint(store, str(domain["plan_relation"]), endpoint,
                    node_id=str(domain["plan_records"][plan_id]), actor=actor)
    store.edit(str(domain["subscription_params"]["plan_id"]),
               ["body", "floor", "value"], plan_id, actor=actor)
    return endpoint


def set_plan_parameter(store: Store, domain: Mapping[str, Any], plan_id: str,
                       name: str, value: Any,
                       *, actor: str = "monetization-domain") -> str:
    if plan_id not in domain["plan_params"] or name not in domain["plan_params"][plan_id]:
        raise KeyError("unknown plan parameter %r.%r" % (plan_id, name))
    if name in _NUMERIC_PLAN_FIELDS:
        value = float(value)
        if value < 0 or (name == "seats" and value < 1):
            raise ValueError("plan %s has an invalid value" % name)
    elif name == "features":
        value = [str(item).strip() for item in value]
        if any(not item for item in value):
            raise ValueError("plan features must be non-empty")
    elif name == "byo_key":
        value = bool(value)
    elif name in ("id", "title"):
        value = str(value).strip()
        if not value:
            raise ValueError("plan %s must be non-empty" % name)
    node_id = str(domain["plan_params"][plan_id][name])
    store.edit(node_id, ["body", "floor", "value"], value, actor=actor)
    return node_id


def set_seats(store: Store, domain: Mapping[str, Any], seats: int,
              *, actor: str = "monetization-domain") -> str:
    seats = int(seats)
    if seats < 1:
        raise ValueError("seat count must be at least one")
    node_id = str(domain["subscription_params"]["seat_count"])
    store.edit(node_id, ["body", "floor", "value"], float(seats), actor=actor)
    return node_id


def set_usage(store: Store, domain: Mapping[str, Any], *, actor: str = "meter", **values):
    touched = []
    for name, value in values.items():
        if name not in ("tokens", "node_runs", "connector_calls", "credits"):
            raise KeyError("unknown usage meter %r" % name)
        value = float(value)
        if value < 0:
            raise ValueError("usage cannot be negative")
        node_id = str(domain["usage_params"][name])
        store.edit(node_id, ["body", "floor", "value"], value, actor=actor)
        touched.append(node_id)
    return touched


def set_billing_approval(store: Store, domain: Mapping[str, Any], approved: bool,
                         *, approver: str = "", approved_at: str = "",
                         actor: str = "founder") -> list[str]:
    if approved and (not approver.strip() or not approved_at.strip()):
        raise ValueError("approved billing requires approver and timestamp")
    values = {"approved": bool(approved), "approver": approver.strip(),
              "approved_at": approved_at.strip()}
    touched = []
    for name, value in values.items():
        node_id = str(domain["approval_params"][name])
        store.edit(node_id, ["body", "floor", "value"], value, actor=actor)
        touched.append(node_id)
    return touched


def set_billing_context(store: Store, domain: Mapping[str, Any], *,
                        idempotency_key: str, privacy_scope: str = "T1 INTERNAL",
                        actor: str = "founder") -> list[str]:
    key = str(idempotency_key).strip()
    scope = str(privacy_scope).strip()
    if not key:
        raise ValueError("billing requires a non-empty idempotency key")
    if not scope:
        raise ValueError("billing requires a privacy scope")
    key_id = str(domain["idempotency_params"]["key"])
    scope_id = str(domain["privacy_params"]["request_scope"])
    store.edit(key_id, ["body", "floor", "value"], key, actor=actor)
    store.edit(scope_id, ["body", "floor", "value"], scope, actor=actor)
    return [key_id, scope_id]


def apply_billing(store: Store, domain: Mapping[str, Any], sink: MutableMapping[Any, Any],
                  *, operation: str = "checkout", actor: str = "founder") -> dict[str, Any]:
    for gate_name in ("approval_gate", "idempotency_gate", "privacy_gate"):
        if not bool(store.pull(str(domain[gate_name]))):
            raise PermissionError("billing %s is closed" % gate_name.replace("_", " "))
    if operation not in domain["billing_effects"]:
        raise KeyError("unknown billing operation %r" % operation)
    effect = str(domain["billing_effects"][operation])
    target = store.pull(store.nodes[effect]["params"]["target"])
    change = store.pull(store.nodes[effect]["params"]["change"])
    if target in sink and sink[target] != change:
        raise ValueError("idempotency key collision for a different billing plan")
    store.apply_op({"op": "unfreeze", "id": effect, "actor": actor})
    try:
        store.edit(effect, ["body", "floor", "target"], target, actor=actor)
        return apply_effect(store, effect, sink, actor=actor)
    finally:
        store.apply_op({"op": "freeze", "id": effect, "actor": actor})


__all__ = [
    "AUTHORITY_WIRES", "DEFAULT_PLANS", "apply_billing",
    "build_monetization_domain", "select_plan", "set_billing_approval",
    "set_billing_context", "set_plan_parameter", "set_seats", "set_usage",
]
