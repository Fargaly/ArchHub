"""Physical-map courts for immutable Cell revisions without linear lookup."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from statistics import median
from time import perf_counter
from types import MappingProxyType

import pytest
from rpds import HashTrieMap

from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
    _OverlayCellMap,
    dense_read_snapshot,
    overlay_read_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


def _cell(root: str, atom: bytes = b"value") -> Cell:
    return Cell(root, NULL_CELL_ID, NULL_CELL_ID, atom)


class _LinearOverlayReference(Mapping[str, Cell]):
    """Exact former lookup shape retained only as the performance comparator."""

    def __init__(self, base: Mapping[str, Cell], delta: Mapping[str, Cell]):
        self._base = base
        self._delta = MappingProxyType(dict(delta))
        self._created = sum(1 for root in delta if root not in base)

    def __getitem__(self, root: str) -> Cell:
        source: Mapping[str, Cell] = self
        while isinstance(source, _LinearOverlayReference):
            try:
                return source._delta[root]
            except KeyError:
                source = source._base
        return source[root]

    def __iter__(self):
        yielded = set()
        layers = []
        source: Mapping[str, Cell] = self
        while isinstance(source, _LinearOverlayReference):
            layers.append(source)
            source = source._base
        for root in source:
            yielded.add(root)
            yield root
        for layer in reversed(layers):
            for root in layer._delta:
                if root not in yielded:
                    yielded.add(root)
                    yield root

    def __len__(self) -> int:
        return len(self._base) + self._created


def test_cell_store_uses_one_persistent_map_without_chaining_revisions():
    store = CellStore()
    store._COPY_ON_COMMIT_CELL_LIMIT = 1
    snapshots = []
    for revision in range(40):
        snapshots.append(store.snapshot())
        store.commit(store.revision, create=(_cell(
            "persistent:%s" % revision, str(revision).encode("ascii")
        ),))

    current = store.snapshot()
    assert isinstance(current.cells, _OverlayCellMap)
    assert isinstance(current.cells._cells, HashTrieMap)
    assert current.cells._depth == 1
    assert len(current.cells) == 41
    for revision, snapshot in enumerate(snapshots):
        assert "persistent:%s" % revision not in snapshot.cells
    with pytest.raises(TypeError):
        current.cells["forbidden"] = _cell("forbidden")


def test_candidate_and_commit_snapshots_share_the_persistent_contract():
    store = CellStore()
    store._COPY_ON_COMMIT_CELL_LIMIT = 1
    store.commit(store.revision, create=(_cell("existing", b"before"),))
    base = store.snapshot()
    candidate = overlay_read_snapshot(
        base,
        create=(_cell("created"),),
        replace=(_cell("existing", b"after"),),
    )
    assert isinstance(candidate.cells, _OverlayCellMap)
    assert isinstance(candidate.cells._cells, HashTrieMap)
    assert candidate.cells["existing"].atom == b"after"
    assert base.cells["existing"].atom == b"before"

    committed = store.commit(
        base.revision,
        create=(_cell("created"),),
        replace=(_cell("existing", b"after"),),
    )
    assert committed == candidate.revision
    assert dict(store.snapshot().cells) == dict(candidate.cells)
    with pytest.raises(Conflict):
        store.commit(base.revision, create=(_cell("stale"),))
    with pytest.raises(InvalidCell, match="dangling"):
        store.commit(
            store.revision,
            create=(Cell("dangling", "missing", NULL_CELL_ID, b""),),
        )


def test_dense_read_does_not_materialize_an_already_bounded_persistent_map():
    store = CellStore()
    store._COPY_ON_COMMIT_CELL_LIMIT = 1
    for index in range(8):
        store.commit(
            store.revision,
            create=(_cell("dense:%s" % index, str(index).encode("ascii")),),
        )
    persistent = store.snapshot()
    dense = dense_read_snapshot(persistent)

    assert dense is persistent
    assert dense.cells is persistent.cells
    assert dict(dense.cells) == dict(persistent.cells)


def test_physical_insertion_order_cannot_change_cell_digests():
    cells = (_cell("alpha", b"a"), _cell("beta", b"b"), _cell("gamma", b"c"))
    forward = CellStore()
    reverse = CellStore()
    forward.commit(forward.revision, create=cells)
    reverse.commit(reverse.revision, create=tuple(reversed(cells)))

    assert forward.revision_chain_digest() == reverse.revision_chain_digest()
    assert forward.fingerprint("alpha") == reverse.fingerprint("alpha")


def test_persistent_lookup_beats_the_exact_linear_overlay_reference():
    base = {
        "cell:%s" % index: _cell("cell:%s" % index)
        for index in range(8_000)
    }
    persistent: Mapping[str, Cell] = _OverlayCellMap(
        MappingProxyType(base), {}
    )
    linear: Mapping[str, Cell] = MappingProxyType(base)
    for revision in range(16):
        delta = {
            "delta:%s:%s" % (revision, index): _cell(
                "delta:%s:%s" % (revision, index), b"delta"
            )
            for index in range(16)
        }
        persistent = _OverlayCellMap(persistent, delta)
        linear = _LinearOverlayReference(linear, delta)

    roots = tuple("cell:%s" % ((index * 7919) % 8_000) for index in range(40_000))

    def samples(mapping: Mapping[str, Cell]) -> tuple[float, ...]:
        measured = []
        for _ in range(5):
            started = perf_counter()
            total = sum(len(mapping[root].atom) for root in roots)
            measured.append((perf_counter() - started) * 1000)
            assert total == len(roots) * len(b"value")
        return tuple(measured)

    persistent_ms = median(samples(persistent))
    linear_ms = median(samples(linear))
    assert dict(persistent) == dict(linear)
    assert persistent_ms < linear_ms * 0.6


def test_runtime_and_windows_bundle_declare_the_persistent_map_dependency():
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    build = (
        ROOT / "packaging" / "windows" / "requirements-build.txt"
    ).read_text(encoding="utf-8")
    assert "rpds-py>=0.30,<1" in runtime
    assert "rpds-py==0.30.0" in build
