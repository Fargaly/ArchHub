"""SLOWHOME: real HTTP reads stay usable with blocked network and absent Office."""
import http.client
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from nodelang.host_brokers import _com_alive as bounded_com_alive

def _profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / 'state'))


def _close_server(server):
    server.close()
    # Keep all probe work inside the socket denylist and disposable profile.
    deadline = time.monotonic() + 30
    probes = [value for value in vars(server).values() if hasattr(value, 'running')]
    while any(probe.running for probe in probes) and time.monotonic() < deadline:
        time.sleep(.01)
    assert not any(probe.running for probe in probes)


def test_cold_reads_do_not_wait_for_network_or_hosts(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    subprocess.run(['node', '--max-old-space-size=512', str(root / '03.TOOLS/packaging/compile_studio.cjs')],
                   cwd=root, check=True, capture_output=True, text=True, timeout=180)
    _profile(tmp_path, monkeypatch)
    from nodelang import host_brokers
    from nodelang.nograph_server import NoGraphServer

    # No Office automation is allowed, including in a background probe.
    monkeypatch.setattr(host_brokers, '_com_probe', lambda _prog: False)
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex
    allowed = []

    def blocked(sock, address):
        if isinstance(address, tuple) and (address[0] not in ('127.0.0.1', '::1') or address[1] not in allowed):
            raise OSError('network blocked by SLOWHOME court')
        return original(sock, address)

    def blocked_ex(sock, address):
        if isinstance(address, tuple) and (address[0] not in ('127.0.0.1', '::1') or address[1] not in allowed):
            return 10061
        return original_ex(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked_ex)
    server = NoGraphServer(tmp_path / 'state')
    allowed.append(server.port)
    started = time.perf_counter()
    server.start()
    print(f'server_start_ms: {(time.perf_counter()-started)*1000:.2f}')
    try:
        for path, body in (
            ('/api/universal/workshop', None),
            ('/api/router/settings', {}),
            ('/api/universal/settings-action', {'function': 'read'}),
            ('/api/universal/settings-action', {'function': 'readControls'}),
            ('/api/session-files', {'action': 'initial'}),
            ('/api/universal/cloud-session', None),
            ('/api/universal/hosts', None),
            ('/api/universal/providers', None),
            ('/api/universal/models', None),
            ('/api/universal/workshop', {'action': 'data-api', 'function': 'listAgentsWorking'}),
            ('/api/universal/workshop', {'action': 'data-api', 'function': 'listWorkshopMessages', 'args': [None]}),
            ('/api/universal/workshop', {'action': 'data-api', 'function': 'listLiveAgents'}),
            ('/api/universal/settings-action', {'function': 'hostProgramState', 'args': ['revit']}),
        ):
            connection = http.client.HTTPConnection('127.0.0.1', server.port, timeout=3)
            started = time.perf_counter()
            connection.request('POST' if body is not None else 'GET', path,
                               body=json.dumps(body) if body is not None else None,
                               headers={'Content-Type': 'application/json',
                                        'X-ArchHub-Session': server.browser_session_token,
                                        'X-ArchHub-CSRF': server.browser_csrf_token})
            response = connection.getresponse()
            payload = json.loads(response.read())
            elapsed = (time.perf_counter() - started) * 1000
            connection.close()
            print(f'{path} {json.dumps(body) if body is not None else "GET"}: {elapsed:.2f} ms HTTP {response.status}')
            assert response.status == 200, payload
            assert payload['ok'], payload
            assert elapsed < 300, (path, elapsed)
    finally:
        _close_server(server)
    # Paints get a fresh profile/server, without the HTTP court warming its caches.
    _profile(tmp_path / 'browser', monkeypatch)
    server = NoGraphServer(tmp_path / 'browser/state')
    allowed[:] = [server.port]
    started = time.perf_counter()
    server.start()
    print(f'browser_server_start_ms: {(time.perf_counter()-started)*1000:.2f}')
    try:
        env = {**os.environ, 'SLOWHOME_URL': server.public_url + '/studio/?bootstrap=' + server.browser_bootstrap_token}
        browser = subprocess.run(['node', str(Path(__file__).parents[1] / 'tests_js' / 'slowhome_browser.cjs')],
                                 env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
        print(browser.stdout)
        assert browser.returncode == 0, browser.stderr
    finally:
        _close_server(server)


def test_catalogue_cold_stale_fresh_and_failure(tmp_path, monkeypatch):
    from nodelang import model_catalogue as catalogue
    from nodelang.model_router import _OPENROUTER_FREE_MODELS_DEFAULT
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    pending, released = threading.Event(), threading.Event()

    def fetch(**_kwargs):
        pending.set()
        assert released.wait(3)
        raise OSError('offline')

    monkeypatch.setattr(catalogue, 'openrouter_models', fetch)
    started = time.perf_counter()
    cold = catalogue.cached_free_routes()
    assert time.perf_counter() - started < .3
    assert cold['models'] == ['openrouter/free', *['openrouter/' + route for route in _OPENROUTER_FREE_MODELS_DEFAULT]]
    assert cold['refreshing']
    assert pending.wait(1)
    path = tmp_path / 'ArchHub/settings/openrouter-catalogue.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'at': 0, 'routes': ['fixture/cached:free']}), encoding='utf-8')
    assert catalogue.cached_free_routes()['models'][-1] == 'openrouter/fixture/cached:free'
    released.set()
    deadline = time.monotonic() + 2
    while catalogue.cached_free_routes()['refreshing'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert not catalogue.cached_free_routes()['refreshing']
    assert 'unavailable' in catalogue.cached_free_routes()['catalogue_error']
    assert json.loads(path.read_text())['routes'] == ['fixture/cached:free']
    path.write_text(json.dumps({'at': time.time(), 'routes': ['fixture/fresh:free']}), encoding='utf-8')
    fresh = catalogue.cached_free_routes()
    assert fresh['models'][-1] == 'openrouter/fixture/fresh:free'
    assert not fresh['refreshing']
    # Zero-priced catalogue ids need not carry OpenRouter's :free suffix.
    path.write_text(json.dumps({'at': 0, 'routes': ['fixture/cached:free']}), encoding='utf-8')
    monkeypatch.setattr(catalogue, '_router_refreshes', {})
    monkeypatch.setattr(catalogue, 'openrouter_models', lambda **_kwargs: [
        {'route': 'fixture/zero-priced', 'prompt_price_per_m': 0,
         'completion_price_per_m': 0, 'all_prices_zero': True}])
    catalogue.cached_free_routes()
    deadline = time.monotonic() + 2
    while catalogue.cached_free_routes()['refreshing'] and time.monotonic() < deadline:
        time.sleep(.01)
    assert catalogue.cached_free_routes()['models'][-1] == 'openrouter/fixture/zero-priced'


def test_account_returns_saved_value_while_cloud_waits(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    from nodelang import cloud_signin, settings_owner
    from nodelang.nograph_server import NoGraphServer, r_cloud_session
    from nodelang.cloud_session import _account_key
    pending, released = threading.Event(), threading.Event()
    held = {'token': 'synthetic-court-bearer', 'email': 'court@example.test'}
    monkeypatch.setattr(cloud_signin, 'sign_in_state', lambda **_kwargs: {'signed_in': True, 'email': held['email']})
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda _path: held)

    def read(_owner):
        pending.set()
        assert released.wait(3)
        return {'profile': {'name': 'Fresh court name'}}

    monkeypatch.setattr(settings_owner.SettingsOwner, 'read', read)
    store = settings_owner.AccountFiles(tmp_path / 'settings/account.json')
    store.write('cached-read:' + _account_key(held), {'profile': {'name': 'Saved court name'}})
    server = NoGraphServer(tmp_path)
    server._session.value = {'signed_in': True, 'email': held['email'], '_cache_key': _account_key(held)}

    def metadata_refresh():
        assert released.wait(3)
        return server._session.value

    server._session.probe = metadata_refresh
    try:
        started = time.perf_counter()
        summary = r_cloud_session(server, None)
        assert time.perf_counter() - started < .3
        assert summary['signed_in'] and summary['checking']
        assert '_cache_key' not in summary
        started = time.perf_counter()
        answer = server.account_read()
        assert time.perf_counter() - started < .3
        assert answer['profile']['name'] == 'Saved court name'
        assert answer['accountChecking']
        assert pending.wait(1)
        released.set()
        deadline = time.monotonic() + 2
        while (server._account.running or server._session.running) and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.account_read()['profile']['name'] == 'Fresh court name'
        # A new bearer never receives the previous session's metadata.
        held = {**held, 'token': 'another-synthetic-bearer'}
        server._session.value = {'signed_in': True, '_cache_key': _account_key(held)}
        assert server.account_read().get('profile') is None
        server._session.value = {'signed_in': False}
        assert server.account_read() == {'accountChecking': False}
    finally:
        released.set()
        server.httpd.server_close()


def test_a_stuck_office_probe_is_bounded_and_single_flight(monkeypatch):
    from nodelang import host_brokers
    pending, released = threading.Event(), threading.Event()
    calls = []

    def probe(prog):
        calls.append(prog)
        pending.set()
        assert released.wait(3)
        return True

    monkeypatch.setattr(host_brokers, '_com_probe', probe)
    monkeypatch.setattr(host_brokers, '_com_alive', bounded_com_alive)
    monkeypatch.setattr(host_brokers, '_COM_PROBES', {})
    try:
        started = time.perf_counter()
        assert host_brokers._com_alive('Court.Application') is False
        assert time.perf_counter() - started < .3
        assert pending.wait(1)
        assert host_brokers._com_alive('Court.Application') is False
        assert calls == ['Court.Application']
    finally:
        released.set()


def test_invalidated_probe_cannot_restore_signed_out_session():
    from nodelang.nograph_server import Cached
    pending, released = threading.Event(), threading.Event()

    def probe():
        pending.set()
        assert released.wait(3)
        return {'signed_in': True}

    cache = Cached(30, probe)
    cache.get()
    assert pending.wait(1)
    cache.reset({'signed_in': False})
    released.set()
    deadline = time.monotonic() + 2
    while cache.running and time.monotonic() < deadline:
        time.sleep(.01)
    assert not cache.running
    assert cache.value == {'signed_in': False}


def test_account_snapshots_replace_old_sessions_and_keep_preferences(tmp_path):
    from nodelang.settings_owner import AccountFiles
    store = AccountFiles(tmp_path / 'account.json')
    store.write('account:fixture', {'profile': {'name': 'Saved preference'}})
    store.write('cached-read:first', {'profile': {'name': 'Old account'}})
    store.write('cached-read:second', {'profile': {'name': 'Current account'}})
    assert store.read('cached-read:first') == {}
    assert store.read('cached-read:second')['profile']['name'] == 'Current account'
    assert store.read('account:fixture')['profile']['name'] == 'Saved preference'


def test_account_refresh_keeps_one_bearer_and_discards_a_switched_session(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch)
    from nodelang import cloud_signin, settings_owner
    from nodelang.nograph_server import NoGraphServer
    pending, released = threading.Event(), threading.Event()
    held = {'token': 'first-court-bearer', 'email': 'first@example.test'}
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda _path: held)
    tokens = []

    def cloud(*_args, session, **_kwargs):
        tokens.append(session['token'])
        return {'profile': {'name': 'First account'}}

    def read(owner):
        owner.cloud('GET', '/v1/me')
        pending.set()
        assert released.wait(3)
        return owner.cloud('GET', '/v1/me')

    monkeypatch.setattr(settings_owner, 'cloud_call', cloud)
    monkeypatch.setattr(settings_owner.SettingsOwner, 'read', read)
    server = NoGraphServer(tmp_path / 'state')
    server._session.reset(server._read_session())
    server._session.at = time.time()
    key = server._session.value['_cache_key']
    try:
        server.account_read()
        account = server._account
        assert pending.wait(1)
        held = {'token': 'second-court-bearer', 'email': 'second@example.test'}
        server._session.reset(server._read_session())
        released.set()
        deadline = time.monotonic() + 2
        while account.running and time.monotonic() < deadline:
            time.sleep(.01)
        assert not account.running
        assert tokens == ['first-court-bearer', 'first-court-bearer']
        assert account.value == {}
        assert settings_owner.AccountFiles(server.settings_dir / 'account.json').read('cached-read:' + key) == {}
    finally:
        released.set()
        server.httpd.server_close()
