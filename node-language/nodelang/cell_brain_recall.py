"""Recall by meaning: the graph holds the vectors, never the model.

`brain_embeddings` in the superseded app was an index file beside the store, so
the index could drift from the facts it indexed and nothing noticed. Here an
embedding is a graph fact like any other: it names the model that produced it,
carries that model's exact dimension, and points at the fact it describes.

The kernel does not compute embeddings. A provider does that, outside, and hands
the vector in -- the same shape as the secret vault. What the kernel guarantees
is that a vector which does not match its declared model is refused, that recall
never mixes models, and that deleting the index really does forget.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from .cell_protocols import prepare_append_relation_members, read_relation
from .universal_cell import NULL_CELL_ID, Cell, InvalidCell

INDEX_ROOT = "app:brain:recall-index"
ENTRY_ROLE = INDEX_ROOT + ":role:entry"
FACT_ROLE = INDEX_ROOT + ":role:fact"
MODEL_ROLE = INDEX_ROOT + ":role:model"
VECTOR_ROLE = INDEX_ROOT + ":role:vector"

ADMITTED_MODELS: Mapping[str, int] = MappingProxyType({
    "local-minilm-v2": 8,
    "cloud-embed-v3": 16,
})


@dataclass(frozen=True, slots=True)
class Recalled:
    fact_root: str
    model: str
    similarity: float


def _terminal(root_id, value):
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot, root_id):
    cell = snapshot.cells.get(root_id)
    if cell is None:
        raise InvalidCell("recall text is missing at %s" % root_id)
    return bytes(cell.atom).decode("utf-8")


def _pack(vector):
    return struct.pack("<%dd" % len(vector), *vector)


def _unpack(raw):
    return struct.unpack("<%dd" % (len(raw) // 8), raw)


def assert_vector(model, vector):
    """A vector that does not match its declared model is not a vector."""
    if model not in ADMITTED_MODELS:
        raise InvalidCell("embedding model is not admitted: %s" % model)
    expected = ADMITTED_MODELS[model]
    if len(vector) != expected:
        raise InvalidCell(
            "model %s produces %d values, got %d" % (model, expected, len(vector))
        )
    for value in vector:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise InvalidCell("embedding contains a value that is not a number")
    if not any(value != 0.0 for value in vector):
        raise InvalidCell("an all-zero embedding cannot be compared to anything")


def ensure_index(store):
    snapshot = store.snapshot()
    if INDEX_ROOT in snapshot.cells:
        return INDEX_ROOT
    store.commit(snapshot.revision, create=(
        _terminal(ENTRY_ROLE, "entry"),
        _terminal(FACT_ROLE, "fact"),
        _terminal(MODEL_ROLE, "model"),
        _terminal(VECTOR_ROLE, "vector"),
        Cell(INDEX_ROOT, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    return INDEX_ROOT


def _entry_root(fact_root, model):
    return "%s:entry:%s:%s" % (INDEX_ROOT, model, fact_root)


def index_fact(store, *, fact_root, model, vector):
    """Point an embedding at a fact the graph already holds."""
    vector = tuple(float(value) for value in vector)
    assert_vector(model, vector)
    snapshot = store.snapshot()
    if fact_root not in snapshot.cells:
        raise InvalidCell("cannot index a fact the graph does not hold")
    ensure_index(store)
    snapshot = store.snapshot()
    root = _entry_root(fact_root, model)
    vector_root = root + ":vector"
    model_root = root + ":model"
    packed = Cell(vector_root, NULL_CELL_ID, NULL_CELL_ID, _pack(vector))
    if root in snapshot.cells:
        # Re-indexing replaces the vector; the fact keeps ONE entry per model.
        store.commit(snapshot.revision, replace=(packed,))
        return root
    store.commit(snapshot.revision, create=(
        packed,
        _terminal(model_root, model),
        Cell(root, NULL_CELL_ID, NULL_CELL_ID, b"relation"),
    ))
    snapshot = store.snapshot()
    patch = prepare_append_relation_members(snapshot, root, (
        (FACT_ROLE, fact_root),
        (MODEL_ROLE, model_root),
        (VECTOR_ROLE, vector_root),
    ), budget=10_000)
    store.commit(snapshot.revision, create=patch.create, replace=patch.replace)
    snapshot = store.snapshot()
    index = prepare_append_relation_members(
        snapshot, INDEX_ROOT, ((ENTRY_ROLE, root),), budget=100_000)
    store.commit(snapshot.revision, create=index.create, replace=index.replace)
    return root


def _cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise InvalidCell("an all-zero embedding cannot be compared to anything")
    return dot / (left_norm * right_norm)


def indexed_facts(snapshot, model):
    """Every fact indexed under one model. Never across models."""
    if INDEX_ROOT not in snapshot.cells:
        return ()
    found = []
    for member in read_relation(snapshot, INDEX_ROOT, budget=100_000):
        if member.role_id != ENTRY_ROLE:
            continue
        entry = member.participant_id
        entry_members = read_relation(snapshot, entry, budget=10_000)

        def one(role, label):
            values = [m.participant_id for m in entry_members if m.role_id == role]
            if len(values) != 1:
                raise InvalidCell("recall entry has no single %s" % label)
            return values[0]

        entry_model = _text(snapshot, one(MODEL_ROLE, "model"))
        if entry_model != model:
            continue
        vector_cell = snapshot.cells[one(VECTOR_ROLE, "vector")]
        found.append((one(FACT_ROLE, "fact"), _unpack(bytes(vector_cell.atom))))
    return tuple(found)


def recall_by_similarity(snapshot, *, model, query, limit=5):
    """Nearest facts first. No index, no cache, no second place to look."""
    query = tuple(float(value) for value in query)
    assert_vector(model, query)
    if limit < 1:
        raise InvalidCell("a recall of nothing is not a recall")
    scored = [
        Recalled(fact_root, model, _cosine(query, vector))
        for fact_root, vector in indexed_facts(snapshot, model)
    ]
    scored.sort(key=lambda item: (-item.similarity, item.fact_root))
    return tuple(scored[:limit])
