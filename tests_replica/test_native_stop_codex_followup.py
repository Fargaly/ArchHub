"""Automatic follow-up for Codex rollouts, and Claude peers known only by their pipe.

Codex shapes are the ones its rollouts hold (read 2026-09-28): collaboration
send_message {target, message}, exec session-link.ps1 send <link> --file, and the
Session Link bridge header on Claude's reply. A Session Link bridge answers a Claude
session from its pipe alone; ~/.claude/sessions/<pid>.json names that pipe.
"""
import json
import os
from datetime import datetime, timezone

from nodelang import native_stop_hook as hook

T0 = 1_790_000_000.0
LINK = '25f34d2c9ee20190'
CLAUDE = '2b338572-c520-4ec7-a9e8-a155198adb68'
ASK = 'Which piece is mine? Reply on this channel.'


def _at(seconds):
    return datetime.fromtimestamp(T0 + seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def _item(seconds, payload, kind='response_item'):
    return {'timestamp': _at(seconds), 'type': kind, 'payload': payload}


def _decide(tmp_path, entries, seconds, registry=None):
    transcript = tmp_path / 'rollout.jsonl'
    transcript.write_text('\n'.join(json.dumps(e) for e in entries) + '\n', encoding='utf-8')
    payload = {'session_id': '019a7f3e-5c1d-7a2b-9e44-0d6c8b1f2a3e', 'transcript_path': str(transcript),
               'stop_hook_active': False}
    return hook.followup_decision(payload, now=T0 + seconds, guard_directory=tmp_path / 'guard',
                                  registry_directory=registry)


SCRIPT_OK = "[{'type': 'input_text', 'text': 'Script completed in 1.2s'}]"
SCRIPT_FAILED = "[{'type': 'input_text', 'text': 'Script failed with exit code 1'}]"


def _reply_item(seconds, kind='FunctionCallOutput'):
    return _item(seconds, {'type': 'item_completed', 'item': {'type': kind, 'text': '[From Claude Code: planner; session %s; link %s; message m-1]\nACCEPT' % (CLAUDE, LINK)}},
                 kind='event_msg')


def _link_send(seconds, tmp_path, text=ASK, output=SCRIPT_OK):
    note = tmp_path / ('msg-%d.txt' % seconds)
    note.write_text(text, encoding='utf-8')
    os.utime(note, (T0 + seconds, T0 + seconds))  # written at the send, as agents do
    command = '& ' + chr(39) + r'C:\x\session-link.ps1' + chr(39) + ' send %s --file ' % LINK + chr(39) + str(note) + chr(39)
    return [_item(seconds, {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'c%d' % seconds, 'input': command}),
            _item(seconds + 1, {'type': 'custom_tool_call_output', 'call_id': 'c%d' % seconds, 'output': output})]


def test_a_codex_session_link_request_is_chased_until_the_claude_reply_arrives(tmp_path):
    entries = _link_send(0, tmp_path)
    held = _decide(tmp_path, entries, 700)
    assert held['decision'] == 'block' and LINK in held['reason']
    reply = _reply_item(100)

    fresh = tmp_path / 'answered'
    fresh.mkdir()
    assert _decide(fresh, _link_send(0, fresh) + [reply], 700) is None


def test_codex_collaboration_sends_count_and_own_subagents_do_not(tmp_path):
    def call(seconds, target, message):
        return [_item(seconds, {'type': 'function_call', 'name': 'send_message', 'namespace': 'collaboration',
                                'call_id': 'f%d' % seconds, 'arguments': json.dumps({'target': target, 'message': message})}),
                _item(seconds + 1, {'type': 'function_call_output', 'call_id': 'f%d' % seconds, 'output': ''})]
    assert _decide(tmp_path, call(0, '/root/worker', ASK), 700) is None
    fresh = tmp_path / 'peer'
    fresh.mkdir()
    assert _decide(fresh, call(0, 'ping-review', ASK), 700)['decision'] == 'block'


def test_a_claude_peer_known_only_by_its_pipe_answers_a_send_to_its_name(tmp_path):
    """717 sends to the bridge name; the bridge replies from its pipe alone."""
    name, pipe = 'codex-01a07b65-25f3', r'\\.\pipe\LOCAL\cc-msg-7490b9ab0000000000000000000000ff'
    send = [{'type': 'assistant', 'timestamp': _at(0), 'message': {'content': [
                {'type': 'tool_use', 'id': 't1', 'name': 'SendMessage', 'input': {'to': name, 'message': ASK}}]}},
            {'type': 'user', 'timestamp': _at(1), 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 't1', 'content': json.dumps({'success': True})}]}}]
    reply = {'type': 'user', 'timestamp': _at(100), 'message': {'content': 'yes'},
             'origin': {'kind': 'peer', 'from': 'uds:%5C%5C.%5Cpipe%5CLOCAL%5Ccc-msg-7490b9ab0000000000000000000000ff'}}
    tail = [{'type': 'user', 'timestamp': _at(105), 'origin': {'kind': 'task-notification'}, 'message': {'content': 'x'}}]
    registry = tmp_path / 'sessions'
    registry.mkdir()
    (registry / '94084.json').write_text(json.dumps({'pid': os.getpid(), 'startedAt': 2, 'sessionId': '7490b9ab-0000-0000-0000-000000000000',
                                                     'messagingSocketPath': pipe, 'name': name}), encoding='utf-8')
    blind = tmp_path / 'blind'
    blind.mkdir()
    assert _decide(blind, send + [reply] + tail, 700)['decision'] == 'block', 'without the registry it cannot know'
    assert _decide(tmp_path, send + [reply] + tail, 700, registry=registry) is None


