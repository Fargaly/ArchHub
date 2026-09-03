from __future__ import annotations

from nodelang import KINDS, NO_VALUE, Store, relation_sources, validate_store
from nodelang.core import relation_stages
from nodelang.domains.cockpit import (
    build_cockpit_domain,
    cockpit_write_preview,
    rewire_dispatch,
    set_founder_evidence,
    submit_cockpit_command,
)


def _domain(*, verified=False):
    store = Store()
    users = store.add("group", "Users source", inner=[
        store.add("value", "User count", floor={"op": "value", "value": 4})
    ])
    metrics = store.add("group", "Metrics source", inner=[
        store.add("value", "MRR", floor={"op": "value", "value": 1200})
    ])
    selfext = store.add("group", "Self-extension source", inner=[
        store.add("value", "Proposal state", floor={"op": "value", "value": "idle"})
    ])
    domain = build_cockpit_domain(
        store,
        identity_verified=verified,
        source_nodes={"users": users, "metrics": metrics},
        self_extension_node=selfext,
    )
    return store, domain


def test_cockpit_is_one_open_super_node_with_explicit_operational_relations():
    store, domain = _domain()

    assert validate_store(store) is True
    assert set(node["kind"] for node in store.nodes.values()) <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    for key in (
        "surface", "founder_gate", "redactor", "router", "read_tools",
        "user_view", "live_metrics", "write_preview", "purge",
        "kill_switches", "withheld", "audit", "agent_loop",
    ):
        assert store.nodes[domain[key]]["kind"] == "group"
    assert domain["direct_agent_relation"] in store.nodes[domain["agent_loop"]]["body"]["inner"]
    assert all(store.nodes[relation]["kind"] == "wire" for relation in domain["relations"])
    assert set(domain["source_relations"]) == {"users", "metrics"}
    assert all(store.nodes[node_id]["kind"] == "param"
               for params in domain["route_params"].values()
               for node_id in params.values())


def test_keyword_router_is_visible_deterministic_and_uses_editable_keywords():
    store, domain = _domain()

    submitted = submit_cockpit_command(store, domain, "show live revenue metrics")
    assert submitted == {
        "route": "read", "redacted": False, "value": "show live revenue metrics"
    }
    # Declaration order intentionally resolves a tie: "show" matches read and
    # "metrics" matches metrics, so the first visible candidate wins.
    assert store.pull(domain["route_scores"]["read"]) == 1
    assert store.pull(domain["route_scores"]["metrics"]) == 1

    read_keyword = domain["route_params"]["read"]["keyword:000"]
    store.edit(read_keyword, ["body", "floor", "value"], "unrelated", actor="founder")
    submit_cockpit_command(store, domain, "revenue metrics")
    assert store.pull(domain["selected_route"]) == "metrics"
    assert validate_store(store) is True


def test_secret_shaped_command_is_withheld_before_it_enters_the_command_node():
    store, domain = _domain()
    raw = "change api_key=THIS-MUST-NOT-LAND-IN-THE-GRAPH"

    result = submit_cockpit_command(store, domain, raw)

    assert result["redacted"] is True
    assert result["value"] == "[REDACTED BY COCKPIT POLICY]"
    assert store.pull(domain["command"]) == "[REDACTED BY COCKPIT POLICY]"
    assert store.pull(domain["redacted"]) is True
    assert raw not in repr(store.nodes)
    assert store.pull(domain["audit_params"]["last_event"])["redacted"] is True


def test_write_and_destructive_paths_are_founder_gated_and_frozen_by_default():
    store, domain = _domain(verified=False)
    submit_cockpit_command(store, domain, "write deployment state")
    params = domain["write_params"]
    store.edit(params["target"], ["body", "floor", "value"], "deployment.enabled")
    store.edit(params["change"], ["body", "floor", "value"], {"enabled": True})
    store.edit(params["approved"], ["body", "floor", "value"], True)
    store.edit(params["approver"], ["body", "floor", "value"], "founder")

    assert store.pull(domain["founder_verdict"]) == 0
    assert cockpit_write_preview(store, domain) is NO_VALUE
    assert store.nodes[domain["write_effect"]]["meta"]["frozen"] is True
    assert store.nodes[domain["purge_effect"]]["meta"]["frozen"] is True
    assert store.nodes[domain["kill_effect"]]["meta"]["frozen"] is True

    set_founder_evidence(store, domain, verified=True)
    preview = cockpit_write_preview(store, domain)
    assert preview["fired"] is False
    assert preview["dry_run"] is True
    assert preview["plan"] == {
        "target": "deployment.enabled", "change": {"enabled": True}
    }
    assert validate_store(store) is True


def test_dispatch_relation_is_a_rewirable_node_with_visible_guard_stage():
    store, domain = _domain()
    relation = domain["dispatch_relations"]["read"]
    original = relation_sources(store.nodes, store.nodes[relation])[0]["node_id"]
    assert original == domain["selected_route"]
    assert [(item["mode"], item["node_id"])
            for item in relation_stages(store.nodes, store.nodes[relation])] == [
        ("guard", domain["route_scores"]["read"])
    ]

    replacement = store.add("value", "Manual route", floor={"op": "value", "value": "read"})
    rewire_dispatch(store, domain, "read", replacement)
    assert relation_sources(store.nodes, store.nodes[relation])[0]["node_id"] == replacement
    assert validate_store(store) is True


def test_cockpit_actions_append_audit_history_in_the_same_table():
    store, domain = _domain()
    before = len([node for node in store.nodes.values() if node["kind"] == "history"])

    submit_cockpit_command(store, domain, "check system status", submitted_at="2026-07-12T20:00:00Z")

    after = [node for node in store.nodes.values() if node["kind"] == "history"]
    assert len(after) > before
    assert store.pull(domain["audit_params"]["sequence"]) == 1
    assert store.pull(domain["audit_params"]["last_event"])["event"] == "command_submitted"
    assert any(node["body"]["floor"]["entry"].get("actor") == "cockpit-boundary"
               for node in after)
