"""Versioned graph selection for authenticated context input predicates.

Preparing or reading this descriptor does not authorize its installation. The
owner must select its root through the admitted adoption/runtime configuration.
"""
from dataclasses import dataclass
from collections.abc import Mapping
import hashlib
from types import MappingProxyType
import uuid

from .cell_protocols import compose_relation_cells, read_relation, _relation_chain_ids
from .universal_cell import Cell, InvalidCell, NULL_CELL_ID


CONTEXT_FIELDS = ("subject", "principal", "tenant", "assurance", "action",
    "object", "scope", "purpose", "classification", "audience")
VERSION = b"archhub/authenticated-policy-context/v1"


@dataclass(frozen=True, slots=True)
class PolicyContextBinding:
    root: str
    predicates: Mapping[str, str]
    digest: str
    read_roots: tuple[str, ...]


def prepare_policy_context_binding():
    """Return a new descriptor root and closed Cell patch; do not commit it."""
    root = str(uuid.uuid4())
    cells, pairs = [], []
    for name in ("version", *CONTEXT_FIELDS):
        role, value = str(uuid.uuid4()), str(uuid.uuid4())
        cells.extend((Cell(role, NULL_CELL_ID, NULL_CELL_ID, name.encode("ascii")),
            Cell(value, NULL_CELL_ID, NULL_CELL_ID,
                VERSION if name == "version" else ("context-input/" + name).encode("ascii"))))
        pairs.append((role, value))
    relation = compose_relation_cells(pairs, relation_id=root)
    return root, (*cells, *relation.cells)


def read_policy_context_binding(snapshot, root):
    members = read_relation(snapshot, root, budget=32, retain_projection=False)
    if len(members) != len(CONTEXT_FIELDS) + 1:
        raise InvalidCell("policy context binding fields are incomplete")
    selected, seen = {}, set()
    read_ids = set(_relation_chain_ids(snapshot, root, budget=32))
    for member in members:
        role = snapshot.cells[member.role_id]
        value = snapshot.cells[member.participant_id]
        if len(role.atom) > 64 or len(value.atom) > 128:
            raise InvalidCell("policy context binding field exceeds its size bound")
        if any(cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID for cell in (role, value)):
            raise InvalidCell("policy context binding fields must be leaves")
        try:
            name = role.atom.decode("ascii")
        except UnicodeDecodeError as exc:
            raise InvalidCell("policy context binding field is invalid") from exc
        if name not in ("version", *CONTEXT_FIELDS) or name in seen:
            raise InvalidCell("policy context binding field is unknown or duplicated")
        seen.add(name)
        expected = VERSION if name == "version" else ("context-input/" + name).encode("ascii")
        if value.atom != expected:
            raise InvalidCell("policy context binding version or predicate is invalid")
        if name != "version":
            selected[name] = value.id
        read_ids.update((member.incidence_id, role.id, value.id))
    if set(selected) != set(CONTEXT_FIELDS) or len(set(selected.values())) != len(selected):
        raise InvalidCell("policy context binding predicate identities are invalid")
    digest = hashlib.sha256(b"ArchHub/policy-context-binding/v1\0")
    for identity in sorted(read_ids):
        cell = snapshot.cells[identity]
        for field in (cell.id.encode(), cell.link0.encode(), cell.link1.encode(), cell.atom):
            digest.update(len(field).to_bytes(8, "big") + field)
    return PolicyContextBinding(root, MappingProxyType(selected), digest.hexdigest(), tuple(sorted(read_ids)))
