import threading
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace

from nodelang import application_server as app
from nodelang.application_server import ApplicationServer, _VERIFIED_MACHINE_PEER_CONTEXT
from nodelang.application_machine_transport import MachinePipePeer


def test_duplicate_enrollment_shares_one_inflight_result(monkeypatch):
    joined = threading.Barrier(6)
    class ObservedFuture(Future):
        def result(self, timeout=None):
            joined.wait(10)
            return super().result(timeout)
    monkeypatch.setattr(app, 'Future', ObservedFuture)
    server = ApplicationServer(enable_machine_transport=False, live_watch=False,
                               enable_machine_projection_prewarm=False)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    original = server._enroll_universal_machine_agent_session
    def enroll(body, **kwargs):
        calls.append(body)
        entered.set()
        assert release.wait(10)
        return original(body, **kwargs)
    monkeypatch.setattr(server, '_enroll_universal_machine_agent_session', enroll)
    request = {'method': 'POST', 'path': '/api/universal/agent-session',
               'body': {'runtime': 'codex', 'external_session_id': 'routefast-duplicate'}}
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            first = pool.submit(server.dispatch_universal_machine_route, request)
            assert entered.wait(10)
            others = [pool.submit(server.dispatch_universal_machine_route, dict(request)) for _ in range(5)]
            joined.wait(10)
            release.set()
            results = [first.result(20), *(f.result(20) for f in others)]
        assert len(calls) == 1
        assert all(result == results[0] for result in results)
    finally:
        release.set()
        server.close()


def test_coalescing_shares_errors_cleans_retry_and_separates_peers(monkeypatch):
    server = object.__new__(ApplicationServer)
    server.universal_registry = SimpleNamespace(authorization=SimpleNamespace(
        session=SimpleNamespace(context=object)))
    server.universal_checkpoint_guard = None
    server._machine_agent_session_lock = threading.RLock()
    server._machine_agent_enrollments = {}
    server.mutation_lock = threading.RLock()
    server.require_universal_http_route = lambda *args, **kwargs: None
    entered, release = threading.Event(), threading.Event()
    joined = threading.Barrier(4)
    class ObservedFuture(Future):
        def result(self, timeout=None):
            joined.wait(10)
            return super().result(timeout)
    monkeypatch.setattr(app, 'Future', ObservedFuture)
    calls = []
    def enroll(body, **kwargs):
        calls.append(body)
        entered.set()
        assert release.wait(10)
        raise ValueError('shared-enrollment-error')
    server._enroll_universal_machine_agent_session = enroll
    request = {'runtime_id': 'same', 'request_id': 'different-per-request', 'method': 'POST',
        'path': '/api/universal/agent-session', 'session': {},
        'body': {'runtime': 'codex', 'external_session_id': 'same'}}
    peer = MachinePipePeer(100, 1.0)
    def call(holder):
        current = dict(request)
        token = _VERIFIED_MACHINE_PEER_CONTEXT.set((server, current, holder))
        try:
            return server._dispatch_universal_machine_route(current)
        except ValueError as exc:
            return str(exc)
        finally:
            _VERIFIED_MACHINE_PEER_CONTEXT.reset(token)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(call, peer)
        assert entered.wait(10)
        followers = [pool.submit(call, peer) for _ in range(3)]
        joined.wait(10)
        release.set()
        assert [first.result(10), *(f.result(10) for f in followers)] == ['shared-enrollment-error'] * 4
    assert len(calls) == 1 and not server._machine_agent_enrollments
    assert call(peer) == 'shared-enrollment-error'
    assert len(calls) == 2 and not server._machine_agent_enrollments
    calls.clear()
    entered.clear()
    release.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(call, peer)
        assert entered.wait(10)
        other = pool.submit(call, MachinePipePeer(101, 1.0))
        release.set()
        assert first.result(10) == other.result(10) == 'shared-enrollment-error'
    assert len(calls) == 2 and not server._machine_agent_enrollments
