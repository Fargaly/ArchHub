"""A session that cannot silently fail to save.

The old save wrote and hoped. A save that cannot be read back identically is not
a save, so this one reads it back before it says yes.

Autosave fired on a timer and wrote whatever it found, so an idle session
produced revisions forever. Saving the same payload twice does nothing here --
the debounce is a fact about the payload, not a timer.

A session moves draft to active to closed and no other way, so a closed session
cannot quietly accept more work.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .cell_brain_ownership import bind_owner, read_owner
from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

SESSIONS_ROOT = "app:sessions"
SESSION_ROLE = SESSIONS_ROOT + ":role:session"
STATE_ROLE = SESSIONS_ROOT + ":role:state"
PARAM_ROLE = SESSIONS_ROOT + ":role:parameter"
SAVE_ROLE = SESSIONS_ROOT + ":role:save"
PIN_ROLE = SESSIONS_ROOT + ":role:pinned"

DRAFT = SESSIONS_ROOT + ":state:draft"
ACTIVE = SESSIONS_ROOT + ":state:active"
CLOSED = SESSIONS_ROOT + ":state:closed"

LEGAL_MOVES = {DRAFT: (ACTIVE,), ACTIVE: (CLOSED,), CLOSED: ()}


@dataclass(frozen=True, slots=True)
class Session:
    root_id: str
    owner_root: str
    state: str
    parameters: dict
    saves: tuple
    pinned: bool


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("session text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_sessions(store):
    snapshot = store.snapshot()
    if SESSIONS_ROOT in snapshot.cells:
        return SESSIONS_ROOT
    created = [
        _terminal(SESSION_ROLE, "session"), _terminal(STATE_ROLE, "state"),
        _terminal(PARAM_ROLE, "parameter"), _terminal(SAVE_ROLE, "save"),
        _terminal(PIN_ROLE, "pinned"),
    ]
    created.extend(
        _terminal(s, s.rsplit(":", 1)[-1]) for s in (DRAFT, ACTIVE, CLOSED))
    created.append(Cell(SESSIONS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"))
    store.commit(snapshot.revision, create=tuple(created))
    return SESSIONS_ROOT


def open_session(store, *, session_root, owner_root):
    snapshot = store.snapshot()
    if owner_root not in snapshot.cells:
        raise InvalidCell("session owner is not a root the graph holds")
    if session_root in snapshot.cells:
        raise InvalidCell("session already exists: %s" % session_root)
    ensure_sessions(store)
    snapshot = store.snapshot()
    store.commit(snapshot.revision, create=(
        Cell(session_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, session_root, ((STATE_ROLE, DRAFT),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    bind_owner(store, subject_root=session_root, owner_root=owner_root)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, SESSIONS_ROOT, ((SESSION_ROLE, session_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return session_root


def read_session(snapshot, session_root):
    if session_root not in snapshot.cells:
        raise InvalidCell("no such session: %s" % session_root)
    members = read_relation(snapshot, session_root, budget=100_000)
    state = [m.participant_id for m in members if m.role_id == STATE_ROLE]
    if len(state) != 1:
        raise InvalidCell("session has no single state")
    params = {}
    for m in members:
        if m.role_id != PARAM_ROLE:
            continue
        key = m.participant_id.rsplit(":param:", 1)[-1]
        params[key] = _text(snapshot, m.participant_id)
    saves = tuple(
        _text(snapshot, m.participant_id)
        for m in members if m.role_id == SAVE_ROLE
    )
    return Session(
        session_root, read_owner(snapshot, session_root), state[0],
        params, saves,
        any(m.role_id == PIN_ROLE for m in members),
    )


def move_to(store, session_root, target_state):
    """Draft to active to closed. Nothing else, in either direction."""
    snapshot = store.snapshot()
    session = read_session(snapshot, session_root)
    if target_state not in LEGAL_MOVES.get(session.state, ()):
        raise InvalidCell(
            "a session cannot move from %s to %s" % (session.state, target_state))
    members = read_relation(snapshot, session_root, budget=100_000)
    state_member = next(m for m in members if m.role_id == STATE_ROLE)
    incidence = snapshot.cells[state_member.incidence_id]
    store.commit(snapshot.revision, replace=(
        Cell(incidence.id, incidence.link0, target_state, incidence.atom),))
    return target_state


def set_parameter(store, session_root, *, key, value):
    """The parameter pool. A closed session takes nothing more."""
    key = key.strip()
    if not key:
        raise InvalidCell("a parameter without a name cannot be recalled")
    snapshot = store.snapshot()
    session = read_session(snapshot, session_root)
    if session.state == CLOSED:
        raise InvalidCell("a closed session cannot take more parameters")
    param_root = "%s:param:%s" % (session_root, key)
    if param_root in snapshot.cells:
        store.commit(snapshot.revision, replace=(_terminal(param_root, value),))
        return param_root
    store.commit(snapshot.revision, create=(_terminal(param_root, value),))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(
        snapshot, session_root, ((PARAM_ROLE, param_root),), budget=100_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return param_root


def _digest(payload):
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save(store, session_root, *, payload):
    """Write, then read back. A save that does not round-trip is not a save."""
    if not payload:
        raise InvalidCell("saving nothing would erase the session")
    snapshot = store.snapshot()
    session = read_session(snapshot, session_root)
    if session.state == CLOSED:
        raise InvalidCell("a closed session cannot be saved to")
    digest = _digest(payload)
    save_root = "%s:save:%s" % (session_root, digest)
    if save_root in snapshot.cells:
        raise InvalidCell("that exact payload is already saved")
    store.commit(snapshot.revision, create=(_terminal(save_root, payload),))
    snapshot = store.snapshot()
    if _text(snapshot, save_root) != payload:
        raise InvalidCell("the save did not round-trip and was not accepted")
    patch = prepare_append_relation_members(
        snapshot, session_root, ((SAVE_ROLE, save_root),), budget=100_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return save_root


def autosave(store, session_root, *, payload):
    """Saving the same thing twice does nothing. True when it actually wrote."""
    snapshot = store.snapshot()
    session = read_session(snapshot, session_root)
    if session.saves and session.saves[-1] == payload:
        return False
    save(store, session_root, payload=payload)
    return True


def pin(store, session_root):
    snapshot = store.snapshot()
    session = read_session(snapshot, session_root)
    if session.pinned:
        raise InvalidCell("session is already pinned")
    patch = prepare_append_relation_members(
        snapshot, session_root, ((PIN_ROLE, session_root),), budget=100_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return True


def replay(snapshot, session_root):
    """Every save, oldest first. The session is its own history."""
    return read_session(snapshot, session_root).saves
