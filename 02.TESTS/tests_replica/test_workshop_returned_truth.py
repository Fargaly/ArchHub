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
    from nodelang.nograph_server import JsonFile
    from nodelang.user_paths import state_directory
    JsonFile(state_directory() / 'settings/workspaces.json', {}).update({'roots': [
        {'root_id': 'product', 'label': 'ArchHub', 'path': str(directory.parent)},
        {'root_id': 'other', 'label': 'OtherProject', 'path': sender(tmp_path).cwd},
    ]})
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


# F320: the Workshop routes by session id, not by the folder in the label.

class RecordingTransport:
    """The app's background loop pushes through this instead of a live session."""
    def __init__(self):
        self.sent = []

    def inject(self, recipient, text, **kwargs):
        self.sent.append((recipient['id'], kwargs['message_id']))
        return {'status': 'injected', 'dispatch_attempted': True}


def move_folder(tmp_path, observed, context, status='working'):
    """The same agent process, now working in another folder of the same project."""
    moved = tmp_path / 'ArchHub' / '35.02-APP-DESIGN'
    moved.mkdir(parents=True, exist_ok=True)
    peer = SimpleNamespace(pid=observed.pid, created_at=observed.created_at, cwd=str(moved))
    return peer, mailbox.call('declare', {'task': 'moved folder', 'paths': [str(moved)], 'status': status,
        'request_id': 'unassigned'}, context, peer=peer)['declaration']


def pulled(context, observed):
    return [row['id'] for row in mailbox.call('pending', {}, context, peer=observed)['pending']]


def sender_label(tmp_path):
    return mailbox._identity({'threadId': 'wsreturned-sender'}, sender(tmp_path))[0]['sender_label']


def routed_sessions(message_id):
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, message_id, principal=mailbox.DELIVERY_AUTHOR)
        return [row['session'] for row in mailbox._routing(message)['recipients']]


