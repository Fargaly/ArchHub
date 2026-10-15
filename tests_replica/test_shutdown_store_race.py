"""Shutdown must drain actual probe threads before releasing native storage."""
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from nodelang.application_server import ApplicationServer
from nodelang.universal_cell import CellStore, InvalidCell, NULL_CELL_ID


def _noop(*args, **kwargs):
    pass


class BlockingStore:
    revision = 1

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.active = False
        self.violations = []
        self.order = []

    def read(self):
        if self.closed.is_set():
            self.violations.append('read after close')
        self.active = True
        self.entered.set()
        try:
            assert self.release.wait(5), 'court failed to release blocking read'
            return {'ok': True}
        finally:
            self.active = False
            self.order.append('read finished')

    def close(self):
        if self.active:
            self.violations.append('closed during read')
        self.order.append('store closed')
        self.closed.set()


def _server(monkeypatch, store):
    from nodelang import app_brain, brain_cloud_runner
    monkeypatch.setattr(app_brain, 'unbind', _noop)
    monkeypatch.setattr(brain_cloud_runner, 'stop', _noop)
    server = ApplicationServer.__new__(ApplicationServer)
    server.universal_store = store
    server.mutation_lock = threading.RLock()
    server._model_execution_idle = threading.Event()
    server._model_execution_idle.set()
    server._snapshot_stop = threading.Event()
    server._snapshot_event = threading.Event()
    server._snapshot_revision = 0
    server._live_stop = threading.Event()
    server._projection_prewarm_stop = threading.Event()
    for name in ('_snapshot_thread', '_live_thread', '_projection_prewarm_thread',
                 'universal_cloud_server', '_universal_cloud_thread', 'machine_transport',
                 '_runtime_fence_release', 'universal_checkpoint_guard',
                 'universal_checkpoint_signing_authority'):
        setattr(server, name, None)
    server._machine_agent_session_lock = threading.RLock()
    for name in ('_machine_agent_sessions', '_machine_agent_recovery_capabilities',
                 '_machine_agent_release_receipts', '_machine_agent_continuation_receipts',
                 '_machine_agent_challenges', '_browser_sessions',
                 '_browser_canvas_projections', '_browser_canvas_layout_leases',
                 '_browser_scope_canvas_projections', '_browser_scope_canvas_identities',
                 '_browser_scope_projection_lineage'):
        setattr(server, name, {})
    server._browser_session_lock = threading.RLock()
    server.universal_registry = SimpleNamespace(browser_session_protocol=None,
        browser_publish_court=SimpleNamespace(configure=_noop))
    server.universal_reaction_engine = SimpleNamespace(start=_noop, stop=_noop)
    server.conversation_content = SimpleNamespace(close=_noop)
    server._owns_universal_store = True
    server._owns_universal_checkpoint_signing_authority = False
    for name in ('_stop_cloud_relay', '_begin_runtime_drain', 'flush_snapshot',
                 '_release_runtime_ownership'):
        setattr(server, name, _noop)
    stopped = threading.Event()
    server.httpd = SimpleNamespace(server_address=('127.0.0.1', 0),
        serve_forever=lambda: stopped.wait(5), shutdown=stopped.set, server_close=_noop)
    server.thread = None
    server.browser_session_token = 'court'
    server.enable_machine_projection_prewarm = False
    return server.start()


def _shutdown_during_probe(monkeypatch, kind='brain'):
    store = BlockingStore()
    server = _server(monkeypatch, store)
    errors = []
    if kind == 'approvals':
        server._baboom_pending_approvals_cache_lock = threading.RLock()
        server._baboom_pending_approvals_cache = {'revision': -1, 'expires_at': 0, 'count': None}
        server._baboom_pending_approvals_refreshing = False
        server._refresh_baboom_pending_founder_approvals = lambda *_: store.read()
        launch = lambda: server._baboom_pending_founder_approvals_count(
            context=None, read_guard=None, cache_only=True)
        worker_name = 'archhub-baboom-pending-approvals'
    elif kind == 'tool-hub':
        from nodelang import universal_graphs
        monkeypatch.setattr(universal_graphs, 'project_graph_index', lambda *_a, **_k: store.read())
        server._tool_hub_graph_cache_key = lambda binding: 'court'
        server._remember_tool_hub_graph_sessions = _noop
        binding = SimpleNamespace(context=None)
        launch = lambda: server._refresh_tool_hub_graph_sessions(binding)
        worker_name = 'archhub-tool-hub-graphs'
    else:
        launch = lambda: server._refresh_in_background('brain', 0, store.read)
        worker_name = 'archhub-probe-brain'
    launch()
    assert store.entered.wait(2)
    def close():
        try:
            server.close()
        except BaseException as exc:
            errors.append(exc)
    closer = threading.Thread(target=close)
    closer.start()
    try:
        time.sleep(0.03)
        assert not store.closed.is_set(), 'store closed before active probe finished'
    finally:
        store.release.set()
        closer.join(5)
        if server.thread:
            server.httpd.shutdown()
            server.thread.join(2)
    assert not closer.is_alive()
    assert errors == []
    assert store.violations == []
    assert store.order == ['read finished', 'store closed']
    assert not any(t.name == worker_name and t.is_alive()
                   for t in threading.enumerate())
    launch()
    time.sleep(0.01)
    assert store.violations == []


def test_shutdown_waits_for_blocked_probe_before_closing_store(monkeypatch):
    _shutdown_during_probe(monkeypatch)


