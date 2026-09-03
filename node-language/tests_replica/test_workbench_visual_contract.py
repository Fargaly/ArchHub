"""Acceptance court for real interface-backed wires inside the Workbench."""
from __future__ import annotations

import nodelang.universal_application as universal_application_module
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_protocols import read_relation
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    append_universal_workshop_entry,
    build_universal_application,
    create_universal_governed_work,
    project_universal_canvas,
    restore_universal_application,
    set_universal_scope,
)
from nodelang.universal_cell import Cell, CellStore


def _application(tmp_path):
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    return build_universal_application(
        resolve_map_path(),
        CellStore(tmp_path / "workbench-visual-contract.sqlite3"),
        key_provider=provider,
    )


def test_workbench_wires_have_real_selectable_interface_endpoints(tmp_path):
    """No nested composition may draw a centre-to-centre relation line."""
    store, registry = _application(tmp_path)
    try:
        brain_root = registry.map.domains["brain"]
        work_root, _membership, _revision = create_universal_governed_work(
            store,
            registry,
            title="Prove Workbench sockets",
            description="Every visible workshop wire needs real endpoints.",
            priority=100,
            external_key="court:workbench-interface-endpoints",
            references={"scope": brain_root},
            x=640,
            y=180,
        )
        plan = append_universal_workshop_entry(
            store,
            registry,
            actor_root=registry.authorization.subject_root,
            category_root=registry.workshop_category_roots["plan"],
            content="Define the visual wire contract before implementation.",
            reference_roots=(work_root,),
            idempotency_key="court:workbench-interface:plan",
            created_at="2026-07-21T10:00:00+00:00",
        )
        research = append_universal_workshop_entry(
            store,
            registry,
            actor_root=registry.authorization.subject_root,
            category_root=registry.workshop_category_roots["research"],
            content="Verify the existing exact-interface mechanism.",
            reference_roots=(work_root,),
            evidence_roots=(registry.map.grand_map_root,),
            idempotency_key="court:workbench-interface:research",
            created_at="2026-07-21T10:01:00+00:00",
        )

        snapshot = store.snapshot()
        view = registry.view_sessions[registry.authorization.subject_root]
        visibility_members = read_relation(
            snapshot, view.visibility_root, budget=100_000
        )
        assigned = {
            member.participant_id
            for member in visibility_members
            if member.role_id == registry.roles["visible"]
        }
        indexed_interfaces = {
            member.participant_id
            for member in visibility_members
            if member.role_id == registry.assembly_protocol.role("interface")
        }
        for relation_root in (
            member.participant_id
            for member in read_relation(
                snapshot, registry.workshop_workbench_root, budget=100_000
            )
            if member.role_id == registry.roles["relation"]
        ):
            for member in read_relation(snapshot, relation_root, budget=256):
                if member.role_id not in {
                    registry.roles["source"], registry.roles["target"],
                }:
                    continue
                interface = universal_application_module._project_canvas_interface(
                    snapshot, registry.assembly_protocol, member.participant_id
                )
                if interface is not None and interface["owner"] in assigned:
                    assert member.participant_id in indexed_interfaces

        set_universal_scope(store, registry, brain_root)
        set_universal_scope(store, registry, registry.workshop_workbench_root)
        projection = project_universal_canvas(store, registry)

        expected = {
            (work_root, plan.root_id),
            (work_root, research.root_id),
            (research.root_id, registry.map.grand_map_root),
        }
        observed = {
            (wire["source"], wire["target"])
            for wire in projection["wires"]
        }
        assert expected <= observed

        ports = {
            (node["id"], port["id"]): port
            for node in projection["nodes"]
            for port in node["ports"]
        }
        for wire in projection["wires"]:
            assert wire["source_interface"]
            assert wire["target_interface"]
            source_port = ports[(wire["source"], wire["source_interface"])]
            target_port = ports[(wire["target"], wire["target_interface"])]
            assert wire["source_incidence"] in source_port["endpoint_incidences"]
            assert wire["target_incidence"] in target_port["endpoint_incidences"]
            assert wire["id"] in source_port["relation_roots"]
            assert wire["id"] in target_port["relation_roots"]
    finally:
        store.close()


def test_restore_upgrades_legacy_workbench_endpoints_without_losing_wires(
    tmp_path,
):
    """Previously saved direct endpoints become interfaces during restore."""
    path = tmp_path / "legacy-workbench.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    brain_root = registry.map.domains["brain"]
    work_root, _membership, _revision = create_universal_governed_work(
        store,
        registry,
        title="Restore legacy Workbench sockets",
        description="Saved direct endpoints must not survive a restore.",
        priority=100,
        external_key="court:legacy-workbench-interface-endpoints",
        references={"scope": brain_root},
        x=640,
        y=180,
    )
    append_universal_workshop_entry(
        store,
        registry,
        actor_root=registry.authorization.subject_root,
        category_root=registry.workshop_category_roots["plan"],
        content="Create a legacy shape for the restore court.",
        reference_roots=(work_root,),
        idempotency_key="court:legacy-workbench:plan",
        created_at="2026-07-21T10:00:00+00:00",
    )

    snapshot = store.snapshot()
    legacy_replacements = []
    workbench_members = read_relation(
        snapshot, registry.workshop_workbench_root, budget=100_000
    )
    for relation_root in (
        member.participant_id for member in workbench_members
        if member.role_id == registry.roles["relation"]
    ):
        for member in read_relation(snapshot, relation_root, budget=256):
            if member.role_id not in {
                registry.roles["source"], registry.roles["target"],
            }:
                continue
            interface = universal_application_module._project_canvas_interface(
                snapshot, registry.assembly_protocol, member.participant_id
            )
            if interface is None:
                continue
            incidence = snapshot.cells[member.incidence_id]
            legacy_replacements.append(Cell(
                incidence.id,
                incidence.link0,
                str(interface["owner"]),
                incidence.atom,
            ))
    assert legacy_replacements
    store.commit(snapshot.revision, replace=tuple(legacy_replacements))
    store.close()

    reopened, restored = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    try:
        set_universal_scope(reopened, restored, restored.map.domains["brain"])
        set_universal_scope(
            reopened, restored, restored.workshop_workbench_root
        )
        projection = project_universal_canvas(reopened, restored)
        assert projection["wires"]
        assert all(
            wire["source_interface"] and wire["target_interface"]
            for wire in projection["wires"]
        )
    finally:
        reopened.close()
