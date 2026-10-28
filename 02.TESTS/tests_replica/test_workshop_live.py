"""Workshop live delivery: pushed now or failed now with a reason; never pending; gateway onboarding."""
import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    yield tmp_path


def declare(context, name):
    from nodelang.workshop_mailbox import call
    return call('declare', {'task': 'live test', 'paths': [str(__import__('pathlib').Path.cwd())], 'status': 'working', 'request_id': 'LIVE', 'display_name': name}, context)


def test_delivery_is_once_per_recipient(monkeypatch):
    from nodelang import workshop_live
    pushes = []
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: pushes.append(a) or ('delivered', 'claude-peer-pipe', ''))
    from nodelang.workshop_mailbox import application_history
    row = {'session': 's1', 'agent': 'A', 'runtime': 'claude', 'native_session_id': 'abc'}
    with application_history() as history:
        first = workshop_live.deliver(history, 'm1', [row], 'Ahmed', 'hi')
        second = workshop_live.deliver(history, 'm1', [row], 'Ahmed', 'hi')
    assert len(pushes) == 1 and first[0]['state'] == 'delivered' and second[0]['repeat'] is True


def test_every_push_goes_through_workshop_and_fails_now_with_its_reason():
    from nodelang.workshop_live import push
    state, channel, reason = push('gemini', 'x', 'hi', 'm2')        # no process: nothing to type into
    assert (state, channel) == ('failed', 'workshop') and 'console' in reason
    state, channel, reason = push('cursor', 'thread-1', 'hi', 'm3')  # Cursor Desktop Bridge off on this PC
    assert (state, channel) == ('failed', 'workshop') and 'Cursor' in reason


def _rollout(home, thread, originator):
    import json
    folder = home / 'sessions' / '2026' / '10' / '28'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ('rollout-2026-10-28T10-00-00-%s.jsonl' % thread)).write_text(
        json.dumps({'type': 'session_meta', 'payload': {'id': thread, 'originator': originator}}) + '\n', encoding='utf-8')


def test_workshop_gets_one_recipient_with_its_door(profile, monkeypatch):
    from nodelang import workshop_live, workshop_mailbox
    monkeypatch.setenv('CODEX_HOME', str(profile / 'codex'))
    _rollout(profile / 'codex', 'desk-1', 'Codex Desktop')
    _rollout(profile / 'codex', 'term-1', 'codex_cli_rs')
    sent = []

    class Transport:
        def inject(self, recipient, text, **kw):
            sent.append(recipient)
            return {'status': 'injected'}
    monkeypatch.setattr(workshop_mailbox, '_local_transport', lambda env=None: Transport())
    assert workshop_live.push('codex', 'desk-1', 'hi', 'm9', pids=(4242,)) == ('delivered', 'workshop', '')
    workshop_live.push('codex', 'term-1', 'hi', 'm10', pids=(4343,))
    workshop_live.push('goose', 'baboom', 'hi', 'm11', pids=(1,))
    assert sent == [{'app': 'codex', 'id': 'desk-1', 'pids': [4242], 'desktop': True},   # Desktop: app bridge, never a seat
                    {'app': 'codex', 'id': 'term-1', 'pids': [4343]},                    # terminal: its console seat
                    {'app': 'archhub', 'id': 'baboom'}]                      # the app's BABOOM door


def test_wrong_session_is_refused_not_queued():
    from nodelang.workshop_live import push
    state, channel, reason = push('claude', '00000000-dead-beef-0000-000000000000', 'hi', 'm4')
    assert state == 'failed' and channel == 'workshop' and reason


