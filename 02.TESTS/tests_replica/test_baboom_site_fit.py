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
import secrets
import time
from http.cookies import SimpleCookie
from urllib.error import HTTPError
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
                               'Project folders belong in the standard CDE container. [STD-21]')
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


@pytest.mark.parametrize('model_answer,accepted', [
    ('Fire doors must stay open. [STD-21]', False),
    ('Glass doors need 2 hours. [STD-21]', False),
    ('Fire doors must stay closed. [STD-21]', True),
    ('Fire doors must stay closed. [STD-22]', False),
    ('Fire doors must stay closed. [STD-21] Glass doors need 2 hours. [STD-21]', False),
    ('Fire doors must stay closed. Glass doors need 2 hours. [STD-21]', False),
    ('Fire doors must stay closed. [STD-21] Unsupported trailing claim.', False),
    ('Fire doors must stay closed [STD-21]. Fire doors need 2 hours [STD-21].', True),
    ('“FIRE doors   must stay closed!” [STD-21]', False),
    ('Fire doors need 999 hours. [STD-99]', False),
    ('Fire doors need 2 hours. [STD-21] [STD-99]', False),
    ('Fire doors need 2 hours.', False),
    ('Fire doors need 999 hours. [STD-21]', False),
    ('Fire doors need 2 hours. [STD-22]', False),
    ('Fire doors need 2 hours. [STD-21]', True),
])
def test_model_grounding_uses_only_cited_retrieved_passages(tmp_path, model_answer, accepted):
    path = tmp_path / 'index.json'
    path.write_text(json.dumps({'chunks': [
        {'id': 'STD-21', 'title': 'Fire doors', 'head': 'Rating', 'href': 'doors.html',
         'text': 'Fire doors must stay closed. Fire doors need 2 hours.'},
        {'id': 'STD-22', 'title': 'Other rules', 'head': 'Other rules', 'href': 'other.html',
         'text': 'Fire doors alternative rating is 999 hours.'}]}), encoding='utf-8')
    index = baboom_standard.Index(path)
    complete = Mock(side_effect=['fire doors', model_answer])
    result = baboom_standard.answer(index, 'fire doors', token='synthetic-reader', complete=complete)
    assert complete.call_count == 2
    if accepted:
        assert result['answer'].startswith('I am BABOOM, an AI assistant.')
        assert model_answer in result['answer']
    else:
        assert result == baboom_standard.answer(index, 'fire doors', token='synthetic-reader')
        assert model_answer not in json.dumps(result, ensure_ascii=False)
        assert 'Glass doors' not in json.dumps(result) and 'Unsupported' not in json.dumps(result)
        assert '999' not in result['answer'] and 'STD-99' not in result['answer']


def test_grounding_normalises_whitespace_without_changing_internal_punctuation():
    hits = [{'id': 'STD-21', 'text': 'Fire doors must stay closed. Fire doors need 2 hours.'}]
    assert not baboom_standard._grounded(' “FIRE doors\n must\tstay closed!” [STD-21] ', hits)
    assert baboom_standard._grounded(' “Fire doors\n must\tstay closed.” [STD-21] ', hits)
    assert baboom_standard._grounded('“Fire doors must stay closed.” [STD-21] “Fire doors need 2 hours.” [STD-21]', hits)
    assert not baboom_standard._grounded('Fire-doors must stay closed. [STD-21]', hits)
    assert not baboom_standard._grounded('Fire doors must stay closed.🔥 [STD-21]', hits)


def test_arabic_model_answer_falls_back_to_english_cited_excerpt(tmp_path):
    path = tmp_path / 'index.json'
    path.write_text(json.dumps({'chunks': [
        {'id': 'STD-21', 'title': 'Fire doors', 'head': 'Rating', 'href': 'doors.html',
         'text': 'Fire doors must stay closed. Fire doors need 2 hours.'}]}), encoding='utf-8')
    index = baboom_standard.Index(path)
    rejected = 'أبواب الحريق لازم تفضل مقفولة. [STD-21]'
    complete = Mock(side_effect=['fire doors', rejected])
    result = baboom_standard.answer(index, 'أبواب الحريق STD-21', token='synthetic-reader', complete=complete)
    assert complete.call_count == 2
    assert result == baboom_standard.answer(index, 'أبواب الحريق STD-21', token='synthetic-reader')
    assert 'Fire doors must stay closed.' in result['answer'] and '[STD 21]' in result['answer']
    assert rejected not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize('quantity', ['2 mm', '2 m²', '2 kg/m³', '2 °C', '2%', '2′', '2"', '2e3 Pa', '2 MPa'])
