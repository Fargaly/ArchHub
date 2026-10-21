"""Forcing court for graph-authoritative reusable assemblies."""
import inspect

import pytest

from nodelang.cell_catalog import (
    bootstrap_assembly_protocol,
    build_catalog,
    build_definition,
    build_interface,
    build_role_obligation,
    catalog_verification_scope,
    compose_catalog_instance,
    instantiate_catalog_definition,
    open_instance,
    project_catalog,
    read_definition,
    release_definition,
    verify_released_definition,
    verify_released_catalog,
    verify_released_catalog_stable,
)
from nodelang.cell_protocols import read_relation
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _add_terminals(store, *names):
    cells = [
        Cell("fixture:" + name, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii"))
        for name in names
    ]
    store.commit(store.revision, create=cells)
    return {name: "fixture:" + name for name in names}


def _released_definition(store, protocol, *, definition_id="definition:counter"):
    roots = _add_terminals(
        store, "body", "state", "status", "error", "evidence", "contract",
    )
    interface = build_interface(
        store,
        protocol,
        interface_id=definition_id + ":interface",
        target_root=roots["body"],
        contract_root=roots["contract"],
    )
    obligations = tuple(
        build_role_obligation(
            store,
            protocol,
            obligation_id=definition_id + ":obligation:" + role_name,
            required_role=protocol.role(role_name),
        ).root_id
        for role_name in ("status", "error")
    )
    parts = (
        roots["body"],
        roots["state"],
        roots["status"],
        roots["error"],
        *interface.part_roots,
    )
    built = build_definition(
        store,
        protocol,
        definition_id=definition_id,
        name="Counter",
        version="1.0.0",
        part_roots=parts,
        interface_roots=(interface.root_id,),
        state_roots=(roots["state"],),
        status_roots=(roots["status"],),
        error_roots=(roots["error"],),
        evidence_roots=(roots["evidence"],),
        obligation_roots=obligations,
        shared_roots=(roots["contract"],),
    )
    digest = release_definition(store, protocol, definition_id)
    return built, roots, interface, digest


@pytest.fixture()
def released():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    built, roots, interface, digest = _released_definition(store, protocol)
    catalog = build_catalog(store, protocol, (built.root_id,))
    return store, protocol, built, roots, interface, digest, catalog


def test_protocol_and_definition_are_cells_not_kernel_kinds(released):
    store, protocol, built, _, _, _, catalog = released
    assert set(Cell.__dataclass_fields__) == {"id", "link0", "link1", "atom"}
    assert protocol.root_id in store.snapshot().cells
    assert built.root_id in store.snapshot().cells
    assert catalog in store.snapshot().cells
    assert project_catalog(store.snapshot(), protocol, catalog) == ({
        "id": built.root_id,
        "name": "Counter",
        "version": "1.0.0",
        "interfaces": 1,
        "parts": 8,
    },)


def test_release_verification_cache_is_request_scoped_and_revision_bound(released):
    store, protocol, built, _, _, _, catalog = released
    before = store.snapshot()
    with catalog_verification_scope():
        definition = verify_released_definition(
            before, protocol, built.root_id
        )
        assert verify_released_definition(
            before, protocol, built.root_id
        ) is definition
        verified_catalog = verify_released_catalog(before, protocol, catalog)
        assert verify_released_catalog(before, protocol, catalog) is verified_catalog

        name = before.cells[built.name_root]
        store.commit(before.revision, replace=(Cell(
            name.id, name.link0, name.link1, b"Tampered name"
        ),))
        with pytest.raises(InvalidCell, match="definition has drifted"):
            verify_released_definition(
                store.snapshot(), protocol, built.root_id
            )


def test_stable_catalog_proof_ignores_unrelated_commits_and_rejects_dependency_drift(
    released,
):
    store, protocol, built, _, _, _, catalog_root = released
    first = verify_released_catalog_stable(
        store, store.snapshot(), protocol, catalog_root
    )
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(Cell(
        "court:catalog:unrelated",
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"unrelated",
    ),))
    assert verify_released_catalog_stable(
        store, store.snapshot(), protocol, catalog_root
    ) is first

    snapshot = store.snapshot()
    name = snapshot.cells[built.name_root]
    store.commit(snapshot.revision, replace=(Cell(
        name.id, name.link0, name.link1, b"Tampered name"
    ),))
    with pytest.raises(InvalidCell, match="definition has drifted"):
        verify_released_catalog_stable(
            store, store.snapshot(), protocol, catalog_root
        )
    assert store.listener_failures() == ()


