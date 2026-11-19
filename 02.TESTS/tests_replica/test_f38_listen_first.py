"""F38: HTTP listen returns before cloud relay / TriggerService warm-up.
F16: a Run records results without inventing extra canvas nodes.
"""
import contextlib
import threading
import time

import pytest


@pytest.fixture
def isolated_profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))
    return tmp_path / 'state'


def test_server_returns_before_slow_warm_up(isolated_profile, monkeypatch):
    from nodelang import nograph_server as owner
    import nodelang.canvas_triggers as triggers_mod

    held = threading.Event()
    entered = threading.Event()

    def slow_relay(self, *, restart=False):
        entered.set()
        held.wait(5)
        return None

    class SlowTriggers:
        def __init__(self, *args, **kwargs):
            entered.set()
            held.wait(5)
            raise RuntimeError('TriggerService must not block listen')

        def refresh(self):
            return None

    monkeypatch.setattr(owner.NoGraphServer, 'ensure_cloud_relay', slow_relay)
    monkeypatch.setattr(triggers_mod, 'TriggerService', SlowTriggers)

    server = owner.NoGraphServer(isolated_profile)
    started = time.perf_counter()
    server.start()
    listen_ms = (time.perf_counter() - started) * 1000
    try:
        assert listen_ms < 1500, f'listen blocked on warm-up: {listen_ms:.1f} ms'
        assert server.thread is not None and server.thread.is_alive()
        assert server.triggers is None
        assert entered.wait(2), 'warm-up thread never started'
    finally:
        held.set()
        time.sleep(0.05)
        server.close()


def test_close_during_warm_up_leaves_no_relay_or_trigger_service_running(isolated_profile, monkeypatch):
    """The warm-up's relay and trigger service belong to the server's lifecycle: a relay the warm-up finishes making
    after close() returned is closed at once, never attached, and no trigger service is left running."""
    from nodelang import nograph_server as owner
    import nodelang.canvas_triggers as triggers_mod
    import nodelang.cloud_relay as relay_mod

    entered, release = threading.Event(), threading.Event()
    made, services = [], []

    class LateRelay:
        def __init__(self):
            self._stop = threading.Event()
            self.closed = False

        def close(self, timeout_seconds=None):
            self.closed = True
            self._stop.set()

    def held_factory(**_kwargs):
        entered.set()
        assert release.wait(10), 'the test never released the relay factory'
        relay = LateRelay()
        made.append(relay)
        return relay

    class Agents:
        def __init__(self, **_kwargs):
            pass

        def call(self, *_args, **_kwargs):
            return {}

    class Triggers:
        def __init__(self, *args, **kwargs):
            self.closed = False
            services.append(self)

        def refresh(self):
            return None

        def close(self):
            self.closed = True

    monkeypatch.setattr(relay_mod, 'start_cloud_relay', held_factory)
    monkeypatch.setattr(relay_mod, 'McpWorkshopAgents', Agents)
    monkeypatch.setattr(triggers_mod, 'TriggerService', Triggers)

    server = owner.NoGraphServer(isolated_profile).start()
    assert entered.wait(10), 'warm-up never reached the relay factory'
    warm = next(thread for thread in threading.enumerate() if thread.name == 'archhub-nograph-warm')
    server.close()          # returns while the factory is still held
    release.set()           # only now does the factory hand back its relay
    warm.join(10)
    assert not warm.is_alive(), 'the warm-up is still running after close'
    assert len(made) == 1 and made[0].closed, 'the relay made after close was left running'
    assert server.cloud_relay is None and server.triggers is None
    assert all(service.closed for service in services), 'a trigger service made during close was left running'


def test_run_does_not_invent_history_nodes(isolated_profile, monkeypatch):
    """F16 Book: agent traffic and run history are not written onto the canvas."""
    from nodelang import canvas_documents, session_files

    monkeypatch.setattr(session_files, 'sessions_directory', lambda: isolated_profile / 'Sessions')
    (isolated_profile / 'Sessions').mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(session_files, 'catalogue', lambda: [])
    monkeypatch.setattr(canvas_documents, 'locked', lambda path: contextlib.nullcontext())

    document = session_files.new_document('History off canvas')
    document['nodes'] = [{
        'id': 'note-1', 'type': 'note', 'title': 'Note', 'params': {},
        'position': {'x': 0, 'y': 0},
        'ports': {'source': [{'id': 'out', 'type': 'any'}], 'target': []},
    }]
    document['wires'] = []
    path = isolated_profile / 'history.archhub'
    isolated_profile.mkdir(parents=True, exist_ok=True)
    session_files.write_document(path, document)
    result = session_files.run_document(session_files.read_document(path), path=str(path), again=True)
    held = result.get('document') or session_files.read_document(path)
    assert [row['id'] for row in held['nodes']] == ['note-1']
    assert set(result['results']) == {'note-1'}