def test_grounding_matches_the_whole_quantity_and_unit(quantity):
    hits = [{'id': 'STD-21', 'text': 'The limit is ' + quantity + '.'}]
    assert baboom_standard._grounded('The limit is ' + quantity + '. [STD-21]', hits)
    assert not baboom_standard._grounded('The limit is ' + quantity.replace('2', '999', 1) + '. [STD-21]', hits)
    if 'm³' in quantity or 'mm' in quantity:
        changed_unit = quantity.replace('m³', 'm²').replace('mm', 'cm')
        assert not baboom_standard._grounded('The limit is ' + changed_unit + '. [STD-21]', hits)
    if 'MPa' in quantity:
        assert not baboom_standard._grounded('The limit is 2 mPa. [STD-21]', hits)


@pytest.mark.parametrize('passage,model_answer,accepted', [
    ('Do not leave fire doors open.', 'Leave fire doors open. [STD-21]', False),
    ('Only after the alarm is reset, open the fire door.', 'Open the fire door. [STD-21]', False),
    ('The limit is 2 MPa.', 'The limit is 2 mPa. [STD-21]', False),
    ('Do not leave fire doors open.', 'Do not leave fire doors open. [STD-21]', True),
    ('“Do  not leave fire doors open.”', ' “Do not\tleave fire doors\n open.” [STD-21] ', True),
    ('Do not leave fire doors open.', 'Do not leave Fire doors open. [STD-21]', False),
    ('Do not leave fire doors open.', 'fire doors open. [STD-21]', False),
    ('Do not leave fire doors open.', 'Do not leave fire doors open! [STD-21]', False),
    ('The limit is +2 MPa.', 'The limit is 2 MPa. [STD-21]', False),
    (' '.join(['word'] * 110) + ' until reset.', ' '.join(['word'] * 110) + ' [STD-21]', False),
    (' '.join(['word'] * 110) + ' until reset.', ' '.join(['word'] * 110) + '. [STD-21]', False),
    (' '.join(['word'] * 110) + ' until reset.', ' '.join(['word'] * 110) + ' until reset. [STD-21]', False),
    (' '.join(['word'] * 109) + ' reset.', ' '.join(['word'] * 109) + ' reset. [STD-21]', True),
    ('Keep closed. ' + ' '.join(['word'] * 110) + ' until reset.', 'Keep closed. [STD-21]', True),
    ('Keep closed. Reset first.', 'Keep closed. [STD-21] Reset first. [STD-21]', True),
    ('Keep closed. Reset first.', 'Keep closed. [STD-21] Open now. [STD-21]', False),
])
def test_model_requires_complete_exact_source_sentences(tmp_path, passage, model_answer, accepted):
    path = tmp_path / 'index.json'
    path.write_text(json.dumps({'chunks': [
        {'id': 'STD-21', 'title': 'Fire doors', 'head': 'Rules', 'href': 'doors.html',
         'text': passage}]}), encoding='utf-8')
    index = baboom_standard.Index(path)
    complete = Mock(side_effect=['', model_answer])
    result = baboom_standard.answer(index, 'STD-21', token='synthetic-reader', complete=complete)
    assert complete.call_count == 2
    assert baboom_standard._grounded(model_answer, index.chunks) is accepted
    if accepted:
        assert result['answer'] == baboom_standard.public_reply(model_answer)
        assert result['links'][0]['title'] == 'STD-21 Fire doors'
    else:
        assert result == baboom_standard.answer(index, 'STD-21', token='synthetic-reader')
        assert model_answer not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize('site,state,sends', [
    ('https://baboom.archhub.io', 'active', True),
    ('http://baboom.archhub.io', 'active', False),
    ('https://elsewhere.example', 'active', False),
    ('https://baboom.archhub.io.evil.example', 'active', False),
    ('https://baboom.archhub.io', 'expired', False),
    ('https://baboom.archhub.io', 'refused', False),
    ('https://baboom.archhub.io', 'absent', False),
])
def test_desktop_account_cookie_is_pinned_and_not_logged(monkeypatch, capsys, caplog, site, state, sends):
    from nodelang import cloud_signin
    credential = secrets.token_urlsafe(32)
    held = {'token': credential, 'expires_at': time.time() + (60 if state != 'expired' else -60),
            'refused_at': 1 if state == 'refused' else None} if state != 'absent' else {}
    read = Mock(return_value=held)
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', read)
    monkeypatch.setattr(baboom_standard, 'SITE', site)

    def open_request(request, **kwargs):
        cookie = SimpleCookie(request.get_header('Cookie') or '')
        assert bool('bbm_s' in cookie) == sends
        if sends:
            assert bool(cookie['bbm_s'].value == credential)
        assert credential not in request.full_url
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'answer': 'Sign in', 'links': [{'href': '/api/auth/start?next=/'}]}).encode()
        return response

    opener = Mock(open=open_request)
    monkeypatch.setattr(baboom_standard.http, 'build_opener', lambda handler: opener)
    assert baboom_standard.ask_standard('fire doors') == {
        'answer': 'The standard answer is unavailable. Open the standard site.', 'links': []}
    assert read.call_count == int(site == 'https://baboom.archhub.io')
    output = capsys.readouterr()
    assert credential not in output.out + output.err + caplog.text


