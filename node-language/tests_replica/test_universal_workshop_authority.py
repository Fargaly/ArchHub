"""Migration court: Workshop is one Cell authority inside the application."""
from nodelang.cell_deliberation import (
    append_deliberation_entry,
    evaluate_deliberation_gate,
    list_deliberation_entries,
    read_deliberation_space,
)
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
import json

from nodelang.universal_application import (
    append_universal_workshop_entry,
    build_universal_application,
    create_universal_governed_work,
    project_universal_founder_attention_briefing,
    project_universal_founder_workshop_report,
    project_universal_canvas,
    restore_universal_application,
    set_universal_selection,
    set_universal_scope,
)
from nodelang.universal_cell import CellStore
from nodelang.universal_cell import Cell


def test_workshop_has_one_root_in_application_brain_and_restart(tmp_path):
    path = tmp_path / "application-workshop.sqlite3"
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    snapshot = store.snapshot()
    application_members = {
        item.participant_id for item in read_relation(
            snapshot, registry.application_root, budget=100_000
        ) if item.role_id == registry.roles["member"]
    }
    brain_root = registry.map.domains["brain"]
    brain_members = {
        item.participant_id for item in read_relation(
            snapshot, brain_root, budget=100_000
        ) if item.role_id == registry.roles["member"]
    }
    assert registry.workshop_root == "app:workshop"
    assert registry.deliberation_protocol.root_id in application_members
    assert registry.workshop_root in application_members
    assert registry.workshop_workbench_root in application_members
    assert registry.workshop_workbench_root in brain_members
    assert {
        registry.workshop_root,
        registry.brain_control_ledger_root,
        registry.governed_work_registry_root,
        registry.governed_work_claim_binding_protocol_root,
        registry.governed_work_claim_binding_registry_root,
    }.isdisjoint(brain_members)
    workbench_scopes = {
        item.participant_id for item in read_relation(
            snapshot, registry.workshop_workbench_root, budget=100_000
        ) if item.role_id == registry.roles["scope"]
    }
    assert registry.workshop_root in workbench_scopes
    assert registry.governed_work_registry_root in application_members
    assert registry.governed_work_registry_root in workbench_scopes
    assert registry.governed_work_registry_root not in brain_members
    work_authority = read_relation(
        snapshot, registry.governed_work_registry_root, budget=100_000
    )
    assert {
        item.participant_id for item in work_authority
        if item.role_id == registry.roles["authority"]
    } == {
        registry.standard_library.governed_domains.definitions[
            "governed-work"
        ].definition_root
    }
    workshop_wire = read_relation(
        snapshot, registry.workshop_work_wire_root, budget=32
    )
    assert {
        item.participant_id for item in workshop_wire
        if item.role_id == registry.roles["source"]
    } == {registry.workshop_root}
    assert {
        item.participant_id for item in workshop_wire
        if item.role_id == registry.roles["target"]
    } == {registry.governed_work_registry_root}
    workbench_members = read_relation(
        snapshot, registry.workshop_workbench_root, budget=100_000
    )
    assert {
        item.participant_id for item in workbench_members
        if item.role_id == registry.roles["scope"]
    } >= {
        registry.workshop_root,
        registry.governed_work_registry_root,
        registry.workshop_assignment_registry_root,
    }
    assert {
        item.participant_id for item in workbench_members
        if item.role_id == registry.roles["member"]
    } == {registry.work_completion_court_root}
    space = read_deliberation_space(
        snapshot, registry.deliberation_protocol, registry.workshop_root
    )
    assert space.policy_root == registry.authorization.policy_root
    assert space.action_root == registry.authorization.protocol.actions["create"]
    assert space.participant_roots == (registry.authorization.subject_root,)

    work_root, work_wire, _ = create_universal_governed_work(
        store,
        registry,
        title="Make Brain work Cell-native",
        description="Replace the active_work_v1 authority without projection.",
        priority=100,
        external_key="grand-map:brain-work-authority",
        references={"scope": brain_root},
        x=640,
        y=180,
    )
    registered_work = {
        item.participant_id for item in read_relation(
            store.snapshot(), registry.governed_work_registry_root,
            budget=100_000,
        ) if item.role_id == registry.roles["member"]
    }
    assert registered_work == {work_root}
    membership = read_relation(store.snapshot(), work_wire, budget=32)
    assert {
        item.participant_id for item in membership
        if item.role_id == registry.roles["source"]
    } == {registry.governed_work_registry_root}
    assert {
        item.participant_id for item in membership
        if item.role_id == registry.roles["target"]
    } == {work_root}

    entry = append_universal_workshop_entry(
        store,
        registry,
        actor_root=registry.authorization.subject_root,
        category_root=registry.workshop_category_roots["plan"],
        content="Migrate the Workshop authority before its transport.",
        reference_roots=(work_root,),
        idempotency_key="workshop-migration-plan:v1",
        created_at="2026-07-17T13:00:00+00:00",
    )
    assert evaluate_deliberation_gate(
        store.snapshot(),
        registry.deliberation_protocol,
        registry.workshop_root,
        phase_root=registry.workshop_phase_roots["claim"],
        reference_root=work_root,
    ).allowed
    coordination_before_research = evaluate_deliberation_gate(
        store.snapshot(),
        registry.deliberation_protocol,
        registry.workshop_root,
        phase_root=registry.workshop_phase_roots["coordinate"],
        reference_root=work_root,
    )
    assert coordination_before_research.allowed is False
    assert coordination_before_research.missing_category_roots == (
        registry.workshop_category_roots["research"],
    )
    assert coordination_before_research.missing_evidence_category_roots == (
        registry.workshop_category_roots["research"],
    )
    research_entry = append_universal_workshop_entry(
        store,
        registry,
        actor_root=registry.authorization.subject_root,
        category_root=registry.workshop_category_roots["research"],
        content="Record the source evidence for the Workshop migration plan.",
        reference_roots=(work_root,),
        evidence_roots=(registry.map.grand_map_root,),
        idempotency_key="workshop-migration-research:v1",
        created_at="2026-07-17T13:01:00+00:00",
    )
    assert evaluate_deliberation_gate(
        store.snapshot(),
        registry.deliberation_protocol,
        registry.workshop_root,
        phase_root=registry.workshop_phase_roots["coordinate"],
        reference_root=work_root,
    ).allowed
    work_projection = project_universal_canvas(store, registry)
    assert work_projection["selected"] == work_root
    interfaces = {
        item["name"]: item
        for item in work_projection["selected_assembly"]["interfaces"]
    }
    assert interfaces["title"]["value"] == "Make Brain work Cell-native"
    assert interfaces["description"]["value"].startswith("Replace the")
    assert interfaces["priority"]["value"] == "100"
    assert interfaces["external-key"]["value"] == (
        "grand-map:brain-work-authority"
    )
    assert interfaces["scope"]["target"] == brain_root

    set_universal_scope(store, registry, brain_root)
    projected = project_universal_canvas(store, registry)
    workbench_node = next(
        node for node in projected["nodes"]
        if node["id"] == registry.workshop_workbench_root
    )
    assert workbench_node["label"] == "Workshop Workbench"
    assert projected["scope"]["current"] == brain_root
    set_universal_scope(store, registry, registry.workshop_workbench_root)
    workbench_projection = project_universal_canvas(store, registry)
    assert workbench_projection["scope"]["current"] == (
        registry.workshop_workbench_root
    )
    assert {node["id"] for node in workbench_projection["nodes"]} >= {
        work_root,
        registry.work_completion_court_root,
        entry.root_id,
        research_entry.root_id,
        registry.map.grand_map_root,
    }
    assert {
        (wire["source"], wire["target"])
        for wire in workbench_projection["wires"]
    } >= {
        (work_root, entry.root_id),
        (work_root, research_entry.root_id),
        (research_entry.root_id, registry.map.grand_map_root),
    }
    store.close()

    reopened, restored = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    assert restored.workshop_root == registry.workshop_root
    assert restored.workshop_workbench_root == registry.workshop_workbench_root
    assert restored.governed_work_registry_root == (
        registry.governed_work_registry_root
    )
    restored_work = {
        item.participant_id for item in read_relation(
            reopened.snapshot(), restored.governed_work_registry_root,
            budget=100_000,
        ) if item.role_id == restored.roles["member"]
    }
    assert restored_work == {work_root}
    restored_brain_members = {
        item.participant_id for item in read_relation(
            reopened.snapshot(), restored.map.domains["brain"], budget=100_000
        ) if item.role_id == restored.roles["member"]
    }
    assert {
        restored.workshop_root,
        restored.brain_control_ledger_root,
        restored.governed_work_registry_root,
        restored.governed_work_claim_binding_protocol_root,
        restored.governed_work_claim_binding_registry_root,
    }.isdisjoint(restored_brain_members)
    set_universal_scope(reopened, restored, brain_root)
    restored_projection = project_universal_canvas(reopened, restored)
    restored_node = next(
        item for item in restored_projection["nodes"] if item["id"] == work_root
    )
    assert restored_node["label"] == "Make Brain work Cell-native"
    assert restored_node["assembly"]["operational"][
        "current_state_label"
    ] == "OPEN"
    entries = list_deliberation_entries(
        reopened.snapshot(),
        restored.deliberation_protocol,
        restored.workshop_root,
    )
    assert tuple(item.root_id for item in entries) == (
        entry.root_id,
        research_entry.root_id,
    )
    assert entries[0].content == "Migrate the Workshop authority before its transport."
    assert entries[1].category_root == restored.workshop_category_roots["research"]
    assert entries[1].evidence_roots == (restored.map.grand_map_root,)
    restored_workbench = read_relation(
        reopened.snapshot(), restored.workshop_workbench_root, budget=100_000
    )
    assert {
        item.participant_id for item in restored_workbench
        if item.role_id == restored.roles["member"]
    } >= {
        work_root,
        restored.work_completion_court_root,
        entry.root_id,
        research_entry.root_id,
        restored.map.grand_map_root,
    }
    reopened.close()


