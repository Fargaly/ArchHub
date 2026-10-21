"""Fresh source desktop HTTP court; external providers are fakes, never the rig."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
INJECTION = r'''
import faulthandler, json, os, socket, threading, time
from pathlib import Path
from types import SimpleNamespace
from nodelang import application_server, model_catalogue, goose_runtime
from app import secrets_store
state = Path(os.environ['ARCHHUB_TEST_STATE_DIR'])
secrets_store._try_keyring = lambda: None
# All external edges are fake; desktop construction, authority, admissions and reads are real.
original_connect = socket.socket.connect
allowed_ports = set()
def connect(sock, address):
    if isinstance(address, tuple) and (address[0] not in ('127.0.0.1', 'localhost', '::1')
            or address[1] not in allowed_ports):
        raise OSError('READS court: external network forbidden')
    return original_connect(sock, address)
socket.socket.connect = connect
model_catalogue.openrouter_models = lambda **kw: [{'id': 'openrouter/free', 'name': 'Free', 'route': 'openrouter/free'}]
model_catalogue.local_models = lambda **kw: []
model_catalogue.subscription_cli_models = lambda **kw: []
goose_runtime.start_goose_for_baboom = lambda *a, **kw: None
def answer(*a, **kw):
    if kw.get('before_dispatch'): kw['before_dispatch']()
    return 'READS fake provider reply'
original_init = application_server.ApplicationServer.__init__
def init(self, *a, **kw):
    original_init(self, *a, **kw)
    self.goose_brain = SimpleNamespace(ask=answer)
application_server.ApplicationServer.__init__ = init
original_start = application_server.ApplicationServer.start
def start(self):
    allowed_ports.add(self.httpd.server_address[1])
    result = original_start(self)
    def ready():
        time.sleep(3)
        (state / 'http.json').write_text(json.dumps({'url': self.url, 'session': self.browser_session_token}), encoding='utf-8')
        time.sleep(9)
        with (state / 'threads.txt').open('w') as stream:
            faulthandler.dump_traceback(file=stream, all_threads=True)
    threading.Thread(target=ready, daemon=True).start()
    return result
application_server.ApplicationServer.start = start
'''

FAKE_PROVIDER = r'''
import io
from nodelang import model_router
original_discover_key = model_router.discover_key
def discover_key(family, **kwargs):
    if family == 'openrouter':
        return 'reads-fake-provider-key', 'READS fake credential'
    return original_discover_key(family, **kwargs)
model_router.discover_key = discover_key
original_urlopen = model_router.urllib.request.urlopen
def urlopen(request, *args, **kwargs):
    if getattr(request, 'full_url', '') != model_router.OPENROUTER_CHAT:
        return original_urlopen(request, *args, **kwargs)
    body = json.loads(request.data)
    assert body['model'] == 'openrouter/free'
    assert any('Reply PONG' in str(row.get('content', '')) for row in body['messages'])
    (state / 'provider-call.json').write_text(json.dumps({'model': body['model']}), encoding='utf-8')
    return io.BytesIO(json.dumps({'model': 'openrouter/free', 'usage': {'cost': 0},
        'choices': [{'message': {'role': 'assistant', 'content': 'READS fake provider reply'},
                     'finish_reason': 'stop'}]}).encode())
model_router.urllib.request.urlopen = urlopen
'''


@pytest.mark.parametrize(('rig_env', 'fake_provider'), [(False, False), (True, False), (False, True)],
    ids=['no-rig', 'rig-profile', 'fake-provider'])
def test_fresh_desktop_reads_and_first_send(tmp_path, rig_env, fake_provider):
    from tools.real_app_check.real_app_check import free_port, isolated_env
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    profile = tmp_path / 'profile'
    for name in ('APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'TEMP', 'state', 'claude-config'):
        (profile / name).mkdir(parents=True)
    injection = tmp_path / 'injection'
    injection.mkdir()
    (injection / 'sitecustomize.py').write_text(
        INJECTION + (FAKE_PROVIDER if fake_provider else ''), encoding='utf-8')
    env = isolated_env(dict(os.environ), profile, cdp_port=free_port(), lock_port=free_port())
    env.pop('OPENROUTER_API_KEY', None)
    env.update(PYTHONPATH=str(injection) + os.pathsep + str(ROOT),
        ARCHHUB_GRAND_MAP_PATH=str(ROOT / '01.APP/nodelang/data/public_runtime_map.json'),
        ARCHHUB_TEST_NO_OPEN='1', QT_QPA_PLATFORM='offscreen')
    if rig_env:
        # Exact pre-provisioning shape from real_app.py; the retired endpoint is popped there.
        code = """from pathlib import Path
