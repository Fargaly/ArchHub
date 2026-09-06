"""brain.health must answer while the store is busy writing.

Thread dump of the founder's daemon, 2026-09-06 05:15, taken while it had
stopped answering: brain.health was inside storage.get_meta waiting on the
connection lock, a second thread was stacked behind it, and brain-sync-worker
was active pushing 1,824 facts. A status read that queues behind a bulk write
turns a slow sync into a dead daemon.
"""
from __future__ import annotations

import threading
import time

import pytest

from personal_brain import storage


class _Store:
    """A store whose lock a writer is holding."""

    def __init__(self, held: bool):
        self._lock = threading.RLock()
        self._values = {"k": "latched"}
        self.blocking_reads = 0
        self._held = held

    _META_PROBE_SECONDS = storage.BrainStore._META_PROBE_SECONDS
    peek_meta = storage.BrainStore.peek_meta

    class _Conn:
        def __init__(self, values):
            self._values = values
        def execute(self, _sql, params):
            key = params[0]
            class _Row(dict):
                def __getitem__(self, item):
                    return dict.__getitem__(self, item)
            value = self._values.get(key)
            return type("R", (), {"fetchone": staticmethod(
                lambda: {"value": value} if value is not None else None)})()

    @property
    def _conn(self):
        return self._Conn(self._values)


def test_a_busy_store_answers_busy_instead_of_waiting():
    store = _Store(held=True)
    holder_ready = threading.Event()
    release = threading.Event()

    def hold():
        with store._lock:
            holder_ready.set()
            release.wait(5)

    writer = threading.Thread(target=hold, daemon=True)
    writer.start()
    assert holder_ready.wait(2)
    try:
        began = time.monotonic()
        answer = store.peek_meta("k", timeout=0.2)
        spent = time.monotonic() - began
        assert answer is storage.BUSY, answer
        assert spent < 1.0, "the status read waited %.1fs" % spent
        assert not answer, "BUSY must be falsey so callers stay inert"
    finally:
        release.set()
        writer.join(2)


def test_a_free_store_answers_the_value():
    store = _Store(held=False)
    assert store.peek_meta("k", timeout=0.5) == "latched"
    assert store.peek_meta("absent", timeout=0.5) is None


def test_the_auth_latch_check_uses_the_non_blocking_read():
    import inspect

    from personal_brain import personal_cloud_sync

    source = inspect.getsource(personal_cloud_sync.PersonalCloudSync._is_auth_invalid_for)
    assert "peek_meta" in source and "BUSY" in source
    # A busy store must read as "not latched", which is the inert answer.
    assert source.count("return False") >= 3


def test_a_busy_store_never_reports_a_token_as_rejected():
    from personal_brain import personal_cloud_sync

    class _AlwaysBusy:
        def peek_meta(self, _key, **_kw):
            return storage.BUSY
        def get_meta(self, _key):
            raise AssertionError("the status path must not take the blocking read")

    holder = personal_cloud_sync.PersonalCloudSync.__new__(
        personal_cloud_sync.PersonalCloudSync)
    holder.store = _AlwaysBusy()
    assert holder._is_auth_invalid_for("any-token") is False


def test_every_read_on_the_status_path_is_non_blocking():
    """The first fix covered one of two. A thread dump found the other.

    After _is_auth_invalid_for stopped waiting, brain.health still blocked in
    get_meta through _load_cursor, called from the same status() body. Both
    reads on that path must peek.
    """
    import inspect

    from personal_brain import personal_cloud_sync

    status = inspect.getsource(personal_cloud_sync.PersonalCloudSync.status)
    assert "_load_cursor()" not in status, "status must not take the blocking read"
    assert "_peek_cursor()" in status

    peek = inspect.getsource(personal_cloud_sync.PersonalCloudSync._peek_cursor)
    assert "peek_meta" in peek and "BUSY" in peek


def test_a_busy_store_still_reports_a_cursor():
    from personal_brain import personal_cloud_sync

    class _AlwaysBusy:
        def peek_meta(self, _key, **_kw):
            return storage.BUSY
        def get_meta(self, _key):
            raise AssertionError("the status path must not take the blocking read")

    holder = personal_cloud_sync.PersonalCloudSync.__new__(
        personal_cloud_sync.PersonalCloudSync)
    holder.store = _AlwaysBusy()
    said = holder._peek_cursor()
    assert isinstance(said, str) and said, said

    class _Free(_AlwaysBusy):
        def peek_meta(self, _key, **_kw):
            return "2026-09-06T05:00:00Z"

    holder.store = _Free()
    assert holder._peek_cursor() == "2026-09-06T05:00:00Z"
    holder.store = _AlwaysBusy()
    assert holder._peek_cursor() == "2026-09-06T05:00:00Z", (
        "a busy store reports the cursor it last saw")
