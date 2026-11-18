"""F419 "see why the program is slow", second cause: after the reply_to index, every connector still burned 30-58%
of a core. Each poll re-ran the To-line text match over the whole room and read the declarations three times
(0.3 s of CPU a poll on the founder's 14,660-row store; a poll follows every tool call). A note is matched once."""
from pathlib import Path

from nodelang import workshop_mailbox as mailbox

CONTEXT, ROOM_NOTES = {'threadId': 'poll-cost'}, 6000


def _declare(**names):
    return mailbox.call('declare', {'task': 'poll cost', 'paths': [str(Path.cwd())], 'status': 'working',
                                    'request_id': 'F419', **names}, CONTEXT)['declaration']


def _room():
    """A room at a fraction of the founder's size: notes for other agents, none for this session."""
    row = "INSERT INTO messages VALUES(?,?,?,'Other agent',?,?,'[]','[]','[]',NULL,'2026-11-18T00:00:00+00:00',?,1)"
    with mailbox.application_history() as history:
        start = history._db.execute('SELECT last_sequence FROM conversations WHERE id=?', (mailbox.ROOM,)).fetchone()[0]
        history._db.execute('BEGIN IMMEDIATE')
        history._db.executemany(row, (('room-%d' % n, mailbox.ROOM, start + n + 1, 'To Somebody Else:\nnote %d' % n,
                                       mailbox.CATEGORY, 'room-%d' % n) for n in range(ROOM_NOTES)))
        history._db.execute('UPDATE conversations SET last_sequence=? WHERE id=?', (start + ROOM_NOTES, mailbox.ROOM))
        history._db.execute('COMMIT')


def _note(to, text):
    with mailbox.application_history() as history:
        row = history.append(mailbox.ROOM, author='Other agent', content='To ' + to + ':\n' + text,
                             category=mailbox.CATEGORY, idempotency_key='note-' + text)
        return row['id'] if isinstance(row, dict) else row


def _poll(declaration):
    """One connector poll: the ids it would hand over, and the SQLite steps it cost (counted, not timed)."""
    identity = {'sender_key': declaration['session'], 'sender_label': declaration['agent'],
                'sender': declaration['agent'] + ' [' + declaration['session'] + ']'}
    steps = [0]

    def count():
        steps[0] += 1
    with mailbox.application_history() as history:
        history._db.set_progress_handler(count, 100)
        try:
            page = mailbox._pending(history, identity, declaration['runtime'])
        finally:
            history._db.set_progress_handler(None, 0)
    return [message['id'] for message in page['pending']], steps[0]


def test_one_poll_serves_a_burst_of_tool_calls_and_a_new_note_still_reaches_the_page():
    import time
    from nodelang import native_agent_mcp
    polls, notes = [], []

    def room(method, body, context):
        if method == 'pending':
            polls.append(time.monotonic())
        return {'pending': list(notes)}
    server = native_agent_mcp.build_server(mailbox_call=room, _registry_catalogue=True)
    send = server._tool_manager._tools['send'].fn
    tool_call = send.__closure__[send.__code__.co_freevars.index('start')].cell_contents   # what every tool call does
    try:
        ends = time.monotonic() + 2.5
        while time.monotonic() < ends:                        # an agent at work: about 50 tool calls
            tool_call(CONTEXT)
            time.sleep(0.05)
        burst = len(polls)
        notes.append({'id': 'late-note'})
        waited = time.monotonic()
        while not server._mailbox_pages.get(tuple(CONTEXT.items()), {}).get('pending'):
            assert time.monotonic() - waited < 8, 'the note never reached the page'
            tool_call(CONTEXT)
            time.sleep(0.05)
    finally:
        server._mailbox_stop()
    print('\nF419 store polls for about 50 tool calls in 2.5 s: %d' % burst)
    assert 1 <= burst <= 3                                    # it was one poll per tool call


def test_a_poll_matches_each_note_once_and_still_hands_over_every_addressed_note():
    declaration = _declare()
    _room()
    first = _note(declaration['agent'], 'first')
    found, cold = _poll(declaration)
    assert found == [first]
    again, warm = _poll(declaration)
    assert again == [first]
    print('\nF419 poll over %d room notes: %d -> %d hundred SQLite steps' % (ROOM_NOTES, cold, warm))
    assert warm * 3 < cold                                   # the whole room is not matched again
    second = _note(declaration['agent'], 'second')            # a note written after the last poll still arrives
    renamed = _note('Night Shift', 'for a name it does not hold yet')
    assert _poll(declaration)[0] == [first, second]
    getattr(mailbox, '_ROUTED', {}).clear()                   # a new connector process hands over the same notes
    assert _poll(declaration)[0] == [first, second]
    declaration = _declare(display_name='Night Shift')        # new names: the older notes are matched again
    assert _poll(declaration)[0] == [first, second, renamed]
