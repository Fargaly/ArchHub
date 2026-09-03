"""Who owns a memory, and how ownership moves.

`brain_owner_binding` gated nothing in the superseded app: the store had one
user, so ownership was assumed. The moment a brain federates or syncs, an
assumed owner is a leak. Ownership is a graph fact here: exactly one owner per
root, no default, and a transfer that the current owner has to consent to.

There is deliberately no "read the owner, or fall back to the caller". A root
with no owner raises. Assuming is how the leak happens.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

REGISTRY_ROOT = "app:brain:ownership"
BINDING_ROLE = REGISTRY_ROOT + ":role:binding"
SUBJECT_ROLE = REGISTRY_ROOT + ":role:subject"
OWNER_ROLE = REGISTRY_ROOT + ":role:owner"
CONSENT_ROLE = REGISTRY_ROOT + ":role:consent"


@dataclass(frozen=True, slots=True)
class Ownership:
    subject_root: str
    owner_root: str
    consent_roots: tuple


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def ensure_registry(store):
    snapshot = store.snapshot()
    if REGISTRY_ROOT in snapshot.cells:
        return REGISTRY_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(BINDING_ROLE, "binding"),
        _terminal(SUBJECT_ROLE, "subject"),
        _terminal(OWNER_ROLE, "owner"),
        _terminal(CONSENT_ROLE, "consent"),
        Cell(REGISTRY_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return REGISTRY_ROOT


def _binding_root(subject_root):
    return "%s:binding:%s" % (REGISTRY_ROOT, subject_root)


def _read(snapshot, binding_root):
    members = read_relation(snapshot, binding_root, budget=10_000)

    def many(role):
        return tuple(m.participant_id for m in members if m.role_id == role)

    def one(role, label):
        found = many(role)
        if len(found) != 1:
            raise InvalidCell("ownership has no single %s" % label)
        return found[0]

    return Ownership(
        one(SUBJECT_ROLE, "subject"),
        one(OWNER_ROLE, "owner"),
        many(CONSENT_ROLE),
    )


def bind_owner(store, *, subject_root, owner_root):
    """Give a root exactly one owner. A second one is refused."""
    snapshot = store.snapshot()
    for root, label in ((subject_root, "subject"), (owner_root, "owner")):
        if root not in snapshot.cells:
            raise InvalidCell("ownership %s is not a root the graph holds" % label)
    ensure_registry(store)
    snapshot = store.snapshot()
    binding = _binding_root(subject_root)
    if binding in snapshot.cells:
        raise InvalidCell("root already has an owner: %s" % subject_root)
    store.commit(snapshot.revision, create=(
        Cell(binding, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, binding, (
        (SUBJECT_ROLE, subject_root),
        (OWNER_ROLE, owner_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    registry = prepare_append_relation_members(
        snapshot, REGISTRY_ROOT, ((BINDING_ROLE, binding),), budget=100_000)
    store.commit(snapshot.revision, create=registry.create, replace=registry.replace)
    return binding


def read_owner(snapshot, subject_root):
    """The owner, from the graph. An unowned root raises -- never a default."""
    binding = _binding_root(subject_root)
    if binding not in snapshot.cells:
        raise InvalidCell("root has no owner: %s" % subject_root)
    return _read(snapshot, binding).owner_root


def transfer_owner(store, *, subject_root, to_owner_root, consent_root):
    """Move ownership. The CURRENT owner has to have consented."""
    snapshot = store.snapshot()
    binding = _binding_root(subject_root)
    if binding not in snapshot.cells:
        raise InvalidCell("root has no owner to transfer: %s" % subject_root)
    if to_owner_root not in snapshot.cells:
        raise InvalidCell("ownership owner is not a root the graph holds")
    if consent_root not in snapshot.cells:
        raise InvalidCell("a transfer without consent is a seizure")
    current = _read(snapshot, binding)
    if current.owner_root == to_owner_root:
        raise InvalidCell("root already belongs to that owner")
    consent_members = read_relation(snapshot, consent_root, budget=10_000)
    granted = {m.participant_id for m in consent_members}
    if current.owner_root not in granted or subject_root not in granted:
        raise InvalidCell("consent does not name this owner and this subject")

    members = read_relation(snapshot, binding, budget=10_000)
    owner_member = next(m for m in members if m.role_id == OWNER_ROLE)
    incidence = snapshot.cells[owner_member.incidence_id]
    store.commit(snapshot.revision, replace=(
        Cell(incidence.id, incidence.link0, to_owner_root, incidence.atom),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, binding, ((CONSENT_ROLE, consent_root),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return to_owner_root


def owned_by(snapshot, owner_root):
    """Everything one owner holds."""
    if REGISTRY_ROOT not in snapshot.cells:
        return ()
    found = []
    for member in read_relation(snapshot, REGISTRY_ROOT, budget=100_000):
        if member.role_id != BINDING_ROLE:
            continue
        ownership = _read(snapshot, member.participant_id)
        if ownership.owner_root == owner_root:
            found.append(ownership.subject_root)
    return tuple(sorted(found))
