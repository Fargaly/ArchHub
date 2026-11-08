"""BABOOM contracts exercised through native events, HTTP and an isolated offscreen Qt window."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from nodelang import agent_status, baboom_persona, baboom_reactions, baboom_standard
from nodelang.baboom_persona import host_outcome, safe_speech


@pytest.mark.parametrize('text', ['x' * 141, 'two\nlines', 'https://example.com', r'C:\secret\file.py',
                                 '/home/me/file', 'relative/file.txt', 'const x = 1', 'def hello():',
                                 'Bearer hidden', 'api_key=hidden', 'sk-' + 'x' * 40, 'a' * 40,
                                 'x = 1', 'a@example.com', 'text\u2028more', 'example.com', 'print(1)'])
def test_unsafe_speech_is_rejected_whole(text):
    assert not safe_speech(text)
    assert baboom_persona.speech(text) == 'Open the task for details.'
    assert baboom_persona.speech(text, 'https://unsafe.example') == 'Open the task for details.'


def test_persona_is_brand_data_reloaded_next_turn_and_cannot_grant_permissions(tmp_path, monkeypatch):
    persona = baboom_persona.load_persona()
    assert len(persona['moments']) == 6
    assert persona['source']['quote'] == 'One voice, his: precise, practical, a little playful. The tone moves with the moment.'
    for moment in persona['moments'].values():
        assert safe_speech(moment['en']) and safe_speech(moment['ar'])
    path = tmp_path / 'persona.json'
    path.write_text(json.dumps(persona), encoding='utf-8')
    monkeypatch.setattr(baboom_persona, 'PERSONA', path)
    before = baboom_persona.persona_instructions()
    persona.update(tone=['Use exact counts.'], permissions='unlock-every-tool')
    path.write_text(json.dumps(persona), encoding='utf-8')
    after = baboom_persona.persona_instructions()
    assert before != after and 'Use exact counts.' in after and 'unlock-every-tool' not in after
    from nodelang import hook_decision
    event = {'session_id': 'persona-court', 'tool_name': 'Write', 'tool_input': {'path': 'sample.txt', 'content': 'hello'}}
    monkeypatch.setattr(hook_decision, 'scan_secrets', lambda *a, **k: ('ok', [], 'test'))
    monkeypatch.setattr(hook_decision, 'cedar_forbids', lambda *a, **k: ('ok', ['court-refusal']))
    assert hook_decision.decide(event, 'claude-code')['verdict'] == 'refuse'


@pytest.mark.parametrize('status,expected', [('failed', 'failed'), ('denied', 'refused'), ('running', 'unconfirmed')])
def test_host_receipt_overrules_model_prose(status, expected):
    assert expected in host_outcome([{'status': status}])
    assert host_outcome([{'status': 'ok', 'result': [{'type': 'text', 'text': '{"ok":false}'}]}]) == 'A tool failed. Open the task for its status.'
    assert host_outcome([{'status': 'ok', 'result': [{'type': 'content', 'content': {'type': 'text', 'text': '{"ok":false}'}}]}]) == 'A tool failed. Open the task for its status.'
    assert host_outcome([{'status': 'ok', 'result': {'structuredContent': {'ok': False}}}]) == 'A tool failed. Open the task for its status.'


def test_non_founder_identity_is_deterministic_without_a_model(monkeypatch):
    from nodelang import baboom_nograph
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', None)
    assert baboom_nograph.ask('Are you a human?')['text'] == 'I am BABOOM, an AI assistant.'
    assert baboom_persona.public_reply('I am a human.') == baboom_persona.IDENTITY + ' Open the task for details.'
    assert not baboom_standard.is_standard_question('Apply the standard to the sheets')


def test_failed_tool_reaches_the_companion_as_host_status(monkeypatch):
    from nodelang import baboom_nograph, settings_owner

    class Brain:
        def ask(self, *args, **kwargs):
            return {'text': '{"answer":"Done. Everything succeeded.","actions":[{"tool":"write"}]}',
                    'steps': [{'tool': 'Revit', 'status': 'failed'}], 'via': {'model': 'court'}}

    monkeypatch.setitem(baboom_nograph._STATE, 'brain', Brain())
    monkeypatch.setattr(settings_owner, 'read_router_settings', lambda: {
        'agents': {}, 'providerPreferences': {}, 'default_model': 'openrouter/free',
        'providers': {'openrouter': {'enabled': True}}})
    result = baboom_nograph.ask('Read the model')
    assert result['text'] == 'A tool failed. Open the task for its status.'
    assert result['actions'] == []
    assert baboom_nograph.NoGraphTransport().respond_baboom_command(utterance='Read the model')['response']['summary'] == result['text']


def test_shared_index_http_answer_and_unknown_rule(tmp_path, monkeypatch):
    index_path = tmp_path / 'index.json'
    index_path.write_text(json.dumps({'chunks': [
        {'id': 'STD-FOLDERS-02', 'title': 'Project folders', 'head': 'Project folders',
         'href': 'folders.html', 'text': 'Project folders belong in the project CDE container.'}]}), encoding='utf-8')
    index = baboom_standard.Index(index_path)
    question = 'where do project folders go?'
    expected = baboom_standard.answer(index, question)
    assert expected['answer'].startswith(baboom_persona.IDENTITY)
    assert '[STD FOLDERS-02]' in expected['answer']
    assert not baboom_standard.answer(index, 'interstellar quantum rules')['links']

    class Site(BaseHTTPRequestHandler):
        def do_POST(self):
            q = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['question']
            body = json.dumps(baboom_standard.answer(index, q)).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(baboom_standard, 'SITE', 'http://127.0.0.1:' + str(server.server_port))
    try:
        assert baboom_standard.ask_standard(question) == expected
        from nodelang import baboom_nograph
        assert baboom_nograph.ask(question)['text'] == expected['answer']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_explicit_profile_reaches_transcript_projection_and_activity(tmp_path, monkeypatch):
    environment = {'ARCHHUB_TEST_STATE_DIR': str(tmp_path / 'explicit-state'), 'ARCHHUB_AGENT_PROFILE': str(tmp_path / 'explicit-home')}
    path = tmp_path / 'native.jsonl'
    path.write_text(json.dumps({'payload': {'type': 'task_started'}}) + '\n', encoding='utf-8')
    captured = []
    monkeypatch.setattr(baboom_reactions, 'emit', lambda *args, **kwargs: captured.append(kwargs))
    agent_status.project_baboom_reaction('codex', 'explicit-profile', path, environment=environment)
    assert captured[0]['environment'] is environment
    state = Path(environment['ARCHHUB_TEST_STATE_DIR']) / 'workshop'
    state.mkdir(parents=True)
    with sqlite3.connect(state / 'messages.sqlite3') as db:
        db.execute('CREATE TABLE workshop_declarations(record TEXT)')
        db.execute('INSERT INTO workshop_declarations VALUES(?)', (json.dumps({'runtime': 'codex', 'native_session_id': 'explicit-profile'}),))
        db.execute('CREATE TABLE workshop_activity(sequence INTEGER PRIMARY KEY, at TEXT, action TEXT, detail TEXT)')
    monkeypatch.setattr(agent_status, 'project_baboom_reaction', lambda *args, **kwargs: captured.append(kwargs))
    assert baboom_reactions.latest(environment=environment) is None
    assert captured[-1]['environment'] is environment


def test_live_codex_log_growth_is_seen_when_windows_mtime_stays_at_open(tmp_path):
    environment = {'ARCHHUB_TEST_STATE_DIR': str(tmp_path / 'state')}
    path = tmp_path / 'open-rollout.jsonl'
    path.touch()
    held_mtime = int((time.time() - 60) * 1_000_000_000)
    for payload, expected in [({'type': 'task_started'}, 'thinking'),
                              ({'type': 'function_call', 'name': 'apply_patch'}, 'editing'),
                              ({'type': 'task_complete'}, 'success')]:
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'payload': payload}) + '\n')
        os.utime(path, ns=(held_mtime, held_mtime))
        agent_status.project_baboom_reaction('codex', 'held-open-writer', path, environment=environment)
        assert baboom_reactions.latest(environment=environment).state == expected


def test_existing_compact_standard_ids_resolve_only_the_indexed_rule(tmp_path):
    path = tmp_path / 'index.json'
    path.write_text(json.dumps({'chunks': [
        {'id': 'STD-21', 'title': 'BIM initiation', 'head': 'Project initiation',
         'href': 'initiation.html', 'text': 'Start the project with the approved template.'},
        {'id': 'STD-01', 'title': 'Manual', 'head': 'Pages', 'href': 'manual.html',
         'text': 'See page 21 for background.'}]}), encoding='utf-8')
    index = baboom_standard.Index(path)
    for question in ('STD21', 'what does STD-21 say?', 'standard 21'):
        assert {c['id'] for c in index.search(question)} == {'STD-21'}
        assert '[STD 21]' in baboom_standard.answer(index, question)['answer']
    for question in ('STD1', 'STD-01', 'standard 1'):
        assert {c['id'] for c in index.search(question)} == {'STD-01'}
    assert not index.search('STD99')


def test_release_admits_the_persona_without_widening_json_admission(tmp_path):
    script = tmp_path / 'persona-admission.ps1'
    script.write_text(r'''
param([string]$Build)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'release script does not parse' }
$definition = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Test-CandidateInput'}, $true)
if (-not $definition) { throw 'release admission function is absent' }
. ([scriptblock]::Create($definition.Extent.Text))
$acompilerInputs = @()
@{persona=(Test-CandidateInput 'selected' 'nodelang/data/baboom/persona.json');
  otherJson=(Test-CandidateInput 'selected' 'nodelang/data/baboom/notes.json');
  credentials=(Test-CandidateInput 'selected' 'nodelang/data/baboom/credentials.json')} | ConvertTo-Json -Compress
''', encoding='utf-8')
    shell = shutil.which('powershell') or shutil.which('pwsh')
    build = Path(__file__).resolve().parents[2] / '03.TOOLS/installer/build_release.ps1'
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(script), str(build)],
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == {'persona': True, 'otherJson': False, 'credentials': False}


@pytest.mark.parametrize('vendor', ['claude-code', 'codex', 'gemini', 'opencode', 'cursor', 'goose'])
def test_every_vendor_maps_and_throttles_without_storing_input(vendor):
    secret = r'C:\private\secret.py'
    payload = {'session_id': vendor, 'hook_event_name': 'UserPromptSubmit', 'prompt': secret}
    assert baboom_reactions.emit(payload, vendor)
    assert not baboom_reactions.emit(payload, vendor)
    for event, expected in [('PermissionRequest', 'waiting'), ('Stop', 'success'), ('StopFailure', 'error')]:
        assert baboom_reactions.emit({**payload, 'hook_event_name': event}, vendor)
        assert baboom_reactions.latest().state == expected
    assert baboom_reactions.reaction_kind({'tool_name': 'Bash', 'tool_input': {'command': 'python -m pytest'}}) == 'testing'
    assert baboom_reactions.reaction_kind({'tool_name': 'apply_patch'}) == 'editing'
    assert baboom_reactions.reaction_kind({'tool_name': 'shell_command', 'arguments': '{"command":"Set-Content proof-note.txt verified"}'}) == 'editing'
    assert baboom_reactions.reaction_kind({'type': 'item_completed', 'item': {'type': 'command_execution', 'status': 'failed'}}) == 'error'
    path = Path(os.environ['ARCHHUB_TEST_STATE_DIR']) / 'workshop' / 'messages.sqlite3'
    with sqlite3.connect(path) as db:
        stored = str(db.execute('SELECT actor,detail FROM workshop_activity').fetchall())
    assert 'private' not in stored and 'secret.py' not in stored


@pytest.mark.parametrize('vendor', ['claude', 'codex'])
def test_native_task_changes_the_actual_offscreen_qt_pose_within_one_second(tmp_path, monkeypatch, vendor):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from nodelang.baboom_native_companion import BaboomNativeCompanionController, create_baboom_native_companion_window
    from nodelang.baboom_native_host import BaboomNativeHost
    from nodelang.baboom_visual_assets import BaboomSpriteAtlas
    from nodelang.baboom_nograph import NoGraphTransport
    from nodelang.user_paths import state_directory

    app = QApplication.instance() or QApplication([])
    atlas_path = tmp_path / 'atlas.png'
    image = QImage(1536, 2288, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(28, 187, 171, 255))
    assert image.save(str(atlas_path))
    atlas = BaboomSpriteAtlas(atlas_path, 1536, 2288, 8, 11, 192, 208)
    host = BaboomNativeHost(NoGraphTransport(), external_session_id='offscreen-proof', device_credential_provider=lambda _: {})
    host.connect()
    monkeypatch.setattr('nodelang.baboom_nograph.shows_as_choice', lambda _: 'Screen')
    controller = BaboomNativeCompanionController(host, atlas, occupied_provider=lambda: ())
    window = create_baboom_native_companion_window(controller, reduced_motion=True, work_rows=lambda: [])
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    transcript = tmp_path / 'native.jsonl'
    native_id = 'task-proof-' + vendor
    monkeypatch.setattr(agent_status, 'transcript_path', lambda runtime, identity: transcript)
    state = state_directory() / 'workshop'
    state.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(state / 'messages.sqlite3') as db:
        db.execute('CREATE TABLE workshop_declarations(record TEXT)')
        db.execute('INSERT INTO workshop_declarations VALUES(?)', (json.dumps({'runtime': vendor, 'native_session_id': native_id}),))
    window.start_projection()
    try:
        sequence = [('task_started', 'thinking'), ('edit', 'editing'), ('task_complete', 'success')]
        for event, expected in sequence:
            if vendor == 'codex':
                payload = {'type': event} if event != 'edit' else {'type': 'function_call', 'name': 'apply_patch', 'arguments': '{"patch":"private code"}'}
                row = {'type': 'event_msg' if event != 'edit' else 'response_item', 'payload': payload, 'timestamp': str(time.time())}
            else:
                row = {'type': 'user', 'message': {'content': 'private prompt'}} if event == 'task_started' else {
                    'type': 'assistant', 'message': {'stop_reason': 'end_turn'} if event == 'task_complete' else {
                        'content': [{'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': r'C:\secret.py', 'code': 'private code'}}]}}
            with transcript.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row) + '\n')
            start = time.monotonic()
            while time.monotonic() - start < 1:
                app.processEvents()
                if window._work_presence and window._work_presence.state == expected:
                    break
                QTest.qWait(5)
            assert window._work_presence.state == expected
            assert time.monotonic() - start < 1
            assert window._frame.motion == ('think' if expected == 'thinking' else 'cast')
            assert safe_speech(window._state_bubble.text())
            assert not window.grab().isNull()
        window._open_interaction()
        for status, label in [('running', 'A tool is running.'), ('completed', 'A tool completed.'),
                              ('succeeded', 'A tool completed.'), ('failed', 'A tool failed. Open the task for its status.')]:
            window._apply_progress((window._interaction_generation, {'tool': 'proof', 'status': status}))
            assert window._transient_report == label
            assert window._report.text() == label
        window._apply_response({'response': {'kind': 'answer', 'summary': 'Done. Everything succeeded.',
                                           'data': {'steps': [{'tool': r'C:\private.py', 'status': 'failed'}]}}})
        assert window._transient_report == 'A tool failed. Open the task for its status.'
        assert window._report.text() == window._transient_report
        with sqlite3.connect(state / 'messages.sqlite3') as db:
            db.execute('DELETE FROM workshop_activity')
        window._busy = True
        window._submitted_utterance = r'C:\private\secret.py'
        window.refresh()
        assert safe_speech(window._work_presence.bubble)
    finally:
        window.stop_projection()
        window.close()
