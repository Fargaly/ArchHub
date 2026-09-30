"""Court: restore's relation reuse holds the whole restore, reads the same graph, and is let go after.

A fixture reopen walked 37,228 relations for 13,343 distinct keys: 64% of the
walks repeated one the restore scope had evicted, because the scope kept at
most 8,192 entries / 32 MiB while restore touches ~13.3k relations. The scope
now keeps up to 32,768 entries / 128 MiB (restore only). Reuse is an
accelerator: every relation read and the revision must be identical, walks
fewer, and nothing it retained may outlive the restore.
"""
from __future__ import annotations

import gc
import shutil
import weakref

import pytest

from nodelang import cell_protocols

OLD_ENTRIES, OLD_BYTES = 8192, 32 * 1024 * 1024


@pytest.fixture(scope="module")
def saved_application(tmp_path_factory):
    from nodelang.application_server import ApplicationServer
    root = tmp_path_factory.mktemp("restore-reuse")
    state = root / "archhub-test.universal.sqlite3"
    ApplicationServer(universal_state_path=state, enable_machine_transport=False,
                      enable_machine_projection_prewarm=False).close()
    return state


def _reopen(state, monkeypatch, tag, ceiling=None):
    """Reopen a copy; every read_relation return in call order, the revision, walks, a weakref to the scope cache."""
    from nodelang.application_server import ApplicationServer
    if ceiling is not None:
        monkeypatch.setattr(cell_protocols, "RESTORE_RELATION_PROJECTION_MAX_ENTRIES", ceiling[0])
        monkeypatch.setattr(cell_protocols, "RESTORE_RELATION_PROJECTION_MAX_BYTES", ceiling[1])
    read_relation, walk = cell_protocols.read_relation, cell_protocols._read_relation_walk
    seen, walks, caches = [], [0], []

    def recorded(snapshot, relation_root, **kwargs):
        try:
            members = read_relation(snapshot, relation_root, **kwargs)
        except Exception as refusal:
            seen.append((snapshot.revision, relation_root, "refused", type(refusal).__name__, str(refusal)))
            raise
        seen.append((snapshot.revision, relation_root, tuple(members)))
        return members

    def counted(snapshot, relation_root, budget, cache, cache_key):
        walks[0] += 1
        if cache is not None and not caches:
            caches.append(weakref.ref(cache))
        return walk(snapshot, relation_root, budget, cache, cache_key)

    import sys
    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("nodelang") and getattr(module, "read_relation", None) is read_relation:
            monkeypatch.setattr(module, "read_relation", recorded)
    monkeypatch.setattr(cell_protocols, "_read_relation_walk", counted)
    copy = state.parent / tag
    copy.mkdir()
    for item in state.parent.glob(state.name + "*"):
        if item.is_file() and not item.name.endswith(".lock"):
            shutil.copy2(item, copy / item.name)
    server = ApplicationServer(universal_state_path=copy / state.name, enable_machine_transport=False,
                               enable_machine_projection_prewarm=False)
    try:
        return seen, server.universal_store.revision, walks[0], caches
    finally:
        server.close()
        monkeypatch.undo()


def test_the_restore_ceiling_is_raised():
    assert cell_protocols.RESTORE_RELATION_PROJECTION_MAX_ENTRIES == 32768
    assert cell_protocols.RESTORE_RELATION_PROJECTION_MAX_BYTES == 128 * 1024 * 1024


def test_every_relation_read_is_identical_and_walks_are_fewer(saved_application, monkeypatch):
    control_a = _reopen(saved_application, monkeypatch, "old-a", (OLD_ENTRIES, OLD_BYTES))
    control_b = _reopen(saved_application, monkeypatch, "old-b", (OLD_ENTRIES, OLD_BYTES))
    raised = _reopen(saved_application, monkeypatch, "raised")
    assert control_a[0], "the reopen read no relation; the court would prove nothing"
    # The control: the same ceiling twice reads the same graph, so the comparison below is valid.
    assert (control_b[0], control_b[1]) == (control_a[0], control_a[1])
    assert raised[0] == control_a[0]
    assert raised[1] == control_a[1]
    assert raised[2] < control_a[2], (raised[2], control_a[2])


def test_nothing_the_restore_retained_outlives_it(saved_application, monkeypatch):
    _, _, _, caches = _reopen(saved_application, monkeypatch, "released")
    assert caches, "restore used no bounded reuse scope"
    gc.collect()
    assert caches[0]() is None, "the restore's relation reuse is still alive after restore"
    assert cell_protocols._RELATION_PROJECTION_CACHE.get() is None
