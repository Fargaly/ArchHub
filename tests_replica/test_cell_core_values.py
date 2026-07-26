"""Core Values are a governed graph authority, not executable prose."""
from types import MappingProxyType

import pytest

from nodelang.cell_core_values import (
    CORE_VALUE_KEYS,
    ControlCoverage,
    build_value_traced_decision,
    compose_core_values_authority,
    project_core_values_authority,
    read_value_traced_decision,
    validate_core_values_authority,
)
from nodelang.cell_protocols import CellBatch, inspect_properties, read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell
from nodelang.universal_map_import import PropertyRef


def _fixture():
    store = CellStore()
    roles = {
        name: "test:role:%s" % name
        for name in (
            "owner", "value", "label", "member", "scope", "source",
            "target", "why", "property", "authority",
        )
    }
    controls = {
        key: "test:control:%s" % key
        for key in CORE_VALUE_KEYS
    }
    actor = "test:actor:founder"
    subject = "test:subject:application"
    wip = "test:lifecycle:wip"
    store.commit(store.revision, create=tuple(
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)
        for root, atom in (
            *((root, name.encode("ascii")) for name, root in roles.items()),
            *((root, key.encode("ascii")) for key, root in controls.items()),
            (actor, b"Founder"),
            (subject, b"ArchHub application"),
            (wip, b"WIP"),
        )
    ))
    batch = CellBatch(store)
    labels = {}
    root_properties = {}

    def add_property(owner_root, namespace, key, value):
        label_root = labels.get(key)
        if label_root is None:
            label_root = "test:label:%s" % key.replace(" ", "-")
            batch.add(Cell(
                label_root, NULL_CELL_ID, NULL_CELL_ID, key.encode("utf-8")
            ))
            labels[key] = label_root
        token = "%s:%s" % (namespace, key.replace(" ", "-"))
        value_root = "test:value:%s:%s" % (owner_root, token)
        relation_root = "test:property:%s:%s" % (owner_root, token)
        atom = str(value).encode("utf-8")
        batch.add(Cell(value_root, NULL_CELL_ID, NULL_CELL_ID, atom))
        batch.relation([
            (roles["owner"], owner_root),
            (roles["value"], value_root),
            (roles["label"], label_root),
        ], relation_id=relation_root)
        root_properties.setdefault(owner_root, []).append(relation_root)
        return PropertyRef(relation_root, value_root, label_root)

    coverage = {
        key: ControlCoverage(
            control_roots=(controls[key],),
            gap_descriptions=(
                ("remaining external proof for %s" % key,)
                if key in {"security", "respect-time", "architect-review"}
                else ()
            ),
        )
        for key in CORE_VALUE_KEYS
    }
    authority = compose_core_values_authority(
        batch,
        roles,
        add_property,
        coverage,
        wip_state_root=wip,
        actor_root=actor,
    )
    batch.commit()
    return (
        store, MappingProxyType(roles), controls, actor, subject, wip,
        authority, root_properties,
    )


def test_constitution_is_one_openable_nested_cell_graph():
    store, roles, _controls, _actor, _subject, _wip, authority, _props = _fixture()
    snapshot = store.snapshot()
    root_members = read_relation(snapshot, authority.root_id, budget=64)
    root_children = {
        member.participant_id for member in root_members
        if member.role_id == roles["member"]
    }
    assert root_children == {
        authority.source_root,
        authority.anchor_root,
        authority.systems_root,
        authority.pillars_root,
        authority.control_map_root,
        authority.conflicts_root,
        authority.adoption_decision_root,
    }
    assert len(authority.system_roots) == 4
    assert len(authority.pillar_roots) == 3
    assert set(authority.value_roots) == set(CORE_VALUE_KEYS)
    assert len(authority.value_roots) == 10
    assert all(type(cell) is Cell for cell in snapshot.cells.values())