def test_founder_workshop_report_is_bounded_and_keeps_protected_entries_opaque(tmp_path):
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(tmp_path / "workshop-report.sqlite3"),
        key_provider=provider,
    )
    try:
        for index in range(9):
            if index == 1:
                content = "Review 50.TOOLING details before sharing."
            elif index == 8:
                content = r"Public report path C:\Users\founder\ArchHub\README.md"
            else:
                content = "Public Workshop entry %s." % index
            append_deliberation_entry(
                store,
                registry.deliberation_protocol,
                space_root=registry.workshop_root,
                actor_root=registry.authorization.subject_root,
                category_root=registry.workshop_category_roots["finding"],
                content=content,
                idempotency_key="founder-workshop-report:%s" % index,
                created_at="2026-07-20T12:%02d:00+00:00" % index,
                authorization_protocol=registry.authorization.protocol,
                authentication_broker=registry.authorization.broker,
                authentication_context=registry.authorization.session.context(),
            )

        report = project_universal_founder_workshop_report(store, registry)

        assert report["projection"] == "founder-local-workshop-report"
        assert report["count"] == 9
        assert report["protected"] == 1
        assert report["truncated"] is True
        assert [item["sequence"] for item in report["entries"]] == list(range(2, 10))
        assert report["entries"][0]["text"] == "[protected Workshop entry]"
        assert report["entries"][-1]["text"].endswith("[path]")
        encoded = str(report)
        assert "50.TOOLING" not in encoded
        assert "C:\\Users\\fargaly" not in encoded
        assert "actor_root" not in encoded
        assert "reference_roots" not in encoded
    finally:
        store.close()


