from __future__ import annotations

import pytest

from nodelang import KINDS, Store, relation_sources, relation_stages, relation_targets
from nodelang.core import validate_store
from nodelang.domains.selfext import (
    apply_installation,
    apply_rollback,
    build_self_extension_domain,
    set_court_evidence,
    set_install_approval,
    set_proposal_parameter,
    set_rollback_approval,
)


def _pairs(store: Store) -> set[tuple[str, str]]:
    pairs = set()
    for node in store.nodes.values():
        if node["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, node):
            for target in relation_targets(store.nodes, node):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def _green_court(store: Store, domain: dict) -> None:
    values = {
        "impossible_state_passed": True,
        "confidence": 0.99,
        "spec_tests_passed": True,
        "tail_coverage": 1.0,
        "independent_judge": True,
        "juror_diversity": 0.75,
        "evidence_present": True,
        "evidence_refs": ["court://run/001"],
    }
    for name, value in values.items():
        set_court_evidence(store, domain, name, value)


def test_self_extension_is_one_table_open_groups_and_generic_nodes():
    store = Store()
    domain = build_self_extension_domain(store)

    assert validate_store(store) is True
    assert set(node["kind"] for node in store.nodes.values()) <= KINDS
    assert store.nodes[domain["session"]]["kind"] == "session"
    assert store.nodes[domain["proposal"]]["kind"] == "proposal"
    assert store.nodes[domain["proposal"]]["meta"]["frozen"] is True
    for name in (
        "requirements", "library", "generated", "evidence", "court",
        "approval", "installation", "rollback_approval", "rollback",
    ):
        assert store.nodes[domain[name]]["kind"] == "group"
        assert store.open(domain[name])
    assert store.nodes[domain["install_effect"]]["meta"]["frozen"] is True
    assert store.nodes[domain["rollback_effect"]]["meta"]["frozen"] is True
    assert not any(
        node["body"].get("floor", {}).get("op") in {
            "install_plugin", "self_extend", "register_plugin"
        }
        for node in store.nodes.values()
    )


def test_proposal_and_evidence_parameter_edits_recook_visible_gates():
    store = Store()
    domain = build_self_extension_domain(store)

    touched = set_proposal_parameter(
        store, domain, "intent", "Build a geometry transformer", actor="founder"
    )
    assert touched == domain["proposal_params"]["intent"]
    assert store.pull(domain["proposal_record"])["intent"] == (
        "Build a geometry transformer"
    )
    assert store.nodes[domain["proposal"]]["meta"]["frozen"] is True
    assert store.pull(domain["court_verdict"]) == 0

    _green_court(store, domain)
    assert store.pull(domain["court_verdict"]) == 1
    set_court_evidence(store, domain, "confidence", 0.2)
    assert store.pull(domain["court_gates"]["confidence"]) is False
    assert store.pull(domain["court_verdict"]) == 0
    assert validate_store(store) is True


def test_unapproved_or_red_install_is_blocked_and_proposal_stays_inert():
    store = Store()
    domain = build_self_extension_domain(store)
    sink = {}

    assert store.pull(domain["install_result"]) == []
    with pytest.raises(PermissionError, match="approval"):
        apply_installation(store, domain, sink)
    assert sink == {}

    set_install_approval(
        store, domain, True, approver="founder", approved_at="2026-07-12T12:00:00Z"
    )
    assert store.pull(domain["approval_gate"]) == 1
    with pytest.raises(PermissionError, match="court"):
        apply_installation(store, domain, sink)
    assert sink == {}
    assert store.nodes[domain["install_effect"]]["meta"]["frozen"] is True


def test_lifecycle_and_effect_gates_are_explicit_relation_nodes():
    store = Store()
    domain = build_self_extension_domain(store)
    pairs = _pairs(store)

    assert (domain["proposal"], domain["requirements"]) in pairs
    assert (domain["requirements"], domain["library"]) in pairs
    assert (domain["library"], domain["generated"]) in pairs
    assert (domain["generated"], domain["evidence"]) in pairs
    assert (domain["evidence"], domain["court"]) in pairs
    assert (domain["installation"], domain["rollback"]) in pairs

    install_stages = relation_stages(
        store.nodes, store.nodes[domain["install_relation"]]
    )
    assert [(stage["mode"], stage["node_id"]) for stage in install_stages] == [
        ("guard", domain["approval_gate"]),
        ("guard", domain["court_verdict"]),
        ("map", domain["installation"]),
    ]
    rollback_stages = relation_stages(
        store.nodes, store.nodes[domain["rollback_relation"]]
    )
    assert [(stage["mode"], stage["node_id"]) for stage in rollback_stages] == [
        ("guard", domain["rollback_gate"]),
        ("guard", domain["court_verdict"]),
        ("map", domain["rollback"]),
    ]
    assert validate_store(store) is True


def test_green_approved_install_has_audited_reversible_plan():
    store = Store()
    baseline = {"version": "before"}
    domain = build_self_extension_domain(store, baseline=baseline)
    target = store.pull(store.nodes[domain["installation"]]["params"]["target"])
    sink = {target: baseline}

    _green_court(store, domain)
    set_install_approval(
        store, domain, True, approver="founder", approved_at="2026-07-12T12:00:00Z"
    )
    dry_result = store.pull(domain["install_result"])
    assert dry_result[0]["fired"] is False
    assert dry_result[0]["dry_run"] is True

    installed = apply_installation(store, domain, sink, actor="founder")
    assert installed["fired"] is True
    assert sink[target]["action"] == "attach_subgraph"
    assert store.pull(domain["installed"]) is True
    assert store.nodes[domain["install_effect"]]["meta"]["frozen"] is True

    with pytest.raises(PermissionError, match="rollback approval"):
        apply_rollback(store, domain, sink)
    set_rollback_approval(
        store, domain, True, approver="founder", approved_at="2026-07-12T12:05:00Z"
    )
    rolled_back = apply_rollback(store, domain, sink, actor="founder")
    assert rolled_back["fired"] is True
    assert sink[target] == {
        "action": "restore_baseline",
        "subgraph": domain["generated"],
        "baseline": baseline,
    }
    assert store.pull(domain["installed"]) is False
    assert store.nodes[domain["rollback_effect"]]["meta"]["frozen"] is True
    history_ops = [
        node["body"]["floor"]["entry"]["op"]
        for node in store.nodes.values()
        if node["kind"] == "history"
    ]
    assert history_ops.count("effect_apply") == 2
    assert "unfreeze" in history_ops and "freeze" in history_ops
    assert validate_store(store) is True
