"""'database is locked' since 16:02: every open ran the same doomed retention delete, so no send could commit.
Founder rule: never delete his data without his word. Opening deletes nothing; the old delete is explicit only,
in small committed batches; sends wait out a busy writer."""
from datetime import datetime, timedelta, timezone
import sqlite3
import threading
import time

import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    yield tmp_path


CONTEXT = {'threadId': 'retention-sender'}


def _declare():
    from pathlib import Path
    from nodelang.workshop_mailbox import call
    call('declare', {'task': 'retention', 'paths': [str(Path.cwd())], 'status': 'working', 'request_id': 'RET'}, CONTEXT)


def _seed(count, *, waiting=0, poison_at=None):
    """count expired room rows, each replying to the one before; the oldest `waiting` are held for delivery."""
    from nodelang.workshop_mailbox import CATEGORY, ROOM, application_history
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    ids = []
    with application_history() as history:
        for index in range(count):
            content = 'poison' if index == poison_at else 'old %d' % index
            row = history.append(ROOM, author='Old agent', content=content, category=CATEGORY,
                idempotency_key='seed-%d' % index, created_at=old, reply_to=ids[-1] if ids else None)
            ids.append(row['id'] if isinstance(row, dict) else row)
        for message_id in ids[:waiting]:
            history._db.execute("INSERT INTO workshop_waiting VALUES(?, 'someone')", (message_id,))
    return ids


def _expired_count():
    from nodelang.workshop_mailbox import ROOM, profile_database
    with sqlite3.connect(profile_database()) as connection:
        return connection.execute("SELECT count(*) FROM messages WHERE conversation_id=? AND author='Old agent'",
                                  (ROOM,)).fetchone()[0]


def test_fifty_boot_opens_delete_nothing_and_take_no_write_lock(monkeypatch):
    # Founder rule: never delete his data without his word. The app boots while another process writes.
    from nodelang import workshop_mailbox
    from nodelang.workshop_mailbox import application_history, call, profile_database
    _declare()
    _seed(40)
    monkeypatch.setattr(workshop_mailbox, '_retain_messages', lambda history: pytest.fail('automatic delete'))
    monkeypatch.setattr(workshop_mailbox, '_SESSION_MIGRATED', set())    # a fresh process: first open is a boot
    writer = sqlite3.connect(profile_database(), isolation_level=None, timeout=2)
    writer.execute('BEGIN IMMEDIATE')
    try:
        for _ in range(50):
            with application_history(busy_timeout_seconds=0.05) as history:
                assert history._db.execute("SELECT 1 FROM messages LIMIT 1").fetchone()
    finally:
        writer.execute('ROLLBACK')
        writer.close()
    assert _expired_count() == 40
    assert call('send', {'to': 'Ahmed', 'text': 'old rows stay'}, CONTEXT)['message_id']
    assert _expired_count() == 40


def test_retention_drains_in_small_committed_batches_and_skips_held_rows(monkeypatch):
    from nodelang import workshop_mailbox
    from nodelang.workshop_mailbox import ROOM, _EXPIRED, application_history, _retain_messages
    _seed(37, waiting=3)
    monkeypatch.setattr(workshop_mailbox, '_RETAIN_RUN_SECONDS', 0)    # one batch per run
    counts = [_expired_count()]
    with application_history() as history:
        for _ in range(10):
            started = time.monotonic()
            _retain_messages(history)
            assert time.monotonic() - started < workshop_mailbox._RETAIN_BATCH_SECONDS + 0.5
            counts.append(_expired_count())
        cutoff = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        assert history._db.execute("SELECT 1" + _EXPIRED + " LIMIT 1", (ROOM, cutoff)).fetchone() is None
        assert history._db.execute("SELECT count(*) FROM messages WHERE reply_to IS NOT NULL AND reply_to NOT IN "
                                   "(SELECT id FROM messages)").fetchone()[0] == 0
    batch = workshop_mailbox._RETAIN_BATCH
    assert 8 <= batch <= 16
    assert counts[:3] == [37, 37 - batch, 37 - 2 * batch]       # each run commits exactly one small batch
    assert counts[-1] == 3                                       # rows held for delivery are never deleted


def test_an_interrupted_run_keeps_the_batches_it_committed():
    from nodelang import workshop_mailbox
    from nodelang.workshop_mailbox import application_history, _retain_messages
    batch = workshop_mailbox._RETAIN_BATCH
    _seed(40, poison_at=40 - batch - 2)                          # newest first: the poison sits in batch two
    with application_history() as history:
        history._db.execute("CREATE TEMP TRIGGER poison BEFORE DELETE ON messages WHEN old.content='poison' "
                            "BEGIN SELECT RAISE(ABORT, 'interrupted'); END")
        with pytest.raises(sqlite3.DatabaseError):
            _retain_messages(history)
    assert _expired_count() == 40 - batch


def test_a_send_waits_out_a_writer_holding_the_lock_for_three_seconds(monkeypatch):
    from nodelang import workshop_mailbox
    from nodelang.workshop_mailbox import call, profile_database
    _declare()
    _seed(12)
    opened = []
    real = workshop_mailbox.application_history

    def counted(*args, **kwargs):
        opened.append(kwargs.get('busy_timeout_seconds'))
        return real(*args, **kwargs)
    holding = threading.Event()

    def writer():
        connection = sqlite3.connect(profile_database(), isolation_level=None, timeout=2)
        connection.execute('BEGIN IMMEDIATE')
        holding.set()
        time.sleep(3)
        connection.execute('ROLLBACK')
        connection.close()
    thread = threading.Thread(target=writer)
    thread.start()
    assert holding.wait(5)
    monkeypatch.setattr(workshop_mailbox, 'application_history', counted)
    try:
        sent = call('send', {'to': 'Ahmed', 'text': 'waited for the writer'}, CONTEXT)
    finally:
        thread.join()
    assert sent['message_id']
    tries = [wait for wait in opened if wait is not None]        # call()'s store opens carry their busy wait
    assert _expired_count() == 12
    assert 1 <= len(tries) <= 4 and all(1.0 <= wait <= 2.0 for wait in tries)   # long waits, not 50 ms reopen storms