def test_old_folder_label_reaches_the_moved_session_by_push(peer, tmp_path):
    declaration, _label, transcript, context, observed = peer
    old_label = declaration['agent']
    moved_peer, updated = move_folder(tmp_path, observed, context)
    assert updated['agent'] != old_label and updated['session'] == declaration['session']
    assert updated['agent'].rsplit(' / ', 1)[-1] == old_label.rsplit(' / ', 1)[-1]
    result = mailbox.call('send', {'to': old_label, 'text': 'address by earlier folder label'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded' and result['matched'] == 1, result
    assert wait_receipts(result)[0]['state'] == 'delivered'
    frames = [json.loads(line)['text'] for line in transcript.read_text().splitlines()]
    assert sum('address by earlier folder label' in frame for frame in frames) == 1
    visible = mailbox.call('read', {'since': 0}, context, peer=moved_peer)['messages']
    assert result['message_id'] in {row['id'] for row in visible}


def test_old_folder_label_reaches_the_moved_session_by_pull_exactly_once(peer, tmp_path, monkeypatch):
    """Review fault 7: the pull path (an agent reading its pending messages) after a folder move."""
    declaration, _label, transcript, context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)   # nothing is pushed: only the pull path
    old_label = declaration['agent']
    before = mailbox.call('send', {'to': old_label, 'text': 'sent before the move'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    moved_peer, updated = move_folder(tmp_path, observed, context)
    assert updated['agent'] != old_label
    after = mailbox.call('send', {'to': old_label, 'text': 'sent to the old label after the move'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert (before['matched'], after['matched'], after['status']) == (1, 1, 'recorded'), (before, after)
    assert pulled(context, moved_peer) == [before['message_id'], after['message_id']]
    mailbox.call('seen', {'message_ids': [before['message_id'], after['message_id']],
        'channel': 'connector tool result'}, context, peer=moved_peer)
    assert pulled(context, moved_peer) == []
    assert not transcript.exists()


def test_dead_session_token_under_another_folder_is_returned_not_passed_to_its_successor(peer, tmp_path):
    _declaration, _label, transcript, _context, observed = peer
    body = {'task': 'role handover', 'paths': [str(tmp_path)], 'request_id': 'unassigned', 'role': 'design'}
    dead = mailbox.call('declare', {**body, 'status': 'done'},
        {'claude/sessionID': 'old-role-session'}, peer=observed)['declaration']
    mailbox.call('declare', {**body, 'status': 'working'}, {'claude/sessionID': 'new-role-session'}, peer=observed)
    host, _folder, token = dead['agent'].split(' / ')
    result = mailbox.call('send', {'to': host + ' / another-folder / ' + token, 'text': 'must not redirect'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'returned', result
    assert [row['state'] for row in result['delivery']] == ['returned'], result
    assert not transcript.exists()


def test_seen_by_one_recipient_keeps_the_other_recipients_receipt_and_one_delivery(peer, tmp_path, monkeypatch):
    """Review fault 1: A marks a two-recipient message seen; B's receipt survives and B gets it exactly once."""
    first, _label, _transcript, context_a, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    context_b = {'claude/sessionID': 'wsreturned-second-claude'}
    second = mailbox.call('declare', {'task': 'second receiver', 'paths': [observed.cwd], 'status': 'working',
        'request_id': 'unassigned'}, context_b, peer=observed)['declaration']
    result = mailbox.call('send', {'to': first['agent'] + ', ' + second['agent'], 'text': 'two recipients'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded' and result['matched'] == 2, result
    message_id = result['message_id']

    def receipts():
        with mailbox.application_history() as history:
            return dict(history._db.execute(
                'SELECT recipient, state FROM workshop_live_deliveries WHERE message_id=?', (message_id,)).fetchall())
    with mailbox.application_history() as history:
        history._db.execute(workshop_live.SCHEMA)
        for recipient in (first['agent'], second['session'], second['agent']):   # A's provisional name; B's receipts
            history._db.execute('INSERT INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)',
                (message_id, recipient, recipient, 'claude', '', 'workshop', 'pending', 'queued',
                 '2026-11-16T00:00:00+00:00', 0))
    mailbox.call('seen', {'message_ids': [message_id], 'channel': 'connector tool result'}, context_a, peer=observed)
    assert receipts() == {first['session']: 'delivered', second['session']: 'pending', second['agent']: 'pending'}
    pushes = []
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: pushes.append(a) or ('delivered', 'workshop', ''))
    with mailbox.application_history() as history:   # a later push finds B's receipt, so it does not inject again
        again = workshop_live.deliver(history, message_id, [{'session': second['session'], 'agent': second['agent'],
            'runtime': 'claude', 'native_session_id': second['native_session_id']}], 'sender', 'two recipients')
    assert pushes == [] and again[0]['repeat'] is True, (pushes, again)
    assert pulled(context_b, observed) == [message_id]
    mailbox.call('seen', {'message_ids': [message_id], 'channel': 'connector tool result'}, context_b, peer=observed)
    assert receipts() == {first['session']: 'delivered', second['session']: 'delivered'}
    assert pulled(context_b, observed) == [] and pulled(context_a, observed) == []


@pytest.mark.parametrize('ended', ['never existed', 'ended', 'ended role holder'])
def test_short_id_of_an_ended_session_is_returned_and_never_reaches_a_later_session(peer, tmp_path, monkeypatch, ended):
    """Review fault 2: a short id is resolved once, at send; it is returned, not queued, and never floats on."""
    _declaration, _label, transcript, _context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    body = {'task': 'short id', 'paths': [str(tmp_path)], 'request_id': 'unassigned',
            **({'role': 'design'} if ended == 'ended role holder' else {})}
    if ended != 'never existed':
        mailbox.call('declare', {**body, 'status': 'done'}, {'claude/sessionID': 'abc123ff-ended'}, peer=observed)
    result = mailbox.call('send', {'to': 'abc123', 'text': 'short id of a session that is not there'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'returned', result
    assert [row['state'] for row in result['delivery']] == ['returned'], result
    with mailbox.application_history() as history:
        assert history._db.execute('SELECT count(*) FROM workshop_waiting WHERE message_id=?',
            (result['message_id'],)).fetchone()[0] == 0
    later = {'claude/sessionID': 'abc123ff-later'}   # an unrelated new session whose id starts the same
    mailbox.call('declare', {**body, 'status': 'working'}, later, peer=observed)
    assert result['message_id'] not in pulled(later, observed)
    transport = RecordingTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    for _ in range(3):
        worker.tick()
    assert not [row for row in transport.sent if row[1].startswith(result['message_id'])], transport.sent
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, result['message_id'], principal=mailbox.DELIVERY_AUTHOR)
        assert mailbox.delivery_events(history, message) == {}
    assert not transcript.exists()


def test_short_id_still_reaches_the_session_it_named_when_it_was_sent(peer, tmp_path, monkeypatch):
    _declaration, _label, _transcript, _context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    live = {'claude/sessionID': 'feed01aa-live'}
    mailbox.call('declare', {'task': 'short id', 'paths': [str(tmp_path)], 'status': 'working',
        'request_id': 'unassigned'}, live, peer=observed)
    result = mailbox.call('send', {'to': 'feed01', 'text': 'short id of a live session'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded' and result['matched'] == 1, result
    assert pulled(live, observed) == [result['message_id']]


def asked_from_a_session_without_a_token(tmp_path, observed):
    """An agent whose connector gives no session id: its label has no token, only its folder changes."""
    author = mailbox.call('declare', {'task': 'asks a question', 'paths': [observed.cwd], 'status': 'working',
        'request_id': 'unassigned'}, {}, peer=observed)['declaration']
    assert ' / session-' not in author['agent']
    question = mailbox.call('send', {'to': sender_label(tmp_path), 'text': 'a question from the first folder?'},
        {}, peer=observed)
    return author, question


def test_reply_naming_the_authors_old_label_reaches_the_moved_author(peer, tmp_path, monkeypatch):
    """Review fault 3, positive: the To line names the author by the label it wrote under."""
    _declaration, _label, _transcript, _context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    author, question = asked_from_a_session_without_a_token(tmp_path, observed)
    moved_peer, updated = move_folder(tmp_path, observed, {})
    assert updated['agent'] != author['agent'] and updated['session'] == author['session']
    reply = mailbox.call('send', {'to': author['agent'], 'text': 'the answer', 'reply_to': question['message_id']},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert reply['status'] == 'recorded' and reply['matched'] == 1, reply
    assert routed_sessions(reply['message_id']) == [author['session']]
    assert pulled({}, moved_peer) == [reply['message_id']]
    visible = mailbox.call('read', {'since': 0}, {}, peer=moved_peer)['messages']
    assert reply['message_id'] in {row['id'] for row in visible}
    mailbox.call('seen', {'message_ids': [reply['message_id']], 'channel': 'connector tool result'}, {}, peer=moved_peer)
    assert pulled({}, moved_peer) == []


def test_reply_addressed_to_someone_else_does_not_add_the_replied_author(peer, tmp_path, monkeypatch):
    """Review faults 3 and 4, negative: on send and in the background loop the author is not a recipient."""
    declaration, _label, _transcript, _context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    _author, question = asked_from_a_session_without_a_token(tmp_path, observed)
    moved_peer, _updated = move_folder(tmp_path, observed, {})
    reply = mailbox.call('send', {'to': declaration['agent'], 'text': 'for another agent',
        'reply_to': question['message_id']}, {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert reply['matched'] == 1, reply
    assert routed_sessions(reply['message_id']) == [declaration['session']]
    transport = RecordingTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    for _ in range(3):
        worker.tick()
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, reply['message_id'], principal=mailbox.DELIVERY_AUTHOR)
        assert set(mailbox.delivery_events(history, message)) == {declaration['session']}
    assert reply['message_id'] not in pulled({}, moved_peer)


def test_background_loop_resolves_a_reply_like_the_direct_path(peer, tmp_path, monkeypatch):
    """Review fault 4: the author was resting when the reply was sent; the app's loop re-routes it by the same
    rule the send uses (the To line names the author's old label), and the author can then pull it."""
    _declaration, _label, _transcript, _context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    author, question = asked_from_a_session_without_a_token(tmp_path, observed)
    move_folder(tmp_path, observed, {}, status='done')
    reply = mailbox.call('send', {'to': author['agent'], 'text': 'answered while resting',
        'reply_to': question['message_id']}, {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert reply['matched'] == 0 and routed_sessions(reply['message_id']) == [], reply
    moved_peer, _back = move_folder(tmp_path, observed, {})
    worker = mailbox.WorkshopInjection(None, RecordingTransport())
    for _ in range(3):
        worker.tick()
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, reply['message_id'], principal=mailbox.DELIVERY_AUTHOR)
        assert 'attempt' in mailbox.delivery_events(history, message).get(author['session'], {})
    assert pulled({}, moved_peer) == [reply['message_id']]


def test_declared_name_ending_in_another_sessions_token_is_refused_and_never_addressed(peer, tmp_path, monkeypatch):
    """Review fault 5: nobody receives another session's messages by naming itself after its token."""
    victim, _label, _transcript, _context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    impostor = {'claude/sessionID': 'wsreturned-impostor'}
    body = {'task': 'impostor', 'paths': [str(tmp_path)], 'status': 'working', 'request_id': 'unassigned'}
    token = victim['agent'].rsplit(' / ', 1)[-1]
    for name in (victim['agent'], token, 'Friendly helper / ' + token):
        for field in ('display_name', 'title'):
            with pytest.raises(ValueError, match="another session's id"):
                mailbox.call('declare', {**body, field: name}, impostor, peer=observed)
    own = mailbox.call('declare', body, impostor, peer=observed)['declaration']
    renamed = mailbox.call('declare', {**body, 'title': own['agent']}, impostor, peer=observed)['declaration']
    assert renamed['title'] == own['agent']   # its own token is its own name
    with mailbox.application_history() as history:   # a row stored before this rule existed
        history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.display_name',?) "
            'WHERE root=?', (victim['agent'], own['root']))
    result = mailbox.call('send', {'to': victim['agent'], 'text': 'for the real session only'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['matched'] == 1 and routed_sessions(result['message_id']) == [victim['session']], result
    assert result['message_id'] not in pulled(impostor, observed)


def test_two_running_rows_of_one_native_session_get_one_injection(peer, tmp_path):
    """Review fault 6: a second live row with the same native id must not double the delivery."""
    declaration, _label, transcript, context, observed = peer
    twin = {**declaration, 'root': declaration['root'] + ':twin', 'session': 'agent:session:' + 'd' * 64,
            'updated_at': '2026-01-01T00:00:00+00:00'}
    with mailbox.application_history() as history:
        history._db.execute('INSERT INTO workshop_declarations VALUES(?,?)', (twin['root'], json.dumps(twin)))
        running = [row for row in mailbox.read_declarations(history._db)
                   if row['native_session_id'] == declaration['native_session_id']]
    assert len(running) == 2 and all(row['current'] for row in running)
    result = mailbox.call('send', {'to': declaration['agent'], 'text': 'one session, one delivery'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded' and result['matched'] == 1, result
    assert [row['state'] for row in wait_receipts(result)] == ['delivered']
    time.sleep(1)   # a second push, if one were made, has landed by now
    frames = [json.loads(line)['text'] for line in transcript.read_text().splitlines()]
    assert sum('one session, one delivery' in frame for frame in frames) == 1, frames
    with mailbox.application_history() as history:
        twin_identity = {'sender_key': twin['session'], 'sender_label': twin['agent'],
                         'sender': twin['agent'] + ' [' + twin['session'] + ']'}
        assert mailbox._pending(history, twin_identity, 'claude')['pending'] == []
    assert pulled(context, observed) == []


def test_reply_to_the_old_row_of_a_native_session_with_two_live_rows_reaches_it_once(peer, tmp_path):
    """Two live rows (old key, new key) of one native session share the label token; a reply answers a message
    written under the old key and names the old label. The final union is one addressee: one receipt, one push."""
    declaration, _label, transcript, context, observed = peer
    host, _folder, token = declaration['agent'].split(' / ')
    old = {**declaration, 'root': declaration['root'] + ':old', 'session': 'agent:session:' + 'e' * 64,
           'agent': host + ' / old-folder / ' + token, 'updated_at': '2026-01-01T00:00:00+00:00'}
    with mailbox.application_history() as history:
        history._db.execute('INSERT INTO workshop_declarations VALUES(?,?)', (old['root'], json.dumps(old)))
        question = history.append(mailbox.ROOM, author=old['agent'] + ' [' + old['session'] + ']',
            content='To ' + sender_label(tmp_path) + ':\na question from the old key?', category=mailbox.CATEGORY,
            idempotency_key='f320-old-key-question')
        rows = mailbox.read_declarations(history._db, include_archived=True)
        running = [row for row in rows if row.get('current')
                   and row['native_session_id'] == declaration['native_session_id']]
        assert {row['session'] for row in running} == {declaration['session'], old['session']}
        probe = {'content': 'To ' + old['agent'] + ':\nx', 'category': mailbox.CATEGORY,
                 'author': 'another sender', 'reply_to': question['id']}
        assert [row['session'] for row in mailbox._resolve(history, probe, rows)] == [declaration['session']]
    result = mailbox.call('send', {'to': old['agent'], 'text': 'one reply, one native session',
        'reply_to': question['id']}, {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded' and result['matched'] == 1, result
    assert routed_sessions(result['message_id']) == [declaration['session']]
    assert [row['state'] for row in wait_receipts(result)] == ['delivered']
    time.sleep(1)   # a second push, if one were made, has landed by now
    frames = [json.loads(line)['text'] for line in transcript.read_text().splitlines()]
    assert sum('one reply, one native session' in frame for frame in frames) == 1, frames
    assert pulled(context, observed) == []


def test_attempt_under_a_replaced_declaration_key_counts_for_its_replacement_in_the_background_loop(peer, tmp_path):
    """A stored message was addressed to, and attempted for, the old declaration key of a native session; the
    session was then re-declared under a new key (same native id, same token). The app's loop must not push it
    again under the new key: one native session, one attempt, one injection."""
    declaration, _label, transcript = peer[:3]
    host, _folder, token = declaration['agent'].split(' / ')
    old = {**declaration, 'root': declaration['root'] + ':old', 'session': 'agent:session:' + 'f' * 64,
           'agent': host + ' / old-folder / ' + token, 'status': 'done', 'updated_at': '2026-01-01T00:00:00+00:00'}
    native = declaration['native_session_id']
    with mailbox.application_history() as history:
        history._db.execute('INSERT INTO workshop_declarations VALUES(?,?)', (old['root'], json.dumps(old)))
        message = history.append(mailbox.ROOM, author='another sender',
            content='To ' + old['agent'] + ':\nhistorical message for the old key', category=mailbox.CATEGORY,
            idempotency_key='f320-historical-old-key')
        recipient = {'session': old['session'], 'agent': old['agent']}
        mailbox._delivery_receipt(history, message, recipient, 'addressed', runtime='claude', native_session_id=native)
        mailbox._delivery_receipt(history, message, recipient, 'attempt')
        assert not next(row for row in mailbox.read_declarations(history._db, include_archived=True)
                        if row['session'] == old['session'])['current']
    transport = RecordingTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    for _ in range(3):
        worker.tick()
    assert not [row for row in transport.sent if row[1].startswith(message['id'])], transport.sent
    with mailbox.application_history() as history:
        events = mailbox.delivery_events(history, history.get(mailbox.ROOM, message['id'],
                                                              principal=mailbox.DELIVERY_AUTHOR))
    assert [key for key, records in events.items() if 'attempt' in records] == [old['session']], events
    assert not transcript.exists()


# F320 matrix: one native session is one addressee on every path, whatever its declaration history.
# Each cell asserts exactly one delivery per addressee (or none where an earlier receipt already holds) and no
# stranded unacknowledged receipt. The resolver and the receipt grouping are never mocked; only the outer
# transports (sender push, app injection) are recorded.

class MatrixTransport:
    def __init__(self):
        self.sent = []

    def inject(self, recipient, text, **kwargs):
        self.sent.append((recipient['app'], recipient['id'], kwargs['message_id']))
        return {'status': 'injected', 'dispatch_attempted': True}


MATRIX_HISTORIES = ('one-row', 'two-live', 'old-archived', 'old-gone', 'moved', 'second-recipient', 'other-runtime')
MATRIX = [(path, history) for path in ('send', 'push', 'pull', 'tick', 'watch', 'reply') for history in MATRIX_HISTORIES] + [
    ('pull', 'old-archived-header-elsewhere'),   # reviewer (b): only the receipt routes it; the header names no alias
    ('pull', 'old-gone-header-elsewhere'),       # reviewer (c): no declaration; only the receipt keeps the native id
    ('pull', 'old-gone-answered'),               # (c): an answered sibling suppresses replay
    ('pull', 'old-archived-delivered'),          # a delivered sibling suppresses replay
    ('repeat', 'old-archived'),                  # (e): same idempotency key after a push under the old key, re-declared
    ('repeat', 'old-gone'),                      # (e): the same, the old declaration removed
]


def run_repeat_cell(peer_value, tmp_path, monkeypatch, history_name):
    """The real sender worker: a push lands under the old key; the session is re-declared under a new key with the
    same native identity; the sender repeats the same idempotency key. No second live push."""
    declaration = peer_value[0]
    host, _folder, token = declaration['agent'].split(' / ')
    plain = {key: value for key, value in declaration.items() if key not in ('display_name', 'title', 'aliases')}
    old = {**plain, 'root': declaration['root'] + ':old', 'session': 'agent:session:' + '5' * 64,
           'agent': host + ' / old-folder / ' + token, 'updated_at': '2099-01-01T00:00:00+00:00'}   # newest: it takes it
    _insert_declaration(old)
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: True)
    pushes = []
    monkeypatch.setattr(workshop_live, 'push',
        lambda runtime, native, *a, **k: pushes.append((runtime, native)) or ('delivered', 'workshop', ''))
    body = {'to': old['agent'], 'text': 'repeat-' + history_name, 'idempotency_key': 'f320-repeat-' + history_name}
    first = mailbox.call('send', body, {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert routed_sessions(first['message_id']) == [old['session']], first
    assert [row['state'] for row in wait_receipts(first)] == ['delivered']
    with mailbox.application_history() as history:
        if history_name == 'old-gone':
            history._db.execute('DELETE FROM workshop_declarations WHERE root=?', (old['root'],))
        else:
            history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.status','done') WHERE root=?",
                                (old['root'],))
    again = mailbox.call('send', body, {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert again['message_id'] == first['message_id'], again
    time.sleep(1)   # a second push, if one were made, has landed by now
    assert pushes == [('claude', declaration['native_session_id'])], pushes
    with mailbox.application_history() as history:   # the sender worker's own lookup, given the replacement key
        rows = workshop_live.deliver(history, first['message_id'], [{'session': declaration['session'],
            'agent': declaration['agent'], 'runtime': 'claude', 'native_session_id': declaration['native_session_id']}],
            'sender', body['text'])
    assert pushes == [('claude', declaration['native_session_id'])] and rows[0].get('repeat') is True, (pushes, rows)


def _insert_declaration(row):
    with mailbox.application_history() as history:
        history._db.execute('INSERT INTO workshop_declarations VALUES(?,?)', (row['root'], json.dumps(row)))


def _matrix_setup(history_name, peer_value, tmp_path):
    """(addressees, target) for one history. An addressee is the row its native session pulls with; target is the
    key and label the message's receipts and To line use for the first addressee."""
    declaration, _label, _transcript, context, observed = peer_value
    host, folder, token = declaration['agent'].split(' / ')
    old_label = host + ' / old-folder / ' + token
    plain = {key: value for key, value in declaration.items() if key not in ('display_name', 'title', 'aliases')}
    main, target, addressees = declaration, {'session': declaration['session'], 'agent': declaration['agent']}, []
    if history_name == 'two-live':
        target = {**plain, 'root': declaration['root'] + ':twin', 'session': 'agent:session:' + '7' * 64,
                  'agent': old_label, 'updated_at': '2026-01-01T00:00:00+00:00'}
        _insert_declaration(target)
    elif history_name.startswith('old-archived'):
        target = {**plain, 'root': declaration['root'] + ':old', 'session': 'agent:session:' + '8' * 64,
                  'agent': old_label, 'status': 'done', 'updated_at': '2026-01-01T00:00:00+00:00'}
        _insert_declaration(target)
    elif history_name.startswith('old-gone'):
        target = {'session': 'agent:session:' + '9' * 64, 'agent': old_label}
    elif history_name == 'moved':
        _peer, main = move_folder(tmp_path, observed, context)
        target = {'session': main['session'], 'agent': declaration['agent']}
    elif history_name in ('second-recipient', 'other-runtime'):
        native = 'wsreturned-second-native' if history_name == 'second-recipient' else declaration['native_session_id']
        second = {**plain, 'root': declaration['root'] + ':second', 'session': 'agent:session:' + '6' * 64,
                  'native_session_id': native,
                  'runtime': 'claude' if history_name == 'second-recipient' else 'codex',
                  'agent': (host if history_name == 'second-recipient' else 'Codex') + ' / ' + folder
                  + ' / session-' + sha256(native.encode()).hexdigest()[:12]}
        _insert_declaration(second)
        addressees.append(second)
    return [main, *addressees], target


def _key_identity(row):
    return {'sender_key': row['session'], 'sender_label': row['agent'], 'sender': row['agent'] + ' [' + row['session'] + ']'}


def _matrix_pull(row):
    with mailbox.application_history() as history:
        return [message['id'] for message in mailbox._pending(history, _key_identity(row), row['runtime'])['pending']]


def _matrix_seen(row, message_id):
    with mailbox.application_history() as history:
        mailbox._seen(history, {'message_ids': [message_id], 'channel': 'connector tool result'},
                      _key_identity(row), row['runtime'])


def _matrix_seed(target, addressees, header, text):
    """A stored message routed by addressed receipts (the historical path), one per addressee."""
    with mailbox.application_history() as history:
        message = history.append(mailbox.ROOM, author='another sender', content='To ' + header + ':\n' + text,
                                 category=mailbox.CATEGORY, idempotency_key='f320-matrix-' + text)
        for row in [target, *addressees[1:]]:
            mailbox._delivery_receipt(history, message, {'session': row['session'], 'agent': row['agent']},
                'addressed', runtime=row.get('runtime') or 'claude',
                native_session_id=row.get('native_session_id') or addressees[0]['native_session_id'])
    return message


@pytest.mark.parametrize('path, history_name', MATRIX)
def test_one_native_session_is_one_addressee_on_every_path(peer, tmp_path, monkeypatch, path, history_name):
    run_matrix_cell(peer, tmp_path, monkeypatch, path, history_name)


def run_matrix_cell(peer_value, tmp_path, monkeypatch, path, history_name):
    if path == 'repeat':
        run_repeat_cell(peer_value, tmp_path, monkeypatch, history_name)
        return
    addressees, target = _matrix_setup(history_name, peer_value, tmp_path)
    identities = [mailbox.recipient_identity(row) for row in addressees]
    assert len(set(identities)) == len(identities), identities   # a different runtime is a different addressee
    labels = ', '.join([target['agent'], *(row['agent'] for row in addressees[1:])])
    text = path + '-' + history_name + '-please-confirm?'
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: path in ('push', 'reply'))
    pushes = []
    monkeypatch.setattr(workshop_live, 'push',
        lambda runtime, native, *a, **k: pushes.append((runtime, native)) or ('delivered', 'workshop', ''))
    caller = {'threadId': 'wsreturned-sender'}

    def per_identity(pairs):
        return [sum(1 for pair in pairs if tuple(pair) == identity[1:]) for identity in identities]

    if path in ('send', 'push', 'reply'):
        body = {'to': labels, 'text': text}
        if path == 'reply':
            with mailbox.application_history() as history:   # a question written under the target's key
                question = history.append(mailbox.ROOM, author=target['agent'] + ' [' + target['session'] + ']',
                    content='To ' + sender_label(tmp_path) + ':\na question?', category=mailbox.CATEGORY,
                    idempotency_key='f320-matrix-question-' + history_name)
            body['reply_to'] = question['id']
        result = mailbox.call('send', body, caller, peer=sender(tmp_path))
        assert result['status'] == 'recorded' and result['matched'] == len(addressees), result
        with mailbox.application_history() as history:
            message = history.get(mailbox.ROOM, result['message_id'], principal=mailbox.DELIVERY_AUTHOR)
            routed = [mailbox.recipient_identity(row) for row in mailbox._routing(message)['recipients']]
        assert sorted(routed) == sorted(identities), routed
        if path != 'send':
            wait_receipts(result)
            time.sleep(1)   # a second push, if one were made, has landed by now
            assert per_identity(pushes) == [1] * len(addressees), pushes
        return
    header = 'retired-alias' if history_name.endswith('header-elsewhere') else labels
    message = _matrix_seed(target, addressees, header, text)
    if path == 'pull':
        expected = [message['id']]
        if history_name == 'old-gone-answered':
            with mailbox.application_history() as history:
                mailbox._delivery_receipt(history, message, target, 'answered', reply_message_id='earlier')
            expected = []
        if history_name == 'old-archived-delivered':
            with mailbox.application_history() as history:
                history._db.execute(workshop_live.SCHEMA)
                history._db.execute('INSERT INTO workshop_live_deliveries VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (message['id'], target['session'], target['agent'], 'claude', target['native_session_id'],
                     'workshop', 'delivered', 'pushed before the move', '2026-11-16T00:00:00+00:00', 0))
            expected = []
        for row in addressees:
            assert _matrix_pull(row) == expected, (row['session'], expected)   # first pull: exactly once
            _matrix_seen(row, message['id'])
            assert _matrix_pull(row) == [], row['session']                    # second pull: nothing stranded
        if history_name == 'two-live':
            assert _matrix_pull(target) == []
        return
    transport = MatrixTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    if path == 'tick':
        for _ in range(3 * len(addressees) + 3):
            worker.tick()
        initial = [(app, native) for app, native, key in transport.sent if key == message['id'] + ':initial']
        assert per_identity(initial) == [1] * len(addressees), transport.sent
        return
    # watch: aged attempts, one retry step due. A sibling's caller-owned dispatch holds for the whole session.
    siblings = history_name in ('two-live', 'old-archived', 'old-gone')
    aged = time.time() - 90
    with mailbox.application_history() as history:
        if siblings:   # both siblings addressed and attempted; only the old one's dispatch is caller-owned
            mailbox._delivery_receipt(history, message, addressees[0], 'addressed', runtime='claude',
                                      native_session_id=addressees[0]['native_session_id'])
            mailbox._delivery_receipt(history, message, target, 'attempt', now=aged, via='workshop', status='caller-owned')
            mailbox._delivery_receipt(history, message, addressees[0], 'attempt', now=aged + 1)
        else:
            for row in [target, *addressees[1:]]:
                mailbox._delivery_receipt(history, message, row, 'attempt', now=aged)
                # the initial push reported it landed; with no reply by the first step the watcher follows up once
                mailbox._delivery_receipt(history, message, row, 'initial-outcome', now=aged, status='injected')
    for _ in range(len(addressees) + 2):
        worker._watched_at = float('-inf')
        with mailbox.application_history() as history:
            worker._watch(history, time.time(), mailbox.read_declarations(history._db, include_archived=True))
    follow_ups = [(app, native) for app, native, key in transport.sent if key == message['id'] + ':reminder']
    assert per_identity(follow_ups) == [0 if siblings else 1] * len(addressees), transport.sent


def test_a_bare_session_tag_addresses_exactly_that_session(peer, tmp_path, monkeypatch):
    """F243: send(to="<12-hex tag>") reaches the live session whose label ends in session-<tag>, exactly."""
    declaration = peer[0]
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    token = declaration['agent'].rsplit(' / ', 1)[-1]
    bare = token[len('session-'):]
    assert token.startswith('session-') and len(bare) == 12
    for target in (bare, token):
        result = mailbox.call('send', {'to': target, 'text': 'bare tag ' + target},
            {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
        assert result['status'] == 'recorded' and result['matched'] == 1, (target, result)
        assert routed_sessions(result['message_id']) == [declaration['session']], target
    for wrong in ('abcdefabcdef', bare[:6]):   # another tag, and a prefix of the right one: never matched
        result = mailbox.call('send', {'to': wrong, 'text': 'wrong tag ' + wrong},
            {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
        assert result['status'] == 'returned' and result['matched'] == 0, (wrong, result)


def test_a_bare_tag_shared_by_two_live_sessions_names_neither(peer):
    with mailbox.application_history() as history:
        declaration = next(row for row in mailbox.read_declarations(history._db) if row['session'] == peer[0]['session'])
    bare = declaration['agent'].rsplit(' / ', 1)[-1][len('session-'):]
    other = {**declaration, 'session': 'agent:session:' + 'c' * 64, 'native_session_id': 'another-native'}
    assert declaration['current'] and other['current']
    message = {'content': 'To ' + bare + ':\nshared tag', 'category': mailbox.CATEGORY, 'author': 'another sender'}
    assert [row['session'] for row in mailbox._recipient_rows(message, [declaration])] == [declaration['session']]
    assert mailbox._recipient_rows(message, [declaration, other]) == []


def test_an_ended_sessions_bare_tag_never_reaches_the_new_role_holder(peer, tmp_path, monkeypatch):
    """F243 review: the role's aliases follow its new holder, but an ended session's bare tag is its own identity."""
    _declaration, _label, transcript, _context, observed = peer
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    body = {'task': 'role handover', 'paths': [str(tmp_path)], 'request_id': 'unassigned', 'role': 'design'}
    dead = mailbox.call('declare', {**body, 'status': 'done'},
        {'claude/sessionID': 'old-role-session'}, peer=observed)['declaration']
    holder = mailbox.call('declare', {**body, 'status': 'working'},
        {'claude/sessionID': 'new-role-session'}, peer=observed)['declaration']
    bare = dead['agent'].rsplit(' / ', 1)[-1][len('session-'):]
    assert len(bare) == 12 and bare not in holder['agent']
    with mailbox.application_history() as history:
        current = next(row for row in mailbox.read_declarations(history._db) if row['session'] == holder['session'])
    assert bare not in current.get('aliases', ()) and 'design' in mailbox._aliases({}, current)
    result = mailbox.call('send', {'to': bare, 'text': 'must not reach the new holder'},
        {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'returned' and result['matched'] == 0, result
    assert result['message_id'] not in pulled({'claude/sessionID': 'new-role-session'}, observed)
    assert not transcript.exists()


# F320: one durable claim before a Workshop delivery. Threads meet at a barrier at the dispatch point: if two paths
# could both dispatch, both reach it together; with the claim only one ever does (the barrier then times out).

class BarrierDispatch:
    """The sender push and the app's transport, both recorded at one barrier."""
    def __init__(self):
        self.barrier, self.sent = threading.Barrier(2), []

    def _meet(self):
        try:
            self.barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass

    def push(self, runtime, native, _text, message_id, **_kwargs):
        self.sent.append(('push', runtime, native, message_id))
        self._meet()
        return 'delivered', 'workshop', ''

    def inject(self, recipient, _text, **kwargs):
        self.sent.append(('inject', recipient['app'], recipient['id'], kwargs['message_id']))
        self._meet()
        return {'status': 'injected', 'dispatch_attempted': True}


def _recorded_message(tmp_path, monkeypatch, to, text):
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: False)
    result = mailbox.call('send', {'to': to, 'text': text}, {'threadId': 'wsreturned-sender'}, peer=sender(tmp_path))
    assert result['status'] == 'recorded' and result['matched'] == 1, result
    return result['message_id']


def _live_row(row, native):
    return {'session': row['session'], 'agent': row['agent'], 'runtime': row.get('runtime') or 'claude',
            'native_session_id': native}


def _deliver(message_id, row):
    with mailbox.application_history() as history:
        return workshop_live.deliver(history, message_id, [row], 'sender', 'claimed once')


def _states(message_id):
    with mailbox.application_history() as history:
        return [row['state'] for row in workshop_live.deliveries(history, [message_id]).get(message_id, [])]


def test_two_simultaneous_sends_of_one_idempotency_key_dispatch_once(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    dispatch = BarrierDispatch()
    monkeypatch.setattr(workshop_live, 'push', dispatch.push)
    monkeypatch.setattr(mailbox, '_sender_may_push', lambda *a: True)
    body = {'to': declaration['agent'], 'text': 'simultaneous same key', 'idempotency_key': 'f320-claim-same-key'}
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _index: mailbox.call('send', body, {'threadId': 'wsreturned-sender'},
                                                            peer=sender(tmp_path)), range(2)))
    message_id = results[0]['message_id']
    assert results[1]['message_id'] == message_id, results
    wait_receipts(results[0])   # the winner waits out the barrier, then records
    time.sleep(1)   # a second push, if one were made, has landed by now
    assert dispatch.sent == [('push', 'claude', declaration['native_session_id'], message_id + ':initial')], dispatch.sent
    assert _states(message_id) == ['delivered']


def test_simultaneous_old_and_new_declaration_keys_of_one_native_session_dispatch_once(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    host, _folder, token = declaration['agent'].split(' / ')
    old = {**declaration, 'root': declaration['root'] + ':old', 'session': 'agent:session:' + '4' * 64,
           'agent': host + ' / old-folder / ' + token, 'updated_at': '2026-01-01T00:00:00+00:00'}
    _insert_declaration(old)
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'old and new keys at once')
    dispatch = BarrierDispatch()
    monkeypatch.setattr(workshop_live, 'push', dispatch.push)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda row: _deliver(message_id, _live_row(row, native)), (old, declaration)))
    assert dispatch.sent == [('push', 'claude', native, message_id + ':initial')], dispatch.sent
    assert _states(message_id) == ['delivered']


def test_sender_push_and_background_tick_overlapping_dispatch_once_with_one_transport_id(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'sender and loop at once')
    dispatch = BarrierDispatch()
    monkeypatch.setattr(workshop_live, 'push', dispatch.push)
    worker = mailbox.WorkshopInjection(None, dispatch)

    def background():
        with mailbox.application_history() as history:
            worker._tick(history, time.time(), message_id=message_id)
    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(_deliver, message_id, _live_row(declaration, native)), pool.submit(background)]:
            future.result()
    assert len(dispatch.sent) == 1, dispatch.sent
    assert dispatch.sent[0][1:] == ('claude', native, message_id + ':initial'), dispatch.sent


def test_a_claim_whose_winner_died_reads_uncertain_and_is_never_replayed(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    row = _live_row(declaration, native)
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'the winner died mid-send')
    fresh_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'the winner is still sending')
    bound = mailbox.CLAIM_NODE['params']['uncertain_after_seconds']
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, message_id, principal=mailbox.DELIVERY_AUTHOR)
        fresh = history.get(mailbox.ROOM, fresh_id, principal=mailbox.DELIVERY_AUTHOR)
        assert mailbox.claim_delivery(history, message, row, 'initial', 'sender', now=time.time() - bound - 5)[0]
        assert mailbox.claim_delivery(history, fresh, row, 'initial', 'sender')[0]
        mailbox._delivery_receipt(history, message, row, 'addressed', runtime='claude', native_session_id=native)
    dispatch = MatrixTransport()   # the claim wrote the attempt the watcher scans, at the claim's time
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: dispatch.sent.append(('push',) + a[:2]) or ('delivered', 'workshop', ''))
    assert [value['state'] for value in _deliver(message_id, row)] == ['uncertain']
    assert [value['state'] for value in _deliver(fresh_id, row)] == ['in-flight']
    worker = mailbox.WorkshopInjection(None, dispatch)
    for target in (message_id, fresh_id):
        with mailbox.application_history() as history:
            worker._tick(history, time.time(), message_id=target)
    for _ in range(3):   # the stall watcher holds an uncertain initial dispatch: no follow-up push
        worker._watched_at = float('-inf')
        with mailbox.application_history() as history:
            worker._watch(history, time.time(), mailbox.read_declarations(history._db, include_archived=True))
    assert dispatch.sent == [], dispatch.sent
    assert _states(message_id) == ['uncertain'] and _states(fresh_id) == []


def test_a_claim_for_one_runtime_does_not_hold_the_same_looking_token_in_another(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'another runtime, same token')
    codex = {'session': 'agent:session:' + '3' * 64, 'agent': 'Codex / other / session-x', 'runtime': 'codex',
             'native_session_id': native}
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, message_id, principal=mailbox.DELIVERY_AUTHOR)
        assert mailbox.claim_delivery(history, message, codex, 'initial', 'sender')[0]
    pushes = []
    monkeypatch.setattr(workshop_live, 'push', lambda runtime, native_id, *a, **k: pushes.append((runtime, native_id))
                        or ('delivered', 'workshop', ''))
    assert [value['state'] for value in _deliver(message_id, _live_row(declaration, native))] == ['delivered']
    assert pushes == [('claude', native)], pushes


# F320: three outcomes on a claim, the watcher fed from the claim, truthful legacy readback, resolve then claim.
# The watcher's clock is passed in (a fake clock): its steps fall at 60, 120, 240 and 480 s after the attempt.

def _watch_at(worker, at):
    worker._watched_at = float('-inf')
    with mailbox.application_history() as history:
        worker._watch(history, at, mailbox.read_declarations(history._db, include_archived=True))


def _events(message_id):
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, message_id, principal=mailbox.DELIVERY_AUTHOR)
        return mailbox.delivery_events(history, message)


def test_sender_only_refused_initial_is_retried_once_at_the_next_step(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'refused at first, can you confirm?')
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('failed', 'none', 'no live door'))
    start = time.time()
    assert [row['state'] for row in _deliver(message_id, _live_row(declaration, native))] == ['refused']
    assert _states(message_id) == ['refused']
    transport = MatrixTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, start + 30)                        # before the first step: nothing
    assert transport.sent == []
    for at in (start + 70, start + 80, start + 90):      # the first step, under its own claim, exactly once
        _watch_at(worker, at)
    assert transport.sent == [('claude', native, message_id + ':reminder')], transport.sent
    with mailbox.application_history() as history:       # the loop does not push the initial step again
        worker._tick(history, time.time(), message_id=message_id)
    assert len(transport.sent) == 1, transport.sent


def test_sender_only_uncertain_initial_is_held_shown_and_escalated(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'the door timed out, did it land?')
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('uncertain', 'workshop', 'timed out'))
    start = time.time()
    assert [row['state'] for row in _deliver(message_id, _live_row(declaration, native))] == ['uncertain']
    transport = MatrixTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    for at in (start + 70, start + 130, start + 250):    # held at every re-push step
        _watch_at(worker, at)
    assert transport.sent == [] and not any('reminder' in records for records in _events(message_id).values())
    _watch_at(worker, start + 490)                       # the last step escalates
    assert transport.sent == [] and any('escalated' in records for records in _events(message_id).values())
    assert _states(message_id) == ['uncertain']


def test_a_sender_that_died_after_claiming_becomes_uncertain_and_is_escalated(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'the sender died, was it sent?')
    claimed = time.time() - 200
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, message_id, principal=mailbox.DELIVERY_AUTHOR)
        assert mailbox.claim_delivery(history, message, _live_row(declaration, native), 'initial', 'sender',
                                      now=claimed)[0]
    transport = MatrixTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, claimed + 70)                      # still inside the bound: in flight, nothing done
    assert not any({'reminder', 'escalated'} & set(records) for records in _events(message_id).values())
    _watch_at(worker, claimed + 490)                     # past the bound: uncertain, escalated, never re-pushed
    assert transport.sent == [] and any('escalated' in records for records in _events(message_id).values())
    assert _states(message_id) == ['uncertain']


def test_an_exception_from_the_transport_is_recorded_uncertain_not_failed(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']

    class Breaks:
        def inject(self, *_args, **_kwargs):
            raise RuntimeError('pipe closed after the write')

        def close(self):
            return None
    monkeypatch.setattr(mailbox, '_local_transport', lambda env=None: Breaks())
    assert workshop_live.push('claude', native, 'x', 'probe:initial')[0] == 'uncertain'
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'the transport raised')
    assert [row['state'] for row in _deliver(message_id, _live_row(declaration, native))] == ['uncertain']
    assert _states(message_id) == ['uncertain']
    with mailbox.application_history() as history:
        message = history.get(mailbox.ROOM, message_id, principal=mailbox.DELIVERY_AUTHOR)
        assert mailbox.claim_delivery(history, message, _live_row(declaration, native), 'initial', 'background') \
            == (False, 'uncertain')


def test_legacy_receipts_read_by_their_actual_status(peer, tmp_path):
    declaration = peer[0]
    row = _live_row(declaration, declaration['native_session_id'])
    cases = [([('initial-outcome', {'status': 'failed'})], 'refused'),
             ([('initial-outcome', {'status': 'not_sent'})], 'refused'),
             ([('attempt', {})], 'uncertain'),
             ([('attempt', {}), ('initial-outcome', {'status': 'cancelled_wait'})], 'uncertain'),
             ([('attempt', {}), ('initial-outcome', {'status': 'injected'})], 'delivered'),
             ([('answered', {'reply_message_id': 'earlier'})], 'delivered')]
    with mailbox.application_history() as history:
        for index, (events, expected) in enumerate(cases):
            message = history.append(mailbox.ROOM, author='another sender', content='To ' + declaration['agent']
                + ':\nlegacy %d' % index, category=mailbox.CATEGORY, idempotency_key='f320-legacy-%d' % index)
            mailbox._delivery_receipt(history, message, row, 'addressed', runtime='claude',
                                      native_session_id=row['native_session_id'])
            for event, details in events:
                mailbox._delivery_receipt(history, message, row, event, **details)
            assert mailbox.claim_delivery(history, message, row, 'initial', 'background') == (False, expected), index
        clean = history.append(mailbox.ROOM, author='another sender', content='To ' + declaration['agent']
            + ':\nno history', category=mailbox.CATEGORY, idempotency_key='f320-legacy-clean')
        assert mailbox.claim_delivery(history, clean, row, 'initial', 'background') == (True, 'in-flight')


@pytest.mark.parametrize('order', ['sender-first', 'native-first', 'plain-key-then-bound'])
def test_a_late_native_id_is_claimed_once(peer, tmp_path, monkeypatch, order):
    run_late_native(peer, tmp_path, monkeypatch, order)


def run_late_native(peer_value, _tmp_path, monkeypatch, order):
    """Resolve, then claim, then dispatch: an OpenCode-style declaration gains its native id late. A message admitted
    under the plain declaration key and later bound to the native id is never claimable again under the native id."""
    declaration = peer_value[0]
    plain = {key: value for key, value in declaration.items() if key not in ('display_name', 'title', 'aliases')}
    late = {**plain, 'root': declaration['root'] + ':opencode', 'session': 'agent:session:' + '2' * 64,
            'runtime': 'opencode', 'native_session_id': None, 'agent': 'OpenCode / late / session-late'}
    _insert_declaration(late)
    resolved = '' if order == 'plain-key-then-bound' else 'oc-native-1'
    monkeypatch.setattr(workshop_live, 'opencode_session', lambda pids: resolved)
    pushes = []

    def push(runtime, native, *_args, **_kwargs):
        pushes.append((runtime, native))
        return ('delivered', 'workshop', '') if native else ('failed', 'none', 'no live door')
    monkeypatch.setattr(workshop_live, 'push', push)
    with mailbox.application_history() as history:
        message = history.append(mailbox.ROOM, author='another sender', content='To ' + late['agent'] + ':\nlate native',
                                 category=mailbox.CATEGORY, idempotency_key='f320-late-' + order)
    bound = {'session': 'agent:session:' + '1' * 64, 'agent': late['agent'], 'runtime': 'opencode',
             'native_session_id': 'oc-native-1'}   # another path that knows the native id
    plain_row = {'session': late['session'], 'agent': late['agent'], 'runtime': 'opencode', 'native_session_id': None}
    if order == 'native-first':
        with mailbox.application_history() as history:
            assert mailbox.claim_delivery(history, message, bound, 'initial', 'background')[0]
        assert [row['state'] for row in _deliver(message['id'], plain_row)] == ['in-flight']
        assert pushes == []
        return
    first = _deliver(message['id'], plain_row)
    with mailbox.application_history() as history:
        history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.native_session_id',?) "
                            'WHERE root=?', ('oc-native-1', late['root']))
        again = mailbox.claim_delivery(history, message, bound, 'initial', 'background')
    if order == 'sender-first':
        assert [row['state'] for row in first] == ['delivered'] and pushes == [('opencode', 'oc-native-1')], pushes
        assert again == (False, 'delivered'), again
    else:
        assert [row['state'] for row in first] == ['refused'] and pushes == [('opencode', '')], pushes
        assert again == (False, 'refused'), again


def test_a_delivered_sender_push_that_asks_gets_no_follow_up_and_no_escalation(peer, tmp_path, monkeypatch):
    """Founder rule: nothing may interrupt a busy session. A sender push that landed is never followed up."""
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'landed, can you answer when free?')
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('delivered', 'workshop', ''))
    start = time.time()
    assert [row['state'] for row in _deliver(message_id, _live_row(declaration, native))] == ['delivered']
    transport = MatrixTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    for at in (start + 70, start + 130, start + 250, start + 490, start + 600):
        _watch_at(worker, at)
    assert transport.sent == [], transport.sent
    assert not any({'reminder', 'reminder:2', 'reminder:3', 'escalated'} & set(records)
                   for records in _events(message_id).values())


# F320: the latest claimed step drives the watcher; ambiguity evidence outranks labels.

class AnswersUncertain(MatrixTransport):
    """A door that took the follow-up but could not confirm it."""
    def inject(self, recipient, text, **kwargs):
        super().inject(recipient, text, **kwargs)
        return {'status': 'uncertain', 'dispatch_attempted': True}


def _refused_by_the_sender(tmp_path, monkeypatch, declaration, text):
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], text)
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('failed', 'none', 'no live door'))
    start = time.time()
    assert [row['state'] for row in _deliver(message_id, _live_row(declaration, declaration['native_session_id']))] \
        == ['refused']
    return message_id, start


def test_an_uncertain_later_step_is_held_and_escalated_once_never_re_pushed(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _refused_by_the_sender(tmp_path, monkeypatch, declaration, 'refused, then unsure, answer?')
    transport = AnswersUncertain()
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, start + 70)                        # the refused initial is retried once: the door is unsure
    assert transport.sent == [('claude', native, message_id + ':reminder')], transport.sent
    for at in (start + 130, start + 250, start + 260):   # the unsure step is held: no second follow-up
        _watch_at(worker, at)
    assert len(transport.sent) == 1, transport.sent
    for at in (start + 490, start + 500):                # escalated once at the last step, no injection
        _watch_at(worker, at)
    assert len(transport.sent) == 1, transport.sent
    escalations = [records['escalated'] for records in _events(message_id).values() if 'escalated' in records]
    assert len(escalations) == 1, escalations


def test_a_winner_that_died_after_claiming_a_later_step_leads_to_escalation_not_a_loop(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _refused_by_the_sender(tmp_path, monkeypatch, declaration, 'refused, then the watcher died?')
    with mailbox.application_history() as history:       # a watcher claimed the first follow-up and died before sending
        message = history.get(mailbox.ROOM, message_id, principal=mailbox.DELIVERY_AUTHOR)
        assert mailbox.claim_delivery(history, message, {**_live_row(declaration, native)}, 'reminder', 'watch',
                                      now=start + 60)[0]
    transport = MatrixTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, start + 130)                       # the dead claim is still in flight: wait
    assert not any('escalated' in records for records in _events(message_id).values())
    for at in (start + 250, start + 260, start + 490, start + 500):   # past the bound: held, then escalated once
        _watch_at(worker, at)
    assert transport.sent == [], transport.sent
    escalations = [records['escalated'] for records in _events(message_id).values() if 'escalated' in records]
    assert len(escalations) == 1, escalations


def test_contradictory_door_answers_read_as_uncertain():
    cases = [(('failed', True), 'uncertain'), (('not_sent', True), 'uncertain'), (('queued', None), 'queued'),
             (('held', None), 'uncertain'), (('injected', False), 'uncertain'), (('uncertain', False), 'uncertain'),
             (('not_sent', False), 'refused'), (('failed', None), 'refused'), (('injected', True), 'delivered'),
             (('injected', None), 'delivered'), (('something-new', None), 'uncertain')]
    assert [mailbox.delivery_outcome(*answer) for answer, _expected in cases] == [expected for _answer, expected in cases]


def test_legacy_receipts_keep_dispatch_attempted(peer, tmp_path):
    declaration = peer[0]
    row = _live_row(declaration, declaration['native_session_id'])
    cases = [({'status': 'failed', 'dispatch_attempted': True}, 'uncertain'),
             ({'status': 'failed', 'dispatch_attempted': False}, 'refused'),
             ({'status': 'injected', 'dispatch_attempted': False}, 'uncertain'),
             ({'status': 'uncertain', 'dispatch_attempted': False}, 'uncertain')]
    with mailbox.application_history() as history:
        for index, (outcome, expected) in enumerate(cases):
            message = history.append(mailbox.ROOM, author='another sender', content='To ' + declaration['agent']
                + ':\nlegacy dispatch %d' % index, category=mailbox.CATEGORY, idempotency_key='f320-dispatch-%d' % index)
            mailbox._delivery_receipt(history, message, row, 'addressed', runtime='claude',
                                      native_session_id=row['native_session_id'])
            mailbox._delivery_receipt(history, message, row, 'attempt')
            mailbox._delivery_receipt(history, message, row, 'initial-outcome', **outcome)
            assert mailbox.claim_delivery(history, message, row, 'initial', 'background') == (False, expected), index


def test_a_cursor_hook_push_reads_queued_and_is_never_re_pushed_or_escalated(peer, tmp_path, monkeypatch):
    """Cursor's hook queue is how its messages normally arrive: queued is its own outcome, never an interruption."""
    declaration = peer[0]
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], 'for cursor, can you answer?')
    cursor = {'session': 'agent:session:' + '0' * 64, 'agent': 'Cursor / folder / session-c', 'runtime': 'cursor',
              'native_session_id': 'cursor-thread-1'}
    start = time.time()
    assert [row['state'] for row in _deliver(message_id, cursor)] == ['queued']   # the real push: Cursor's hook
    transport = MatrixTransport()
    worker = mailbox.WorkshopInjection(None, transport)
    for at in (start + 70, start + 130, start + 250, start + 490, start + 600):
        _watch_at(worker, at)
    assert transport.sent == [], transport.sent
    assert not any({'reminder', 'reminder:2', 'reminder:3', 'escalated'} & set(records)
                   for records in _events(message_id).values())
    assert _states(message_id) == ['queued']
    assert mailbox.delivery_outcome('queued') == 'queued' and mailbox.delivery_outcome('failed', True) == 'uncertain'


# F320: escalation is one durable record (claim, escalated receipt, coordinator note) and one coordinator push.

class CoordinatorTransport(MatrixTransport):
    """Finds the coordinator by its title, like the app's transport, and records every injection."""
    def __init__(self, native, title):
        super().__init__()
        self.native, self.title = native, title

    def discover(self, **_kwargs):
        return {'recipients': [{'id': self.native, 'title': self.title}]}


def _escalation_notes(message_id):
    with mailbox.application_history() as history:
        return history._db.execute("SELECT count(*) FROM messages WHERE conversation_id=? AND reply_to=? "
            "AND idempotency_key LIKE 'workshop-escalation:%'", (mailbox.ROOM, message_id)).fetchone()[0]


def _uncertain_sender_push(tmp_path, monkeypatch, declaration, text):
    message_id = _recorded_message(tmp_path, monkeypatch, declaration['agent'], text)
    monkeypatch.setattr(workshop_live, 'push', lambda *a, **k: ('uncertain', 'workshop', 'timed out'))
    start = time.time()
    assert [row['state'] for row in _deliver(message_id, _live_row(declaration, declaration['native_session_id']))] \
        == ['uncertain']
    return message_id, start


def test_a_stop_before_the_escalation_commits_leaves_nothing_and_the_next_pass_escalates_once(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'unsure, then a stop, answer?')
    transport = CoordinatorTransport(native, '717 coordinator (live)')
    worker = mailbox.WorkshopInjection(None, transport)
    with mailbox.application_history() as history:
        store = type(history)
    original = store.append
    stops = []

    def stop_once(self, conversation_id, **fields):   # the process stops as the coordinator note is written
        if str(fields.get('idempotency_key', '')).startswith('workshop-escalation:') and not stops:
            stops.append(fields['reply_to'])
            raise RuntimeError('process stopped mid-escalation')
        return original(self, conversation_id, **fields)
    monkeypatch.setattr(store, 'append', stop_once)
    with pytest.raises(RuntimeError, match='mid-escalation'):
        _watch_at(worker, start + 490)
    assert stops == [message_id]
    assert not any('escalated' in records for records in _events(message_id).values())   # neither receipt nor note
    assert _escalation_notes(message_id) == 0 and transport.sent == []
    for at in (start + 500, start + 510):                # the next pass escalates, once
        _watch_at(worker, at)
    assert [len([1 for records in _events(message_id).values() if 'escalated' in records]),
            _escalation_notes(message_id)] == [1, 1]
    assert [key.endswith(':escalation') for _app, _native, key in transport.sent] == [True], transport.sent
    assert _states(message_id) == ['uncertain']


def test_two_watchers_on_one_snapshot_write_one_note_and_inject_it_once(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'unsure, two watchers, answer?')
    transport = CoordinatorTransport(native, '717 coordinator (live)')
    workers = [mailbox.WorkshopInjection(None, transport) for _ in range(2)]
    barrier, asks = threading.Barrier(2), mailbox._asks_for_reply

    def after_the_snapshot(message):   # each watcher has read the receipts; they meet here, then race to escalate
        try:
            barrier.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
        return asks(message)
    monkeypatch.setattr(mailbox, '_asks_for_reply', after_the_snapshot)

    def watch(worker):
        _watch_at(worker, start + 490)
    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(watch, worker) for worker in workers]:
            future.result()
    assert _escalation_notes(message_id) == 1
    assert [len([1 for records in _events(message_id).values() if 'escalated' in records])] == [1]
    assert [key.endswith(':escalation') for _app, _native, key in transport.sent] == [True], transport.sent


# F320: a committed escalation note reaches the coordinator later if its push never started; a started one never replays.

def _escalation_note(message_id):
    with mailbox.application_history() as history:
        row = history._db.execute("SELECT id FROM messages WHERE conversation_id=? AND reply_to=? "
            "AND idempotency_key LIKE 'workshop-escalation:%'", (mailbox.ROOM, message_id)).fetchone()
        return history.get(mailbox.ROOM, row['id'], principal=mailbox.DELIVERY_AUTHOR) if row else None


def _coordinator_pushes(transport):
    return [key for _app, _native, key in transport.sent if key.endswith(':escalation')]


def test_a_stop_after_the_escalation_commit_is_pushed_once_on_the_next_pass(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'stop after the note, answer?')
    transport = CoordinatorTransport(native, '717 coordinator (live)')
    worker = mailbox.WorkshopInjection(None, transport)
    found = worker._coordinator
    stops = []

    def discovery_breaks_once(declarations):   # the process stops right after the commit, before any claim
        if not stops:
            stops.append(1)
            raise RuntimeError('stopped before the coordinator claim')
        return found(declarations)
    monkeypatch.setattr(worker, '_coordinator', discovery_breaks_once)
    with pytest.raises(RuntimeError, match='before the coordinator claim'):
        _watch_at(worker, start + 490)
    assert _escalation_notes(message_id) == 1 and _coordinator_pushes(transport) == []
    for at in (start + 500, start + 510, start + 520):
        _watch_at(worker, at)
    assert _coordinator_pushes(transport) == [_escalation_note(message_id)['id'] + ':escalation'], transport.sent
    assert _escalation_notes(message_id) == 1


def test_an_absent_coordinator_gets_the_escalation_once_when_it_appears(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'coordinator away, answer?')
    transport = CoordinatorTransport(native, 'someone else')   # no session carries the coordinator's title yet
    worker = mailbox.WorkshopInjection(None, transport)
    for at in (start + 490, start + 500):
        _watch_at(worker, at)
    assert _escalation_notes(message_id) == 1 and _coordinator_pushes(transport) == []
    transport.title = worker.coordinator_title   # the coordinator comes back
    for at in (start + 510, start + 520, start + 530):
        _watch_at(worker, at)
    assert _coordinator_pushes(transport) == [_escalation_note(message_id)['id'] + ':escalation'], transport.sent


def test_a_claimed_coordinator_push_that_never_finished_is_not_replayed(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'push began then stopped?')
    transport = CoordinatorTransport(native, 'someone else')
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, start + 490)
    note = _escalation_note(message_id)
    with mailbox.application_history() as history:   # a push claimed the note and stopped before its outcome
        seat = {**mailbox._ESCALATION_CLAIM, 'agent': json.dumps({'session': declaration['session'],
                                                                  'native_session_id': native})}
        assert mailbox.claim_delivery(history, note, seat, 'escalation', 'watch')[0]
    transport.title = worker.coordinator_title
    for at in (start + 500, start + 510, start + 520):
        _watch_at(worker, at)
    assert _coordinator_pushes(transport) == [], transport.sent


