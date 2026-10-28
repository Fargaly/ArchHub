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
