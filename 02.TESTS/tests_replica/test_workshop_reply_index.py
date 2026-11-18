"""F419 "see why the program is slow": 15 connector processes burned a core each. py-spy put every busy thread in
delivery_events (one query per message of every poll); the store held no index on reply_to, so each call walked
every delivery receipt. The store gets its declared reply_to index on open, without a write lock once it exists."""
import json
import sqlite3
import time

NOTES, RECEIPTED, EVENTS, PAGE = 12800, 550, ('addressed', 'attempt', 'initial-outcome', 'answered'), 100


def _seed():
    """The founder's store at the time: ~15,000 rows, ~2,200 of them delivery receipts, and no reply_to index."""
    from nodelang.workshop_mailbox import (CATEGORY, DELIVERY_AUTHOR, DELIVERY_CATEGORY, DELIVERY_PREFIX, ROOM,
                                           application_history)
    row = "INSERT INTO messages VALUES(?,?,?,?,?,?,'[]','[]','[]',?,'2026-11-18T00:00:00+00:00',?,1)"
    with application_history() as history:
        db = history._db
        db.execute('DROP INDEX workshop_reply_to')
        db.execute('BEGIN IMMEDIATE')
        db.executemany(row, (('note-%d' % n, ROOM, n + 1, 'Agent %d' % (n % 40), 'note %d' % n, CATEGORY,
                              'note-%d' % (n - 1) if n % 2 else None, 'seed-%d' % n) for n in range(NOTES)))
        sequence = NOTES
        for n in range(NOTES - RECEIPTED, NOTES):
            for event in EVENTS:
                sequence += 1
                db.execute(row, ('receipt-%d' % sequence, ROOM, sequence, DELIVERY_AUTHOR,
                                 json.dumps({'recipient': 'session-%d' % (n % 7), 'label': 'peer', 'event': event}),
                                 DELIVERY_CATEGORY, 'note-%d' % n, DELIVERY_PREFIX + str(sequence)))
        db.execute('UPDATE conversations SET last_sequence=? WHERE id=?', (sequence, ROOM))
        db.execute('COMMIT')
    return [{'id': 'note-%d' % n, 'sequence': n + 1} for n in range(NOTES - PAGE, NOTES)]


def _cost(history, page):
    """One read page: SQLite steps (counted, not timed) and wall milliseconds per delivery_events call."""
    from nodelang.workshop_mailbox import delivery_events
    steps = [0]

    def count():
        steps[0] += 1
    history._db.set_progress_handler(count, 1)
    try:
        found = [delivery_events(history, message) for message in page]
    finally:
        history._db.set_progress_handler(None, 0)
    started = time.perf_counter()
    for message in page:
        delivery_events(history, message)
    return found, steps[0] // len(page), (time.perf_counter() - started) * 1000 / len(page)


def _plan(history):
    from nodelang.workshop_mailbox import DELIVERY_AUTHOR, DELIVERY_CATEGORY, ROOM
    return ' '.join(row[3] for row in history._db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM messages WHERE conversation_id=? AND reply_to=? "
        "AND author=? AND category=? ORDER BY sequence", (ROOM, 'note-1', DELIVERY_AUTHOR, DELIVERY_CATEGORY)))


def _indexed():
    from nodelang.workshop_mailbox import profile_database
    with sqlite3.connect(profile_database()) as db:
        return db.execute("SELECT sql FROM sqlite_master WHERE name='workshop_reply_to'").fetchone()


def test_a_message_reads_its_own_receipts_not_every_receipt():
    from nodelang.workshop_mailbox import application_history, profile_database
    page = _seed()
    assert _indexed() is None
    with application_history(read_only=True) as history:           # the store as the installed build left it
        assert 'workshop_reply_to' not in _plan(history)
        before, steps_before, ms_before = _cost(history, page)
    writer = sqlite3.connect(profile_database(), isolation_level=None, timeout=2)
    writer.execute('BEGIN IMMEDIATE')
    try:                                                           # busy store: the open still works, index later
        with application_history(busy_timeout_seconds=0.05) as history:
            assert history._db.execute('SELECT 1 FROM messages LIMIT 1').fetchone()
        assert _indexed() is None
    finally:
        writer.execute('ROLLBACK')
    with application_history() as history:                         # the next open of an existing store adds it
        assert 'USING INDEX workshop_reply_to' in _plan(history)
        after, steps_after, ms_after = _cost(history, page)
    from nodelang.conversation_history import WORKSHOP_SEND_INDEXES
    assert _indexed()[0] in WORKSHOP_SEND_INDEXES                   # the one the history schema check admits
    writer.execute('BEGIN IMMEDIATE')
    try:                                                           # once it exists, an open takes no write lock
        for _ in range(20):
            with application_history(busy_timeout_seconds=0.05) as history:
                assert 'USING INDEX workshop_reply_to' in _plan(history)
    finally:
        writer.execute('ROLLBACK')
        writer.close()
    print('\nF419 delivery_events per call: %d -> %d SQLite steps, %.3f -> %.3f ms'
          % (steps_before, steps_after, ms_before, ms_after))
    assert after == before and sum(len(found) for found in after) == PAGE      # same receipts, one recipient each
    assert steps_before > len(EVENTS) * RECEIPTED                   # it walked every receipt for one message
    assert steps_after * 20 < steps_before
