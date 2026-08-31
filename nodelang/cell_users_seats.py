"""Firms, seats, and invites that are bound to the person they were sent to.

An invite is a credential in an email. The superseded app stored the token and
compared it, and let anyone holding the link accept -- so a forwarded email was
an account. Here the token is kept as a fingerprint bound to the firm AND to the
address it was sent to, so accepting from another address fails even with the
right token.

Seats are counted before they are given, not after. A firm cannot end up owing
more seats than it bought because the check happens at the moment of accepting.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .cell_brain_ownership import bind_owner, read_owner
from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

FIRMS_ROOT = "app:users:firms"
FIRM_ROLE = FIRMS_ROOT + ":role:firm"
SEATS_ROLE = FIRMS_ROOT + ":role:seats"
MEMBER_ROLE = FIRMS_ROOT + ":role:member"
INVITE_ROLE = FIRMS_ROOT + ":role:invite"
SPENT_ROLE = FIRMS_ROOT + ":role:spent"

MINIMUM_TOKEN_LENGTH = 16


@dataclass(frozen=True, slots=True)
class Firm:
    root_id: str
    owner_root: str
    seats: int
    member_roots: tuple
    seats_taken: int

    @property
    def seats_free(self):
        return self.seats - self.seats_taken


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("firm text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def invite_fingerprint(firm_root, email, token):
    """Bound to the firm AND the address. A forwarded token opens nothing."""
    return hashlib.sha256(
        ("\x00".join((firm_root, email.strip().casefold(), token)))
        .encode("utf-8")
    ).hexdigest()


def ensure_firms(store):
    snapshot = store.snapshot()
    if FIRMS_ROOT in snapshot.cells:
        return FIRMS_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(FIRM_ROLE, "firm"),
        _terminal(SEATS_ROLE, "seats"),
        _terminal(MEMBER_ROLE, "member"),
        _terminal(INVITE_ROLE, "invite"),
        _terminal(SPENT_ROLE, "spent"),
        Cell(FIRMS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return FIRMS_ROOT


def create_firm(store, *, firm_root, owner_root, seats):
    """A firm buys seats up front. The owner holds the first one."""
    if not isinstance(seats, int) or isinstance(seats, bool) or seats < 1:
        raise InvalidCell("a firm must buy at least one seat")
    snapshot = store.snapshot()
    if owner_root not in snapshot.cells:
        raise InvalidCell("firm owner is not a root the graph holds")
    if firm_root in snapshot.cells:
        raise InvalidCell("firm already exists: %s" % firm_root)
    ensure_firms(store)
    snapshot = store.snapshot()
    seats_root = firm_root + ":seats"
    store.commit(snapshot.revision, create=(
        _terminal(seats_root, seats),
        Cell(firm_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, firm_root, (
        (SEATS_ROLE, seats_root),
        (MEMBER_ROLE, owner_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    bind_owner(store, subject_root=firm_root, owner_root=owner_root)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, FIRMS_ROOT, ((FIRM_ROLE, firm_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return firm_root


def read_firm(snapshot, firm_root):
    if firm_root not in snapshot.cells:
        raise InvalidCell("no such firm: %s" % firm_root)
    members = read_relation(snapshot, firm_root, budget=10_000)
    seated = tuple(sorted(
        m.participant_id for m in members if m.role_id == MEMBER_ROLE))
    return Firm(
        firm_root,
        read_owner(snapshot, firm_root),
        int(_text(snapshot, firm_root + ":seats")),
        seated,
        len(seated),
    )


def invite(store, *, firm_root, email, token, inviter_root):
    """Only the owner invites, and only while a seat is free."""
    email = email.strip()
    if "@" not in email:
        raise InvalidCell("an invite must name a real address")
    if len(token) < MINIMUM_TOKEN_LENGTH:
        raise InvalidCell(
            "an invite token shorter than %d characters is guessable"
            % MINIMUM_TOKEN_LENGTH
        )
    snapshot = store.snapshot()
    firm = read_firm(snapshot, firm_root)
    if firm.owner_root != inviter_root:
        raise InvalidCell("only the owner of a firm may invite")
    if firm.seats_free < 1:
        raise InvalidCell("the firm has no free seat to invite into")
    digest = invite_fingerprint(firm_root, email, token)
    invite_root = "%s:invite:%s" % (firm_root, digest)
    if invite_root in snapshot.cells:
        raise InvalidCell("that invite was already issued")
    store.commit(snapshot.revision, create=(_terminal(invite_root, digest),))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, firm_root, ((INVITE_ROLE, invite_root),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return invite_root


def accept_invite(store, *, firm_root, email, token, member_root):
    """The address the invite was sent to is part of the key."""
    snapshot = store.snapshot()
    firm = read_firm(snapshot, firm_root)
    if member_root not in snapshot.cells:
        raise InvalidCell("the joining member is not a root the graph holds")
    if member_root in firm.member_roots:
        raise InvalidCell("that member already holds a seat")
    if firm.seats_free < 1:
        raise InvalidCell("the firm has no free seat left")
    digest = invite_fingerprint(firm_root, email, token)
    invite_root = "%s:invite:%s" % (firm_root, digest)
    members = read_relation(snapshot, firm_root, budget=10_000)
    issued = {m.participant_id for m in members if m.role_id == INVITE_ROLE}
    spent = {m.participant_id for m in members if m.role_id == SPENT_ROLE}
    if not any(hmac.compare_digest(invite_root, item) for item in issued):
        raise InvalidCell("this invite is not valid for this address and firm")
    if invite_root in spent:
        raise InvalidCell("this invite was already accepted")
    patch = prepare_append_relation_members(snapshot, firm_root, (
        (MEMBER_ROLE, member_root),
        (SPENT_ROLE, invite_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return member_root


def token_is_readable(snapshot, token):
    """Court helper: the raw token must appear nowhere in the graph."""
    needle = token.encode("utf-8")
    return any(needle in bytes(cell.atom) for cell in snapshot.cells.values())
