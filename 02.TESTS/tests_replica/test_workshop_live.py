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


def test_no_live_channel_fails_now_with_the_reason():
    from nodelang.workshop_live import push
    state, _, reason = push('gemini', 'x', 'hi', 'm2')        # no process: nothing to type into
    assert state == 'failed' and 'console seat' in reason
    state, _, reason = push('cursor', 'mcp:cursor:1:2', 'hi', 'm3')
    assert state == 'failed' and reason


def test_registered_adapter_is_tried_first():
    from nodelang import workshop_live
    seen = []
    workshop_live.register_adapter('antigravity', lambda native, text, mid, pids: seen.append(native) or ('delivered', 'ag-ipc', ''))
    try:
        assert workshop_live.push('antigravity', 'n1', 'hi', 'm5') == ('delivered', 'ag-ipc', '') and seen == ['n1']
    finally:
        workshop_live.ADAPTERS.pop('antigravity')


def test_wrong_session_is_refused_not_queued():
    from nodelang.workshop_live import push
    state, channel, reason = push('claude', '00000000-dead-beef-0000-000000000000', 'hi', 'm4')
    assert state == 'failed' and channel == 'claude-peer-pipe' and reason


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