def test_unknown_mention_refused_and_everyone_reaches_each_joined_agent(monkeypatch):
    from nodelang import workshop_live
    monkeypatch.setattr(workshop_live, 'push', lambda app, native, text, mid, **k: ('delivered', app + '-channel', ''))
    declare({'claude/sessionID': 'c-1'}, 'Claude A')
    declare({'threadId': 'x-1'}, 'Codex B')
    with pytest.raises(ValueError, match='No live agent'):
        workshop_live.send_as_founder('hi', ['nobody'])
    handles = {a['handle'] for a in workshop_live.live_agents()}
    assert {'claude-a', 'codex-b'} <= handles
    sent = workshop_live.send_as_founder('@everyone hi', ['everyone'])
    assert sorted(r['agent'] for r in sent['deliveries'] if r['state'] == 'delivered') == ['Claude A', 'Codex B']
    dm = workshop_live.send_as_founder('@codex-b only you', ['codex-b'])
    assert [r['agent'] for r in dm['deliveries']] == ['Codex B']


def test_gateway_applies_once_per_stamp(profile, monkeypatch):
    from nodelang import workshop_gateway as gateway
    hooks = profile / 'gov' / '.rulesync'
    (hooks / 'rules').mkdir(parents=True)
    (hooks / 'hooks.jsonc').write_text('{"hooks":{"stop":[{"command":"a"}]}}')
    (hooks / 'rules' / 'archhub-ledger.md').write_text('1. one\n2. two\n')
    monkeypatch.setenv('ARCHHUB_GOVERNANCE_HOOKS_DIR', str(profile / 'gov'))
    started = []
    monkeypatch.setattr(gateway.subprocess, 'Popen', lambda *a, **k: started.append(a))
    assert gateway.on_connect('gemini')['state'] == 'applying' and len(started) == 1
    assert gateway.on_connect('gemini')['state'] == 'applying' and len(started) == 1      # same stamp: no relaunch
    (hooks / 'hooks.jsonc').write_text('{"hooks":{"stop":[{"command":"a"},{"command":"b"}]}}')
    gateway.on_connect('gemini')
    assert len(started) == 2 and gateway.counts() == (2, 2)


def test_a_declaration_the_live_list_does_not_return_is_dropped(monkeypatch):
    from nodelang import workshop_live
    from nodelang.workshop_mailbox import call
    call('declare', {'task': 't', 'paths': [str(__import__('pathlib').Path.cwd())], 'status': 'working', 'request_id': 'S1'}, {'threadId': 'stale-thread'})
    call('declare', {'task': 't', 'paths': [str(__import__('pathlib').Path.cwd())], 'status': 'working', 'request_id': 'S2'}, {'threadId': 'live-thread'})
    monkeypatch.setattr(workshop_live, 'live_ids', lambda: dict(codex={'live-thread'}))
    assert [a['native_session_id'] for a in workshop_live.live_agents() if a['app'] == 'codex'] == ['live-thread']


def test_the_same_reply_sent_twice_is_one_message(monkeypatch):
    from nodelang import workshop_live
    from nodelang.workshop_mailbox import call
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('delivered', 'workshop', ''))
    cwd = str(__import__('pathlib').Path.cwd())
    call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'A'}, {'threadId': 'asker'})
    call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'B'}, {'threadId': 'replier'})
    asked = call('send', {'to': 'replier', 'text': 'question'}, {'threadId': 'asker'})
    first = call('send', {'to': 'asker', 'text': 'answer', 'reply_to': asked['message_id']}, {'threadId': 'replier'})
    again = call('send', {'to': 'asker', 'text': 'answer', 'reply_to': asked['message_id']}, {'threadId': 'replier'})
    assert again['message_id'] == first['message_id']


@pytest.mark.parametrize('context,channel', [
    ({'claude/sessionID': 'ack-claude'}, 'claude peer pipe'),
    ({'threadId': 'ack-codex'}, 'codex app bridge'),
    ({'ai.opencode/sessionID': 'ack-opencode'}, 'opencode plugin'),
    ({'goose/sessionID': 'ack-goose'}, 'goose connector'),
])
def test_a_message_injected_once_is_never_attached_again(monkeypatch, context, channel):
    """Any channel: once injected (one delivery receipt), 3 later tool calls carry it 0 more times."""
    from nodelang import workshop_live
    from nodelang.workshop_mailbox import call
    cwd = str(__import__('pathlib').Path.cwd())
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('delivered', channel, ''))
    call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'S'}, {'threadId': 'ack-sender'})
    me = call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'R'}, context)
    sent = call('send', {'to': me['declaration']['display_name'] if 'display_name' in me['declaration'] else me['declaration']['agent'],
                         'text': 'do the thing'}, {'threadId': 'ack-sender'})
    assert [row['state'] for row in sent['delivery']] == ['delivered']
    seen = [m['id'] for _ in range(3) for m in call('pending', {}, context)['pending']]
    assert sent['message_id'] not in seen


