"""Forcing court for the closed, catalogue-only agent composer."""
import inspect

import pytest

from nodelang.cell_adapters import (
    bootstrap_adapter_protocol,
    build_adapter_catalog,
)
from nodelang.cell_catalog import verify_released_catalog
from nodelang.cell_composer import (
    authorize_composer_command,
    bootstrap_composer_protocol,
    build_composer_authority,
    verify_composer_authority,
)
from nodelang.cell_protocols import read_relation
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.cell_catalog import bootstrap_assembly_protocol
from nodelang.universal_cell import Cell, CellStore, InvalidCell


@pytest.fixture()
def governed():
    store = CellStore()
    assembly = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, assembly)
    adapters = bootstrap_adapter_protocol(store)
    adapter_catalog = build_adapter_catalog(store, adapters)
    composer = bootstrap_composer_protocol(store)
    authority = build_composer_authority(
        store, composer, assembly, library.catalog_root,
        adapters, adapter_catalog,
    )
    return store, assembly, library, adapters, adapter_catalog, composer, authority


def test_authority_and_catalogue_are_released_graphs(governed):
    store, assembly, library, adapters, adapter_catalog, composer, authority = governed
    snapshot = store.snapshot()
    catalogue = verify_released_catalog(
        snapshot, assembly, library.catalog_root
    )
    projected = verify_composer_authority(
        snapshot, composer, assembly, adapters, authority.root_id
    )
    assert projected.catalogue_root == catalogue.root_id
    assert projected.adapter_catalogue_root == adapter_catalog
    assert snapshot.cells[projected.actor_root].atom == b"agent composer"
    assert projected.limits["max-instances"] == 256
    assert composer.command("catalog.propose") not in projected.allowed_command_roots


def test_only_released_catalogue_definitions_can_be_instantiated(governed):
    store, assembly, library, adapters, _, composer, authority = governed
    admitted = library.definition_roots[0]
    authorize_composer_command(
        store.snapshot(), composer, assembly, adapters, authority.root_id,
        "catalog.instantiate",
        definition_root=admitted,
        resource_usage={"max-instances": (0, 1)},
    )
    with pytest.raises(InvalidCell, match="outside the released catalogue"):
        authorize_composer_command(
            store.snapshot(), composer, assembly, adapters, authority.root_id,
            "catalog.instantiate",
            definition_root=composer.root_id,
        )


def test_unknown_raw_commands_and_extension_are_denied(governed):
    store, assembly, _, adapters, _, composer, authority = governed
    for command in ("floor.create", "cell.create", "workflow.dump"):
        with pytest.raises(InvalidCell, match="closed grammar"):
            authorize_composer_command(
                store.snapshot(), composer, assembly, adapters, authority.root_id, command
            )
    with pytest.raises(InvalidCell, match="denies command"):
        authorize_composer_command(
            store.snapshot(), composer, assembly, adapters, authority.root_id,
            "catalog.propose",
        )


def test_resource_budgets_fail_before_composition(governed):
    store, assembly, library, adapters, _, composer, authority = governed
    with pytest.raises(InvalidCell, match="max-instances"):
        authorize_composer_command(
            store.snapshot(), composer, assembly, adapters, authority.root_id,
            "catalog.instantiate",
            definition_root=library.definition_roots[0],
            resource_usage={"max-instances": (256, 1)},
        )
    with pytest.raises(InvalidCell, match="undeclared resource"):
        authorize_composer_command(
            store.snapshot(), composer, assembly, adapters, authority.root_id,
            "catalog.connect",
            resource_usage={"surprise-budget": (0, 1)},
        )


def test_authority_and_catalogue_drift_are_detected(governed):
    store, assembly, library, adapters, _, composer, authority = governed
    policy = verify_composer_authority(
        store.snapshot(), composer, assembly, adapters, authority.root_id
    )
    limit_root = next(
        member.participant_id
        for member in read_relation(store.snapshot(), authority.root_id)
        if member.role_id == composer.role("limit")
    )
    limit_value = next(
        member.participant_id
        for member in read_relation(store.snapshot(), limit_root)
        if member.role_id == composer.role("limit-value")
    )
    old = store.read(limit_value)
    store.commit(store.revision, replace=(
        Cell(old.id, old.link0, old.link1, b"999999"),
    ))
    with pytest.raises(InvalidCell, match="authority has drifted"):
        verify_composer_authority(
            store.snapshot(), composer, assembly, adapters, authority.root_id
        )

    # Restore the exact policy value, then prove catalogue membership is also
    # checked on every authorization rather than trusted from startup.
    store.commit(store.revision, replace=(old,))
    assert verify_composer_authority(
        store.snapshot(), composer, assembly, adapters, authority.root_id
    ) == policy
    catalog_member = next(
        member
        for member in read_relation(store.snapshot(), library.catalog_root)
        if member.role_id == assembly.role("catalog-member")
    )
    incidence = store.read(catalog_member.incidence_id)
    store.commit(store.revision, replace=(Cell(
        incidence.id, incidence.link0, composer.root_id, incidence.atom
    ),))
    with pytest.raises(InvalidCell):
        authorize_composer_command(
            store.snapshot(), composer, assembly, adapters, authority.root_id,
            "catalog.connect",
        )


def test_gate_has_no_standard_assembly_name_dispatch():
    source = inspect.getsource(authorize_composer_command).lower()
    for forbidden in ('"watcher"', '"ordered list"', '"session"', '"database"'):
        assert forbidden not in source
