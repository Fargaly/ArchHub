"""Disposable accelerators over graph-held memory.

Coordinator decision 2026-09-17, under SPEC.md 3.1 (accelerators are disposable;
deleting one must not change meaning): the listing index and the recall vectors
are acceleration, never stored meaning. Both are derived from the Cells, both
are bound to exactly what they were derived from, and neither writes a Cell.

* ``MemoryListing`` answers the same question as ``cell_brain_memory.memories``
  for ONE session, from an in-process copy bound to that session and to one
  graph revision. Any other revision rebuilds it from the Cells, so a write can
  never hide behind a stale copy, and closing the session (itself a write)
  leaves the listing reading nothing.
* ``RecallCache`` keeps one embedding per (memory entry root, sha256 of the
  text, embedding model). The entry root is derived from the owner and the
  source id, so two owners never share a vector; an edited text or another
  model is another key, so a stale vector is never used; a missing vector is
  recomputed, never an error.
"""
from __future__ import annotations

import hashlib
import math

from .cell_brain_memory import FORGOTTEN, entry_root, memories
from .universal_cell import InvalidCell


class MemoryListing:
    """A revision-bound copy of one session's memory listing."""

    def __init__(self, store, *, session_root):
        self._store = store
        self._session_root = session_root
        self._revision = None
        self._all = ()
        self.builds = 0

    def drop(self):
        """Throw the copy away. The next read rebuilds it from the Cells."""
        self._revision = None
        self._all = ()

    def memories(self, *, kind=None, include_forgotten=False):
        snapshot = self._store.snapshot()
        if self._revision != snapshot.revision:
            self.drop()
            self._all = memories(snapshot, session_root=self._session_root,
                                 include_forgotten=True)
            self._revision = snapshot.revision
            self.builds += 1
        return tuple(
            memory for memory in self._all
            if (kind is None or memory.kind == kind)
            and (include_forgotten or memory.state != FORGOTTEN))


def _vector(values):
    try:
        vector = tuple(float(value) for value in values)
    except (TypeError, ValueError) as error:
        raise InvalidCell("an embedding must be a sequence of numbers") from error
    if not vector:
        raise InvalidCell("an embedding cannot be empty")
    if any(math.isnan(v) or math.isinf(v) for v in vector):
        raise InvalidCell("an embedding must be finite")
    return vector


def _cosine(left, right):
    if len(left) != len(right):
        raise InvalidCell("embeddings from one model must share a dimension")
    left_norm = math.sqrt(sum(v * v for v in left))
    right_norm = math.sqrt(sum(v * v for v in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


class RecallCache:
    """Embeddings keyed by what they were computed from."""

    def __init__(self):
        self._vectors = {}
        self.computed = 0

    def drop(self):
        self._vectors.clear()

    def discard(self, memory):
        """Lose every vector held for one memory, as a crash or eviction would."""
        root = entry_root(memory.owner_root, memory.fragment_id)
        for key in [key for key in self._vectors if key[0] == root]:
            del self._vectors[key]

    def vector(self, memory, *, model, embed):
        key = (
            entry_root(memory.owner_root, memory.fragment_id),
            hashlib.sha256(memory.text.encode("utf-8")).hexdigest(),
            model,
        )
        found = self._vectors.get(key)
        if found is None:
            found = _vector(embed(memory.text, model))
            self._vectors[key] = found
            self.computed += 1
        return found


def recall(listing, query, *, model, embed, cache, k=5):
    """The listing session's live memories nearest in meaning to the query."""
    if not isinstance(query, str) or not query.strip():
        raise InvalidCell("recall needs something to recall by")
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise InvalidCell("recall must ask for at least one memory")
    if not isinstance(model, str) or not model.strip():
        raise InvalidCell("recall must name its embedding model")
    wanted = _vector(embed(query, model))
    scored = []
    for memory in listing.memories():
        score = _cosine(wanted, cache.vector(memory, model=model, embed=embed))
        scored.append((-score, memory.fragment_id, memory))
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple((memory, -negative) for negative, _, memory in scored[:k])
