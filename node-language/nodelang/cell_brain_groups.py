"""Groups and join codes: the graph holds the fingerprint, never the code.

`community_join_code` stored codes so it could compare them later. A stored
credential is a leaked credential the moment anything projects, syncs, or backs
up the store -- and this store does all three. The code is hashed on the way in
and only the fingerprint is kept, so verifying a code is possible and reading
one out is not.

Only the owner of a group may issue a code, and a code that has been spent
cannot be spent again.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .cell_brain_ownership import bind_owner, read_owner
from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

GROUPS_ROOT = "app:brain:groups"
GROUP_ROLE = GROUPS_ROOT + ":role:group"
MEMBER_ROLE = GROUPS_ROOT + ":role:member"
CODE_ROLE = GROUPS_ROOT + ":role:join-code"
SPENT_ROLE = GROUPS_ROOT + ":role:spent"

MINIMUM_CODE_LENGTH = 12


@dataclass(frozen=True, slots=True)
class Group:
    root_id: str
    owner_root: str
    member_roots: tuple


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def fingerprint(group_root, code):
    """A code becomes a fingerprint bound to its group and nothing else."""
    return hashlib.sha256(
        (group_root + "\x00" + code).encode("utf-8")
    ).hexdigest()


def ensure_groups(store):
    snapshot = store.snapshot()
    if GROUPS_ROOT in snapshot.cells:
        return GROUPS_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(GROUP_ROLE, "group"),
        _terminal(MEMBER_ROLE, "member"),
        _terminal(CODE_ROLE, "join-code"),
        _terminal(SPENT_ROLE, "spent"),
        Cell(GROUPS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return GROUPS_ROOT


def create_group(store, *, group_root, owner_root):
    """A group has exactly one owner, recorded the same way anything else is."""
    snapshot = store.snapshot()
    if owner_root not in snapshot.cells:
        raise InvalidCell("group owner is not a root the graph holds")
    if group_root in snapshot.cells:
        raise InvalidCell("group already exists: %s" % group_root)
    ensure_groups(store)
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(
        Cell(group_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, group_root, ((MEMBER_ROLE, owner_root),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    bind_owner(store, subject_root=group_root, owner_root=owner_root)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, GROUPS_ROOT, ((GROUP_ROLE, group_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return group_root


def read_group(snapshot, group_root):
    if group_root not in snapshot.cells:
        raise InvalidCell("no such group: %s" % group_root)
    members = read_relation(snapshot, group_root, budget=10_000)
    return Group(
        group_root,
        read_owner(snapshot, group_root),
        tuple(sorted(
            m.participant_id for m in members if m.role_id == MEMBER_ROLE)),
    )


def issue_join_code(store, *, group_root, code, issuer_root):
    """Only the owner issues. Only the fingerprint is kept."""
    snapshot = store.snapshot()
    group = read_group(snapshot, group_root)
    if group.owner_root != issuer_root:
        raise InvalidCell("only the owner of a group may issue a join code")
    if len(code) < MINIMUM_CODE_LENGTH:
        raise InvalidCell(
            "a join code shorter than %d characters is guessable"
            % MINIMUM_CODE_LENGTH
        )
    digest = fingerprint(group_root, code)
    code_root = "%s:code:%s" % (group_root, digest)
    if code_root in snapshot.cells:
        raise InvalidCell("that join code was already issued")
    store.commit(snapshot.revision, create=(_terminal(code_root, digest),))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, group_root, ((CODE_ROLE, code_root),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return code_root


def _code_state(snapshot, group_root):
    members = read_relation(snapshot, group_root, budget=10_000)
    issued = {m.participant_id for m in members if m.role_id == CODE_ROLE}
    spent = {m.participant_id for m in members if m.role_id == SPENT_ROLE}
    return issued, spent


def join_with_code(store, *, group_root, code, member_root):
    """Spend a code once. A wrong code says nothing about the right one."""
    snapshot = store.snapshot()
    read_group(snapshot, group_root)
    if member_root not in snapshot.cells:
        raise InvalidCell("joining member is not a root the graph holds")
    digest = fingerprint(group_root, code)
    code_root = "%s:code:%s" % (group_root, digest)
    issued, spent = _code_state(snapshot, group_root)
    if not any(hmac.compare_digest(code_root, item) for item in issued):
        raise InvalidCell("join code is not valid for this group")
    if code_root in spent:
        raise InvalidCell("join code was already used")
    patch = prepare_append_relation_members(snapshot, group_root, (
        (MEMBER_ROLE, member_root),
        (SPENT_ROLE, code_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return member_root


def code_is_readable(snapshot, group_root, code):
    """Court helper: the raw code must appear nowhere in the graph."""
    needle = code.encode("utf-8")
    return any(needle in bytes(cell.atom) for cell in snapshot.cells.values())
