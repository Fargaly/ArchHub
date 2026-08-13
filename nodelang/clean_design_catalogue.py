"""Carry the design-system catalogue into the clean graph as graph state.

The catalogue CONTENT already exists and is good: fourteen icons, fifteen
controls, fifteen bindings, with zones, orders, capabilities and the
conditions that decide when a control applies. What does not fit is its
IDENTITY. Those modules name things after themselves --
"app:icon-catalog:lucide:1.25.0" -- while this authority requires opaque
identities, so a name can never be guessed, and every fact about a thing
has to be stored as data that can be read and revised rather than parsed
out of an address.

They are also still the old application's modules. Mutating them would
break a shipping product to serve a rebuild, so they are used here as a
SOURCE and never as a store: the legacy builders run against a throwaway
in-memory store, the result is read out, and what lands in this graph is
minted fresh under this authority's own rules.
"""
from __future__ import annotations

from .cell_control_bindings import (
    _text,
    ensure_archhub_control_binding_catalog,
    project_control_binding_catalog,
)
from .cell_control_presentations import (
    ensure_archhub_control_catalog,
    project_control_catalog,
)
from .application import STYLESHEET
from .cell_icons import ensure_archhub_icon_catalog, project_icon_catalog
from .cell_protocols import read_relation
from .universal_cell import NULL_CELL_ID, InvalidCell
from .unified_authority import (
    COMMAND_BUDGET,
    CallerCommandCapability,
    UnifiedAuthority,
    declare_definition,
    read_definition,
    revise_definition,
)
from .universal_cell import CellStore


DESIGN_CATALOGUE_DEFINITION = "Design System Catalogue"


def _export_condition(snapshot, protocol, root_id, depth=0):
    """Carry the condition itself, not the answer it happens to give.

    Baking applicability at compose time would make one catalogue mean one
    fixed set of buttons. The condition travels as data so the same
    catalogue yields different applicable controls in different scopes and
    selections -- which is the whole reason a condition exists.
    """
    if depth > 8:
        raise InvalidCell("control condition nests too deeply to carry")
    facts_by_root = {root: name for name, root in protocol.facts.items()}
    operators_by_root = {
        root: name for name, root in protocol.operators.items()
    }
    members = read_relation(snapshot, root_id, budget=128)
    operator_root = next(
        member.participant_id for member in members
        if member.role_id == protocol.role("operator")
    )
    operands = []
    for member in members:
        if member.role_id != protocol.role("operand"):
            continue
        operand_root = member.participant_id
        if operand_root in facts_by_root:
            operands.append({"fact": facts_by_root[operand_root]})
            continue
        cell = snapshot.cells.get(operand_root)
        if cell is None:
            raise InvalidCell("control condition operand is missing")
        if cell.link0 == NULL_CELL_ID and cell.link1 == NULL_CELL_ID:
            operands.append({"literal": _text(snapshot, operand_root)})
            continue
        operands.append(
            _export_condition(snapshot, protocol, operand_root, depth + 1)
        )
    return {"operator": operators_by_root[operator_root], "operands": operands}


def compose_design_catalogue() -> dict[str, object]:
    """Read the catalogue content without writing to any real graph."""
    scratch = CellStore()
    icons = ensure_archhub_icon_catalog(scratch)
    controls = ensure_archhub_control_catalog(scratch, icons)
    bindings = ensure_archhub_control_binding_catalog(scratch, controls)
    snapshot = scratch.snapshot()
    icon_projection = project_icon_catalog(
        snapshot, icons.protocol, icons.catalog_root
    )
    control_projection = project_control_catalog(
        snapshot, controls.protocol, icons.protocol, controls.catalog_root
    )
    binding_projection = project_control_binding_catalog(
        snapshot, bindings.protocol, bindings.catalog_root
    )
    icon_rows = []
    for name, icon in sorted(icon_projection.icons.items()):
        icon_rows.append({
            "name": name,
            "root": icon.root_id,
            "source": icon.source_root,
            "view_box": icon.view_box,
            "primitives": [
                {
                    "order": primitive.order,
                    "tag": primitive.tag,
                    "attributes": dict(primitive.attributes),
                }
                for primitive in icon.primitives
            ],
        })
    control_rows = []
    for control in control_projection.controls.values():
        binding = binding_projection.bindings.get(control.owner_root)
        if binding is None:
            # A control whose binding is absent is carried as unbound
            # rather than given one the projector guessed. A name-shaped
            # join is invisible until somebody renames a control.
            activation = None
        else:
            activation = {
                "binding": binding.root_id,
                "capability": binding.capability_root,
                "arguments": dict(binding.arguments),
                "condition": _export_condition(
                    snapshot, bindings.protocol, binding.condition_root
                ),
            }
        control_rows.append({
            "owner": control.owner_root,
            "label": control.label,
            "title": control.title,
            "zone": control.zone,
            "order": control.order,
            "icon": control.icon_root,
            "activation": activation,
        })
    control_rows.sort(key=lambda row: (row["zone"], row["order"]))
    # The stylesheet is part of the catalogue for the same reason the
    # controls are: the canvas satisfied every contract and still showed
    # nothing, because appearance was the one thing no court could see and
    # the page carried nine rules of its own. It travels with the rest, so
    # revising the catalogue restyles the canvas without touching code.
    return {
        "icons": icon_rows,
        "controls": control_rows,
        "stylesheet": STYLESHEET,
    }


def install_design_catalogue(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> str:
    """Declare the catalogue as graph state, or revise it when it drifts.

    It lands as one definition in the authority's catalogue carrying the
    catalogue in its presentation contract. That makes it revisable
    through the ordinary signed path -- change the catalogue, the canvas
    changes, with no code edit -- and keeps every fact about a control
    (its zone, order, icon, capability and the condition that decides
    when it applies) readable in the graph instead of parsed out of a
    name.
    """
    catalogue = compose_design_catalogue()
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
        if projection.name == DESIGN_CATALOGUE_DEFINITION:
            existing = projection
            break
    if existing is None:
        result = declare_definition(
            authority,
            DESIGN_CATALOGUE_DEFINITION,
            caller=caller,
            command_id=command_id,
            presentation=catalogue,
        )
        return result.root_id
    if dict(existing.contracts["presentation"]) == catalogue:
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
        presentation=catalogue,
        courts=dict(existing.contracts["courts"]),
        provenance=dict(existing.contracts["provenance"]),
    )
    return existing.root_id


def read_design_catalogue(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> dict[str, object] | None:
    """Read the catalogue the graph holds, or None when it holds none.

    None is an honest answer and the caller must fail loudly on it. A
    default catalogue here would be exactly the Python invention this
    exists to remove, and would hide a graph that was never installed.
    """
    snapshot = authority.store.snapshot()
    for member in read_relation(
        snapshot, authority.manifest.catalogue_root, budget=COMMAND_BUDGET
    ):
        if member.role_id != authority.role("definition"):
            continue
        projection = read_definition(
            authority, member.participant_id, caller=caller
        )
        if projection.name == DESIGN_CATALOGUE_DEFINITION:
            return dict(projection.contracts["presentation"])
    return None


__all__ = [
    "DESIGN_CATALOGUE_DEFINITION",
    "compose_design_catalogue",
    "install_design_catalogue",
    "read_design_catalogue",
]