def test_replying_acknowledges_a_message_that_was_never_injected(monkeypatch):
    from nodelang import workshop_live
    from nodelang.workshop_mailbox import call
    cwd = str(__import__('pathlib').Path.cwd())
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('failed', 'none', 'no live session'))
    call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'S'}, {'threadId': 'r-sender'})
    me = call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'R'}, {'threadId': 'r-replier'})
    sent = call('send', {'to': me['declaration']['agent'], 'text': 'question'}, {'threadId': 'r-sender'})
    assert sent['message_id'] in [m['id'] for m in call('pending', {}, {'threadId': 'r-replier'})['pending']]
    call('send', {'to': 'r-sender', 'text': 'answer', 'reply_to': sent['message_id']}, {'threadId': 'r-replier'})
    seen = [m['id'] for _ in range(3) for m in call('pending', {}, {'threadId': 'r-replier'})['pending']]
    assert sent['message_id'] not in seen


def test_connector_hands_a_pending_message_over_once_and_records_the_receipt():
    """Goose/any MCP client: the message rides one tool result, then 3 more calls carry it 0 times."""
    import time
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session
    from nodelang import native_agent_mcp as native
    seen = []

    def mailbox(method, body, context, **kwargs):
        if method == 'pending':
            return {'pending': [{'id': 'm-once', 'text': 'do the thing'}], 'more': False}
        if method == 'seen':
            seen.extend(body['message_ids'])
        return {'ok': True}

    server = native.build_server(mailbox_call=mailbox)

    def carried(result):
        return sum('m-once' in item.text for item in result.content if getattr(item, 'text', None) and 'Workshop peer messages' in item.text)

    async def run():
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            args = {'task': 't', 'paths': ['.'], 'status': 'working', 'request_id': 'R'}
            first = 0
            for _ in range(100):
                first = carried(await session.call_tool('declare', args))
                if first:
                    break
                await anyio.sleep(0.05)
            later = []
            for _ in range(3):
                await anyio.sleep(0.1)
                later.append(carried(await session.call_tool('declare', args)))
            return first, later

    try:
        first, later = anyio.run(run)
    finally:
        server._mailbox_stop()
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        time.sleep(0.05)
    assert first == 1 and later == [0, 0, 0]
    assert seen == ['m-once']


def test_a_failed_push_is_still_one_sent_reply(monkeypatch):
    """Goose re-sent its reply on 'failed'; the send says it is recorded, and a retry is the same reply."""
    from nodelang import workshop_live
    from nodelang.workshop_mailbox import call
    cwd = str(__import__('pathlib').Path.cwd())
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('failed', 'none', 'no live door'))
    call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'S'}, {'threadId': 'f-asker'})
    me = call('declare', {'task': 't', 'paths': [cwd], 'status': 'working', 'request_id': 'R'}, {'threadId': 'f-replier'})
    asked = call('send', {'to': me['declaration']['agent'], 'text': 'question'}, {'threadId': 'f-asker'})
    first = call('send', {'to': 'f-asker', 'text': 'AGENTLINK-REPLY 1', 'reply_to': asked['message_id']}, {'threadId': 'f-replier'})
    assert 'do not send it again' in first['note']
    again = call('send', {'to': 'F-Asker', 'text': ' agentlink-reply  1 ', 'reply_to': asked['message_id']}, {'threadId': 'f-replier'})
    assert again['message_id'] == first['message_id']


def test_push_without_a_session_id_says_where_the_message_is():
    from nodelang.workshop_live import push
    state, channel, reason = push('opencode', '', 'text', 'm1')
    assert (state, channel) == ('failed', 'none') and 'reads the message in the Workshop' in reason
