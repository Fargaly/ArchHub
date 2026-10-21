"""Source-built standard assemblies admitted above the universal-cell floor.

This module builds catalogue content; it does not add runtime dispatch. The
catalogue remains a graph relation and instances are created by the one generic
instantiator in ``cell_catalog``.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_catalog import (
    AssemblyProtocol,
    build_catalog,
    build_definition,
    build_interface,
    build_role_obligation,
    release_definition,
)
from .cell_protocols import CellBatch
from .cell_lifecycle import (
    LifecycleProtocol,
    bootstrap_lifecycle_protocol,
    build_versioned_asset_definition,
)
from .cell_domain_catalog import (
    GovernedDomainLibrary,
    build_governed_domain_library,
)
from .cell_reactions import (
    ReactionProtocol,
    bootstrap_reaction_protocol,
    build_reaction_manifest,
)
from .cell_state_machine import (
    StateMachineProtocol,
    bootstrap_state_machine_protocol,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore


@dataclass(frozen=True, slots=True)
class StandardLibraryBuild:
    catalog_root: str
    definition_roots: tuple[str, ...]
    shared_roots: Mapping[str, str]
    reaction_protocol: ReactionProtocol
    lifecycle_protocol: LifecycleProtocol
    state_machine_protocol: StateMachineProtocol
    governed_domains: GovernedDomainLibrary


def build_standard_library_v0(
    store: CellStore,
    protocol: AssemblyProtocol,
    *,
    prefix: str = "standard-library-v0",
    catalog_id: str | None = None,
    catalog_version: str = "1.0.0",
    domain_keys: tuple[str, ...] | None = None,
) -> StandardLibraryBuild:
    """Build only definitions with a passing operational court."""
    shared = {
        "item-role": prefix + ":ordered-list:role:item",
        "interface-name": prefix + ":ordered-list:interface-name",
        "contract": prefix + ":ordered-list:contract",
        "documentation": prefix + ":ordered-list:documentation",
        "presentation": prefix + ":ordered-list:presentation",
        "evidence": prefix + ":ordered-list:evidence",
    }
    list_state = prefix + ":ordered-list:state"
    batch = CellBatch(store)
    batch.add(Cell(
        shared["item-role"], NULL_CELL_ID, NULL_CELL_ID, b"ordered item"
    ))
    batch.add(Cell(
        shared["interface-name"], NULL_CELL_ID, NULL_CELL_ID, b"items"
    ))
    batch.add(Cell(
        shared["contract"], NULL_CELL_ID, NULL_CELL_ID,
        b"ordered relation; stable incidence identity; duplicate values allowed",
    ))
    batch.add(Cell(
        shared["documentation"], NULL_CELL_ID, NULL_CELL_ID,
        b"Ordered List: insert, remove, and drag-reorder without changing item identity",
    ))
    batch.add(Cell(
        shared["presentation"], NULL_CELL_ID, NULL_CELL_ID,
        b"standard-library/ordered-list",
    ))
    batch.add(Cell(
        shared["evidence"], NULL_CELL_ID, NULL_CELL_ID,
        b"tests_replica/test_cell_standard_library.py::test_ordered_list_is_operational",
    ))
    batch.add(Cell(list_state, NULL_CELL_ID, NULL_CELL_ID, b""))
    batch.commit()

    interface = build_interface(
        store,
        protocol,
        interface_id=prefix + ":ordered-list:interface:items",
        target_root=list_state,
        name_root=shared["interface-name"],
        member_role_root=shared["item-role"],
        contract_root=shared["contract"],
        presentation_root=shared["presentation"],
        documentation_root=shared["documentation"],
    )
    state_obligation = build_role_obligation(
        store,
        protocol,
        obligation_id=prefix + ":ordered-list:obligation:state",
        required_role=protocol.role("state"),
    )
    definition = build_definition(
        store,
        protocol,
        definition_id=prefix + ":definition:ordered-list",
        name="Ordered List",
        version="1.0.0",
        part_roots=(
            list_state,
            shared["interface-name"],
            shared["contract"],
            shared["documentation"],
            shared["presentation"],
            *interface.part_roots,
        ),
        interface_roots=(interface.root_id,),
        state_roots=(list_state,),
        evidence_roots=(shared["evidence"],),
        obligation_roots=(state_obligation.root_id,),
        shared_roots=(shared["item-role"],),
    )
    release_definition(store, protocol, definition.root_id)

    reaction = bootstrap_reaction_protocol(
        store, prefix=prefix + ":reaction-protocol"
    )
    watcher = {
        "source-slot": prefix + ":watcher:source-slot",
        "interface-name": prefix + ":watcher:interface-name",
        "event-log": prefix + ":watcher:event-log",
        "fingerprint": prefix + ":watcher:fingerprint",
        "cursor": prefix + ":watcher:cursor",
        "status": prefix + ":watcher:status",
        "error": prefix + ":watcher:error",
        "contract": prefix + ":watcher:contract",
        "documentation": prefix + ":watcher:documentation",
        "presentation": prefix + ":watcher:presentation",
        "evidence": prefix + ":watcher:evidence",
    }
    batch = CellBatch(store)
    for root_id, atom in (
        (watcher["source-slot"], b"unwired source"),
        (watcher["interface-name"], b"source"),
        (watcher["event-log"], b""),
        (watcher["fingerprint"], b""),
        (watcher["cursor"], b"0"),
        (watcher["status"], b"idle"),
        (watcher["error"], b""),
        (
            watcher["contract"],
            b"committed graph source; coalesced event history; bounded fixed point",
        ),
        (
            watcher["documentation"],
            b"Watcher: emits an inspectable event when its wired graph source changes",
        ),
        (watcher["presentation"], b"standard-library/watcher"),
        (
            watcher["evidence"],
            b"tests_replica/test_cell_reactions.py::test_watcher_is_operational",
        ),
    ):
        batch.add(Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, atom))
    batch.commit()
    watcher_interface = build_interface(
        store,
        protocol,
        interface_id=prefix + ":watcher:interface:source",
        target_root=watcher["source-slot"],
        name_root=watcher["interface-name"],
        contract_root=watcher["contract"],
        presentation_root=watcher["presentation"],
        documentation_root=watcher["documentation"],
    )
    reaction_manifest = build_reaction_manifest(
        store,
        reaction,
        reaction_id=prefix + ":watcher:reaction",
        source_interface=watcher_interface.root_id,
        event_log=watcher["event-log"],
        fingerprint_state=watcher["fingerprint"],
        cursor_state=watcher["cursor"],
        status_state=watcher["status"],
        error_state=watcher["error"],
    )
    watcher_obligations = tuple(
        build_role_obligation(
            store,
            protocol,
            obligation_id=prefix + ":watcher:obligation:" + role_name,
            required_role=protocol.role(role_name),
        ).root_id
        for role_name in ("state", "rule", "status", "error")
    )
    watcher_definition = build_definition(
        store,
        protocol,
        definition_id=prefix + ":definition:watcher",
        name="Watcher",
        version="1.0.0",
        part_roots=(
            watcher["source-slot"],
            watcher["interface-name"],
            watcher["event-log"],
            watcher["fingerprint"],
            watcher["cursor"],
            watcher["status"],
            watcher["error"],
            watcher["contract"],
            watcher["documentation"],
            watcher["presentation"],
            *watcher_interface.part_roots,
            *reaction_manifest.part_roots,
        ),
        interface_roots=(watcher_interface.root_id,),
        state_roots=(
            watcher["event-log"],
            watcher["fingerprint"],
            watcher["cursor"],
            watcher["status"],
            watcher["error"],
        ),
        rule_roots=(reaction_manifest.root_id,),
        capability_roots=(reaction.root_id,),
        status_roots=(watcher["status"],),
        error_roots=(watcher["error"],),
        evidence_roots=(watcher["evidence"],),
        obligation_roots=watcher_obligations,
        shared_roots=(
            *reaction.roles.values(),
            *reaction.states.values(),
            reaction.root_id,
            reaction.registry_root,
        ),
    )
    release_definition(store, protocol, watcher_definition.root_id)

    lifecycle = bootstrap_lifecycle_protocol(
        store, prefix=prefix + ":lifecycle-protocol"
    )
    versioned_asset = build_versioned_asset_definition(
        store,
        protocol,
        lifecycle,
        prefix=prefix + ":versioned-asset",
    )
    state_machine = bootstrap_state_machine_protocol(
        store, prefix=prefix + ":state-machine-protocol"
    )
    governed_domains = build_governed_domain_library(
        store,
        protocol,
        lifecycle,
        state_machine,
        prefix=prefix + ":governed-domains",
        domain_keys=domain_keys,
    )
    definition_roots = (
        definition.root_id,
        watcher_definition.root_id,
        versioned_asset.definition_root,
        *governed_domains.definition_roots,
    )
    catalog_root = build_catalog(
        store,
        protocol,
        definition_roots,
        catalog_id=catalog_id or prefix + ":catalog",
        version=catalog_version,
    )
    return StandardLibraryBuild(
        catalog_root=catalog_root,
        definition_roots=definition_roots,
        shared_roots=MappingProxyType({**shared, **{
            "watcher-" + key: value for key, value in watcher.items()
        }}),
        reaction_protocol=reaction,
        lifecycle_protocol=lifecycle,
        state_machine_protocol=state_machine,
        governed_domains=governed_domains,
    )


__all__ = ["StandardLibraryBuild", "build_standard_library_v0"]
