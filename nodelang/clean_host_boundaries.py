"""Publish the host and document boundaries into the clean graph.

ArchHub reaches seven hosts and eight document formats -- Revit,
AutoCAD, Rhino, 3ds Max, Blender, Speckle, Outlook; dwg, ifc, 3dm, csv,
pdf and their model files. The boundaries for all of them were already
written and were never installed anywhere, so the clean runtime knew of
no host at all: the canvas could draw a building and had no way to say
anything to the application that holds it.

Nothing here talks to a host. It publishes the BOUNDARY each host is
reached through, as cells, so a later effect has somewhere signed to
land instead of a direct call from whatever code felt like making one.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_adapters import bootstrap_adapter_protocol
from .cell_connector_execution import (
    bootstrap_baboom_connector_execution_protocol,
)
from .cell_legacy_core_nodes import (
    DOC_FAMILIES,
    HOST_FAMILIES,
    build_legacy_core_node_authority,
)
from .cell_model_execution import bootstrap_baboom_model_execution_protocol
from .universal_cell import CellStore


@dataclass(frozen=True, slots=True)
class CleanHostBoundaries:
    hosts: tuple[str, ...]
    documents: tuple[str, ...]
    operations: dict[str, str]


def compose_host_boundaries() -> CleanHostBoundaries:
    """Read every boundary without writing to any real graph."""
    scratch = CellStore()
    adapters = bootstrap_adapter_protocol(scratch)
    connectors = bootstrap_baboom_connector_execution_protocol(scratch)
    models = bootstrap_baboom_model_execution_protocol(scratch)
    authority = build_legacy_core_node_authority(
        scratch, adapters, connectors, models
    )
    return CleanHostBoundaries(
        tuple(sorted(authority.host_providers)),
        tuple(sorted(authority.document_providers)),
        {
            family: provider.operation
            for family, provider in sorted(authority.host_providers.items())
        },
    )


HOST_BOUNDARY_DEFINITION = "Host Boundary Catalogue"


def install_host_boundaries(
    authority,
    *,
    caller,
    command_id: str,
) -> str:
    """Declare the boundaries as graph state, or revise them when they drift.

    They land as one definition carrying every host and document family,
    so the set of applications ArchHub can reach is a fact the graph
    holds and a revision changes -- not a tuple in a module that only a
    deploy can move.
    """
    from .cell_protocols import read_relation
    from .unified_authority import (
        COMMAND_BUDGET,
        declare_definition,
        read_definition,
        revise_definition,
    )

    composed = compose_host_boundaries()
    carried = {
        "hosts": list(composed.hosts),
        "documents": list(composed.documents),
        "operations": dict(composed.operations),
    }
    snapshot = authority.store.snapshot()
    existing = None
    for member in read_relation(
        snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
    ):
        if member.role_id != authority.role("definition"):
            continue
        projection = read_definition(
            authority, member.participant_id, caller=caller
        )
        if projection.name == HOST_BOUNDARY_DEFINITION:
            existing = projection
            break
    if existing is None:
        return declare_definition(
            authority,
            HOST_BOUNDARY_DEFINITION,
            caller=caller,
            command_id=command_id,
            presentation=carried,
        ).root_id
    if dict(existing.contracts["presentation"]) == carried:
        return existing.root_id
    revise_definition(
        authority,
        existing.root_id,
        existing.name,
        caller=caller,
        command_id=command_id,
        version=existing.version,
        defaults=dict(existing.contracts["defaults"]),
        parameters=dict(existing.contracts["parameters"]),
        interfaces=dict(existing.contracts["interfaces"]),
        rules=dict(existing.contracts["rules"]),
        presentation=carried,
        courts=dict(existing.contracts["courts"]),
        provenance=dict(existing.contracts["provenance"]),
    )
    return existing.root_id


def read_host_boundaries(authority, *, caller):
    """The boundaries the graph holds, or None when it holds none."""
    from .cell_protocols import read_relation
    from .unified_authority import COMMAND_BUDGET, read_definition

    snapshot = authority.store.snapshot()
    for member in read_relation(
        snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
    ):
        if member.role_id != authority.role("definition"):
            continue
        projection = read_definition(
            authority, member.participant_id, caller=caller
        )
        if projection.name == HOST_BOUNDARY_DEFINITION:
            return dict(projection.contracts["presentation"])
    return None


__all__ = [
    "CleanHostBoundaries",
    "HOST_BOUNDARY_DEFINITION",
    "install_host_boundaries",
    "read_host_boundaries",
    "DOC_FAMILIES",
    "HOST_FAMILIES",
    "compose_host_boundaries",
]
