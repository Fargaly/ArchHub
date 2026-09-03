"""Reflexion: a failure is not closed by explaining it, only by controlling it.

The superseded app ran a reflexion worker that wrote notes. A note is not a
control. Fixing root causes is only real if the graph REFUSES to close a failure
that has no control attached, and if the second occurrence of the same failure
says out loud that the control did not work.

A signature is what makes two failures the same failure. Recurrence is measured
against it, not against wording.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

LEDGER_ROOT = "app:brain:reflexion-ledger"
FAILURE_ROLE = LEDGER_ROOT + ":role:failure"
SIGNATURE_ROLE = LEDGER_ROOT + ":role:signature"
NARRATIVE_ROLE = LEDGER_ROOT + ":role:what-happened"
EVIDENCE_ROLE = LEDGER_ROOT + ":role:evidence"
CAUSE_ROLE = LEDGER_ROOT + ":role:root-cause"
CONTROL_ROLE = LEDGER_ROOT + ":role:control"
STATE_ROLE = LEDGER_ROOT + ":role:state"

OPEN = LEDGER_ROOT + ":state:open"
CONTROLLED = LEDGER_ROOT + ":state:controlled"
RECURRED = LEDGER_ROOT + ":state:recurred"

_ROLES = (
    FAILURE_ROLE, SIGNATURE_ROLE, NARRATIVE_ROLE, EVIDENCE_ROLE,
    CAUSE_ROLE, CONTROL_ROLE, STATE_ROLE,
)
_STATES = (OPEN, CONTROLLED, RECURRED)


@dataclass(frozen=True, slots=True)
class Reflexion:
    root_id: str
    signature: str
    what_happened: str
    evidence_roots: tuple
    root_cause: str | None
    control_roots: tuple
    state: str


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("reflexion text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_ledger(store):
    snapshot = store.snapshot()
    if LEDGER_ROOT in snapshot.cells:
        return LEDGER_ROOT
    created = [_terminal(role, role.rsplit(":", 1)[-1]) for role in _ROLES]
    created.extend(_terminal(s, s.rsplit(":", 1)[-1]) for s in _STATES)
    created.append(Cell(LEDGER_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"))
    store.commit(snapshot.revision, create=tuple(created))
    return LEDGER_ROOT


def _failure_root(signature, occurrence):
    return "%s:failure:%s:%d" % (LEDGER_ROOT, signature, occurrence)


def _read(snapshot, root):
    members = read_relation(snapshot, root, budget=10_000)

    def many(role):
        return tuple(m.participant_id for m in members if m.role_id == role)

    def one(role, label):
        found = many(role)
        if len(found) != 1:
            raise InvalidCell("reflexion has no single %s" % label)
        return found[0]

    causes = many(CAUSE_ROLE)
    return Reflexion(
        root,
        _text(snapshot, one(SIGNATURE_ROLE, "signature")),
        _text(snapshot, one(NARRATIVE_ROLE, "narrative")),
        many(EVIDENCE_ROLE),
        _text(snapshot, causes[0]) if causes else None,
        many(CONTROL_ROLE),
        one(STATE_ROLE, "state"),
    )


def occurrences(snapshot, signature):
    """Every time this exact failure has been seen, oldest first."""
    if LEDGER_ROOT not in snapshot.cells:
        return ()
    found = []
    for member in read_relation(snapshot, LEDGER_ROOT, budget=100_000):
        if member.role_id != FAILURE_ROLE:
            continue
        entry = _read(snapshot, member.participant_id)
        if entry.signature == signature:
            found.append(entry)
    return tuple(found)


def record_failure(store, *, signature, what_happened, evidence_roots):
    """Record a failure. A second with the same signature is a RECURRENCE."""
    signature = signature.strip()
    what_happened = what_happened.strip()
    if not signature:
        raise InvalidCell("a failure without a signature cannot recur or be found")
    if not what_happened:
        raise InvalidCell("a failure must say what happened")
    evidence = tuple(dict.fromkeys(evidence_roots))
    if not evidence:
        raise InvalidCell("a failure without evidence is an opinion")
    ensure_ledger(store)
    snapshot = store.snapshot()
    if any(root not in snapshot.cells for root in evidence):
        raise InvalidCell("failure evidence references missing cells")

    prior = occurrences(snapshot, signature)
    root = _failure_root(signature, len(prior))
    state = RECURRED if prior else OPEN
    sig_root = root + ":signature"
    narrative_root = root + ":narrative"
    store.commit(snapshot.revision, create=(
        _terminal(sig_root, signature),
        _terminal(narrative_root, what_happened),
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    members = [
        (SIGNATURE_ROLE, sig_root),
        (NARRATIVE_ROLE, narrative_root),
        (STATE_ROLE, state),
    ]
    members.extend((EVIDENCE_ROLE, item) for item in evidence)
    patch = prepare_append_relation_members(snapshot, root, members, budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    ledger = prepare_append_relation_members(
        snapshot, LEDGER_ROOT, ((FAILURE_ROLE, root),), budget=100_000)
    store.commit(snapshot.revision, create=ledger.create, replace=ledger.replace)
    return root


def control_failure(store, failure_root, *, root_cause, control_roots):
    """Close a failure by naming its cause AND the control that prevents it."""
    root_cause = root_cause.strip()
    controls = tuple(dict.fromkeys(control_roots))
    if not root_cause:
        raise InvalidCell("a failure is not controlled by describing it")
    if not controls:
        raise InvalidCell("a root cause without a control changes nothing")
    snapshot = store.snapshot()
    if failure_root not in snapshot.cells:
        raise InvalidCell("no such failure: %s" % failure_root)
    if any(root not in snapshot.cells for root in controls):
        raise InvalidCell("control references missing cells")
    entry = _read(snapshot, failure_root)
    if entry.state == CONTROLLED:
        raise InvalidCell("failure is already controlled")

    cause_root = failure_root + ":root-cause"
    if cause_root not in snapshot.cells:
        store.commit(snapshot.revision, create=(_terminal(cause_root, root_cause),))
        snapshot = store.snapshot()
    members = read_relation(snapshot, failure_root, budget=10_000)
    state_member = next(m for m in members if m.role_id == STATE_ROLE)
    incidence = snapshot.cells[state_member.incidence_id]
    store.commit(snapshot.revision, replace=(
        Cell(incidence.id, incidence.link0, CONTROLLED, incidence.atom),
    ))
    snapshot = store.snapshot()
    additions = [(CAUSE_ROLE, cause_root)]
    additions.extend((CONTROL_ROLE, control) for control in controls)
    patch = prepare_append_relation_members(
        snapshot, failure_root, additions, budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return CONTROLLED


def read_reflexion(snapshot, failure_root):
    if failure_root not in snapshot.cells:
        raise InvalidCell("no such failure: %s" % failure_root)
    return _read(snapshot, failure_root)


def failed_controls(snapshot, signature):
    """Controls that were supposed to stop this and did not."""
    prior = occurrences(snapshot, signature)
    if len(prior) < 2:
        return ()
    controls = []
    for entry in prior[:-1]:
        controls.extend(entry.control_roots)
    return tuple(dict.fromkeys(controls))
