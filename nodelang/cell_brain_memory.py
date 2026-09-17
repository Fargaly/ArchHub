"""Personal memory held in the graph: what the brain remembers, as Cells.

The legacy brain (12.PRODUCTION personal-brain-mcp storage.py) kept every fact
in a SQLite table beside the graph and handed the graph hash receipts, so the
graph never held the memory it was said to govern. Here a memory IS graph
state, built only from the owners that already exist:

* one entry relation per memory, registered under ``app:brain:memory``;
* its text and its live-or-forgotten state carried by ``cell_brain_sync``:
  every write names an origin and a clock, the later clock wins, a tie breaks
  on origin, and replaying a write changes nothing;
* exactly one owner, bound through ``cell_brain_ownership``, never a default.

No call takes an owner. Every call names the SESSION it acts in, and the owner
is read from the graph: the ``cell_session_state`` session is bound to its
account when the application opens it for a signed-in person. A caller cannot
name somebody else as the owner, because there is no argument to name one with.
A closed session acts for nobody.

A memory lives at a root derived from its owner and its source id, so the same
source id under two owners is two memories. Writing one memory -- new or
existing, a remember, a forget or a merged record -- is ONE commit; a
concurrent writer makes the whole write start again from a fresh snapshot.

Forgetting is a state, not a deletion. A Cell commit cannot delete, and a
forget has to reach every replica the same way an edit does. Skills, secret
references, wiring and traces are not personal memory: each has its own owner.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import cell_brain_ownership as ownership
from . import cell_session_state as sessions
from .cell_brain_secrets import assert_no_credential_in_text, assert_not_a_secret
from .cell_brain_sync import fragment_cells, held, make_fragment
from .cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, Conflict, InvalidCell

MEMORY_ROOT = "app:brain:memory"
ENTRY_ROLE = MEMORY_ROOT + ":role:entry"
TEXT_ROLE = MEMORY_ROOT + ":role:text"
STATE_ROLE = MEMORY_ROOT + ":role:state"
KIND_ROLE = MEMORY_ROOT + ":role:kind"
CONFIDENCE_ROLE = MEMORY_ROOT + ":role:confidence"
SOURCE_ID_ROLE = MEMORY_ROOT + ":role:source-id"

# Personal memory kinds. skill belongs to cell_brain_skills, secret_ref to the
# secret vault, wiring to its own owner; trace, geometry and image are not text
# the brain recalls.
MEMORY_KINDS = frozenset((
    "fact", "setup", "spatial", "document", "mandate", "hook", "practice",
))
CONFIDENCES = frozenset(("extracted", "inferred"))
LIVE = "live"
FORGOTTEN = "forgotten"
STATES = frozenset((LIVE, FORGOTTEN))

_WRITE_ATTEMPTS = 8


@dataclass(frozen=True, slots=True)
class Memory:
    fragment_id: str
    text: str
    kind: str
    confidence: str
    owner_root: str
    state: str
    text_origin: str
    text_clock: int
    state_origin: str
    state_clock: int


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def acting_owner(snapshot, session_root):
    """The owner a session acts for, read from the graph. Never an argument."""
    if not isinstance(session_root, str) or session_root not in snapshot.cells:
        raise InvalidCell("memory calls need an open session")
    try:
        session = sessions.read_session(snapshot, session_root)
    except InvalidCell:
        raise InvalidCell("memory calls need an open session") from None
    if session.state == sessions.CLOSED:
        raise InvalidCell("a closed session acts for nobody")
    return session.owner_root


def entry_root(owner_root, fragment_id):
    """Where one owner's memory of one source id lives.

    Keyed by a digest of the owner AND the source id, so one owner's id can
    never address another owner's memory, and no source id can collide with
    another root or with the suffixes the sync law adds to the roots it carries.
    """
    key = "%s\n%s" % (owner_root, fragment_id)
    return "%s:entry:%s" % (MEMORY_ROOT, hashlib.sha256(key.encode("utf-8")).hexdigest())


def _text_root(entry):
    return entry + ":text"


def _state_root(entry):
    return entry + ":state"


def _kind_root(entry):
    return entry + ":kind"


def _confidence_root(entry):
    return entry + ":confidence"


def _source_root(entry):
    return entry + ":source-id"


def ensure_memory(store):
    snapshot = store.snapshot()
    if MEMORY_ROOT in snapshot.cells:
        return MEMORY_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(ENTRY_ROLE, "entry"),
        _terminal(TEXT_ROLE, "text"),
        _terminal(STATE_ROLE, "state"),
        _terminal(KIND_ROLE, "kind"),
        _terminal(CONFIDENCE_ROLE, "confidence"),
        _terminal(SOURCE_ID_ROLE, "source-id"),
        Cell(MEMORY_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return MEMORY_ROOT


def _atom_text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("a memory part is missing")
    return bytes(cell.atom).decode("utf-8")


def _read(snapshot, root):
    found = {}
    for member in read_relation(snapshot, root, budget=10_000):
        found.setdefault(member.role_id, []).append(member.participant_id)

    def one(role, label):
        items = found.get(role, ())
        if len(items) != 1:
            raise InvalidCell("memory has no single %s" % label)
        return items[0]

    text = held(snapshot, one(TEXT_ROLE, "text"))
    state = held(snapshot, one(STATE_ROLE, "state"))
    if text is None or state is None:
        raise InvalidCell("a memory lost its synced parts")
    return Memory(
        _atom_text(snapshot, one(SOURCE_ID_ROLE, "source id")),
        text.value,
        _atom_text(snapshot, one(KIND_ROLE, "kind")),
        _atom_text(snapshot, one(CONFIDENCE_ROLE, "confidence")),
        ownership.read_owner(snapshot, root),
        state.value,
        text.origin,
        text.clock,
        state.origin,
        state.clock,
    )


def _check_memory(fragment_id, text, kind, confidence, *origins):
    """Refuse without echoing the refused value into the error."""
    if not isinstance(fragment_id, str) or not fragment_id.strip():
        raise InvalidCell("a memory must name the fragment it carries")
    if not isinstance(text, str) or not text.strip():
        raise InvalidCell("a memory without text remembers nothing")
    if kind not in MEMORY_KINDS:
        raise InvalidCell("that kind is not personal memory; it has its own owner")
    if confidence not in CONFIDENCES:
        raise InvalidCell("memory confidence must be extracted or inferred")
    assert_not_a_secret(text, "memory text")
    assert_no_credential_in_text(text, "memory text")
    assert_no_credential_in_text(fragment_id, "memory source id")
    for origin in origins:
        if isinstance(origin, str):
            assert_no_credential_in_text(origin, "memory origin")


def _fragments_patch(snapshot, fragments):
    """Create or replace the sync Cells of every winning fragment, one commit's worth."""
    winners = {}
    for fragment in fragments:
        best = winners.get(fragment.root_id)
        if best is None or fragment.wins_over(best):
            winners[fragment.root_id] = fragment
    create, replace = [], []
    for root_id, fragment in winners.items():
        current = held(snapshot, root_id)
        if current is None:
            create.extend(fragment_cells(fragment))
        elif fragment.wins_over(current):
            replace.extend(fragment_cells(fragment))
    return tuple(create), tuple(replace)


