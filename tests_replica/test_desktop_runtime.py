"""The normal-window host must drive the same persistent application server."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.desktop import DesktopRuntime, runtime_lock_path  # noqa: E402
import nodelang.desktop as desktop_module  # noqa: E402
from nodelang.universal_application import (  # noqa: E402
    UNIVERSAL_APPLICATION_SCHEMA_VERSION,
)
from nodelang.desktop_supervisor import (  # noqa: E402
    classify_worker_exit,
    crash_history_path,
    lifecycle_path,
    supervisor_lock_path,
)


def test_desktop_runtime_hosts_the_same_valid_persistent_graph(tmp_path):
    runtime = DesktopRuntime(state_path=tmp_path / 'desktop-state.json.gz').start()
    try:
        token = runtime.server.browser_session_token
        state = json.loads(urllib.request.urlopen(urllib.request.Request(
            runtime.url + '/api/state',
            headers={'X-ArchHub-Session': token},
        ), timeout=10).read())
        document_url = runtime.document_url
        page = urllib.request.urlopen(document_url, timeout=10).read().decode('utf-8')
        assert state['valid'] is True and state['persistent'] is True
        assert state['legacy_parallel_runtime'] is False
        assert 'class="archhub-app"' in page
        assert document_url.endswith(
            '&schema=' + UNIVERSAL_APPLICATION_SCHEMA_VERSION
        )
        assert '?bootstrap=' in document_url
        assert runtime.document_url_for('future-schema').endswith(
            '/?schema=future-schema')
        response = urllib.request.urlopen(urllib.request.Request(
            runtime.url + '/', headers={'X-ArchHub-Session': token}
        ), timeout=10)
        assert response.headers['Cache-Control'] == 'no-store'
    finally:
        runtime.close()


def test_desktop_runtime_handoff_keeps_public_url_and_browser_authority(tmp_path):
    runtime = DesktopRuntime(
        state_path=tmp_path / 'desktop-handoff-state.json.gz'
    ).start()
    try:
        stable_url = runtime.url
        token = runtime.server.browser_session_token
        session_root = runtime.server.browser_session_root
        first = runtime.server.prove_runtime_backend_generation()
        runtime.handoff()
        second = runtime.server.prove_runtime_backend_generation()

        response = urllib.request.urlopen(urllib.request.Request(
            stable_url + '/api/state',
            headers={'X-ArchHub-Session': token},
        ), timeout=30)
        state = json.loads(response.read())
        assert runtime.url == stable_url
        assert runtime.server.browser_session_token == token
        assert runtime.server.browser_session_root == session_root
        assert first.generation == 1
        assert second.generation == 2
        assert first.ownership_root != second.ownership_root
        assert response.headers['X-ArchHub-Runtime-Generation'] == '2'
        assert state['universal_runtime_ownership'] == second.ownership_root
    finally:
        runtime.close()


def test_desktop_health_rejects_legacy_state_without_universal_health(monkeypatch):
    calls = []

    def read_state(url, token=None):
        calls.append(('state', url, token))
        return {'ok': True, 'valid': True}

    def read_universal_health(url, token=None):
        calls.append(('health', url, token))
        raise RuntimeError('legacy host has no Universal Cell health')

    monkeypatch.setattr(DesktopRuntime, 'read_state', staticmethod(read_state))
    monkeypatch.setattr(
        DesktopRuntime,
        'read_universal_health',
        staticmethod(read_universal_health),
    )

    assert DesktopRuntime._healthy('http://127.0.0.1:8482', 'session-token') is False
    assert calls == [
        ('state', 'http://127.0.0.1:8482', 'session-token'),
        ('health', 'http://127.0.0.1:8482', 'session-token'),
    ]


def test_desktop_health_accepts_only_authorized_universal_authority(monkeypatch):
    calls = []

    def read_state(url, token=None):
        calls.append(('state', url, token))
        return {'ok': True, 'valid': True}

    def read_universal_health(url, token=None):
        calls.append(('health', url, token))
        return {'ok': True, 'runtime': 'app:archhub'}

    monkeypatch.setattr(DesktopRuntime, 'read_state', staticmethod(read_state))
    monkeypatch.setattr(
        DesktopRuntime,
        'read_universal_health',
        staticmethod(read_universal_health),
    )

    assert DesktopRuntime._healthy('http://127.0.0.1:8482', 'session-token') is True
    assert calls == [
        ('state', 'http://127.0.0.1:8482', 'session-token'),
        ('health', 'http://127.0.0.1:8482', 'session-token'),
    ]


def test_desktop_health_rejects_non_archhub_universal_runtime(monkeypatch):
    monkeypatch.setattr(
        DesktopRuntime,
        'read_state',
        staticmethod(lambda _url, token=None: {'ok': True, 'valid': True}),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        'read_universal_health',
        staticmethod(lambda _url, token=None: {'ok': True, 'runtime': 'other'}),
    )

    assert DesktopRuntime._healthy('http://127.0.0.1:8482', 'session-token') is False


def test_desktop_attaches_to_machine_authority_when_preferred_host_is_not_authority(
    monkeypatch,
):
    def attach_machine_authority(runtime):
        runtime._url = 'http://127.0.0.1:61663'
        runtime._external_bootstrap_url = (
            'http://127.0.0.1:61663/?bootstrap=handoff'
        )
        return True

    monkeypatch.setattr(
        DesktopRuntime,
        '_healthy',
        staticmethod(lambda _url, _token: True),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_attach_machine_authority',
        attach_machine_authority,
    )

    runtime = DesktopRuntime()

    assert runtime.server is None
    assert runtime.gateway is None
    assert runtime.url == 'http://127.0.0.1:61663'
    assert runtime.document_url_for('schema-a') == (
        'http://127.0.0.1:61663/?bootstrap=handoff&schema=schema-a'
    )
    assert runtime.document_url_for('schema-b') == (
        'http://127.0.0.1:61663/?schema=schema-b'
    )


def test_desktop_refuses_second_owner_when_bridge_lacks_browser_handoff(
    monkeypatch,
):
    monkeypatch.setattr(
        DesktopRuntime,
        '_healthy',
        staticmethod(lambda _url, _token: False),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_attach_machine_authority',
        lambda _self: False,
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_active_machine_authority_present',
        staticmethod(lambda: True),
    )

    with pytest.raises(RuntimeError, match='signed Universal authority'):
        DesktopRuntime()


def test_desktop_refuses_stale_signed_authority_instead_of_starting_old_graph(
    monkeypatch,
):
    monkeypatch.setattr(
        DesktopRuntime,
        '_healthy',
        staticmethod(lambda _url, _token: False),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_attach_machine_authority',
        lambda _self: False,
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_active_machine_authority_present',
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_endpoint_is_listening',
        staticmethod(lambda _url: False),
    )

    with pytest.raises(RuntimeError, match='recover or restart'):
        DesktopRuntime()


def test_desktop_refuses_a_legacy_visible_endpoint_before_starting_a_sidecar(
    monkeypatch,
):
    monkeypatch.setattr(
        DesktopRuntime,
        '_healthy',
        staticmethod(lambda _url, _token: False),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_attach_machine_authority',
        lambda _self: False,
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_active_machine_authority_present',
        staticmethod(lambda: False),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_stopped_machine_authority_database',
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_machine_authority_descriptor_present',
        staticmethod(lambda: False),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_endpoint_is_listening',
        staticmethod(lambda _url: True),
    )

    with pytest.raises(RuntimeError, match='controlled authority handoff'):
        DesktopRuntime()


def test_desktop_restarts_only_the_signed_stopped_authority_database(
    monkeypatch, tmp_path,
):
    database = tmp_path / "released-universal.sqlite3"
    database.write_bytes(b"released")
    monkeypatch.setattr(
        DesktopRuntime,
        '_attach_machine_authority',
        lambda _self: False,
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_active_machine_authority_present',
        staticmethod(lambda: False),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_stopped_machine_authority_database',
        staticmethod(lambda: database),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_endpoint_is_listening',
        staticmethod(lambda _url: False),
    )
    monkeypatch.setattr(
        DesktopRuntime,
        '_new_server',
        lambda _self: SimpleNamespace(),
    )
    monkeypatch.setattr(
        desktop_module,
        'RuntimeGateway',
        lambda **kwargs: SimpleNamespace(kwargs=kwargs),
    )

    runtime = DesktopRuntime()

    assert runtime._server_kwargs["state_path"] is None
    assert runtime._server_kwargs["universal_state_path"] == database
    assert runtime._server_kwargs["machine_descriptor_path"] is not None


def test_desktop_lock_and_state_live_outside_the_repository():
    assert runtime_lock_path().parent == Path.home() / 'AppData' / 'Local' / 'ArchHub'
    assert supervisor_lock_path().parent == runtime_lock_path().parent
    assert lifecycle_path().parent == runtime_lock_path().parent
    assert crash_history_path().parent == runtime_lock_path().parent


def test_supervisor_restarts_silent_or_failed_exits_and_respects_clean_close():
    attempt = 'attempt-1'
    assert classify_worker_exit({}, attempt, 0) == 'restart'
    assert classify_worker_exit({'attempt': 'stale', 'status': 'clean'}, attempt, 0) == 'restart'
    assert classify_worker_exit({'attempt': attempt, 'status': 'running'}, attempt, 0) == 'restart'
    assert classify_worker_exit({'attempt': attempt, 'status': 'failed'}, attempt, 1) == 'restart'
    assert classify_worker_exit({'attempt': attempt, 'status': 'clean'}, attempt, 0) == 'stop'
    assert classify_worker_exit({'attempt': attempt, 'status': 'already-running'}, attempt, 0) == 'stop'
