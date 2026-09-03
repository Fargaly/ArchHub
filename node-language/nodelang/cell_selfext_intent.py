"""Asking for something, and what the graph refuses to do about it.

The self-extension loop starts where it is most dangerous: a person asks in
plain language and something starts building. `selfext_agency_gate` existed to
stop that, and it was advisory -- so it stopped nothing.

Here the gate is structural. An intent with no granted scope cannot be broken
into work at all, a leaf outside the granted scope is refused, and nothing may
be built until the library has actually been searched. Every one of those is a
refusal, not a warning.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

INTENTS_ROOT = "app:selfext:intents"
INTENT_ROLE = INTENTS_ROOT + ":role:intent"
TEXT_ROLE = INTENTS_ROOT + ":role:text"
ASKER_ROLE = INTENTS_ROOT + ":role:asker"
SCOPE_ROLE = INTENTS_ROOT + ":role:granted-scope"
LEAF_ROLE = INTENTS_ROOT + ":role:leaf"
SEARCH_ROLE = INTENTS_ROOT + ":role:library-search"


@dataclass(frozen=True, slots=True)
class Intent:
    root_id: str
    text: str
    asker_root: str
    granted_scope: tuple
    leaves: tuple
    searched: bool


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("intent text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def ensure_intents(store):
    snapshot = store.snapshot()
    if INTENTS_ROOT in snapshot.cells:
        return INTENTS_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(INTENT_ROLE, "intent"),
        _terminal(TEXT_ROLE, "text"),
        _terminal(ASKER_ROLE, "asker"),
        _terminal(SCOPE_ROLE, "granted-scope"),
        _terminal(LEAF_ROLE, "leaf"),
        _terminal(SEARCH_ROLE, "library-search"),
        Cell(INTENTS_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return INTENTS_ROOT


def ask(store, *, intent_root, text, asker_root):
    """Record what was asked. Asking grants nothing."""
    text = text.strip()
    if not text:
        raise InvalidCell("an empty intent is not an intent")
    snapshot = store.snapshot()
    if asker_root not in snapshot.cells:
        raise InvalidCell("the asker is not a root the graph holds")
    if intent_root in snapshot.cells:
        raise InvalidCell("intent already exists: %s" % intent_root)
    ensure_intents(store)
    snapshot = store.snapshot()
    text_root = intent_root + ":text"
    store.commit(snapshot.revision, create=(
        _terminal(text_root, text),
        Cell(intent_root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, intent_root, (
        (TEXT_ROLE, text_root),
        (ASKER_ROLE, asker_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, INTENTS_ROOT, ((INTENT_ROLE, intent_root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return intent_root


def read_intent(snapshot, intent_root):
    if intent_root not in snapshot.cells:
        raise InvalidCell("no such intent: %s" % intent_root)
    members = read_relation(snapshot, intent_root, budget=10_000)

    def many(role):
        return tuple(sorted(
            m.participant_id for m in members if m.role_id == role))

    def one(role, label):
        found = many(role)
        if len(found) != 1:
            raise InvalidCell("intent has no single %s" % label)
        return found[0]

    return Intent(
        intent_root,
        _text(snapshot, one(TEXT_ROLE, "text")),
        one(ASKER_ROLE, "asker"),
        many(SCOPE_ROLE),
        many(LEAF_ROLE),
        bool(many(SEARCH_ROLE)),
    )


def grant_scope(store, intent_root, *, scope_roots, granter_root):
    """Only the person who asked may widen what may be touched."""
    scope = tuple(dict.fromkeys(scope_roots))
    if not scope:
        raise InvalidCell("granting nothing is not a grant")
    snapshot = store.snapshot()
    intent = read_intent(snapshot, intent_root)
    if intent.asker_root != granter_root:
        raise InvalidCell("only the asker may grant scope for their intent")
    for root in scope:
        if root not in snapshot.cells:
            raise InvalidCell("granted scope names a root the graph does not hold")
    patch = prepare_append_relation_members(
        snapshot, intent_root,
        tuple((SCOPE_ROLE, root) for root in scope), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return scope


def atomize(store, intent_root, *, leaf_roots):
    """Break an intent into work. Ungranted scope cannot be broken into."""
    leaves = tuple(dict.fromkeys(leaf_roots))
    if not leaves:
        raise InvalidCell("atomizing into nothing is not atomizing")
    snapshot = store.snapshot()
    intent = read_intent(snapshot, intent_root)
    if not intent.granted_scope:
        raise InvalidCell("an intent with no granted scope cannot become work")
    outside = [root for root in leaves if root not in intent.granted_scope]
    if outside:
        raise InvalidCell(
            "work outside the granted scope is refused: %s" % outside[:3])
    patch = prepare_append_relation_members(
        snapshot, intent_root,
        tuple((LEAF_ROLE, root) for root in leaves), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return leaves


def requirement_tree(snapshot, intent_root):
    return read_intent(snapshot, intent_root).leaves


def record_library_search(store, intent_root, *, searched_root):
    """Say out loud that the library was consulted, and against what."""
    snapshot = store.snapshot()
    read_intent(snapshot, intent_root)
    if searched_root not in snapshot.cells:
        raise InvalidCell("a search must name what was searched")
    patch = prepare_append_relation_members(
        snapshot, intent_root,
        ((SEARCH_ROLE, searched_root),), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    return searched_root


def assert_may_build(snapshot, intent_root):
    """Nothing is built from an intent that skipped the library."""
    intent = read_intent(snapshot, intent_root)
    if not intent.leaves:
        raise InvalidCell("nothing was atomized, so there is nothing to build")
    if not intent.searched:
        raise InvalidCell("the library was never searched; building would duplicate")
    return True
