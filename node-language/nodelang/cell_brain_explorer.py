"""Browsing memory: folders that are derived, never maintained.

`brain_explorer` in the superseded app kept a folder tree beside the facts. A
maintained tree drifts the moment anything writes without updating it, and then
the founder is browsing a picture of memory instead of memory.

Here a folder is not stored at all. It is computed from the facts the graph
holds, every time. Delete a fact and its folder shrinks in the same breath;
delete every fact in a folder and the folder is simply not there.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

SHELF_ROOT = "app:brain:memory-shelf"
FACT_ROLE = SHELF_ROOT + ":role:fact"
KIND_ROLE = SHELF_ROOT + ":role:kind"
TITLE_ROLE = SHELF_ROOT + ":role:title"


@dataclass(frozen=True, slots=True)
class Folder:
    kind: str
    count: int
    fact_roots: tuple


@dataclass(frozen=True, slots=True)
class Remembered:
    fact_root: str
    kind: str
    title: str


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("shelf text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_shelf(store):
    snapshot = store.snapshot()
    if SHELF_ROOT in snapshot.cells:
        return SHELF_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(FACT_ROLE, "fact"),
        _terminal(KIND_ROLE, "kind"),
        _terminal(TITLE_ROLE, "title"),
        Cell(SHELF_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return SHELF_ROOT


def _entry_root(fact_root):
    return "%s:entry:%s" % (SHELF_ROOT, fact_root)


def shelve_fact(store, *, fact_root, kind, title):
    """Put a fact on the shelf under a kind. The kind is a fact, not a folder."""
    kind = kind.strip()
    title = title.strip()
    if not kind:
        raise InvalidCell("a fact without a kind cannot be browsed")
    if not title:
        raise InvalidCell("a fact without a title cannot be recognised")
    snapshot = store.snapshot()
    if fact_root not in snapshot.cells:
        raise InvalidCell("cannot shelve a fact the graph does not hold")
    ensure_shelf(store)
    snapshot = store.snapshot()
    entry = _entry_root(fact_root)
    if entry in snapshot.cells:
        raise InvalidCell("fact is already on the shelf: %s" % fact_root)
    kind_root = entry + ":kind"
    title_root = entry + ":title"
    store.commit(snapshot.revision, create=(
        _terminal(kind_root, kind),
        _terminal(title_root, title),
        Cell(entry, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, entry, (
        (FACT_ROLE, fact_root),
        (KIND_ROLE, kind_root),
        (TITLE_ROLE, title_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    shelf = prepare_append_relation_members(
        snapshot, SHELF_ROOT, ((FACT_ROLE, entry),), budget=100_000)
    store.commit(snapshot.revision, create=shelf.create, replace=shelf.replace)
    return entry


def _entries(snapshot):
    if SHELF_ROOT not in snapshot.cells:
        return ()
    found = []
    for member in read_relation(snapshot, SHELF_ROOT, budget=100_000):
        if member.role_id != FACT_ROLE:
            continue
        entry = member.participant_id
        members = read_relation(snapshot, entry, budget=10_000)

        def one(role, label):
            values = [m.participant_id for m in members if m.role_id == role]
            if len(values) != 1:
                raise InvalidCell("shelf entry has no single %s" % label)
            return values[0]

        fact_root = one(FACT_ROLE, "fact")
        if fact_root not in snapshot.cells:
            # The fact is gone. A derived shelf does not keep its ghost.
            continue
        found.append(Remembered(
            fact_root,
            _text(snapshot, one(KIND_ROLE, "kind")),
            _text(snapshot, one(TITLE_ROLE, "title")),
        ))
    return tuple(found)


def folders(snapshot):
    """Every folder, derived. Nothing is stored under this name."""
    grouped = {}
    for entry in _entries(snapshot):
        grouped.setdefault(entry.kind, []).append(entry.fact_root)
    return tuple(
        Folder(kind, len(roots), tuple(sorted(roots)))
        for kind, roots in sorted(grouped.items())
    )


def open_folder(snapshot, kind):
    """What is in one folder, by title."""
    inside = [entry for entry in _entries(snapshot) if entry.kind == kind]
    if not inside:
        raise InvalidCell("no folder holds anything of that kind: %s" % kind)
    return tuple(sorted(inside, key=lambda item: item.title))


def total_remembered(snapshot):
    return len(_entries(snapshot))
