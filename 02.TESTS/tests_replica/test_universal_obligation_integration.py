"""Courts unifying Core Value gaps with persistent graph obligations."""
from __future__ import annotations

from nodelang.cell_attention import (
    list_obligations,
    verify_attention_policy,
)
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
    provision_universal_view_session,
    restore_universal_application,
    set_universal_selection,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"o" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"p" * 32)
    return provider


def test_every_core_value_gap_is_the_subject_of_one_open_obligation():
    store, registry = build_universal_application(resolve_map_path())
    snapshot = store.snapshot()
    gap_roots = {
        gap
        for coverage in registry.core_values.coverage.values()
        for gap in coverage.gap_roots
    }
    obligations = {
        item.root_id: item
        for item in list_obligations(snapshot, registry.attention_protocol)
    }
    integrated = {
        root: obligations[root] for root in registry.core_value_obligation_roots
    }

    assert {item.subject_root for item in integrated.values()} == gap_roots
    assert len(integrated) == len(gap_roots)
    assert all(
        item.state_root == registry.attention_protocol.state("open")
        for item in integrated.values()
    )
    assert all(
        item.owner_root == registry.authorization.subject_root
        and item.reviewer_root == registry.authorization.subject_root
        and item.policy_root == registry.attention_policy_root
        and len(item.dependency_roots) == 1
        and item.required_evidence_roots == (
            "app:obligation-evidence:verified-control-and-review",
        )
        for item in integrated.values()
    )

    policy = verify_attention_policy(
        snapshot,
        registry.attention_protocol,
        registry.attention_policy_root,
    )
    assert policy.class_roots == tuple(
        registry.attention_priority_roots.values()
    )
    application_members = {
        member.participant_id for member in read_relation(
            snapshot, registry.application_root, budget=100_000
        )
    }
    assert set(registry.core_value_obligation_roots) <= application_members


def test_founder_can_see_and_inspect_obligations_but_member_cannot_infer_them():
    store, registry = build_universal_application(resolve_map_path())
    founder = project_universal_canvas(store, registry)
    assert {
        item["root"] for item in founder["obligations"]
    } == set(registry.core_value_obligation_roots)

    obligation = founder["obligations"][0]
    set_universal_selection(
        store, registry, (), focus_root=obligation["root"]
    )
    inspected = project_universal_canvas(store, registry)
    assert inspected["selected"] == obligation["root"]
    assert inspected["selected_title"] == obligation["label"]
    assert {
        item["role"] for item in inspected["connections"]
    } >= {"obligation-subject", "obligation-state", "obligation-priority"}

    member_root = "test:obligation:member"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Obligation member"),
    ))
    provision_universal_view_session(
        store,
        registry,
        member_root,
        visible_roots=(registry.visible_roots[0],),
    )
    authority = registry.authorization
    context = authority.broker.mint_authenticated_context(
        member_root,
        principal_roots=(authority.member_principal_root,),
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=120,
    )
    member_projection = project_universal_canvas(
        store, registry, authentication_context=context
    )
    assert member_projection["obligations"] == []


def test_obligation_identities_and_release_survive_restart_without_rebuild(
    tmp_path,
):
    path = tmp_path / "persistent-obligations.sqlite3"
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    expected = registry.core_value_obligation_roots
    expected_revision = store.revision
    store.close()

    reopened, restored = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=provider
    )
    assert reopened.revision == expected_revision
    assert restored.core_value_obligation_roots == expected
    assert {
        item["root"] for item in project_universal_canvas(
            reopened, restored
        )["obligations"]
    } == set(expected)