# F320: an unclaimed escalation note stays eligible for the retention lifetime; one dispatch claim per note.

def test_a_coordinator_back_after_eighteen_minutes_still_gets_the_escalation_once(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'coordinator away long, answer?')
    transport = CoordinatorTransport(native, 'someone else')
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, start + 490)
    assert _escalation_notes(message_id) == 1 and _coordinator_pushes(transport) == []
    transport.title = worker.coordinator_title           # back 20 minutes after the note was written
    for at in (start + 490 + 1200, start + 490 + 1210, start + 490 + 1220):
        _watch_at(worker, at)
    assert _coordinator_pushes(transport) == [_escalation_note(message_id)['id'] + ':escalation'], transport.sent


def test_two_watchers_seeing_different_coordinator_seats_dispatch_the_note_once(peer, tmp_path, monkeypatch):
    declaration = peer[0]
    native = declaration['native_session_id']
    plain = {key: value for key, value in declaration.items() if key not in ('display_name', 'title', 'aliases')}
    other = {**plain, 'root': declaration['root'] + ':coordinator-b', 'session': 'agent:session:' + 'b' * 64,
             'native_session_id': 'coordinator-b', 'updated_at': '2026-01-01T00:00:00+00:00',
             'agent': declaration['agent'].split(' / ')[0] + ' / coordinator / session-'
             + sha256(b'coordinator-b').hexdigest()[:12]}
    _insert_declaration(other)
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'the seat is changing, answer?')
    _watch_at(mailbox.WorkshopInjection(None, CoordinatorTransport(native, 'someone else')), start + 490)
    assert _escalation_notes(message_id) == 1     # committed, not yet dispatched: the coordinator was away
    title = '717 coordinator (live)'
    transports = [CoordinatorTransport(native, title), CoordinatorTransport('coordinator-b', title)]
    workers = [mailbox.WorkshopInjection(None, transport) for transport in transports]
    barrier = threading.Barrier(2)
    for worker in workers:   # each has found its own seat; they meet, then race for the note's dispatch
        def seen(declarations, found=worker._coordinator):
            rows = found(declarations)
            try:
                barrier.wait(timeout=3)
            except threading.BrokenBarrierError:
                pass
            return rows
        monkeypatch.setattr(worker, '_coordinator', seen)
    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(_watch_at, worker, start + 500) for worker in workers]:
            future.result()
    pushes = _coordinator_pushes(transports[0]) + _coordinator_pushes(transports[1])
    assert pushes == [_escalation_note(message_id)['id'] + ':escalation'], (transports[0].sent, transports[1].sent)
    with mailbox.application_history() as history:   # the one claim records the seat it was sent to
        rows = history._db.execute("SELECT label, outcome FROM workshop_claims WHERE message_id=? AND step='escalation'",
                                   (_escalation_note(message_id)['id'],)).fetchall()
    winner = native if _coordinator_pushes(transports[0]) else 'coordinator-b'
    assert [(json.loads(row['label'])['native_session_id'], row['outcome']) for row in rows] == [(winner, 'delivered')]


