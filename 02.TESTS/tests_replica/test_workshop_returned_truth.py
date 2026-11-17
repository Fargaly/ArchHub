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
    for _ in range(len(addressees) + 2):
        worker._watched_at = float('-inf')
        with mailbox.application_history() as history:
            worker._watch(history, time.time(), mailbox.read_declarations(history._db, include_archived=True))
    follow_ups = [(app, native) for app, native, key in transport.sent if key == message['id'] + ':reminder']
    assert per_identity(follow_ups) == [0 if siblings else 1] * len(addressees), transport.sent
