"""Local idle stop: an agent cannot end a turn by asking the founder what to do.

This rule is local to the transcript. It needs no Work owner authority and it
blocks once; the second Stop for the same turn passes through stop_hook_active.
"""
import io
import json
from datetime import datetime, timezone

from nodelang import native_stop_hook as hook

SESSION = '2b338572-c520-4ec7-a9e8-a155198adb68'
CODEX = '019a7f3e-5c1d-7a2b-9e44-0d6c8b1f2a3e'
T0 = 1_790_000_000.0


def _at(seconds):
    return datetime.fromtimestamp(T0 + seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def _write(tmp_path, entries):
    tmp_path.mkdir(parents=True, exist_ok=True)
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('\n'.join(json.dumps(entry) for entry in entries) + '\n', encoding='utf-8')
    return transcript


def _main(tmp_path, monkeypatch, payload, verdict=None):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(hook.sys, 'argv', ['native_stop_hook', '--vendor', payload.pop('_vendor', 'claude-code')])
    monkeypatch.setattr(hook.sys, 'stdin', type('In', (), {'buffer': io.BytesIO(json.dumps(payload).encode())})())
    monkeypatch.setattr(hook, 'query_stop', lambda payload, vendor: verdict if verdict is not None else {})
    out = io.StringIO()
    monkeypatch.setattr(hook.sys, 'stdout', out)
    assert hook.main() == 0
    return json.loads(out.getvalue())


def test_claude_offer_blocks_once_and_retry_passes(tmp_path, monkeypatch):
    transcript = _write(tmp_path, [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {'content': [
            {'type': 'text', 'text': 'I can keep sweeping the remaining hooks. Want me to continue?'}]}}
    ])
    payload = {'session_id': SESSION, 'transcript_path': str(transcript), 'stop_hook_active': False}
    blocked = _main(tmp_path, monkeypatch, dict(payload))
    assert blocked['decision'] == 'block'
    assert 'Continue the work instead of ending on a question' in blocked['reason']

    retry = _main(tmp_path, monkeypatch, {**payload, 'stop_hook_active': True})
    assert retry.get('decision') != 'block'


def test_claude_done_and_deferred_need_pass(tmp_path, monkeypatch):
    done = _write(tmp_path / 'done', [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {'content': 'PASS. Files changed: 2. Tests: 4 passed.'}}
    ])
    deferred = _write(tmp_path / 'deferred', [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {'content': [
            {'type': 'text', 'text': 'deferred: needs founder password. Do you want me to wait?'}]}}
    ])
    for transcript in (done, deferred):
        result = _main(tmp_path, monkeypatch, {
            'session_id': SESSION, 'transcript_path': str(transcript), 'stop_hook_active': False})
        assert result.get('decision') != 'block'


def test_codex_rollout_last_assistant_question_blocks(tmp_path, monkeypatch):
    transcript = _write(tmp_path, [
        {'timestamp': _at(0), 'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': 'Should I run the rest of the court?'}]}}
    ])
    result = _main(tmp_path, monkeypatch, {
        '_vendor': 'codex', 'session_id': CODEX, 'transcript_path': str(transcript), 'stop_hook_active': False})
    assert result['decision'] == 'block'


def test_arabic_offer_blocks(tmp_path, monkeypatch):
    transcript = _write(tmp_path, [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {'content': 'تحب أكمل نفس المسار؟'}}
    ])
    result = _main(tmp_path, monkeypatch, {
        'session_id': SESSION, 'transcript_path': str(transcript), 'stop_hook_active': False})
    assert result['decision'] == 'block'


def test_stale_question_then_founder_stop_does_not_nudge(tmp_path, monkeypatch):
    transcript = _write(tmp_path, [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {'content': 'Should I continue?'}},
        {'type': 'user', 'timestamp': _at(1), 'message': {'content': 'STOP'}},
    ])
    result = _main(tmp_path, monkeypatch, {
        'session_id': SESSION, 'transcript_path': str(transcript), 'stop_hook_active': False})
    assert result.get('decision') != 'block'


def test_later_human_turn_resets_a_stale_assistant_question(tmp_path, monkeypatch):
    transcript = _write(tmp_path, [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {'content': 'Should I continue?'}},
        {'type': 'user', 'timestamp': _at(1), 'message': {'content': 'status noted'}},
    ])
    result = _main(tmp_path, monkeypatch, {
        'session_id': SESSION, 'transcript_path': str(transcript), 'stop_hook_active': False})
    assert result.get('decision') != 'block'


def test_codex_commentary_question_is_not_final_idle_evidence(tmp_path, monkeypatch):
    transcript = _write(tmp_path, [
        {'timestamp': _at(0), 'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'assistant', 'channel': 'commentary',
            'content': [{'type': 'output_text', 'text': 'Should I run a tool?'}]}},
        {'timestamp': _at(1), 'type': 'response_item', 'payload': {
            'type': 'function_call', 'name': 'shell_command', 'call_id': 'c1', 'arguments': '{}'}},
        {'timestamp': _at(2), 'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'assistant', 'channel': 'final',
            'content': [{'type': 'output_text', 'text': 'PASS. Tests: 1 passed.'}]}},
    ])
    result = _main(tmp_path, monkeypatch, {
        '_vendor': 'codex', 'session_id': CODEX, 'transcript_path': str(transcript), 'stop_hook_active': False})
    assert result.get('decision') != 'block'


def test_local_queue_blocks_until_each_item_id_is_followed_up(tmp_path, monkeypatch):
    blocked = _write(tmp_path / 'blocked', [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {
            'content': 'adopted-not-installed: Claude Desktop connector receipt\nsent-but-unanswered: Ping review reply'}}
    ])
    result = _main(tmp_path, monkeypatch, {
        'session_id': SESSION, 'transcript_path': str(blocked), 'stop_hook_active': False})
    assert result['decision'] == 'block'
    assert 'adopted-not-installed: Claude Desktop connector receipt' in result['reason']
    assert 'sent-but-unanswered: Ping review reply' in result['reason']

    partial = _write(tmp_path / 'partial', [
        {'type': 'assistant', 'timestamp': _at(0), 'message': {
            'content': 'FOLLOW-UP #1 re connector receipt sent.\n'
                       'adopted-not-installed: Claude Desktop connector receipt\n'
                       'sent-but-unanswered: Ping review reply'}}
    ])
    partial_result = _main(tmp_path, monkeypatch, {
        'session_id': SESSION, 'transcript_path': str(partial), 'stop_hook_active': False})
    assert partial_result['decision'] == 'block'
    assert 'sent-but-unanswered: Ping review reply' in partial_result['reason']
    assert 'adopted-not-installed: Claude Desktop connector receipt' not in partial_result['reason']

    for name, text in {
        'followed': 'FOLLOW-UP #1 re connector receipt sent.\nFOLLOW-UP #2 re Ping review reply sent.\n'
                    'adopted-not-installed: Claude Desktop connector receipt\n'
                    'sent-but-unanswered: Ping review reply',
        'deferred': 'deferred: needs Desktop reload',
    }.items():
        transcript = _write(tmp_path / name, [
            {'type': 'assistant', 'timestamp': _at(0), 'message': {'content': text}}
        ])
        passed = _main(tmp_path, monkeypatch, {
            'session_id': SESSION, 'transcript_path': str(transcript), 'stop_hook_active': False})
        assert passed.get('decision') != 'block'