def test_source_and_archhub_translation_are_distinct_digest_bound_nodes():
    store, _roles, _controls, _actor, _subject, wip, authority, _props = _fixture()
    snapshot = store.snapshot()
    assert authority.source_digest != authority.translation_digest
    assert snapshot.cells[authority.source_digest_root].atom.decode("ascii") == (
        authority.source_digest
    )
    assert snapshot.cells[authority.translation_digest_root].atom.decode("ascii") == (
        authority.translation_digest
    )
    decision = read_value_traced_decision(
        snapshot, authority, authority.adoption_decision_root
    )
    assert decision.status_root == wip
    assert "WIP" in snapshot.cells[decision.recommendation_root].atom.decode("utf-8")
    assert validate_core_values_authority(snapshot, authority) is True


def test_control_coverage_cannot_render_partial_as_green():
    store, _roles, controls, _actor, _subject, _wip, authority, _props = _fixture()
    restored = project_core_values_authority(store.snapshot(), _roles)
    assert restored.coverage["truth"].status == "covered"
    assert restored.coverage["security"].status == "partial"
    assert restored.coverage["respect-time"].status == "partial"
    assert restored.coverage["architect-review"].status == "partial"
    assert restored.coverage["security"].control_roots == (controls["security"],)
    assert restored.coverage["security"].gap_roots


def test_all_visible_constitution_properties_are_first_class_relations():
    store, roles, _controls, _actor, _subject, _wip, authority, props = _fixture()
    selected = authority.value_roots["security"]
    rows = inspect_properties(
        store.snapshot(),
        selected_root=selected,
        relation_roots=props[selected],
        owner_role=roles["owner"],
        value_role=roles["value"],
        label_role=roles["label"],
        budget=32,
    )
    labels = {
        store.read(row.label_root).atom.decode("utf-8") for row in rows
    }
    assert {"title", "pillar", "enforcement", "applies_to", "translation"} <= labels


def test_hard_gate_decision_requires_evidence_and_high_risk_reviewer():
    store, _roles, _controls, actor, subject, wip, authority, _props = _fixture()
    with pytest.raises(InvalidCell, match="evidence"):
        build_value_traced_decision(
            store,
            authority,
            decision_id="test:decision:no-evidence",
            actor_root=actor,
            subject_root=subject,
            system_keys=("identity-trust",),
            value_keys=("security",),
            recommendation="deny unverified access",
            evidence_roots=(),
            risk="medium",
            status_root=wip,
        )
    evidence = "test:evidence:security-court"
    store.commit(store.revision, create=(
        Cell(evidence, NULL_CELL_ID, NULL_CELL_ID, b"court attestation"),
    ))
    with pytest.raises(InvalidCell, match="reviewer"):
        build_value_traced_decision(
            store,
            authority,
            decision_id="test:decision:no-reviewer",
            actor_root=actor,
            subject_root=subject,
            system_keys=("identity-trust",),
            value_keys=("security",),
            recommendation="replace released identity policy",
            evidence_roots=(evidence,),
            risk="high",
            status_root=wip,
        )


def test_value_traced_decision_derives_pillars_and_round_trips():
    store, _roles, _controls, actor, subject, wip, authority, _props = _fixture()
    evidence = "test:evidence:browser-court"
    reviewer = "test:reviewer:architect"
    store.commit(store.revision, create=(
        Cell(evidence, NULL_CELL_ID, NULL_CELL_ID, b"browser court"),
        Cell(reviewer, NULL_CELL_ID, NULL_CELL_ID, b"Architect"),
    ))
    root = build_value_traced_decision(
        store,
        authority,
        decision_id="test:decision:ship-ui",
        actor_root=actor,
        subject_root=subject,
        system_keys=("operational-orchestration",),
        value_keys=("respect-time", "test-ship", "simplicity"),
        recommendation="publish only after visual and performance courts",
        evidence_roots=(evidence,),
        risk="high",
        status_root=wip,
        reviewer_root=reviewer,
    )
    projected = read_value_traced_decision(store.snapshot(), authority, root)
    assert projected.system_roots == (
        authority.system_roots["operational-orchestration"],
    )
    assert set(projected.value_roots) == {
        authority.value_roots["respect-time"],
        authority.value_roots["test-ship"],
        authority.value_roots["simplicity"],
    }
    assert set(projected.pillar_roots) == {
        authority.pillar_roots["amanah"],
        authority.pillar_roots["shura"],
        authority.pillar_roots["tajdid"],
    }
    assert projected.reviewer_root == reviewer
    assert projected.evidence_roots == (evidence,)
