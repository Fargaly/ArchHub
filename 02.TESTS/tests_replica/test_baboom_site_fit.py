"""Exercise the real site adapter over loopback, without model or external traffic."""
from contextlib import contextmanager
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
from unittest.mock import Mock

import pytest

from nodelang import baboom_standard, host_addin_retarget

ROOT = Path(__file__).resolve().parents[2]
SERVER = Path('C:/Users/fargaly/00.ARCHUB/50.TOOLING/52.AEC-LIBRARIES/52.03-BA-STANDARD/14.BABOOM-CHAT/server.py')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sites(tmp_path, monkeypatch):
    prepared = tmp_path / 'prepared'
    subprocess.run([sys.executable, '-B', str(ROOT / '03.TOOLS/tools/prepare_baboom_site.py'),
                    str(SERVER), '--out', str(prepared)], check=True, capture_output=True, timeout=30)
    # Load the copied product bytes, rather than a cached source-checkout module.
    for name in ('baboom_persona', 'baboom_standard'):
        qualified = 'nodelang.' + name
        module = load(qualified, prepared / 'nodelang' / (name + '.py'))
        monkeypatch.setitem(sys.modules, qualified, module)
    original = load('original_site', SERVER)
    candidate = load('prepared_site', prepared / 'server.py')
    index = tmp_path / 'index.json'
    index.write_text(json.dumps({'chunks': [
        {'id': 'STD-21', 'title': 'Project folders', 'head': 'Project folders',
         'href': 'folders with spaces.html', 'text': 'Project folders belong in the standard CDE container.'},
        {'id': 'STD-01', 'title': 'Standard manual', 'head': 'Manual',
         'href': 'manual.html', 'text': 'The standard manual describes project folders.'}]}), encoding='utf-8')
    connect = socket.socket.connect

    def loopback(sock, address):
        assert address[0] == '127.0.0.1', 'external network forbidden'
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', loopback)
    for module in (original, candidate):
        module.IDX = module.Index(index)
        module.cloud = Mock(side_effect=AssertionError('external router forbidden'))
        module.complete = Mock(side_effect=lambda token, system, user, *args, **kwargs:
                               'project folders' if system.startswith('Rewrite') else
                               'Project folders belong in the CDE. [STD-21]')
    return original, candidate


@contextmanager
def running(module):
    module.LIM = module.Limits()
    server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def post(port, question, page, signed_in=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        headers = {'Content-Type': 'application/json'}
        if signed_in:
            headers['Cookie'] = 'bbm_s=synthetic-reader'
        connection.request('POST', '/api/chat', json.dumps({'question': question, 'page': page}), headers)
        response = connection.getresponse()
        assert response.status == 200
        return json.loads(response.read())
    finally:
        connection.close()


@pytest.mark.parametrize('question,page', [
    ('project folders', '/folders with spaces.html?x=1&y=2'),
    ('project obscure', '//elsewhere.example'),
    ('standard', 'https://elsewhere.example'),
    ('interstellar quantum', '/'), ('who are you?', '/'), ('فين الشيت؟', '/')])
def test_prepared_signed_out_matches_real_site_without_models(sites, question, page):
    replies = []
    for module in sites:
        with running(module) as port:
            replies.append(post(port, question, page))
        module.complete.assert_not_called()
        module.cloud.assert_not_called()
    assert replies[0] == replies[1]
    assert set(replies[1]) == {'answer', 'links'}
    assert set(replies[1]['links'][0]) == {'title', 'href', 'sub'}
    assert replies[1]['links'][0]['href'].startswith('/api/auth/start?next=/')


def test_prepared_signed_in_keeps_router_and_expired_token_fallback(sites):
    for module in sites:
        with running(module) as port:
            result = post(port, 'project folders', '/', signed_in=True)
            assert '[STD-21]' in result['answer']
            assert module.complete.call_count == 2
            assert all(call.args[0] == 'synthetic-reader' for call in module.complete.call_args_list)
            module.complete.reset_mock(side_effect=True)
            if module is sites[1]:
                assert result['answer'].startswith('I am BABOOM, an AI assistant.')
                assert post(port, 'who are you?', '/', signed_in=True) == {'answer': 'I am BABOOM, an AI assistant.', 'links': []}
                module.complete.assert_not_called()
            module.complete.side_effect = module.CloudError(401)
            expired = post(port, 'project folders', '/', signed_in=True)
            module.complete.assert_called_once()
            assert expired == module.answer(module.IDX, 'project folders', '', '/')
        module.cloud.assert_not_called()


def test_desktop_rejects_prepared_signin_prose_even_with_a_citation(sites, monkeypatch):
    candidate = sites[1]
    with running(candidate) as port:
        monkeypatch.setattr(baboom_standard, 'SITE', f'http://127.0.0.1:{port}')
        monkeypatch.setattr(sys.modules['nodelang.baboom_standard'], 'SITE', f'http://127.0.0.1:{port}')
        expected = {'answer': 'The standard answer is unavailable. Open the standard site.', 'links': []}
        assert baboom_standard.ask_standard('project folders') == expected
        from nodelang import baboom_nograph
        assert baboom_nograph.ask('where do project folders go?')['text'] == expected['answer']
        original_answer = candidate.answer

        def cited_signin(*args, **kwargs):
            reply = original_answer(*args, **kwargs)
            return {**reply, 'answer': reply['answer'] + ' [STD-21]'}

        monkeypatch.setattr(candidate, 'answer', cited_signin)
        assert baboom_standard.ask_standard('project folders') == expected
    candidate.complete.assert_not_called()


def test_real_persona_manifest_has_exact_hash_and_keeps_user_data_excluded(tmp_path):
    source = ROOT / '01.APP'
    manifest = tmp_path / 'source-manifest.tsv'
    host_addin_retarget.write_manifest(source, tmp_path / 'hosts', manifest)
    rows = host_addin_retarget.manifest_rows(manifest.read_bytes())
    name = 'nodelang/data/baboom/persona.json'
    assert rows[name] == hashlib.sha256((source / name).read_bytes()).hexdigest()
    assert host_addin_retarget.protected(Path(name))