def _new_memory_patch(snapshot, root, *, owner_root, fragment_id, kind, confidence,
                      fragments):
    """Every Cell of one new memory, for a single commit against ``snapshot``."""
    parts = compose_relation_cells((
        (TEXT_ROLE, _text_root(root)),
        (STATE_ROLE, _state_root(root)),
        (KIND_ROLE, _kind_root(root)),
        (CONFIDENCE_ROLE, _confidence_root(root)),
        (SOURCE_ID_ROLE, _source_root(root)),
    ), relation_id=root)
    binding = ownership.prepare_bind_owner(
        snapshot, subject_root=root, owner_root=owner_root)
    registry = prepare_append_relation_members(
        snapshot, MEMORY_ROOT, ((ENTRY_ROLE, root),), budget=1_000_000)
    synced, _ = _fragments_patch(snapshot, fragments)
    create = (
        synced
        + (
            _terminal(_kind_root(root), kind),
            _terminal(_confidence_root(root), confidence),
            _terminal(_source_root(root), fragment_id),
        )
        + tuple(parts.cells)
        + binding.create
        + tuple(registry.create)
    )
    return create, binding.replace + tuple(registry.replace)


def _write(store, *, owner_root, fragment_id, kind, confidence, fragments, create_if_new):
    """One memory, one commit, restarted whole when a concurrent writer wins."""
    root = entry_root(owner_root, fragment_id)
    conflict = None
    for _ in range(_WRITE_ATTEMPTS):
        try:
            snapshot = store.snapshot()
            if owner_root not in snapshot.cells:
                raise InvalidCell("memory owner is not a root the graph holds")
            if root in snapshot.cells:
                current = _read(snapshot, root)
                if current.owner_root != owner_root:
                    raise InvalidCell("this memory belongs to another owner")
                if kind is not None and current.kind != kind:
                    raise InvalidCell(
                        "a memory cannot change kind by being remembered again")
                create, replace = _fragments_patch(snapshot, fragments)
                if create or replace:
                    store.commit(snapshot.revision, create=create, replace=replace)
                return root
            if not create_if_new:
                raise InvalidCell("cannot forget what was never remembered")
            if (MEMORY_ROOT not in snapshot.cells
                    or ownership.REGISTRY_ROOT not in snapshot.cells):
                ensure_memory(store)
                ownership.ensure_registry(store)
                continue
            create, replace = _new_memory_patch(
                snapshot, root, owner_root=owner_root, fragment_id=fragment_id,
                kind=kind, confidence=confidence, fragments=fragments)
            store.commit(snapshot.revision, create=create, replace=replace)
            return root
        except Conflict as error:
            conflict = error
    raise conflict or Conflict("memory write kept losing to concurrent writers")


