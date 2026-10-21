"""Court for the generic graph-held exclusive-ownership assembly."""
import pytest

from nodelang.cell_exclusive_ownership import (
    acquire_ownership,
    bootstrap_ownership_protocol,
    project_ownership_protocol,
    read_ownership,
    transition_ownership,
    verify_ownership_authority,
)
from nodelang.cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_members,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _world():
    store = CellStore()
    protocol = bootstrap_ownership_protocol(store, prefix="test:ownership")
    roots = (
        Cell("resource", NULL_CELL_ID, NULL_CELL_ID, b"resource"),
        Cell("holder-a", NULL_CELL_ID, NULL_CELL_ID, b"holder-a"),
        Cell("holder-b", NULL_CELL_ID, NULL_CELL_ID, b"holder-b"),
        Cell("evidence", NULL_CELL_ID, NULL_CELL_ID, b"evidence"),
    )
    store.commit(store.revision, create=roots)
    return store, protocol


def test_ownership_is_a_persistent_cell_graph_not_a_side_record(tmp_path):
    path = tmp_path / "ownership.sqlite3"
    store = CellStore(path)
    protocol = bootstrap_ownership_protocol(store, prefix="test:ownership")
    store.commit(store.revision, create=(
        Cell("resource", NULL_CELL_ID, NULL_CELL_ID, b"resource"),
        Cell("holder-a", NULL_CELL_ID, NULL_CELL_ID, b"holder"),
        Cell("evidence", NULL_CELL_ID, NULL_CELL_ID, b"court"),
    ))
    acquired, _ = acquire_ownership(
        store,
        protocol,
        resource_root="resource",
        holder_root="holder-a",
        evidence_root="evidence",
        ownership_root="ownership-a",
    )
    assert acquired.generation == 1
    assert acquired.state_root == protocol.states["active"]
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())
    store.close()

    reopened = CellStore(path)
    projected = project_ownership_protocol(
        reopened.snapshot(), prefix="test:ownership"
    )
    assert read_ownership(
        reopened.snapshot(), projected, "ownership-a"
    ) == acquired
    reopened.close()


def test_only_one_live_owner_exists_and_generations_form_a_chain():
    store, protocol = _world()
    first, _ = acquire_ownership(
        store,
        protocol,
        resource_root="resource",
        holder_root="holder-a",
        evidence_root="evidence",
        ownership_root="ownership-a",
    )
    with pytest.raises(InvalidCell, match="already has a live owner"):
        acquire_ownership(
            store,
            protocol,
            resource_root="resource",
            holder_root="holder-b",
            evidence_root="evidence",
        )
    draining, _ = transition_ownership(
        store, protocol, first.root_id, event="drain", evidence_root="evidence"
    )
    assert draining.state_root == protocol.states["draining"]
    released, _ = transition_ownership(
        store,
        protocol,
        first.root_id,
        event="release",
        evidence_root="evidence",
    )
    assert released.state_root == protocol.states["released"]
    assert len(released.transition_roots) == 2
    second, _ = acquire_ownership(
        store,
        protocol,
        resource_root="resource",
        holder_root="holder-b",
        evidence_root="evidence",
        ownership_root="ownership-b",
    )
    assert second.generation == 2
    assert second.predecessor_root == first.root_id
    assert len(verify_ownership_authority(store.snapshot(), protocol)) == 2


def test_release_requires_visible_drain_and_failure_is_recorded():
    store, protocol = _world()
    first, _ = acquire_ownership(
        store,
        protocol,
        resource_root="resource",
        holder_root="holder-a",
        evidence_root="evidence",
    )
    with pytest.raises(InvalidCell, match="source state"):
        transition_ownership(
            store,
            protocol,
            first.root_id,
            event="release",
            evidence_root="evidence",
        )
    failed, _ = transition_ownership(
        store,
        protocol,
        first.root_id,
        event="fail-active",
        evidence_root="evidence",
    )
    assert failed.state_root == protocol.states["failed"]
    assert len(failed.transition_roots) == 1
    replacement, _ = acquire_ownership(
        store,
        protocol,
        resource_root="resource",
        holder_root="holder-b",
        evidence_root="evidence",
    )
    assert replacement.generation == 2


def test_authority_rejects_a_forged_second_live_generation():
    store, protocol = _world()
    first, _ = acquire_ownership(
        store,
        protocol,
        resource_root="resource",
        holder_root="holder-a",
        evidence_root="evidence",
        ownership_root="ownership-a",
    )
    transition_ownership(
        store, protocol, first.root_id, event="drain", evidence_root="evidence"
    )
    snapshot = store.snapshot()
    generation = Cell("forged:generation", NULL_CELL_ID, NULL_CELL_ID, b"2")
    acquired = Cell("forged:acquired", NULL_CELL_ID, NULL_CELL_ID, b"1.0")
    relation = compose_relation_cells((
        (protocol.role("resource"), "resource"),
        (protocol.role("holder"), "holder-b"),
        (protocol.role("generation"), generation.id),
        (protocol.role("state"), protocol.states["active"]),
        (protocol.role("acquired-at"), acquired.id),
        (protocol.role("predecessor"), first.root_id),
        (protocol.role("evidence"), "evidence"),
    ), relation_id="forged")
    patch = prepare_append_relation_members(
        snapshot,
        protocol.root_id,
        ((protocol.role("ownership-member"), "forged"),),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(generation, acquired, *relation.cells, *patch.create),
        replace=patch.replace,
    )
    with pytest.raises(InvalidCell, match="multiple live owners"):
        verify_ownership_authority(store.snapshot(), protocol)


def test_authority_rejects_a_state_flip_without_transition_history():
    store, protocol = _world()
    acquired, _ = acquire_ownership(
        store,
        protocol,
        resource_root="resource",
        holder_root="holder-a",
        evidence_root="evidence",
    )
    snapshot = store.snapshot()
    incidence = snapshot.cells[acquired.state_incidence]
    store.commit(
        snapshot.revision,
        replace=(Cell(
            incidence.id,
            incidence.link0,
            protocol.states["released"],
            incidence.atom,
        ),),
    )
    with pytest.raises(InvalidCell, match="lacks transition history"):
        verify_ownership_authority(store.snapshot(), protocol)