def test_codex_quoting_the_header_in_its_own_message_is_not_a_reply(tmp_path):
    quote = _item(100, {'type': 'agent_message', 'author': '/root', 'recipient': '/root/x',
                        'content': [{'text': '[From Claude Code: planner; session %s; link %s; message m-1]' % (CLAUDE, LINK)}]})
    edit = _reply_item(101, kind='CommandExecution')
    assert _decide(tmp_path, _link_send(0, tmp_path) + [quote, edit], 700)['decision'] == 'block'


def test_a_failed_codex_send_is_never_chased(tmp_path):
    assert _decide(tmp_path, _link_send(0, tmp_path, output=SCRIPT_FAILED), 700) is None
    fresh = tmp_path / 'collab'
    fresh.mkdir()
    failed = [_item(0, {'type': 'function_call', 'name': 'send_message', 'namespace': 'collaboration', 'call_id': 'f0',
                        'arguments': json.dumps({'target': 'ping-review', 'message': ASK})}),
              _item(1, {'type': 'function_call_output', 'call_id': 'f0', 'output': 'collaboration tool error: agent thread not found'})]
    assert _decide(fresh, failed, 700) is None


def test_a_message_file_outside_the_scratch_roots_is_never_opened(tmp_path, monkeypatch):
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    monkeypatch.setattr(hook, '_message_roots', lambda: (allowed.resolve(),))
    assert _decide(tmp_path, _link_send(0, tmp_path), 700) is None, 'a file outside the roots is not read, so nothing is counted'
    inside = allowed / 'case'
    inside.mkdir()
    assert _decide(inside, _link_send(0, inside), 700)['decision'] == 'block'


def test_a_stale_or_older_registry_record_never_hides_a_real_overdue_request(tmp_path):
    name, live_pipe, old_pipe = 'codex-01a07b65-25f3', '\\\\.\\pipe\\LOCAL\\cc-msg-' + 'a' * 32, '\\\\.\\pipe\\LOCAL\\cc-msg-' + 'b' * 32
    send = [{'type': 'assistant', 'timestamp': _at(0), 'message': {'content': [
                {'type': 'tool_use', 'id': 't1', 'name': 'SendMessage', 'input': {'to': name, 'message': ASK}}]}},
            {'type': 'user', 'timestamp': _at(1), 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 't1', 'content': json.dumps({'success': True})}]}}]
    tail = [{'type': 'user', 'timestamp': _at(105), 'origin': {'kind': 'task-notification'}, 'message': {'content': 'x'}}]

    def reply_from(pipe):
        return {'type': 'user', 'timestamp': _at(100), 'message': {'content': 'yes'},
                'origin': {'kind': 'peer', 'from': 'uds:' + pipe.replace('\\', '%5C')}}
    registry = tmp_path / 'sessions'
    registry.mkdir()
    (registry / 'dead.json').write_text(json.dumps({'pid': 2 ** 31 - 7, 'startedAt': 9, 'sessionId': 'dead',
                                                    'messagingSocketPath': old_pipe, 'name': name}), encoding='utf-8')
    stale = tmp_path / 'stale'
    stale.mkdir()
    assert _decide(stale, send + [reply_from(old_pipe)] + tail, 700, registry=registry)['decision'] == 'block'
    (registry / 'old.json').write_text(json.dumps({'pid': os.getpid(), 'startedAt': 1, 'sessionId': 'old',
                                                   'messagingSocketPath': old_pipe, 'name': name}), encoding='utf-8')
    (registry / 'new.json').write_text(json.dumps({'pid': os.getpid(), 'startedAt': 5, 'sessionId': 'new',
                                                   'messagingSocketPath': live_pipe, 'name': name}), encoding='utf-8')
    older = tmp_path / 'older'
    older.mkdir()
    assert _decide(older, send + [reply_from(old_pipe)] + tail, 700, registry=registry)['decision'] == 'block'
    newest = tmp_path / 'newest'
    newest.mkdir()
    assert _decide(newest, send + [reply_from(live_pipe)] + tail, 700, registry=registry) is None

