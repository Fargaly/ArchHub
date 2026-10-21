"""Hold every host operation ArchHub can perform as graph state.

The clean runtime knew seven host BOUNDARIES and not one thing that could
be done through them, so the canvas could name Revit and had nothing to
ask it for. The operations exist -- nineteen connectors and a hundred and
fifty five operations, each already declaring its host, its kind, its
inputs and whether it destroys anything -- and they lived only as Python
in another tree.

They land here as cells. Nothing in this module imports that tree: the
records arrive as plain data from a migration someone runs deliberately,
and from then on the runtime reads the graph and only the graph. What
ArchHub can perform is a fact about the graph, not a fact about which
modules happened to import.

Declaring an operation is not permission to run it. This publishes what
CAN be asked for; the signed effect path decides what may be.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from .cell_protocols import read_relation
from .unified_authority import (
    COMMAND_BUDGET,
    CallerCommandCapability,
    UnifiedAuthority,
    declare_definition,
    read_definition,
    revise_definition,
)
from .universal_cell import InvalidCell


HOST_OPERATION_DEFINITION = "Host Operation Catalogue"

_INPUT_FIELDS = ("id", "label", "type", "default", "required", "help")
_OPERATION_FIELDS = (
    "op_id",
    "host",
    "kind",
    "label",
    "description",
    "output_type",
    "destructive",
)


def compose_host_operations(
    records: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Normalise operation records into exactly what the graph will hold.

    Every field is copied from the record it came from. A record that
    cannot name its operation or its host is refused rather than filled
    in, because an operation nobody can address is not an operation, and a
    host invented here is a host the graph never agreed to.
    """
    operations: list[dict[str, object]] = []
    seen: set[str] = set()
    for record in records:
        op_id = record.get("op_id")
        host = record.get("host")
        if type(op_id) is not str or not op_id.strip():
            raise InvalidCell("host operation record has no operation id")
        if type(host) is not str or not host.strip():
            raise InvalidCell("host operation %r names no host" % op_id)
        if op_id in seen:
            raise InvalidCell("host operation %r is declared twice" % op_id)
        seen.add(op_id)
        inputs = []
        for field in record.get("inputs") or ():
            if not isinstance(field, Mapping):
                raise InvalidCell(
                    "host operation %r has an invalid input" % op_id
                )
            name = field.get("id")
            if type(name) is not str or not name.strip():
                raise InvalidCell(
                    "an input of host operation %r has no name" % op_id
                )
            inputs.append({key: field.get(key) for key in _INPUT_FIELDS})
        entry = {key: record.get(key) for key in _OPERATION_FIELDS}
        entry["inputs"] = inputs
        operations.append(entry)
    operations.sort(key=lambda entry: str(entry["op_id"]))
    hosts = sorted({str(entry["host"]) for entry in operations})
    return {"hosts": hosts, "operations": operations}


def _next_version(version: object) -> str:
    """The version after this one, counting from whatever is there.

    A catalogue that is revised needs a version that moves, and the only
    thing that can be relied on about the version already recorded is
    that it is a string. A trailing number is incremented; anything else
    gains one.
    """
    text = str(version or "").strip() or "1"
    digits = ""
    while text and text[-1].isdigit():
        digits = text[-1] + digits
        text = text[:-1]
    if not digits:
        return "%s.1" % (str(version).strip() or "1")
    return "%s%d" % (text, int(digits) + 1)


def install_host_operations(
    authority: UnifiedAuthority,
    catalogue: Mapping[str, object],
    *,
    caller: CallerCommandCapability,
    command_id: str,
) -> str:
    """Declare the operation catalogue as graph state, or revise it.

    One definition carries all of it, so adding an operation to ArchHub is
    revising a definition rather than editing and redeploying code, and
    what the runtime believes it can do is readable in the graph.
    """
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
        if projection.name == HOST_OPERATION_DEFINITION:
            existing = projection
            break
    if existing is None:
        result = declare_definition(
            authority,
            HOST_OPERATION_DEFINITION,
            caller=caller,
            command_id=command_id,
            presentation=dict(catalogue),
        )
        return result.root_id
    if dict(existing.contracts["presentation"]) == dict(catalogue):
        return existing.root_id
    # A revision carries its own version. Leaving it to the callee meant
    # this branch had never run: the catalogue could be declared once and
    # never revised again, which is the one thing this function exists to
    # make possible.
    revise_definition(
        authority,
        existing.root_id,
        existing.name,
        caller=caller,
        command_id=command_id,
        version=_next_version(existing.version),
        presentation=dict(catalogue),
    )
    return existing.root_id


def read_host_operations(
    authority: UnifiedAuthority,
    *,
    caller: CallerCommandCapability,
) -> dict[str, object] | None:
    """What the graph says ArchHub can perform, or nothing at all.

    A graph that was never given the catalogue answers None. It does not
    answer with an empty catalogue, because "this runtime can do nothing"
    and "nobody has told this runtime what it can do" are different facts
    and only one of them is safe to act on.
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
        if projection.name == HOST_OPERATION_DEFINITION:
            return dict(projection.contracts["presentation"])
    return None


__all__ = [
    "HOST_OPERATION_DEFINITION",
    "compose_host_operations",
    "install_host_operations",
    "read_host_operations",
]
