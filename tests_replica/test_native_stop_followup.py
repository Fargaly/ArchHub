"""Courts for automatic follow-up at turn end (founder order 2026-09-28).

An agent that asked another agent for a reply may not end a turn while that
reply is overdue. The Stop hook blocks at most once per overdue item, never
twice in a row, never on a founder-facing turn, and never replays anything.
"""
import io
import json
import time
from datetime import datetime, timezone

from nodelang import native_stop_hook as hook

SESSION = '2b338572-c520-4ec7-a9e8-a155198adb68'
PEER = '717 \u00b7 ArchHub reviews (Ping takeover)'
T0 = 1_790_000_000.0
ASK = 'Which piece is mine? Reply on this channel.'


def _at(seconds):
    return datetime.fromtimestamp(T0 + seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def _send(seconds, message, *, to=PEER, tool='toolu_%d', success=True, with_id=True):
    tool_id = tool % seconds
    result = {'success': success, **({'msg_id': 'm-%d' % seconds} if with_id else {})}
    return [
        {'type': 'assistant', 'timestamp': _at(seconds), 'message': {'content': [
            {'type': 'tool_use', 'id': tool_id, 'name': 'SendMessage', 'input': {'to': to, 'message': message}}]}},
        {'type': 'user', 'timestamp': _at(seconds + 1), 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': tool_id, 'content': json.dumps(result)}]}},
    ]


def _prompt(seconds, kind, **origin):
    return {'type': 'user', 'timestamp': _at(seconds), 'origin': dict(kind=kind, **origin),
            'message': {'content': 'prompt'}}


def _reply(seconds):
    return _prompt(seconds, 'peer', **{'from': r'uds:\\.\pipe\LOCAL\cc-msg-717', 'name': PEER,
                                       'fromSession': 'local_717'})


def _write(tmp_path, entries):
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('\n'.join(json.dumps(entry) for entry in entries) + '\n', encoding='utf-8')
    return transcript


def _stop(tmp_path, entries, seconds, *, active=False):
    payload = {'session_id': SESSION, 'transcript_path': str(_write(tmp_path, entries)),
               'stop_hook_active': active}
    return hook.followup_decision(payload, now=T0 + seconds, guard_directory=tmp_path / 'guard')


def test_overdue_request_blocks_once_with_a_numbered_followup(tmp_path):
    entries = _send(0, ASK) + [_prompt(5, 'task-notification')]
    assert _stop(tmp_path, entries, 300) is None
    result = _stop(tmp_path, entries, 700)
    assert result['decision'] == 'block'
    assert PEER in result['reason'] and 'FOLLOW-UP #1 re m-0' in result['reason']


def test_a_send_without_msg_id_is_named_by_peer_and_send_time(tmp_path):
    entries = _send(0, ASK, with_id=False) + [_prompt(5, 'task-notification')]
    result = _stop(tmp_path, entries, 700)
    stamp = time.strftime('%H:%MZ', time.gmtime(T0))
    assert result['decision'] == 'block' and 'None' not in result['reason']
    assert 'FOLLOW-UP #1 re %s @ %s' % (PEER, stamp) in result['reason']


def test_sent_followup_lets_the_next_stop_pass(tmp_path):
    entries = _send(0, ASK) + [_prompt(5, 'task-notification')]
    assert _stop(tmp_path, entries, 700)['decision'] == 'block'
    entries += _send(710, 'FOLLOW-UP #1 re m-0: which piece is mine? Reply here.')
    assert _stop(tmp_path, entries, 720) is None
    later = _stop(tmp_path, entries, 1410)
    assert later['decision'] == 'block' and 'FOLLOW-UP #2 re m-710' in later['reason']


def test_loop_guard_never_blocks_twice_in_a_row(tmp_path):
    entries = _send(0, ASK) + [_prompt(5, 'task-notification')]
    assert _stop(tmp_path, entries, 700)['decision'] == 'block'
    assert _stop(tmp_path, entries, 701, active=True) is None
    assert _stop(tmp_path, entries, 760) is None
    assert _stop(tmp_path, entries, 1200) is None
    assert _stop(tmp_path, entries, 1400)['decision'] == 'block'


def test_ignored_block_without_continuation_marker_is_not_repeated(tmp_path):
    entries = _send(0, ASK) + [_prompt(5, 'task-notification')]
    assert _stop(tmp_path, entries, 700)['decision'] == 'block'
    assert _stop(tmp_path, entries, 705) is None


def test_founder_turn_is_never_blocked_and_the_followup_is_queued(tmp_path):
    entries = _send(0, ASK) + [_prompt(600, 'human')]
    queued = _stop(tmp_path, entries, 700)
    assert set(queued) == {'systemMessage'} and 'queued' in queued['systemMessage']
    assert _stop(tmp_path, entries, 800) is None
    entries.append(_prompt(900, 'task-notification'))
    assert _stop(tmp_path, entries, 950)['decision'] == 'block'


def test_answered_fyi_failed_and_local_agent_messages_do_not_count(tmp_path):
    entries = (_send(0, ASK) + [_reply(100)]
               + _send(10, 'FYI: step 1 landed. No reply needed.', tool='fyi_%d')
               + _send(20, 'Which piece? Reply.', tool='fail_%d', success=False)
               + _send(30, 'Report back?', to='a076ceea024520353', tool='agent_%d')
               + [_prompt(40, 'task-notification')])
    assert _stop(tmp_path, entries, 5000) is None


def test_main_blocks_an_overdue_followup_even_without_a_native_stop_host(tmp_path, monkeypatch):
    entries = _send(0, ASK) + [_prompt(5, 'task-notification')]
    payload = {'session_id': SESSION, 'transcript_path': str(_write(tmp_path, entries)),
               'stop_hook_active': False}
    monkeypatch.setattr(hook.sys, 'argv', ['native_stop_hook'])
    monkeypatch.setattr(hook.sys, 'stdin', type('In', (), {'buffer': io.BytesIO(json.dumps(payload).encode())})())
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(hook, 'query_stop', lambda payload, vendor: hook._ending_turn(hook.UNAVAILABLE))
    real = hook.followup_decision
    monkeypatch.setattr(hook, 'followup_decision', lambda payload, **kw: real(payload, now=T0 + 700))
    out = io.StringIO()
    monkeypatch.setattr(hook.sys, 'stdout', out)
    assert hook.main() == 0
    result = json.loads(out.getvalue())
    assert result['decision'] == 'block' and 'FOLLOW-UP #1' in result['reason']
    assert 'completion is not declared' in result['systemMessage']