def test_an_unclaimed_escalation_note_past_twenty_days_is_still_pushed_once(peer, tmp_path, monkeypatch):
    """A note that is still in the store stays eligible: no separate dispatch clock (at and beyond the old 20 days)."""
    declaration = peer[0]
    native = declaration['native_session_id']
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'coordinator gone for weeks?')
    transport = CoordinatorTransport(native, 'someone else')
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, start + 490)
    assert _escalation_notes(message_id) == 1 and _coordinator_pushes(transport) == []
    _watch_at(worker, start + 20 * 86400)                # exactly at the old cutoff, still away
    assert _coordinator_pushes(transport) == []
    transport.title = worker.coordinator_title           # back after 21 days
    for at in (start + 21 * 86400, start + 21 * 86400 + 10, start + 21 * 86400 + 20):
        _watch_at(worker, at)
    assert _coordinator_pushes(transport) == [_escalation_note(message_id)['id'] + ':escalation'], transport.sent


def test_after_an_upgrade_only_new_protocol_escalation_notes_are_recovered(peer, tmp_path, monkeypatch):
    """Notes written by the shipping base (c79f6b53: no dispatch claim, push activity only after the effect) are never
    replayed, delivered or not; only a note written by the new protocol is recovered, once."""
    declaration = peer[0]
    native = declaration['native_session_id']
    legacy_ids = []
    with mailbox.application_history() as history:   # the store as c79f6b53 left it
        for index, pushed in enumerate((True, False)):
            asked = history.append(mailbox.ROOM, author='another sender', content='To ' + declaration['agent']
                + ':\nold question %d?' % index, category=mailbox.CATEGORY, idempotency_key='f320-upgrade-asked-%d' % index)
            note = history.append(mailbox.ROOM, author=mailbox.DELIVERY_AUTHOR, content='To 717:\nold escalation %d' % index,
                category=mailbox.CATEGORY, refs=(declaration['session'],), reply_to=asked['id'],
                idempotency_key='workshop-escalation:' + sha256((asked['id'] + '\0' + declaration['session'])
                                                                .encode()).hexdigest())
            legacy_ids.append(note['id'])
            if pushed:   # delivered: its push activity was written after the effect
                mailbox.record_activity(history, mailbox.DELIVERY_AUTHOR, 'escalation-push', note['id'],
                                        recipient=declaration['session'], status='injected')
    message_id, start = _uncertain_sender_push(tmp_path, monkeypatch, declaration, 'new protocol note, answer?')
    transport = CoordinatorTransport(native, 'someone else')
    worker = mailbox.WorkshopInjection(None, transport)
    _watch_at(worker, start + 490)                       # the new note is written while the coordinator is away
    transport.title = worker.coordinator_title
    for at in (start + 500, start + 510, start + 520, start + 530):
        _watch_at(worker, at)
    assert _coordinator_pushes(transport) == [_escalation_note(message_id)['id'] + ':escalation'], transport.sent
    assert not [key for key in _coordinator_pushes(transport) if key.split(':')[0] in legacy_ids]