def remember(store, *, session_root, fragment_id, text, kind, origin, clock,
             confidence="extracted"):
    """Hold one personal memory for the session's owner, or carry a newer version.

    Everything is checked before the first commit, so a refused memory leaves
    the graph exactly as it was. Remembering again cannot change its kind; the
    text and the live state follow the sync law and land together.
    """
    owner_root = acting_owner(store.snapshot(), session_root)
    _check_memory(fragment_id, text, kind, confidence, origin)
    root = entry_root(owner_root, fragment_id)
    fragments = (
        make_fragment(_text_root(root), origin, clock, text),
        make_fragment(_state_root(root), origin, clock, LIVE),
    )
    return _write(store, owner_root=owner_root, fragment_id=fragment_id, kind=kind,
                  confidence=confidence, fragments=fragments, create_if_new=True)


def _owned_root(snapshot, owner_root, fragment_id):
    """The owner's memory root, or None. A root bound to anyone else is refused."""
    root = entry_root(owner_root, str(fragment_id))
    if root not in snapshot.cells:
        return None
    if ownership.read_owner(snapshot, root) != owner_root:
        raise InvalidCell("this memory belongs to another owner")
    return root


def forget(store, *, session_root, fragment_id, origin, clock):
    """Mark the session owner's memory forgotten. It stays readable as what it was."""
    snapshot = store.snapshot()
    owner_root = acting_owner(snapshot, session_root)
    if isinstance(origin, str):
        assert_no_credential_in_text(origin, "memory origin")
    root = _owned_root(snapshot, owner_root, fragment_id)
    if root is None:
        raise InvalidCell("cannot forget what was never remembered")
    fragments = (make_fragment(_state_root(root), origin, clock, FORGOTTEN),)
    return _write(store, owner_root=owner_root, fragment_id=fragment_id, kind=None,
                  confidence=None, fragments=fragments, create_if_new=False)


