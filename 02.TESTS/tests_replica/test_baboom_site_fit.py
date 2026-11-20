"""Exercise the real site adapter over loopback, without model or external traffic."""
from contextlib import contextmanager
import hashlib
import html
import http.client
import importlib.util
import json
from pathlib import Path
import re
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
    return prepare_sites(tmp_path, monkeypatch)


def prepare_sites(tmp_path, monkeypatch, catalogue=None):
    prepared = tmp_path / 'prepared'
    command = [sys.executable, '-B', str(ROOT / '03.TOOLS/tools/prepare_baboom_site.py'),
               str(SERVER), '--out', str(prepared)]
    if catalogue is not None:
        command += ['--catalogue', str(catalogue)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
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


def test_public_catalogue_drives_node_answers_and_excludes_local_capabilities(tmp_path, monkeypatch):
    export = ROOT / '03.TOOLS/packaging/website/export_catalogue.py'
    subprocess.run([sys.executable, '-B', str(export)], check=True, capture_output=True, timeout=60)
    data = json.loads((ROOT / '.cache/site/catalogue.json').read_text(encoding='utf-8'))
    public_count = len(data['nodes'])
    field = next(node for node in data['nodes'] if node['id'] == 'data.field')
    assert field['outputs'] == [{'name': 'values', 'type': 'list'}]
    manual = next(node for node in data['nodes'] if node['id'] == 'tr_manual')
    assert manual['title'] == 'Manual run' and manual['sub'] == 'starts when you press Run'
    assert len([node for node in data['nodes'] if node['title'].casefold() == 'merge']) > 1
    for category in ('skill', 'workspaces', 'models', 'agents'):
        data['nodes'].append({**field, 'id': f'local.{category}', 'cat': category,
                              'title': f'Hidden {category}', 'sub': 'MACHINE_ONLY_CATALOGUE_FIXTURE'})
    catalogue = tmp_path / 'catalogue.json'
    catalogue.write_text(json.dumps(data), encoding='utf-8')
    _, candidate = prepare_sites(tmp_path, monkeypatch, catalogue)
    chunks = json.loads((tmp_path / 'prepared/product-docs.json').read_text(encoding='utf-8'))['chunks']
    assert len([chunk for chunk in chunks if 'node_fields' in chunk]) == public_count
    assert 'MACHINE_ONLY_CATALOGUE_FIXTURE' not in json.dumps(chunks)
    with running(candidate) as port:
        questions = [
            ('What does the Field node output?', 'Outputs: values (list)'),
            ('ما مخرجات عقدة Field؟', 'المخرجات: values (list)'),
            ('What parameters does the Field node have?', 'Parameters: type (text)'),
            ('ما مدخلات عقدة Field؟', 'المدخلات: column (list), type (string)'),
        ]
        for question, expected in questions:
            reply = post(port, question, '/')
            assert expected in reply['answer']
            assert reply['links'] == [{'title': 'Field', 'href': 'https://archhub.io/docs/nodes/data-field/',
                                       'sub': 'Node reference'}]
    manual_href = 'https://archhub.io/docs/nodes/tr-manual/'
    with running(candidate) as port:
        for question, page in [
            ('tr_manual', '/'),
            ('When does the Manual run node start?', '/'),
            ('When does Manual run start?', '/'),
            ('\u0645\u062a\u0649 \u062a\u0628\u062f\u0623 \u0639\u0642\u062f\u0629 Manual run\u061f', '/'),
            ('\u0646\u0648\u062f tr_manual \u0628\u062a\u0634\u062a\u063a\u0644 \u0625\u0645\u062a\u0649\u061f', '/'),
            ('What does tr-manual do?', '/'),
        ]:
            reply = post(port, question, page)
            assert 'starts when you press Run. [tr_manual]' in reply['answer']
            assert reply['links'] == [{'title': 'Manual run', 'href': manual_href, 'sub': 'Node reference'}]
    with running(candidate) as port:
        for question, page in [
            ('When does it start?', '/docs/nodes/tr-manual/?tab=reference'),
            ('When does this node start?', manual_href),
        ]:
            reply = post(port, question, page)
            assert 'starts when you press Run. [tr_manual]' in reply['answer']
            assert reply['links'] == [{'title': 'Manual run', 'href': manual_href, 'sub': 'Node reference'}]
        for question in ('tr_manual outputs', 'Manual run node outputs'):
            reply = post(port, question, '/')
            assert 'Outputs: out (trigger), fire (unknown). [tr_manual]' in reply['answer']
            assert reply['links'][0]['href'] == manual_href
    with running(candidate) as port:
        reply = post(port, 'l_merge_handoff outputs', '/')
        assert 'value (any)' in reply['answer']
        assert reply['links'][0]['href'] == 'https://archhub.io/docs/nodes/l-merge-handoff/'
        for question in ('What does the Merge node output?', 'tr.manual outputs', 'tr.manual',
                         'What are the outputs of the Manual run node and the Field node?'):
            reply = post(port, question, '/')
            assert reply == {'answer': 'I could not find a matching node in the public node reference.', 'links': []}
    with running(candidate) as port:
        for question, page in [
            ('What does this node do?', 'https://other.example/docs/nodes/tr-manual/'),
            ('What does this node do according to STD-21?', '/docs/nodes/tr-manual/'),
            ('Where do project folders go?', '/docs/nodes/tr-manual/'),
        ]:
            reply = post(port, question, page)
            assert reply['links'][0]['href'].startswith('/api/auth/start?')
            assert all(link['href'] != manual_href for link in reply['links'])
    with running(candidate) as port:
        for category in ('skill', 'workspaces', 'models', 'agents'):
            reply = post(port, f'What does the Hidden {category} node output?', '/', signed_in=True)
            assert reply['links'] == []
            assert 'Hidden' not in reply['answer'] and 'MACHINE_ONLY' not in reply['answer']
        reply = post(port, 'What does the Hidden skill node do?', '/', signed_in=True)
        assert reply['links'] == [] and 'MACHINE_ONLY' not in reply['answer']
        reply = post(port, 'ما مخرجات عقدة Hidden skill؟', '/')
        assert reply == {'answer': 'لم أجد عقدة مطابقة في دليل العقد العام.', 'links': []}
    candidate.complete.assert_not_called()
    candidate.cloud.assert_not_called()

    field['outputs'][0]['type'] = 'table'
    manual['sub'] = 'Starts from the updated catalogue'
    catalogue.write_text(json.dumps(data), encoding='utf-8')
    _, refreshed = prepare_sites(tmp_path / 'refreshed', monkeypatch, catalogue)
    with running(refreshed) as port:
        reply = post(port, 'What does the Field node output?', '/')
        manual_reply = post(port, 'tr-manual', '/')
    assert 'Starts from the updated catalogue. [tr_manual]' in manual_reply['answer']
    assert manual_reply['links'][0]['href'] == manual_href
    assert 'values (table)' in reply['answer'] and 'values (list)' not in reply['answer']
    assert reply['links'][0]['href'] == 'https://archhub.io/docs/nodes/data-field/'
    refreshed.complete.assert_not_called()


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
        monkeypatch.setitem(baboom_nograph._STATE, 'brain', object())   # enabled; a standard answer never asks it
        assert baboom_nograph.ask('where do project folders go?')['text'] == expected['answer']
        original_answer = candidate.answer

        def cited_signin(*args, **kwargs):
            reply = original_answer(*args, **kwargs)
            return {**reply, 'answer': reply['answer'] + ' [STD-21]'}

        monkeypatch.setattr(candidate, 'answer', cited_signin)
        assert baboom_standard.ask_standard('project folders') == expected
    candidate.complete.assert_not_called()


@pytest.mark.parametrize('english,arabic,keywords,citation,href,quote,arabic_quote', [
    ('What is ArchHub?', 'ما هو آرك هب؟', 'ArchHub Windows desktop app',
     'getting-started', 'https://archhub.io/docs/getting-started/',
     'ArchHub is a Windows desktop app.', 'آرك هب تطبيق سطح مكتب لنظام ويندوز.'),
    ('How do I add a subtask?', 'كيف أضيف مهمة فرعية؟', 'add subtask properties workshop',
     'workshop', 'https://archhub.io/docs/workshop/',
     'In Properties, enter a title in New subtask and choose Add subtask.',
     'في الخصائص، أدخل عنوانًا في مهمة فرعية جديدة واختر إضافة مهمة فرعية.'),
    ('How do I add a tool server?', 'كيف أضيف خادم أدوات؟', 'add tool server settings connections MCP',
     'connectors', 'https://archhub.io/docs/connectors/',
     'Enter a server address, a command or an MCP JSON snippet, then choose Add tool server.',
     'أدخل عنوان الخادم أو أمرًا أو مقطع MCP JSON، ثم اختر إضافة خادم أدوات.'),
    ('Does setup open a window on first run?', 'هل تظهر نافذة عند الإعداد لأول مرة؟',
     'first open setup background window', 'getting-started', 'https://archhub.io/docs/getting-started/',
     'ArchHub runs setup in the background on first open.',
     'عند فتح آرك هب لأول مرة، يجري الإعداد في الخلفية.'),
    ('Where is my launcher log?', 'أين سجل تشغيل التطبيق؟',
     'startup logs launcher log', 'getting-started', 'https://archhub.io/docs/getting-started/',
     r'On a standard installation, the launcher log is %LOCALAPPDATA%\ArchHub\logs\launcher.log.',
     r'في التثبيت العادي، تجد سجل تشغيل التطبيق في %LOCALAPPDATA%\ArchHub\logs\launcher.log.'),
    ('Does closing the window quit ArchHub?', 'هل إغلاق النافذة ينهي تشغيل آرك هب؟',
     'close quit window tray', 'getting-started', 'https://archhub.io/docs/getting-started/',
     'When the tray is available, closing the window with X sends ArchHub to the tray.',
     'عندما تكون منطقة الإعلام متاحة، يؤدي إغلاق النافذة بزر X إلى نقل آرك هب إليها.'),
    ('Where do project folders go?', 'أين توضع مجلدات المشروع؟', 'project folders',
     'STD-21', '/folders%20with%20spaces.html',
     'Project folders belong in the standard CDE container.', None),
])
@pytest.mark.parametrize('in_arabic', [False, True])
def test_prepared_site_answers_from_cited_guides_in_both_languages(
        sites, english, arabic, keywords, citation, href, quote, arabic_quote, in_arabic):
    candidate = sites[1]
    selected = arabic_quote if in_arabic and arabic_quote else quote

    def complete(token, system, user, *args):
        assert token == 'synthetic-reader'
        if system.startswith('Rewrite'):
            return keywords
        assert f'[{citation}]' in user and selected in user
        return f'{selected} [{citation}]'

    candidate.complete.side_effect = complete
    with running(candidate) as port:
        reply = post(port, arabic if in_arabic else english, '/', signed_in=True)
    assert f'{selected} [{citation}]' in reply['answer']
    if in_arabic and not arabic_quote:
        assert 'النص الأصلي الموثق بالإنجليزية' in reply['answer']
    assert [link['href'] for link in reply['links']] == [href]
    assert candidate.complete.call_count == 2


def test_arabic_reply_does_not_rewrite_the_meaning_of_a_verified_quote(sites):
    candidate = sites[1]
    false_translation = 'آرك هب تطبيق للتنبؤ بالطقس.'
    candidate.complete.side_effect = [
        'ArchHub Windows desktop app',
        'ArchHub is a Windows desktop app. [getting-started]',
        false_translation,
    ]
    with running(candidate) as port:
        reply = post(port, 'ما هو آرك هب؟', '/', signed_in=True)
        assert 'النص الأصلي الموثق بالإنجليزية' in reply['answer']
        assert 'ArchHub is a Windows desktop app. [getting-started]' in reply['answer']
        assert false_translation not in reply['answer']
        assert candidate.complete.call_count == 2
        candidate.complete.side_effect = [
            'ArchHub Windows desktop app', f'{false_translation} [getting-started]']
        refused = post(port, 'ما هو آرك هب؟', '/', signed_in=True)
    assert refused['links'] == []
    assert 'لم أجد إجابة' in refused['answer']


@pytest.mark.parametrize('question,expected', [
    ('How do I bake sourdough?', 'I could not find an answer'),
    ('كيف أخبز خبز العجين المخمر؟', 'لم أجد إجابة'),
])
def test_prepared_site_refuses_out_of_scope(sites, question, expected):
    candidate = sites[1]
    candidate.complete.side_effect = lambda *args: 'bake sourdough' if args[1].startswith('Rewrite') else 'OUT_OF_SCOPE'
    with running(candidate) as port:
        reply = post(port, question, '/', signed_in=True)
    assert expected in reply['answer']
    assert reply['links'] == []


@pytest.mark.parametrize('question,keywords,unsupported', [
    ('Can ArchHub teleport Revit models?', 'ArchHub Revit connectors',
     'ArchHub can teleport Revit models. [connectors]'),
    ('Can I set project units in Settings Projects?', 'ArchHub Settings project units',
     'You can change project units in Settings Projects. [getting-started]'),
])
def test_prepared_site_rejects_unsupported_capability_with_a_real_citation(
        sites, question, keywords, unsupported):
    candidate = sites[1]
    candidate.complete.side_effect = [keywords, unsupported]
    with running(candidate) as port:
        reply = post(port, question, '/', signed_in=True)
    assert reply['links'] == []
    assert 'I could not find an answer' in reply['answer']
    assert candidate.complete.call_count == 2


@pytest.mark.parametrize('question,phrase', [
    ('What is ArchHub and how do I use its Canvas?', 'ArchHub is a Windows desktop app.'),
    ('يعني إيه أرك هب وأستخدم الكانفاس إزاي؟', 'آرك هب تطبيق سطح مكتب لنظام ويندوز.'),
])
def test_signed_out_overview_reads_public_guide_without_model(sites, question, phrase):
    candidate = sites[1]
    with running(candidate) as port:
        reply = post(port, question, '/')
    assert phrase in reply['answer'] and '[getting-started]' in reply['answer']
    assert [link['href'] for link in reply['links']] == ['https://archhub.io/docs/getting-started/']
    candidate.complete.assert_not_called()
    candidate.cloud.assert_not_called()


def test_chat_guide_passages_are_present_at_the_built_public_citation_urls(tmp_path, monkeypatch):
    website = load('public_website', ROOT / '03.TOOLS/packaging/website/build_site.py')
    monkeypatch.setattr(website, 'catalogue', lambda: {'categories': [], 'nodes': [], 'starters': []})
    output = tmp_path / 'website'
    website.build_site(output, 'citation-test', 'https://example.test/citation-test/setup.exe', '0' * 64)
    overview = (output / 'docs/getting-started/index.html').read_text(encoding='utf-8')
    article = overview.split('<main ', 1)[1].split('</main>', 1)[0]
    assert '<a href="/download/">Download ArchHub</a>' in article
    assert '<a href="/account/">Your account</a>' in article
    assert '<a href="/security/">Account privacy</a>' in article
    assert '<a href="https://github.com/Fargaly/ArchHub/issues">Report a problem</a>' in article
    assert (output / 'account/index.html').is_file()
    assert (output / 'security/index.html').is_file()
    pages = {}
    chunks = list(baboom_standard.public_doc_chunks(ROOT / '01.APP/nodelang/site_export.py'))
    assert len({chunk['id'] for chunk in chunks}) == 9
    for chunk in chunks:
        slug = chunk['id']
        if slug not in pages:
            page = (output / 'docs' / slug / 'index.html').read_text(encoding='utf-8')
            article = page.split('<main ', 1)[1].split('</main>', 1)[0]
            pages[slug] = ' '.join(html.unescape(re.sub(r'<[^>]*>', '', article.replace('</li>', ' '))).split())
        for line in chunk['text'].splitlines():
            visible = re.sub(r'^(?:- |\d+\. )', '', line.strip())
            assert ' '.join(visible.split()) in pages[slug], (slug, visible)


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
