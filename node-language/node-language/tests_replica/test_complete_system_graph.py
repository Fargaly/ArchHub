"""System court for ArchHub as one connected node-native super-node."""
from __future__ import annotations

import json

from nodelang.application import build_archhub_application
from nodelang.core import relation_sources, relation_targets, validate_store
from nodelang import map_import


def _pairs(store):
    pairs = set()
    for relation in store.nodes.values():
        if relation["kind"] != "wire":
            continue
        for source in relation_sources(store.nodes, relation):
            for target in relation_targets(store.nodes, relation):
                pairs.add((source["node_id"], target["node_id"]))
    return pairs


def test_application_super_node_owns_every_integrated_domain_and_surface():
    store, reg = build_archhub_application()
    inner = set(store.nodes[reg["app"]]["body"]["inner"])
    sessions = {
        reg["grand"]["session"], reg["brain"], reg["governance"]["session"],
        reg["cde"], reg["models"]["session"], reg["connectors"]["session"],
        reg["orchestration"]["session"], reg["selfext"]["session"],
        reg["monetization"]["session"], reg["users"]["session"],
        reg["cloud"]["session"], reg["community"]["session"],
        reg["cloud_runtime"]["session"],
        reg["publication"]["session"],
        reg["resources"]["session"],
        reg["cockpit_domain"]["session"], reg["website"]["session"],
        reg["canvas_session"],
    }
    assert sessions <= inner
    assert reg["ui_root"] in inner
    assert validate_store(store) is True


def test_required_cross_domain_connections_are_authoritative_relations():
    store, reg = build_archhub_application()
    pairs = _pairs(store)
    task = reg["orchestration"]["task_order"][0]
    expected = {
        (reg["users"]["session"], reg["monetization"]["entitlements"]),
        (reg["cloud"]["session"], reg["cloud_runtime"]["session"]),
        (reg["publication"]["record"], reg["brain"]),
        (reg["publication"]["record"], reg["website"]["session"]),
        (reg["users"]["session"], reg["cloud"]["services"]["cloud_auth"]["service"]),
        (reg["users"]["session"], reg["community"]["community"]),
        (reg["community"]["session"], reg["brain"]),
        (reg["monetization"]["billing"],
         reg["cloud"]["services"]["cloud_billing"]["service"]),
        (reg["cloud"]["services"]["cloud_brain_replica"]["service"],
         reg["community"]["federation"]),
        (reg["selfext"]["proposal_record"], reg["orchestration"]["tasks"][task]),
        (reg["cockpit_domain"]["founder_verdict"],
         reg["orchestration"]["governance_groups"][task]),
        (reg["website"]["route_pages"]["/website/community"]["page"],
         reg["community"]["community"]),
        (reg["cockpit_domain"]["surface"], reg["cockpit"]),
        (reg["cockpit_domain"]["founder_verdict"],
         reg["resources"]["resources"]["governance-standard"]["authority_signal"]),
        (reg["resources"]["resources"]["brain-daemon"]["adapter"], reg["brain"]),
        (reg["resources"]["resources"]["identity-database"]["adapter"],
         reg["users"]["session"]),
        (reg["resources"]["resources"]["website-publication"]["adapter"],
         reg["website"]["session"]),
    }
    assert expected <= pairs


def test_every_external_effect_is_frozen_and_legacy_runtime_is_absent():
    store, _reg = build_archhub_application()
    effects = []
    for node in store.nodes.values():
        floor = node["body"].get("floor", {})
        if floor.get("op") == "effect" or (
            floor.get("op") == "mcp" and floor.get("effectful")
        ):
            effects.append(node)
    assert effects
    assert all(node["meta"].get("frozen") is True for node in effects)
    serialized = json.dumps(store.dump(), sort_keys=True, default=str)
    assert "12.PRODUCTION" not in serialized


def test_clean_public_runtime_contains_no_founder_machine_or_private_authority_paths(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(map_import, "AUTHORITY_CONFIG", tmp_path / "absent.json")
    monkeypatch.delenv(map_import.AUTHORITY_ENV, raising=False)
    store, _reg = build_archhub_application()
    serialized = json.dumps(store.dump(), sort_keys=True, default=str)
    assert "C:\\\\Users\\\\" not in serialized
    assert "30.KNOWLEDGE" not in serialized