@pytest.mark.parametrize('status', [401, 403])
def test_desktop_refused_account_is_truthfully_signed_out(monkeypatch, status):
    from nodelang import cloud_signin
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda path: {
        'token': secrets.token_urlsafe(32), 'expires_at': time.time() + 60})
    opener = Mock()
    opener.open.side_effect = HTTPError(baboom_standard.SITE + '/api/chat', status, 'refused', {}, None)
    monkeypatch.setattr(baboom_standard.http, 'build_opener', lambda handler: opener)
    assert baboom_standard.ask_standard('fire doors') == {
        'answer': 'The standard answer is unavailable. Open the standard site.', 'links': []}


@pytest.mark.parametrize('refusal', [401, 403])
def test_desktop_cookie_reaches_existing_site_validation(sites, monkeypatch, refusal):
    from nodelang import cloud_signin
    candidate = sites[1]
    credential = secrets.token_urlsafe(32)
    cloud_signin.write_cloud_session(cloud_signin.cloud_session_path(), {
        'token': credential, 'expires_at': time.time() + 60})
    with running(candidate) as port:
        real_opener = baboom_standard.http.build_opener(baboom_standard._NoRedirect)

        def tunnel(request, **kwargs):
            # Network mock: the production request stays HTTPS-pinned; only this test bridges to loopback.
            assert request.full_url == 'https://baboom.archhub.io/api/chat'
            local = baboom_standard.http.Request(f'http://127.0.0.1:{port}/api/chat', request.data,
                                                dict(request.header_items()), method='POST')
            return real_opener.open(local, **kwargs)

        monkeypatch.setattr(baboom_standard.http, 'build_opener', lambda handler: Mock(open=tunnel))
        assert '[STD-21]' in baboom_standard.ask_standard('project folders')['answer']
        assert all(bool(call.args[0] == credential) for call in candidate.complete.call_args_list)
        candidate.complete.side_effect = candidate.CloudError(refusal)
        assert baboom_standard.ask_standard('project folders')['answer'] == 'The standard answer is unavailable. Open the standard site.'
    candidate.cloud.assert_not_called()


def test_desktop_redirect_does_not_forward_cookie(monkeypatch):
    from nodelang import cloud_signin
    credential = secrets.token_urlsafe(32)
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda path: {
        'token': credential, 'expires_at': time.time() + 60})
    calls = []

    class Redirect(baboom_standard.http.BaseHandler):
        handler_order = 100

        def https_open(self, request):
            calls.append(request.full_url)
            return self.parent.error('http', request, None, 302, 'redirect',
                                     {'Location': 'https://elsewhere.example/api/chat'})

    build = baboom_standard.http.build_opener
    monkeypatch.setattr(baboom_standard.http, 'build_opener', lambda handler: build(handler, Redirect))
    with pytest.raises(HTTPError) as refused:
        baboom_standard.ask_standard('fire doors')
    assert refused.value.code == 302
    assert calls == ['https://baboom.archhub.io/api/chat']
