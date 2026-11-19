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