def test_founder_attention_briefing_explains_focus_without_exporting_graph_identity(tmp_path):
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"a" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(tmp_path / "attention-briefing.sqlite3"),
        key_provider=provider,
    )
    try:
        set_universal_selection(
            store,
            registry,
            (registry.visible_roots[1],),
            focus_root=registry.visible_roots[1],
        )
        report = project_universal_founder_attention_briefing(store, registry)

        assert report["projection"] == "founder-local-attention-briefing"
        assert report["focus"] == {
            "active": True,
            "label": "Current ArchHub focus",
            "reasons": ["Direct user manipulation"],
        }
        assert report["open_obligations"] >= len(report["obligations"])
        assert report["blocked_obligations"] == 0
        assert len(report["obligations"]) == 3
        assert report["truncated"] is True
        assert all(set(item) == {"priority", "state", "label", "protected"}
                   for item in report["obligations"])
        encoded = json.dumps(report, sort_keys=True)
        assert "app:focus" not in encoded
        assert registry.authorization.session.root_id not in encoded
        assert registry.core_value_obligation_roots[0] not in encoded

        first_obligation = next(
            item for item in report["obligations"] if not item["protected"]
        )
        assert first_obligation["label"]
        obligation_root = registry.core_value_obligation_roots[0]
        obligation = next(
            item for item in read_relation(
                store.snapshot(), obligation_root, budget=100_000
            )
            if item.role_id == registry.attention_protocol.role("obligation-subject")
        )
        why = next(
            item for item in read_relation(
                store.snapshot(), obligation.participant_id, budget=64
            )
            if item.role_id == registry.core_values.roles["why"]
        )
        original = store.snapshot().cells[why.participant_id]
        store.commit(store.revision, replace=(Cell(
            original.id, original.link0, original.link1,
            b"app:focus:must-not-show",
        ),))
        protected_report = project_universal_founder_attention_briefing(
            store, registry
        )
        protected = [
            item for item in protected_report["obligations"] if item["protected"]
        ]
        assert protected
        assert all(
            item["label"] == "[protected attention detail]"
            for item in protected
        )
        assert "must-not-show" not in json.dumps(protected_report, sort_keys=True)
    finally:
        store.close()
