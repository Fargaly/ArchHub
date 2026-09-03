"""Open standard presenter assemblies over the universal Cell floor."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from .cell_protocols import CellBatch, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "label",
    "projector",
    "contract",
    "member",
)


@dataclass(frozen=True, slots=True)
class PresenterProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown presenter role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class PresenterAssembly:
    root_id: str
    label_root: str
    projector_root: str
    contract_root: str
    member_roots: tuple[str, ...]


def compose_presenter_protocol(
    batch: CellBatch,
    *,
    prefix: str = "presenter-protocol",
) -> PresenterProtocol:
    roles = {
        name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
    }
    for name, root_id in roles.items():
        batch.add(Cell(
            root_id, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")
        ))
    root_id = "%s:root" % prefix
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    return PresenterProtocol(root_id, MappingProxyType(roles))


def compose_presenter(
    batch: CellBatch,
    protocol: PresenterProtocol,
    *,
    root_id: str,
    label_root: str,
    projector_root: str,
    contract_root: str,
    member_roots: Iterable[str],
):
    members = tuple(member_roots)
    if not members:
        raise InvalidCell("presenter assembly has no visible primitive members")
    return batch.relation((
        (protocol.role("label"), label_root),
        (protocol.role("projector"), projector_root),
        (protocol.role("contract"), contract_root),
        *((protocol.role("member"), root) for root in members),
    ), relation_id=root_id)


def _one(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members
        if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("presenter must have exactly one %s" % label)
    return values[0]


def read_presenter(
    snapshot: Snapshot,
    protocol: PresenterProtocol,
    root_id: str,
) -> PresenterAssembly:
    members = read_relation(snapshot, root_id, budget=128)
    primitive_roots = tuple(
        member.participant_id for member in members
        if member.role_id == protocol.role("member")
    )
    if not primitive_roots:
        raise InvalidCell("presenter assembly has no visible primitive members")
    return PresenterAssembly(
        root_id,
        _one(members, protocol.role("label"), "label"),
        _one(members, protocol.role("projector"), "projector"),
        _one(members, protocol.role("contract"), "contract"),
        primitive_roots,
    )


__all__ = [
    "ROLE_NAMES",
    "PresenterAssembly",
    "PresenterProtocol",
    "compose_presenter",
    "compose_presenter_protocol",
    "read_presenter",
]
