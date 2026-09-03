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

# Which applications ArchHub reaches and which documents it reads is a
# product boundary, not legacy behavior -- so the fact lives here, in the
# module whose whole job is publishing it, and the legacy bridge imports
# it from here. It sat inside cell_legacy_core_nodes, which made this
# module the one normal-runtime importer of a legacy interpreter and kept
# the floor court red.
HOST_FAMILIES = (
    "revit",
    "autocad",
    "blender",
    "rhino",
    "max",
    "speckle",
    "outlook",
)
DOC_FAMILIES = (
    "revit",
    "dwg",
    "ifc",
    "blender",
    "3dm",
    "max",
    "csv",
    "pdf",
)


def host_operation(family: str) -> str:
    """The single name a host family's dispatch is registered under."""
    return "host.%s.dispatch" % family


def document_operation(family: str) -> str:
    """The single name a document family's read is registered under."""
    return "document.%s.read" % family


@dataclass(frozen=True, slots=True)
class CleanHostBoundaries:
    hosts: tuple[str, ...]
    documents: tuple[str, ...]
    operations: dict[str, str]


def compose_host_boundaries() -> CleanHostBoundaries:
    """The boundary catalogue, from the declared fact.

    This used to bootstrap three protocols into a scratch store and build
    the whole legacy provider authority just to read back names declared
    right here. The bridge court holds that the providers the legacy
    build registers match these families and these operation names, so
    building them again proved nothing the court does not already.
    """
    return CleanHostBoundaries(
        tuple(sorted(HOST_FAMILIES)),
        tuple(sorted(DOC_FAMILIES)),
        {family: host_operation(family) for family in sorted(HOST_FAMILIES)},
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
