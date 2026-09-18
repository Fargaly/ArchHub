"""One pass over the canvas property relations, not one pass per label.

A scope label with no registered properties searched every canvas property
relation for its owner. The founder canvas carries 6,803 of them, so one
canvas read spent 1,281,003 relation reads and 1,299,158 owner scans on 189
labels repeating one pass over one immutable snapshot (3ca3205, 7.08 GB
store, revision 112826). These courts hold the index to the same pass, the
same order, the same budget and the same refusals.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import nodelang.universal_application as universal_application
from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    MatchBudgetExceeded,
)

ROLE_NAMES = ("member", "relation", "property", "owner", "value", "label")
CANVAS_ROOT = "index:canvas"


def _fixture(owners=40, per_owner=2, orphans=3):
    store = CellStore(None)
    roles = {name: "index:role:%s" % name for name in ROLE_NAMES}
    batch = CellBatch(store)
    for role_id in roles.values():
        batch.add(Cell(role_id, NULL_CELL_ID, NULL_CELL_ID, role_id.encode()))
    canvas_members = []
    for index in range(owners):
        owner = "index:owner:%d" % index
        batch.add(Cell(owner, NULL_CELL_ID, NULL_CELL_ID, b"owner"))
        canvas_members.append((roles["member"], owner))
        for slot in range(per_owner):
            value = "index:value:%d:%d" % (index, slot)
            label = "index:label:%d:%d" % (index, slot)
            relation = "index:property:%d:%d" % (index, slot)
            batch.add(Cell(value, NULL_CELL_ID, NULL_CELL_ID, b"v"))
            batch.add(Cell(label, NULL_CELL_ID, NULL_CELL_ID, b"title"))
            batch.relation((
                (roles["owner"], owner),
                (roles["value"], value),
                (roles["label"], label),
            ), relation_id=relation)
            canvas_members.append((roles["property"], relation))
    for index in range(orphans):
        relation = "index:orphan:%d" % index
        value = "index:orphan:value:%d" % index
        batch.add(Cell(value, NULL_CELL_ID, NULL_CELL_ID, b"v"))
        batch.relation(
            ((roles["value"], value),), relation_id=relation
        )
        canvas_members.append((roles["property"], relation))
    batch.relation(canvas_members, relation_id=CANVAS_ROOT)
    batch.commit()
    registry = SimpleNamespace(
        canvas_root=CANVAS_ROOT, roles=roles, root_properties={}
    )
    return store, registry


def _the_pass_it_replaces(snapshot, registry, root_id):
    """The search every label used to run for itself."""
    found = []
    for relation_root in universal_application._canvas_roots(
        snapshot, registry
    )[2]:
        members = read_relation(snapshot, relation_root, budget=16)
        if universal_application._one_for_role(
            members, registry.roles["owner"]
        ) == root_id:
            found.append(relation_root)
    return found


def test_the_index_answers_exactly_what_the_per_label_search_answered():
    store, registry = _fixture(owners=25, per_owner=3)
    snapshot = store.dense_snapshot()
    indexed = universal_application._canvas_property_owner_index(
        snapshot, registry
    )
    for index in range(25):
        owner = "index:owner:%d" % index
        assert indexed.get(owner, []) == _the_pass_it_replaces(
            snapshot, registry, owner
        )
    assert indexed.get("index:owner:absent", []) == []
    assert _the_pass_it_replaces(snapshot, registry, "index:owner:absent") == []


def _counted_relation_reads(monkeypatch):
    calls = []
    original = universal_application.read_relation

    def counting(snapshot, relation_root, **kwargs):
        calls.append(relation_root)
        return original(snapshot, relation_root, **kwargs)

    monkeypatch.setattr(universal_application, "read_relation", counting)
    return calls


def test_the_projection_scope_pays_for_one_pass_not_one_per_label(monkeypatch):
    store, registry = _fixture(owners=30, per_owner=2)
    snapshot = store.dense_snapshot()
    labels = ["index:owner:%d" % index for index in range(30)]

    unscoped = _counted_relation_reads(monkeypatch)
    without = [
        universal_application._canvas_property_owner_index(
            snapshot, registry
        ).get(owner, [])
        for owner in labels
    ]
    passes_without = len(unscoped)

    scoped = _counted_relation_reads(monkeypatch)

    @universal_application._with_canvas_property_owner_index
    def inside():
        return [
            universal_application._canvas_property_owner_index(
                snapshot, registry
            ).get(owner, [])
            for owner in labels
        ]

    within = inside()
    passes_within = len(scoped)

    assert within == without
    # 30 owners with 2 property relations each plus 3 unowned ones: one
    # pass reads the canvas relation and its 63 property relations. Thirty
    # labels used to read all 64 of them thirty times over.
    assert passes_within == 64
    assert passes_without == 30 * 64
    assert passes_without // passes_within == 30


def test_deleting_the_index_changes_nothing_but_time():
    store, registry = _fixture(owners=12, per_owner=2)
    snapshot = store.dense_snapshot()

    @universal_application._with_canvas_property_owner_index
    def scoped():
        held = universal_application._canvas_property_owner_index(
            snapshot, registry
        )
        cache = universal_application._CANVAS_PROPERTY_OWNER_INDEX_CACHE.get()
        assert cache and len(cache) == 1
        cache.clear()
        rebuilt = universal_application._canvas_property_owner_index(
            snapshot, registry
        )
        assert rebuilt == held
        return rebuilt

    assert scoped() == universal_application._canvas_property_owner_index(
        snapshot, registry
    )


def test_a_relation_wider_than_the_budget_refuses_where_it_always_refused():
    store, registry = _fixture(owners=2, per_owner=1, orphans=0)
    batch = CellBatch(store)
    wide = "index:property:wide"
    members = []
    for index in range(20):
        value = "index:wide:value:%d" % index
        batch.add(Cell(value, NULL_CELL_ID, NULL_CELL_ID, b"v"))
        members.append((registry.roles["value"], value))
    batch.relation(members, relation_id=wide)
    batch.commit()
    snapshot = store.dense_snapshot()
    canvas = read_relation(snapshot, CANVAS_ROOT, budget=100_000)
    from nodelang.cell_protocols import append_relation_member
    append_relation_member(
        store, CANVAS_ROOT, registry.roles["property"], wide, budget=100_000
    )
    snapshot = store.dense_snapshot()
    with pytest.raises(MatchBudgetExceeded):
        _the_pass_it_replaces(snapshot, registry, "index:owner:0")
    with pytest.raises(MatchBudgetExceeded):
        universal_application._canvas_property_owner_index(snapshot, registry)
