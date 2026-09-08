"""A background worker holding the store must not silence the brain.

Measured with py-spy on the founder machine, 2026-09-08, while brain.health
timed out and EVERY agent in the workspace failed closed behind it:

    brain-personal-cloud-sync   set_meta         storage.py:1433
    brain-sync-worker           get_fragment     storage.py:740
    brain-tool_0                count_fragments  storage.py:862

Three threads, one shared connection, one process-wide RLock. The writer had
it; the tool call was last in line; the brain looked dead. Antigravity showed
"stdio singleton guard FAIL-CLOSED" and the CDE write gate refused every write
in the workspace, because a permit needs the brain.

WAL already allows concurrent readers alongside one writer. The lock was
serialising reads the database was happy to run at once.
"""
from __future__ import annotations

import inspect
import threading
import time

from personal_brain.storage import BrainStore


def _source(fn) -> str:
    return inspect.getsource(fn)


def test_the_two_reads_that_wedged_it_prefer_their_own_reader():
    """The lock survives only as the in-memory fallback, never the default.

    An in-memory store cannot be reopened, so it has no second connection to
    hand out -- and it has no background workers competing for it either, so
    the lock costs nothing there. On a FILE store the reader must win.
    """
    for fn in (BrainStore.get_fragment, BrainStore.count_fragments):
        body = _source(fn)
        assert "_reader_for_this_thread()" in body
        assert "if reader is None:" in body, (
            "%s must reach the lock only when there is no reader" % fn.__name__
        )
        before_lock = body.index("with self._lock")
        assert body.index("if reader is None:") < before_lock, (
            "%s takes the lock before asking for a reader" % fn.__name__
        )


def test_each_thread_gets_its_own_reader():
    body = _source(BrainStore._reader_for_this_thread)

    assert "self._thread_readers" in body
    assert "query_only=ON" in _source(BrainStore._open_reader)


def test_a_read_answers_while_the_writer_holds_the_lock(tmp_path):
    """The behaviour, not the shape: the read must not wait for the writer."""
    # a FILE store, not ":memory:" -- an in-memory one cannot be reopened,
    # so it has no second reader to prove anything with.
    store = BrainStore.open(str(tmp_path / "brain.db"))
    store.count_fragments()          # open this thread's reader first

    holding = threading.Event()
    release = threading.Event()

    def writer():
        with store._lock:
            holding.set()
            release.wait(timeout=10)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    assert holding.wait(timeout=5), "the writer never took the lock"
    try:
        started = time.monotonic()
        store.count_fragments()
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, (
            "a read waited %.1fs for the writer -- it is still queued" % elapsed
        )
    finally:
        release.set()
        thread.join(timeout=5)