# Verifier specs c0-c3, b0-b2 (13707d55), written against followup_decision directly.
PING, PIPE_A, PIPE_B = 'ping-review', '\\\\.\\pipe\\LOCAL\\cc-msg-' + 'a' * 32, '\\\\.\\pipe\\LOCAL\\cc-msg-' + 'b' * 32


def _claude_send(to):
    return [{'type': 'assistant', 'timestamp': _at(1), 'message': {'content': [
                {'type': 'tool_use', 'id': 't1', 'name': 'SendMessage', 'input': {'to': to, 'message': ASK}}]}},
            {'type': 'user', 'timestamp': _at(2), 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 't1', 'content': json.dumps({'success': True})}]}}]


def _pipe_reply(pipe):
    return [{'type': 'user', 'timestamp': _at(100), 'message': {'content': 'ok'},
             'origin': {'kind': 'peer', 'from': 'uds:' + pipe.replace('\\', '%5C')}},
            {'type': 'user', 'timestamp': _at(105), 'origin': {'kind': 'task-notification'}, 'message': {'content': 'x'}}]


def _records(tmp_path, *records):
    registry = tmp_path / 'registry'
    registry.mkdir()
    for index, record in enumerate(records):
        (registry / ('%d.json' % index)).write_text(json.dumps(record), encoding='utf-8')
    return registry


def test_c0_an_unrelated_pipe_does_not_answer(tmp_path):
    assert _decide(tmp_path, _claude_send(PING) + _pipe_reply(PIPE_A), 700)['decision'] == 'block'


def test_c1_a_dead_session_record_never_links(tmp_path):
    registry = _records(tmp_path, {'pid': 99999, 'name': PING, 'messagingSocketPath': PIPE_A, 'sessionId': 'dead'})
    import psutil
    assert not psutil.pid_exists(99999)
    assert _decide(tmp_path, _claude_send(PING) + _pipe_reply(PIPE_A), 700, registry=registry)['decision'] == 'block'


def test_c2_one_name_never_ties_two_pipes(tmp_path):
    registry = _records(tmp_path,
                        {'pid': os.getpid(), 'startedAt': 1, 'name': 'planner', 'messagingSocketPath': PIPE_A, 'sessionId': 'a'},
                        {'pid': os.getpid(), 'startedAt': 2, 'name': 'planner', 'messagingSocketPath': PIPE_B, 'sessionId': 'b'})
    to_a = 'uds:' + PIPE_A.replace('\\', '%5C')
    assert _decide(tmp_path, _claude_send(to_a) + _pipe_reply(PIPE_B), 700, registry=registry)['decision'] == 'block'


def test_b0_b1_a_codex_send_counts_unless_its_output_failed(tmp_path):
    assert _decide(tmp_path, _link_send(0, tmp_path, output='{"submitted":1}'), 700)['decision'] == 'block'
    failed = tmp_path / 'failed'
    failed.mkdir()
    assert _decide(failed, _link_send(0, failed, output='Exit code: 1\nno such connection'), 700) is None


def test_c3_an_old_header_quoted_by_codex_is_not_a_reply(tmp_path):
    quote = _item(100, {'type': 'agent_message', 'author': '/root', 'recipient': '/root/x',
                        'content': [{'text': '[From Claude Code: planner; session %s; link %s; message m-0]' % (CLAUDE, LINK)}]})
    assert _decide(tmp_path, _link_send(0, tmp_path, output='{"submitted":1}') + [quote], 700)['decision'] == 'block'


def test_b2_a_64_mib_rollout_is_decided_quickly(tmp_path):
    import time
    transcript = tmp_path / 'rollout.jsonl'
    junk = ('{"timestamp":"%s","type":"response_item","payload":{"type":"reasoning","text":"%s"}}\n' % (_at(0), 'x' * 900)).encode()
    with open(transcript, 'wb') as out:
        for _ in range((64 << 20) // len(junk) + 1):
            out.write(junk)
    started = time.perf_counter()
    payload = {'session_id': '019a7f3e-5c1d-7a2b-9e44-0d6c8b1f2a3e', 'transcript_path': str(transcript), 'stop_hook_active': False}
    assert hook.followup_decision(payload, now=T0 + 700, guard_directory=tmp_path / 'guard') is None
    assert time.perf_counter() - started < 5