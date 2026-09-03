"""Application trust-boundary courts for the unbound founder Agent Body."""
from __future__ import annotations

import time

import pytest

from nodelang.cell_authorization import AuthenticationBroker, AuthorizationDenied
from nodelang.cell_protocols import (
    prepare_append_relation_members,
    read_relation,
    rewire_incidence,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
    restore_universal_application,
    select_universal_root,
    set_universal_scope,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"e" * 32)
    return provider


def test_receipt_cannot_claim_an_older_authority_snapshot():
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=provider
    )
    receipt_root = registry.agent_body.body.creation_receipt_root
    snapshot = store.snapshot()
    replacements = []
    for suffix in (":revision", ":resolver-revision"):
        terminal = snapshot.cells[receipt_root + suffix]
        replacements.append(Cell(
            terminal.id,
            terminal.link0,
            terminal.link1,
            b"0",
        ))
    store.commit(store.revision, replace=replacements)
    with pytest.raises(InvalidCell, match="receipt"):
        restore_universal_application(
            resolve_map_path(), store, key_provider=provider
        )


def test_receipt_cannot_claim_an_older_authority_evaluation_time():
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=provider
    )
    receipt_root = registry.agent_body.body.creation_receipt_root
    snapshot = store.snapshot()
    replacements = []
    for suffix in (":evaluated-at", ":resolver-evaluated-at"):
        terminal = snapshot.cells[receipt_root + suffix]
        replacements.append(Cell(
            terminal.id,
            terminal.link0,
            terminal.link1,
            b"0.0",
        ))
    store.commit(store.revision, replace=replacements)
    with pytest.raises(InvalidCell, match="receipt"):
        restore_universal_application(
            resolve_map_path(), store, key_provider=provider
        )


@pytest.mark.parametrize("root_name", ("control", "body", "session"))
def test_restore_rejects_agent_region_disconnected_from_models_domain(
    root_name,
):
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=provider
    )
    domain_root = registry.map.domains["models"]
    root = {
        "control": registry.agent_body.control_root,
        "body": registry.agent_body.body.root_id,
        "session": registry.agent_body.session.root_id,
    }[root_name]
    member = next(
        member for member in read_relation(
            store.snapshot(), domain_root, budget=100_000
        )
        if member.role_id == registry.roles["member"]
        and member.participant_id == root
    )
    rewire_incidence(
        store,
        member.incidence_id,
        registry.authorization.subject_root,
    )
    with pytest.raises(InvalidCell, match="disconnected"):
        restore_universal_application(
            resolve_map_path(), store, key_provider=provider
        )


def test_restore_rejects_duplicate_agent_control_membership():
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=provider
    )
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot,
        registry.agent_body.control_root,
        ((registry.roles["member"], registry.agent_body.body.root_id),),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=patch.create,
        replace=patch.replace,
    )
    with pytest.raises(InvalidCell, match="control relation drifted"):
        restore_universal_application(
            resolve_map_path(), store, key_provider=provider
        )


def test_expired_context_cannot_cross_a_delayed_commit(monkeypatch):
    store = CellStore()
    broker = AuthenticationBroker()
    context = broker.mint_authenticated_context(
        "subject",
        tenant_root=None,
        assurance_root="assurance",
        lifetime_seconds=0.05,
    )
    commit = store.commit

    def delayed_commit(*args, **kwargs):
        time.sleep(0.10)
        return commit(*args, **kwargs)

    monkeypatch.setattr(store, "commit", delayed_commit)
    with pytest.raises(AuthorizationDenied, match="expired"):
        broker.commit_authenticated(
            context,
            store,
            store.revision,
            create=(Cell(
                "must-not-publish",
                NULL_CELL_ID,
                NULL_CELL_ID,
                b"denied",
            ),),
        )
    assert "must-not-publish" not in store.snapshot().cells


def test_agent_body_is_enterable_selectable_and_properties_driven():
    provider = _provider()
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=provider
    )
    set_universal_scope(store, registry, registry.map.domains["models"])
    scoped = project_universal_canvas(store, registry)
    visible = {node["id"] for node in scoped["nodes"]}
    assert {
        registry.agent_body.control_root,
        registry.agent_body.body.root_id,
        registry.agent_body.session.root_id,
    }.issubset(visible)
    select_universal_root(
        store,
        registry,
        registry.agent_body.body.root_id,
    )
    selected = project_universal_canvas(store, registry)
    assert selected["selected"] == registry.agent_body.body.root_id
    assert {row["label"] for row in selected["properties"]}.issuperset({
        "title",
        "color",
    })
