"""Incoming from a peer: quarantined until judged, never applied on arrival.

`brain_community` polled peers and merged what came back. Merging on arrival is
how a shared network becomes a way to write into someone else's brain. Anything
arriving from outside lands in quarantine carrying its provenance, and stays
invisible until a judgement admits it.

A rejection is kept, not deleted. The same claim arriving again is answered from
the record instead of being argued a second time.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_brain_secrets import assert_not_a_secret
from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

COMMUNITY_ROOT = "app:brain:community"
SUBSCRIPTION_ROLE = COMMUNITY_ROOT + ":role:subscription"
INCOMING_ROLE = COMMUNITY_ROOT + ":role:incoming"
PEER_ROLE = COMMUNITY_ROOT + ":role:peer"
CLAIM_ROLE = COMMUNITY_ROOT + ":role:claim"
VERDICT_ROLE = COMMUNITY_ROOT + ":role:verdict"

QUARANTINED = COMMUNITY_ROOT + ":verdict:quarantined"
ADMITTED = COMMUNITY_ROOT + ":verdict:admitted"
REJECTED = COMMUNITY_ROOT + ":verdict:rejected"

_VERDICTS = (QUARANTINED, ADMITTED, REJECTED)


@dataclass(frozen=True, slots=True)
class Incoming:
    root_id: str
    peer_root: str
    claim: str
    verdict: str


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("community text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_community(store):
    snapshot = store.snapshot()
    if COMMUNITY_ROOT in snapshot.cells:
        return COMMUNITY_ROOT
    created = [
        _terminal(SUBSCRIPTION_ROLE, "subscription"),
        _terminal(INCOMING_ROLE, "incoming"),
        _terminal(PEER_ROLE, "peer"),
        _terminal(CLAIM_ROLE, "claim"),
        _terminal(VERDICT_ROLE, "verdict"),
    ]
    created.extend(_terminal(v, v.rsplit(":", 1)[-1]) for v in _VERDICTS)
    created.append(Cell(COMMUNITY_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"))
    store.commit(snapshot.revision, create=tuple(created))
    return COMMUNITY_ROOT


def subscribe(store, peer_root):
    """Agree to hear from a peer. Hearing is not believing."""
    snapshot = store.snapshot()
    if peer_root not in snapshot.cells:
        raise InvalidCell("cannot subscribe to a peer the graph does not hold")
    ensure_community(store)
    snapshot = store.snapshot()
    if peer_root in subscriptions(snapshot):
        raise InvalidCell("already subscribed to %s" % peer_root)
    patch = prepare_append_relation_members(
        snapshot, COMMUNITY_ROOT,
        ((SUBSCRIPTION_ROLE, peer_root),), budget=100_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return peer_root


def subscriptions(snapshot):
    if COMMUNITY_ROOT not in snapshot.cells:
        return ()
    return tuple(sorted(
        m.participant_id
        for m in read_relation(snapshot, COMMUNITY_ROOT, budget=100_000)
        if m.role_id == SUBSCRIPTION_ROLE
    ))


def _incoming_root(peer_root, claim):
    return "%s:incoming:%s:%d" % (COMMUNITY_ROOT, peer_root, abs(hash(claim)) % 10**12)


def receive(store, *, peer_root, claim):
    """Take something in. It arrives quarantined and invisible."""
    claim = claim.strip()
    if not claim:
        raise InvalidCell("an empty claim is not a claim")
    assert_not_a_secret(claim, "incoming claim")
    snapshot = store.snapshot()
    if peer_root not in subscriptions(snapshot):
        raise InvalidCell("nothing is accepted from a peer we did not subscribe to")
    root = _incoming_root(peer_root, claim)
    if root in snapshot.cells:
        raise InvalidCell("this claim from this peer was already received")
    claim_root = root + ":claim"
    store.commit(snapshot.revision, create=(
        _terminal(claim_root, claim),
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, root, (
        (PEER_ROLE, peer_root),
        (CLAIM_ROLE, claim_root),
        (VERDICT_ROLE, QUARANTINED),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, COMMUNITY_ROOT, ((INCOMING_ROLE, root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return root


def _read(snapshot, root):
    members = read_relation(snapshot, root, budget=10_000)

    def one(role, label):
        values = [m.participant_id for m in members if m.role_id == role]
        if len(values) != 1:
            raise InvalidCell("incoming has no single %s" % label)
        return values[0]

    return Incoming(
        root,
        one(PEER_ROLE, "peer"),
        _text(snapshot, one(CLAIM_ROLE, "claim")),
        one(VERDICT_ROLE, "verdict"),
    )


def judge(store, incoming_root, *, admit):
    """Admit or reject. A judged item is never judged again."""
    snapshot = store.snapshot()
    if incoming_root not in snapshot.cells:
        raise InvalidCell("no such incoming: %s" % incoming_root)
    entry = _read(snapshot, incoming_root)
    if entry.verdict != QUARANTINED:
        raise InvalidCell("this was already judged")
    members = read_relation(snapshot, incoming_root, budget=10_000)
    verdict_member = next(m for m in members if m.role_id == VERDICT_ROLE)
    incidence = snapshot.cells[verdict_member.incidence_id]
    decided = ADMITTED if admit else REJECTED
    store.commit(snapshot.revision, replace=(
        Cell(incidence.id, incidence.link0, decided, incidence.atom),
    ))
    return decided


def _all_incoming(snapshot):
    if COMMUNITY_ROOT not in snapshot.cells:
        return ()
    return tuple(
        _read(snapshot, m.participant_id)
        for m in read_relation(snapshot, COMMUNITY_ROOT, budget=100_000)
        if m.role_id == INCOMING_ROLE
    )


def admitted(snapshot):
    """Only what a judgement let in. Nothing else is visible."""
    return tuple(sorted(
        (e for e in _all_incoming(snapshot) if e.verdict == ADMITTED),
        key=lambda e: (e.peer_root, e.claim),
    ))


def quarantine(snapshot):
    return tuple(sorted(
        (e for e in _all_incoming(snapshot) if e.verdict == QUARANTINED),
        key=lambda e: (e.peer_root, e.claim),
    ))


def rejected(snapshot):
    """Kept on purpose: the same claim is answered from the record."""
    return tuple(sorted(
        (e for e in _all_incoming(snapshot) if e.verdict == REJECTED),
        key=lambda e: (e.peer_root, e.claim),
    ))