def test_release_requires_status_error_and_operational_evidence():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    roots = _add_terminals(store, "body", "contract")
    interface = build_interface(
        store,
        protocol,
        interface_id="incomplete:interface",
        target_root=roots["body"],
        contract_root=roots["contract"],
    )
    obligation = build_role_obligation(
        store,
        protocol,
        obligation_id="incomplete:obligation:status",
        required_role=protocol.role("status"),
    )
    build_definition(
        store,
        protocol,
        definition_id="incomplete",
        name="Incomplete",
        version="0.0.1",
        part_roots=(roots["body"], *interface.part_roots),
        interface_roots=(interface.root_id,),
        obligation_roots=(obligation.root_id,),
        shared_roots=(roots["contract"],),
    )
    with pytest.raises(InvalidCell, match="operational evidence"):
        release_definition(store, protocol, "incomplete")

    evidence = Cell(
        "incomplete:evidence", NULL_CELL_ID, NULL_CELL_ID, b"court"
    )
    store.commit(store.revision, create=(evidence,))
    # Evidence cannot be appended after the definition is built without an
    # explicit manifest edit. A second definition proves the graph obligation.
    build_definition(
        store,
        protocol,
        definition_id="missing-status",
        name="Missing status",
        version="0.0.1",
        part_roots=(roots["body"], *interface.part_roots),
        interface_roots=(interface.root_id,),
        evidence_roots=(evidence.id,),
        obligation_roots=(obligation.root_id,),
        shared_roots=(roots["contract"],),
    )
    with pytest.raises(InvalidCell, match="requires 1 status"):
        release_definition(store, protocol, "missing-status")


def test_undeclared_cross_boundary_reference_is_rejected():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    roots = _add_terminals(
        store, "outside", "status", "error", "evidence", "contract",
    )
    body = Cell("bad:body", roots["outside"], NULL_CELL_ID, b"")
    store.commit(store.revision, create=(body,))
    interface = build_interface(
        store,
        protocol,
        interface_id="bad:interface",
        target_root=body.id,
        contract_root=roots["contract"],
    )
    build_definition(
        store,
        protocol,
        definition_id="bad",
        name="Bad",
        version="1.0.0",
        part_roots=(
            body.id, roots["status"], roots["error"], *interface.part_roots,
        ),
        interface_roots=(interface.root_id,),
        status_roots=(roots["status"],),
        error_roots=(roots["error"],),
        evidence_roots=(roots["evidence"],),
        shared_roots=(roots["contract"],),
    )
    with pytest.raises(InvalidCell, match="undeclared boundary"):
        release_definition(store, protocol, "bad")


def test_generic_instantiator_clones_declared_region_and_maps_every_cell(released):
    store, protocol, built, _, _, _, catalog = released
    before = store.revision
    instance = instantiate_catalog_definition(
        store, protocol, catalog, built.root_id
    )
    assert store.revision == before + 1
    definition = read_definition(store.snapshot(), protocol, built.root_id)
    assert set(instance.cell_map) == set(definition.part_roots)
    snapshot = store.snapshot()
    for old_id, new_id in instance.cell_map.items():
        old = snapshot.cells[old_id]
        new = snapshot.cells[new_id]
        assert new.atom == old.atom
        assert new.link0 == instance.cell_map.get(old.link0, old.link0)
        assert new.link1 == instance.cell_map.get(old.link1, old.link1)

    instance_members = read_relation(snapshot, instance.root_id, budget=100_000)
    mapping_roots = [
        member.participant_id for member in instance_members
        if member.role_id == protocol.role("mapping")
    ]
    assert len(mapping_roots) == len(definition.part_roots)
    assert set(instance.cell_map.values()).issubset(
        open_instance(snapshot, protocol, instance.root_id)
    )