import hashlib, json, os
from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
spec=Path('docs/SPEC.md').read_bytes()
gm=json.dumps([{'key':'workspace-root','title':'Workspace Root','nodes':[],'wires':[],'cross':[]}],sort_keys=True,separators=(',',':')).encode()
provision_clean_runtime(Path(os.environ['LOCALAPPDATA'])/'ArchHub/unified-authority', WindowsDpapiSigningKeyProvider(WindowsDpapiSigningKeyProvider.default_path()), WindowsDpapiCallerKeyStore(WindowsDpapiCallerKeyStore.default_path()), caller_key_id='founder.bootstrap', specification_source=spec, specification_sha256=hashlib.sha256(spec).hexdigest(), grand_map_source=gm, grand_map_sha256=hashlib.sha256(gm).hexdigest())
"""
        subprocess.run([sys.executable, '-B', '-c', code], env=env, cwd=ROOT, check=True, capture_output=True, timeout=120)
    proc = subprocess.Popen([sys.executable, '-B', str(ROOT / '01.APP/nodelang/launcher.py')],
        env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = []
    try:
        ready = profile / 'state/http.json'
        deadline = time.monotonic() + 120
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        log = profile / 'state/launcher.log'
        assert ready.exists(), log.read_text(encoding='utf-8')[-3000:]
        endpoint = json.loads(ready.read_text(encoding='utf-8'))
        headers = {'X-ArchHub-Session': endpoint['session'], 'Content-Type': 'application/json'}
        for path in ('/api/universal/models', '/api/universal/node-library?templates=1',
                     '/api/universal/hosts', '/api/universal/application-update'):
            began = time.monotonic()
            try:
                with urlopen(Request(endpoint['url'] + path, headers=headers), timeout=5) as response:
                    body = json.load(response)
                    row = {'path': path, 'status': response.status, 'body': body}
            except HTTPError as exc:
                row = {'path': path, 'status': exc.code, 'body': json.load(exc)}
            except TimeoutError:
                row = {'path': path, 'status': 'timeout'}
            row['seconds'] = round(time.monotonic() - began, 3)
            rows.append(row)
        began = time.monotonic()
        try:
            payload = json.dumps({'prompt': 'Reply PONG', 'model': 'openrouter/free',
                'graph': True, 'graph_id': 'app:canvas', 'generation': {'temperature': 0.7, 'top_p': 0.95, 'max_tokens': 4096},
                'request_id': 'reads-first-send'}).encode()
            try:
                response = urlopen(Request(endpoint['url'] + '/api/universal/agent', data=payload, headers=headers), timeout=30)
            except HTTPError as exc:
                response = exc
            with response:
                chat = {'status': response.status, 'body': json.load(response)}
        except TimeoutError:
            chat = {'status': 'timeout'}
        chat['seconds'] = round(time.monotonic() - began, 3)
        provider_call = profile / 'state/provider-call.json'
        report = {'rig_env': rig_env, 'fake_provider': fake_provider, 'reads': rows, 'chat': chat,
            'provider_call': json.loads(provider_call.read_text(encoding='utf-8')) if provider_call.exists() else None}
        out = tmp_path / 'EVIDENCE'
        out.mkdir(exist_ok=True)
        label = 'fake-provider' if fake_provider else ('rig-profile' if rig_env else 'no-rig')
        (out / (label + '.json.txt')).write_text(json.dumps(report, indent=2), encoding='utf-8')
        for name in ('launcher.log', 'threads.txt'):
            source = profile / 'state' / name
            if source.exists():
                (out / (label + '-' + name)).write_bytes(source.read_bytes())
        assert rows[0]['status'] == 200 and rows[0]['seconds'] < 5, report
        assert any(item.get('route') == 'openrouter/free' or item.get('id') == 'openrouter/free'
            for group in rows[0]['body'].get('groups', ()) for item in group.get('items', ())), report
        assert all(r['status'] != 'timeout' and (r['status'] == 200 or r['body'].get('error')) for r in rows), report
        assert chat['status'] != 'timeout' and chat['seconds'] < 30, report
        assert chat['status'] == 200 or chat['body'].get('error'), report
        answer = chat['body'].get('answer') or chat['body'].get('reply')
        error = chat['body'].get('error')
        assert ((isinstance(answer, str) and answer.strip())
            or (isinstance(error, str) and error.strip())), report
        if fake_provider:
            assert report['provider_call'] == {'model': 'openrouter/free'}, report
            assert chat['status'] == 200 and chat['body'].get('ok') is True, report
            assert answer == 'READS fake provider reply', report
            assert not error, report
        else:
            assert isinstance(error, str) and 'No OpenRouter key' in error, report
    finally:
        proc.terminate()
        proc.wait(timeout=10)
