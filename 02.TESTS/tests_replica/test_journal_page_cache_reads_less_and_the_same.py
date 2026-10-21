"""Court: the journal's page cache reads fewer pages, and exactly the same graph.

Every store connection ran on SQLite's default ~2 MB page cache; a reopen of
the founder's 7 GB journal read 1.65 GB in ~364k 4 KB operations, re-reading
pages it had just evicted. The journal connection now holds a 256 MB page
cache (JOURNAL_PAGE_CACHE_KIB). It is an accelerator: a reopen with and without
it must read the same relations and reach the same revision, with fewer reads.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import shutil
import sys

import pytest

from nodelang import cell_protocols, universal_cell

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="process read counters are the Windows API")


class _IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("ro", "wo", "oo", "rb", "wb", "ob")]


def _read_ops() -> int:
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(_IO)]
    kernel.GetProcessIoCounters.restype = wt.BOOL
    counters = _IO()
    assert kernel.GetProcessIoCounters(kernel.GetCurrentProcess(), ctypes.byref(counters))
    return counters.ro


@pytest.fixture(scope="module")
def saved_application(tmp_path_factory):
    from nodelang.application_server import ApplicationServer
    root = tmp_path_factory.mktemp("page-cache")
    state = root / "archhub-test.universal.sqlite3"
    ApplicationServer(universal_state_path=state, enable_machine_transport=False,
                      enable_machine_projection_prewarm=False).close()
    return state


def _reopen(state, monkeypatch, cache_kib):
    from nodelang.application_server import ApplicationServer
    copy = state.parent / ("reopen-%d" % cache_kib)
    copy.mkdir(exist_ok=True)
    for item in state.parent.glob(state.name + "*"):
        if item.is_file() and not item.name.endswith(".lock"):
            shutil.copy2(item, copy / item.name)
    monkeypatch.setattr(universal_cell, "JOURNAL_PAGE_CACHE_KIB", cache_kib, raising=False)
    seen = []
    walk = cell_protocols._read_relation_walk

    def recorded(snapshot, relation_root, budget, cache, cache_key):
        members = walk(snapshot, relation_root, budget, cache, cache_key)
        seen.append((snapshot.revision, relation_root, members))
        return members

    monkeypatch.setattr(cell_protocols, "_read_relation_walk", recorded)
    before = _read_ops()
    server = ApplicationServer(universal_state_path=copy / state.name, enable_machine_transport=False,
                               enable_machine_projection_prewarm=False)
    try:
        return seen, server.universal_store.revision, _read_ops() - before
    finally:
        server.close()
        monkeypatch.undo()


def test_the_page_cache_reads_less_and_reads_the_same_graph(saved_application, monkeypatch):
    assert getattr(universal_cell, "JOURNAL_PAGE_CACHE_KIB", 0) >= 65536, "the journal holds no page cache"
    without, revision_without, reads_without = _reopen(saved_application, monkeypatch, 0)
    with_cache, revision_with, reads_with = _reopen(saved_application, monkeypatch, 262144)
    assert without, "the reopen walked no relation"
    assert revision_with == revision_without
    assert with_cache == without
    assert reads_with < reads_without * 0.8, (reads_with, reads_without)


def test_the_journal_connection_asks_for_it():
    source = universal_cell.__file__
    text = open(source, encoding="utf-8").read()
    assert 'self._connection.execute("PRAGMA cache_size=-%d" % int(JOURNAL_PAGE_CACHE_KIB))' in text
    assert 'PRAGMA synchronous=FULL' in text  # durability unchanged