def recall_by_owner(snapshot, owner_root, fragment_id):
    """For owners that already resolved the acting owner from a session."""
    root = _owned_root(snapshot, owner_root, fragment_id)
    return None if root is None else _read(snapshot, root)


def recall_memory(snapshot, fragment_id, *, session_root):
    """The session owner's memory, or None when it never remembered it."""
    return recall_by_owner(snapshot, acting_owner(snapshot, session_root), fragment_id)


def _memories(snapshot, owner_root, kind=None, include_forgotten=False):
    if MEMORY_ROOT not in snapshot.cells:
        return ()
    found = []
    for member in read_relation(snapshot, MEMORY_ROOT, budget=1_000_000):
        if member.role_id != ENTRY_ROLE:
            continue
        if ownership.read_owner(snapshot, member.participant_id) != owner_root:
            continue
        memory = _read(snapshot, member.participant_id)
        if member.participant_id != entry_root(owner_root, memory.fragment_id):
            continue  # bound to this owner but not addressable by it
        if kind is not None and memory.kind != kind:
            continue
        if memory.state == FORGOTTEN and not include_forgotten:
            continue
        found.append(memory)
    return tuple(sorted(
        found,
        key=lambda m: (-max(m.text_clock, m.state_clock), m.fragment_id)))


def memories(snapshot, *, session_root, kind=None, include_forgotten=False):
    """The session owner's memories, newest first."""
    return _memories(snapshot, acting_owner(snapshot, session_root), kind,
                     include_forgotten)


def export_memories(snapshot, *, session_root, since_clock=0):
    """The session owner's memories changed at or after a clock, forgotten included."""
    if not isinstance(since_clock, int) or isinstance(since_clock, bool) or since_clock < 0:
        raise InvalidCell("a memory export cannot start before the beginning")
    return tuple(
        memory
        for memory in memories(snapshot, session_root=session_root, include_forgotten=True)
        if max(memory.text_clock, memory.state_clock) >= since_clock)


def merge_memories(store, records, *, session_root):
    """Apply memories another replica of the SAME owner exported.

    Every record is checked against the current graph before the first write: a
    record naming another owner, a record whose memory already exists with
    another kind, or a record that could not be remembered refuses the whole
    batch. Each record then lands text and state in one commit. Order-
    independent, and merging the same export again changes nothing.
    """
    snapshot = store.snapshot()
    owner_root = acting_owner(snapshot, session_root)
    records = tuple(records)
    shape = {}
    for record in records:
        if not isinstance(record, Memory):
            raise InvalidCell("only an exported memory can be merged")
        if shape.setdefault(record.fragment_id, record.kind) != record.kind:
            raise InvalidCell("a merge cannot carry one memory as two kinds")
        if record.owner_root != owner_root:
            raise InvalidCell("a merge cannot carry another owner's memory")
        if record.state not in STATES:
            raise InvalidCell("memory state must be live or forgotten")
        _check_memory(record.fragment_id, record.text, record.kind, record.confidence,
                      record.text_origin, record.state_origin)
        make_fragment(MEMORY_ROOT, record.text_origin, record.text_clock, "")
        make_fragment(MEMORY_ROOT, record.state_origin, record.state_clock, "")
        existing = _owned_root(snapshot, owner_root, record.fragment_id)
        if existing is not None and _read(snapshot, existing).kind != record.kind:
            raise InvalidCell("a merge cannot change a memory's kind")
    for record in records:
        root = entry_root(owner_root, record.fragment_id)
        fragments = (
            make_fragment(_text_root(root), record.text_origin, record.text_clock,
                          record.text),
            make_fragment(_state_root(root), record.text_origin, record.text_clock, LIVE),
            make_fragment(_state_root(root), record.state_origin, record.state_clock,
                          record.state),
        )
        _write(store, owner_root=owner_root, fragment_id=record.fragment_id,
               kind=record.kind, confidence=record.confidence, fragments=fragments,
               create_if_new=True)
    return len(records)
