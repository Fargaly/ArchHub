from __future__ import annotations

import pytest

from nodelang import (KINDS, Store, relation_sources, relation_stages,
                      relation_targets, validate_store)
from nodelang.domains.monetization import (
    AUTHORITY_WIRES,
    apply_billing,
    build_monetization_domain,
    select_plan,
    set_billing_approval,
    set_billing_context,
    set_plan_parameter,
    set_seats,
    set_usage,
)


def test_monetization_is_one_open_table_with_grand_map_authority():
    store = Store()
    domain = build_monetization_domain(store)

    assert validate_store(store) is True
    assert set(node["kind"] for node in store.nodes.values()) <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    assert len(domain["authority_nodes"]) == 15
    assert set(domain["authority_nodes"]) == {
        source for wire in AUTHORITY_WIRES for source in wire
    }
    assert len(domain["authority_relations"]) == 19
    for authority_id, group_id in domain["authority_nodes"].items():
        node = store.nodes[group_id]
        assert node["kind"] == "group"
        assert store.open(group_id)
        assert store.pull(node["params"]["authority_id"]) == authority_id
        assert all(store.nodes[param_id]["kind"] == "param"
                   for param_id in node["params"].values())

    for name in ("checkout", "subscription", "invoice"):
        plan = domain["billing_plans"][name]
        assert store.nodes[plan["group"]]["kind"] == "group"
        assert plan["effect"] in store.open(plan["group"])
        assert store.nodes[plan["effect"]]["meta"]["frozen"] is True


def test_price_seat_and_credit_parameters_propagate_to_open_billing_plans():
    store = Store()
    domain = build_monetization_domain(store, selected_plan="firm", grace_percent=0)

    assert store.pull(domain["monthly_total"]) == 39.0
    assert store.pull(domain["credit_pool"]) == 5_000_000.0
    set_seats(store, domain, 7)
    assert store.pull(domain["extra_seats"]) == 2.0
    assert store.pull(domain["monthly_total"]) == 117.0
    assert store.pull(domain["credit_pool"]) == 35_000_000.0

    set_plan_parameter(store, domain, "firm", "monthly_price", 49)
    set_plan_parameter(store, domain, "firm", "seat_price", 25)
    set_plan_parameter(store, domain, "firm", "credits", 6_000_000)
    assert store.pull(domain["monthly_total"]) == 99.0
    assert store.pull(domain["credit_pool"]) == 42_000_000.0
    for name in ("checkout", "subscription", "invoice"):
        record = store.pull(domain["billing_plans"][name]["record"])
        assert record["plan_id"] == "firm"
        assert record["seats"] == 7.0
        assert record["amount"] == 99.0


def test_entitlements_and_metering_are_explicit_wired_parameter_graphs():
    store = Store()
    domain = build_monetization_domain(store, grace_percent=0)

    assert store.pull(domain["entitlement_value"])["plan_id"] == "free"
    assert store.pull(domain["byo_gate"]) is False
    endpoint = select_plan(store, domain, "pro", actor="founder")
    assert endpoint == domain["plan_source_param"]
    sources = relation_sources(store.nodes, store.nodes[domain["plan_relation"]])
    assert sources[0]["node_id"] == domain["plan_records"]["pro"]
    entitlements = store.pull(domain["entitlement_value"])
    assert entitlements["plan_id"] == "pro"
    assert entitlements["credits"] == 1_000_000.0
    assert store.pull(domain["byo_gate"]) is True

    set_usage(store, domain, tokens=900_000, credits=1_000_001)
    assert store.pull(domain["quota_gates"]["tokens"]) is True
    assert store.pull(domain["quota_gates"]["credits"]) is False
    assert store.pull(domain["quota_gate"]) == 0
    authority_relation = domain["authority_relations"][(
        "monetization_plan_catalog", "monetization_entitlements")]
    assert relation_sources(store.nodes, store.nodes[authority_relation])[0]["node_id"] == domain["catalog"]
    assert relation_targets(store.nodes, store.nodes[authority_relation])[0]["node_id"] == domain["entitlements"]
    assert validate_store(store) is True


def test_billing_is_frozen_guarded_and_idempotent():
    store = Store()
    domain = build_monetization_domain(store)
    sink = {}

    with pytest.raises(PermissionError, match="approval"):
        apply_billing(store, domain, sink)
    set_billing_approval(store, domain, True, approver="founder",
                         approved_at="2026-07-13T00:00:00Z")
    with pytest.raises(PermissionError, match="idempotency"):
        apply_billing(store, domain, sink)
    set_billing_context(store, domain, idempotency_key="upgrade-founder-0001")

    stages = relation_stages(store.nodes, store.nodes[domain["billing_relation"]])
    assert [(stage["role"], stage["mode"]) for stage in stages] == [
        ("approval", "guard"), ("idempotency", "guard"),
        ("privacy", "guard"), ("billing-plan", "map"),
    ]
    dry = store.pull(domain["billing_effect"])
    assert dry["fired"] is False and dry["dry_run"] is True
    first = apply_billing(store, domain, sink)
    second = apply_billing(store, domain, sink)
    assert first["fired"] is True and first["idempotent"] is False
    assert second["fired"] is False and second["idempotent"] is True
    assert len(sink) == 1
    assert store.nodes[domain["billing_effect"]]["meta"]["frozen"] is True

    set_billing_context(store, domain, idempotency_key="invoice-founder-0001")
    invoice = apply_billing(store, domain, sink, operation="invoice")
    assert invoice["fired"] is True
    assert store.nodes[domain["billing_effects"]["invoice"]]["meta"]["frozen"] is True
    history = [node["body"]["floor"]["entry"]["op"]
               for node in store.nodes.values() if node["kind"] == "history"]
    assert "effect_apply" in history and "unfreeze" in history and "freeze" in history
    assert validate_store(store) is True


def test_privacy_gate_blocks_external_billing_when_scope_changes():
    store = Store()
    domain = build_monetization_domain(store)
    set_billing_approval(store, domain, True, approver="founder",
                         approved_at="2026-07-13T00:00:00Z")
    set_billing_context(store, domain, idempotency_key="privacy-0001",
                        privacy_scope="T0 PUBLIC")
    assert store.pull(domain["privacy_gate"]) is False
    with pytest.raises(PermissionError, match="privacy"):
        apply_billing(store, domain, {})


@pytest.mark.parametrize("configuration", [
    {"api_key": "sk_live_not_allowed"},
    {"nested": {"password": "not-allowed"}},
    {"provider": "sk-probable-secret"},
    {"capability_ref": "https://example.invalid/credential"},
])
def test_raw_billing_secrets_are_rejected(configuration):
    with pytest.raises(ValueError, match="secret|op://"):
        build_monetization_domain(Store(), billing_configuration=configuration)


def test_only_external_secret_references_enter_the_graph():
    store = Store()
    domain = build_monetization_domain(store)
    secrets = [node for node in store.nodes.values() if node["kind"] == "secret_ref"]
    assert len(secrets) == 3
    assert all(node["body"]["floor"]["ref"].startswith("op://") for node in secrets)
    assert all("value" not in node["body"]["floor"] for node in secrets)
    dump = repr(store.dump()).casefold()
    assert "sk_live" not in dump and "whsec_" not in dump
    assert domain["billing_effect"] in store.open(domain["billing_plans"]["checkout"]["group"])