def test_instance_can_be_composed_inside_a_caller_owned_atomic_commit(released):
    store, protocol, built, _, _, _, catalog = released
    before = store.snapshot()
    composed = compose_catalog_instance(
        before, protocol, catalog, built.root_id, token="atomic"
    )
    assert store.revision == before.revision
    marker = Cell(
        "caller-owned-marker", NULL_CELL_ID, NULL_CELL_ID, b"same commit"
    )
    store.commit(before.revision, create=(*composed.cells, marker))
    assert composed.instance.root_id in store.snapshot().cells
    assert marker.id in store.snapshot().cells
    assert store.revision == before.revision + 1


def test_instance_state_is_isolated_but_declared_contract_stays_shared(released):
    store, protocol, built, roots, _, _, catalog = released
    first = instantiate_catalog_definition(store, protocol, catalog, built.root_id)
    second = instantiate_catalog_definition(store, protocol, catalog, built.root_id)
    first_state = first.cell_map[roots["state"]]
    second_state = second.cell_map[roots["state"]]
    assert first_state != second_state
    first_cell = store.read(first_state)
    store.commit(store.revision, replace=(
        Cell(first_cell.id, first_cell.link0, first_cell.link1, b"changed"),
    ))
    assert store.read(first_state).atom == b"changed"
    assert store.read(second_state).atom == b"state"
    first_contract_links = [
        cell for cell in first.cell_map.values()
        if store.read(cell).link1 == roots["contract"]
    ]
    assert first_contract_links


def test_released_definition_drift_blocks_new_instances(released):
    store, protocol, built, roots, _, _, catalog = released
    body = store.read(roots["body"])
    store.commit(store.revision, replace=(
        Cell(body.id, body.link0, body.link1, b"drift"),
    ))
    with pytest.raises(InvalidCell, match="has drifted"):
        verify_released_definition(store.snapshot(), protocol, built.root_id)
    with pytest.raises(InvalidCell, match="has drifted"):
        instantiate_catalog_definition(store, protocol, catalog, built.root_id)


def test_catalogue_membership_is_released_and_drift_detected(released):
    store, protocol, built, _, _, _, catalog = released
    projected = verify_released_catalog(store.snapshot(), protocol, catalog)
    assert projected.definition_roots == (built.root_id,)
    member = next(
        item for item in read_relation(store.snapshot(), catalog)
        if item.role_id == protocol.role("catalog-member")
    )
    incidence = store.read(member.incidence_id)
    store.commit(store.revision, replace=(Cell(
        incidence.id, incidence.link0, protocol.root_id, incidence.atom
    ),))
    with pytest.raises(InvalidCell):
        verify_released_catalog(store.snapshot(), protocol, catalog)


def test_direct_definition_recursion_is_rejected():
    store = CellStore()
    protocol = bootstrap_assembly_protocol(store)
    roots = _add_terminals(
        store, "body", "status", "error", "evidence", "contract",
    )
    interface = build_interface(
        store,
        protocol,
        interface_id="recursive:interface",
        target_root=roots["body"],
        contract_root=roots["contract"],
    )
    build_definition(
        store,
        protocol,
        definition_id="recursive",
        name="Recursive",
        version="1.0.0",
        part_roots=(
            roots["body"], roots["status"], roots["error"],
            *interface.part_roots,
        ),
        interface_roots=(interface.root_id,),
        status_roots=(roots["status"],),
        error_roots=(roots["error"],),
        evidence_roots=(roots["evidence"],),
        shared_roots=(roots["contract"],),
        dependency_roots=("recursive",),
    )
    with pytest.raises(InvalidCell, match="recursive"):
        release_definition(store, protocol, "recursive")


def test_instantiator_has_no_catalogue_name_dispatch():
    source = inspect.getsource(instantiate_catalog_definition).lower()
    for forbidden in (
        '"watcher"', '"list"', '"logic"', '"data-store"', '"ai-session"',
    ):
        assert forbidden not in source
