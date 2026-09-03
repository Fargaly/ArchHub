"""Sharing a memory with a firm, without giving it away.

`brain_firm_federation` assumed that whoever could reach the store could share
from it. Ownership and sharing are different powers: only the owner of a fact
may share it, sharing is to a named firm rather than to the world, and what
crosses carries a redaction the sender chose rather than the raw fact.

Nothing here reaches a network. It decides who may share what with whom, which
is the part that cannot be fixed afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_brain_ownership import read_owner
from .cell_brain_secrets import assert_not_a_secret
from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

FEDERATION_ROOT = "app:brain:federation"
FIRM_ROLE = FEDERATION_ROOT + ":role:firm"
MEMBER_ROLE = FEDERATION_ROOT + ":role:member"
SHARE_ROLE = FEDERATION_ROOT + ":role:share"
FACT_ROLE = FEDERATION_ROOT + ":role:fact"
REDACTION_ROLE = FEDERATION_ROOT + ":role:redaction"
SHARER_ROLE = FEDERATION_ROOT + ":role:sharer"


@dataclass(frozen=True, slots=True)
class Share:
    fact_root: str
    firm_root: str
    sharer_root: str
    redaction: str


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("federation text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_federation(store):
    snapshot = store.snapshot()
    if FEDERATION_ROOT in snapshot.cells:
        return FEDERATION_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(FIRM_ROLE, "firm"),
        _terminal(MEMBER_ROLE, "member"),
        _terminal(SHARE_ROLE, "share"),
        _terminal(FACT_ROLE, "fact"),
        _terminal(REDACTION_ROLE, "redaction"),
        _terminal(SHARER_ROLE, "sharer"),
        Cell(FEDERATION_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return FEDERATION_ROOT


def create_firm(store, *, firm_root, member_roots):
    """A firm is the people in it. An empty firm cannot receive anything."""
    members = tuple(dict.fromkeys(member_roots))
    if not members:
        raise InvalidCell("a firm with no members cannot be shared with")
    snapshot = store.snapshot()
    for root in members:
        if root not in snapshot.cells:
            raise InvalidCell("firm member is not a root the graph holds: %s" % root)
    ensure_federation(store)
    snapshot = store.snapshot()
    if firm_root in snapshot.cells:
        raise InvalidCell("firm already exists: %s" % firm_root)
    store.commit(snapshot.revision, create=(
        Cell(firm_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, firm_root,
        tuple((MEMBER_ROLE, root) for root in members), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, FEDERATION_ROOT, ((FIRM_ROLE, firm_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return firm_root


def firm_members(snapshot, firm_root):
    if firm_root not in snapshot.cells:
        raise InvalidCell("no such firm: %s" % firm_root)
    return tuple(sorted(
        m.participant_id
        for m in read_relation(snapshot, firm_root, budget=10_000)
        if m.role_id == MEMBER_ROLE
    ))


def _share_root(fact_root, firm_root):
    return "%s:share:%s:%s" % (FEDERATION_ROOT, firm_root, fact_root)


def share_fact(store, *, fact_root, firm_root, sharer_root, redaction):
    """Only the owner may share, and only a redaction crosses."""
    redaction = redaction.strip()
    if not redaction:
        raise InvalidCell("sharing the raw fact is not sharing a redaction")
    assert_not_a_secret(redaction, "shared redaction")
    snapshot = store.snapshot()
    if fact_root not in snapshot.cells:
        raise InvalidCell("cannot share a fact the graph does not hold")
    firm_members(snapshot, firm_root)
    owner = read_owner(snapshot, fact_root)
    if owner != sharer_root:
        raise InvalidCell("only the owner of a fact may share it")
    ensure_federation(store)
    snapshot = store.snapshot()
    share = _share_root(fact_root, firm_root)
    if share in snapshot.cells:
        raise InvalidCell("fact is already shared with that firm")
    redaction_root = share + ":redaction"
    store.commit(snapshot.revision, create=(
        _terminal(redaction_root, redaction),
        Cell(share, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, share, (
        (FACT_ROLE, fact_root),
        (FIRM_ROLE, firm_root),
        (SHARER_ROLE, sharer_root),
        (REDACTION_ROLE, redaction_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, FEDERATION_ROOT, ((SHARE_ROLE, share),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return share


def _shares(snapshot):
    if FEDERATION_ROOT not in snapshot.cells:
        return ()
    out = []
    for member in read_relation(snapshot, FEDERATION_ROOT, budget=100_000):
        if member.role_id != SHARE_ROLE:
            continue
        members = read_relation(snapshot, member.participant_id, budget=10_000)

        def one(role, label):
            values = [m.participant_id for m in members if m.role_id == role]
            if len(values) != 1:
                raise InvalidCell("share has no single %s" % label)
            return values[0]

        out.append(Share(
            one(FACT_ROLE, "fact"),
            one(FIRM_ROLE, "firm"),
            one(SHARER_ROLE, "sharer"),
            _text(snapshot, one(REDACTION_ROLE, "redaction")),
        ))
    return tuple(out)


def visible_to(snapshot, member_root):
    """What one person can see, through the firms they actually belong to."""
    visible = []
    for share in _shares(snapshot):
        if member_root in firm_members(snapshot, share.firm_root):
            visible.append(share)
    return tuple(sorted(visible, key=lambda s: (s.firm_root, s.fact_root)))