@pytest.mark.parametrize('kind', ['approvals', 'tool-hub'])
def test_shutdown_drains_other_background_refreshes(monkeypatch, kind):
    _shutdown_during_probe(monkeypatch, kind)


@pytest.mark.parametrize('round_number', range(20))
def test_shutdown_during_active_probe_stress(monkeypatch, round_number):
    _shutdown_during_probe(monkeypatch)


def test_sqlite_close_waits_for_read_scope_and_refuses_late_scope(tmp_path):
    store = CellStore(tmp_path / 'shutdown.sqlite3')
    snapshot = store.snapshot()
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def read():
        try:
            with snapshot.read_scope():
                entered.set()
                assert release.wait(5)
        except BaseException as exc:
            errors.append(exc)
    def close():
        try:
            store.close()
        except BaseException as exc:
            errors.append(exc)
        finally:
            closed.set()
    reader = threading.Thread(target=read)
    reader.start()
    assert entered.wait(2)
    closer = threading.Thread(target=close)
    closer.start()
    try:
        assert not closed.wait(0.05), 'native store closed inside a read scope'
        with pytest.raises(InvalidCell, match='closing or closed'):
            with snapshot.read_scope():
                pass
    finally:
        release.set()
        reader.join(5)
        closer.join(5)
    assert not reader.is_alive() and not closer.is_alive()
    assert errors == []
    with pytest.raises(InvalidCell):
        store.snapshot()
    with pytest.raises((InvalidCell, sqlite3.ProgrammingError, RuntimeError)):
        with snapshot.read_scope():
            snapshot.cells.get(NULL_CELL_ID)


def test_probe_timeout_refuses_store_teardown_and_late_admission(monkeypatch):
    from nodelang import application_server as module
    store = BlockingStore()
    server = _server(monkeypatch, store)
    server._refresh_in_background('brain', 0, store.read)
    assert store.entered.wait(2)
    stop = module._stop_background_refreshes
    monkeypatch.setattr(module, '_stop_background_refreshes',
                        lambda owner: stop(owner, timeout=0.02))
    try:
        with pytest.raises(RuntimeError, match='store teardown refused'):
            server.close()
        assert not store.closed.is_set()
        assert server._background_refresh_stop.is_set()
        server._refresh_in_background('late', 0, store.read)
        assert len(server._background_refresh_threads) == 1
    finally:
        store.release.set()
        stop(server, timeout=2)
        server.close()
    assert store.violations == []


@pytest.mark.parametrize('worker_name', ['_live_thread', '_projection_prewarm_thread',
                                       '_universal_cloud_thread'])
def test_poller_timeout_keeps_store_open(monkeypatch, worker_name):
    server = _server(monkeypatch, BlockingStore())
    class StuckWorker:
        def __init__(self):
            self.timeouts = []
        def join(self, timeout):
            self.timeouts.append(timeout)
        def is_alive(self):
            return True
    worker = StuckWorker()
    setattr(server, worker_name, worker)
    try:
        with pytest.raises(RuntimeError, match='store teardown refused'):
            server.close()
        assert worker.timeouts and max(worker.timeouts) <= 10
        assert not server.universal_store.closed.is_set()
        assert server._snapshot_stop.is_set()
        assert server._live_stop.is_set()
        assert server._projection_prewarm_stop.is_set()
    finally:
        setattr(server, worker_name, None)
        server.close()


def test_cached_sqlite_read_is_refused_after_close(tmp_path):
    store = CellStore(tmp_path / 'cached.sqlite3')
    snapshot = store.snapshot()
    assert snapshot.cells.get(NULL_CELL_ID) is not None
    store.close()
    with pytest.raises(InvalidCell):
        snapshot.cells.get(NULL_CELL_ID)
    with pytest.raises(InvalidCell):
        store.read(NULL_CELL_ID)


@pytest.mark.parametrize('method', ['accepted_prefix_fingerprint', 'chained_prefix_fingerprint'])
def test_history_fingerprint_finishes_before_close(tmp_path, method):
    store = CellStore(tmp_path / (method + '.sqlite3'))
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    errors = []
    counter = getattr(store._history_reader, method)
    def blocked(revision):
        entered.set()
        assert release.wait(5)
        return counter(revision)
    setattr(store._history_reader, method, blocked)
    def read():
        try:
            getattr(store, method)(store.revision)
        except BaseException as exc:
            errors.append(exc)
    def close():
        try:
            store.close()
        except BaseException as exc:
            errors.append(exc)
        finally:
            closed.set()
    reader = threading.Thread(target=read)
    reader.start()
    assert entered.wait(2)
    closer = threading.Thread(target=close)
    closer.start()
    try:
        assert not closed.wait(0.05)
    finally:
        release.set()
        reader.join(5)
        closer.join(5)
    assert not reader.is_alive() and not closer.is_alive()
    assert errors == []
    with pytest.raises(InvalidCell):
        getattr(store, method)(0)


def test_cached_historical_sqlite_read_is_refused_after_close(tmp_path):
    from nodelang.universal_cell import Cell
    path = tmp_path / 'history.sqlite3'
    seed = CellStore(path)
    revision = seed.revision
    seed.commit(revision, create=(Cell('shutdown:cell', NULL_CELL_ID, NULL_CELL_ID, b'x'),))
    seed.close()
    store = CellStore(path)
    snapshot = store.at(revision)
    assert snapshot.cells.get(NULL_CELL_ID) is not None
    store.close()
    with pytest.raises(InvalidCell):
        snapshot.cells.get(NULL_CELL_ID)
