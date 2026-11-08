"""Real SQLite mailbox and Session Link Claude peer, entirely in a disposable profile."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

import psutil
import pytest

from nodelang import workshop_mailbox as mailbox, workshop_live


@pytest.fixture
def peer(tmp_path, monkeypatch):
    monkeypatch.setattr(workshop_live, '_LIVE', {'at': 0.0, 'ids': {}})
    for name in ('ARCHHUB_AGENT_PROFILE',):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('WORKSHOP_STATE_DIR', str(tmp_path / 'transport'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    directory = tmp_path / 'ArchHub' / '11.ARCHHUB-APP'
    directory.mkdir(parents=True)
    native = 'wsreturned-live-claude'
    script = Path(__file__).parents[1] / 'tests' / 'workshop_wsinject.mjs'
    process = subprocess.Popen(['node', str(script), str(directory), 'claude', native],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        assert process.stdout.readline().strip() == 'READY'
        context = {'claude/sessionID': native}
        observed = SimpleNamespace(pid=process.pid, created_at=psutil.Process(process.pid).create_time(), cwd=str(directory))
        declaration = mailbox.call('declare', {'task': 'isolated receiver', 'paths': [str(directory)],
            'status': 'working', 'request_id': 'unassigned'}, context, peer=observed)['declaration']
        mailbox.call('declare', {'task': 'isolated sender', 'paths': [sender(tmp_path).cwd],
            'status': 'working', 'request_id': 'unassigned'}, {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
        monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: True)
        label = 'Claude Code / ArchHub / session-' + sha256(native.encode()).hexdigest()[:12]
        yield declaration, label, directory / 'TURNS.jsonl', context, observed
    finally:
        end = time.monotonic() + 15
        while workshop_live._LIVE.get('running') and time.monotonic() < end:
            time.sleep(.05)
        assert not workshop_live._LIVE.get('running'), 'discovery worker outlived its isolated profile'
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def sender(tmp_path):
    process = psutil.Process()
    # Synthetic peer metadata must not inherit an ArchHub checkout in the pytest temp path.
    return SimpleNamespace(pid=process.pid, created_at=process.create_time(), cwd=str(Path(tmp_path.anchor) / 'OtherProject'))


def wait_receipts(result):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        with mailbox.application_history() as history:
            rows = workshop_live.deliveries(history, [result['message_id']]).get(result['message_id'])
        if rows:
            return rows
        time.sleep(.05)
    return pytest.fail('No durable delivery receipt: ' + repr(result))


def test_project_label_reaches_live_claude_in_another_project(peer, tmp_path):
    declaration, label, transcript, context, observed = peer
    result = mailbox.call('send', {'to': label, 'text': 'cross-project proof'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded', result
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, result['message_id'], principal=mailbox.DELIVERY_AUTHOR)
        assert mailbox._message_project(message) == 'OtherProject'
    assert declaration['project'] == 'ArchHub'
    assert wait_receipts(result)[0]['state'] == 'delivered'
    records = [json.loads(line) for line in transcript.read_text().splitlines()]
    assert len(records) == 1 and 'cross-project proof' in records[0]['text']
    visible = mailbox.call('read', {'since': 0}, context, peer=observed)['messages']
    assert result['message_id'] in {row['id'] for row in visible}
    print('CROSS-PROJECT: named live Claude received through Session Link; mailbox visible')


@pytest.mark.parametrize('dead', [False, True])
def test_unknown_and_dead_labels_return_truth_and_live_agents(peer, tmp_path, dead):
    declaration, _label, transcript, _context, observed = peer
    target = 'unknown agent'
    if dead:
        ended = mailbox.call('declare', {'task': 'ended', 'paths': [str(tmp_path)],
            'status': 'done', 'request_id': 'unassigned'}, {'claude/sessionID': 'dead-session'},
            peer=observed)['declaration']
        target = ended['agent']
    result = mailbox.call('send', {'to': target, 'text': 'must not inject'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'returned', result
    assert [row['state'] for row in result['delivery']] == ['returned'], result
    assert declaration['agent'] in result['live_agents'], result
    assert 'not delivered' in result['note'].lower() and 'Sent and recorded' not in result['note']
    assert not transcript.exists()
    print(('DEAD' if dead else 'UNKNOWN') + ': status=returned delivery=returned live agents listed')


def test_existing_exact_label_still_delivered(peer, tmp_path):
    declaration, _label, transcript, _context, _observed = peer
    result = mailbox.call('send', {'to': declaration['agent'], 'text': 'existing path'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded'
    assert wait_receipts(result)[0]['state'] == 'delivered'
    assert 'existing path' in transcript.read_text()
    print('EXISTING: recorded; durable delivered receipt; peer received')


@pytest.mark.parametrize('address', ['agent', 'native_session_id', 'session'])
def test_dead_role_session_label_never_redirects_to_successor(peer, tmp_path, address):
    _declaration, _label, transcript, _context, observed = peer
    body = {'task': 'role handover', 'paths': [str(tmp_path)], 'request_id': 'unassigned', 'role': 'design'}
    dead = mailbox.call('declare', {**body, 'status': 'done'},
        {'claude/sessionID': 'old-role-session'}, peer=observed)['declaration']
    mailbox.call('declare', {**body, 'status': 'working'},
        {'claude/sessionID': 'new-role-session'}, peer=observed)
    result = mailbox.call('send', {'to': dead[address], 'text': 'must not redirect'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'returned', result
    assert [row['state'] for row in result['delivery']] == ['returned'], result
    assert result['live_agents'], result
    assert not transcript.exists()


def test_role_and_human_aliases_still_inherit(peer, tmp_path):
    _declaration, _label, _transcript, _context, observed = peer
    body = {'task': 'role handover', 'paths': [str(tmp_path)], 'request_id': 'unassigned', 'role': 'design'}
    mailbox.call('declare', {**body, 'status': 'done', 'display_name': 'Design owner'},
        {'claude/sessionID': 'old-role-session'}, peer=observed)
    successor = mailbox.call('declare', {**body, 'status': 'working'},
        {'claude/sessionID': 'new-role-session'}, peer=observed)['declaration']
    with mailbox.application_history() as history:
        rows = mailbox.read_declarations(history._db)
        for alias in ('design', 'designer', 'Design owner'):
            message = {'content': 'To ' + alias + ':\nrole handover', 'category': mailbox.CATEGORY,
                       'author': 'another sender'}
            assert [row['session'] for row in mailbox._recipient_rows(message, rows)] == [successor['session']]


def test_existing_handle_still_delivered(peer, tmp_path):
    declaration, _label, transcript, _context, _observed = peer
    agent = next(row for row in workshop_live.live_agents() if row['session'] == declaration['session'])
    result = mailbox.call('send', {'to': '@' + agent['handle'], 'text': 'existing handle'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded', result
    assert wait_receipts(result)[0]['state'] == 'delivered'
    assert 'existing handle' in transcript.read_text()


def test_live_peer_with_stale_connector_registration_is_still_named(peer, tmp_path):
    declaration, label, transcript, _context, _observed = peer
    with mailbox.application_history() as history:
        stale = {**declaration, 'pid': 2_000_000_000, 'created_at': 0, 'native_process': None}
        history._db.execute('UPDATE workshop_declarations SET record=? WHERE root=?',
            (json.dumps(stale), declaration['root']))
        assert not next(row for row in mailbox.read_declarations(history._db, include_archived=True)
                        if row['session'] == declaration['session'])['current']
    result = mailbox.call('send', {'to': label, 'text': 'stale connector proof'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded', result
    assert wait_receipts(result)[0]['state'] == 'delivered'
    assert 'stale connector proof' in transcript.read_text()


def test_mixed_live_and_unknown_keeps_both_outcomes(peer, tmp_path):
    declaration, _label, transcript, _context, _observed = peer
    result = mailbox.call('send', {'to': declaration['agent'] + ', unknown agent', 'text': 'mixed proof'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'returned', result
    assert next(row for row in result['delivery'] if row['agent'] == 'unknown agent')['state'] == 'returned'
    end = time.monotonic() + 15
    while time.monotonic() < end:
        with mailbox.application_history() as history:
            receipts = workshop_live.deliveries(history, [result['message_id']])[result['message_id']]
        if {row['state'] for row in receipts} == {'returned', 'delivered'}:
            break
        time.sleep(.05)
    assert {row['state'] for row in receipts} == {'returned', 'delivered'}, receipts
    assert 'mixed proof' in transcript.read_text()


def test_slow_push_never_claims_sent_or_blocks_sender(peer, tmp_path, monkeypatch):
    declaration, _label, _transcript, _context, _observed = peer
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = workshop_live.push
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        try:
            return original(*args, **kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(workshop_live, 'push', slow)
    try:
        started = time.monotonic()
        result = mailbox.call('send', {'to': declaration['agent'], 'text': 'slow proof'},
            {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
        assert time.monotonic() - started < 2
        assert entered.is_set()
        assert result['status'] == 'recorded'
        assert [row['state'] for row in result['delivery']] == ['pending'], result
        assert 'not yet confirmed' in result['delivery'][0]['reason']
    finally:
        release.set()
        assert finished.wait(15)
    assert wait_receipts(result)[0]['state'] == 'delivered'
    print('NONBLOCKING: recorded/pending before push finished; then delivered')


def test_concurrent_sends_lose_no_mailbox_rows_or_injections(peer, tmp_path):
    declaration, _label, transcript, _context, _observed = peer
    def send(index):
        return mailbox.call('send', {'to': declaration['agent'], 'text': 'concurrent-%d' % index},
            {'threadId': 'wsreturned-sender-%d' % index}, peer=sender(tmp_path))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, range(12)))
    for result in results:
        assert result['status'] == 'recorded'
        receipts = wait_receipts(result)
        assert receipts[0]['state'] == 'delivered', receipts
    with mailbox.application_history() as history:
        saved = {row[0] for row in history._db.execute('SELECT id FROM messages WHERE category=?', (mailbox.CATEGORY,))}
    assert {row['message_id'] for row in results} <= saved
    frames = [json.loads(line)['text'] for line in transcript.read_text().splitlines()]
    assert len(frames) == 12
    assert all(sum(('\nconcurrent-%d\n' % index) in frame for frame in frames) == 1 for index in range(12))
    print('CONCURRENT: 12 sends; 12 mailbox rows; 12 peer frames; lost=0')
