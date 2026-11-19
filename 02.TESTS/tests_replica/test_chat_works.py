"""CHAT-WORKS: a message typed in a session's thread reaches the agent and the answer lands in that same thread.

Founder 2026-11-16: "even its chat does not work". Any installed agent (two vendors here, faked at the push door),
and BABOOM/the model when nobody is mentioned. Nothing is sent to a real session: the push is replaced.
"""
import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'TEMP', 'TMP'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    import contextlib
    from nodelang import canvas_documents
    @contextlib.contextmanager
    def unlocked(path):
        yield
    monkeypatch.setattr(canvas_documents, 'locked', unlocked)
    yield tmp_path


def _declare(context, name):
    from nodelang.workshop_mailbox import call
    return call('declare', {'task': 'chat test', 'paths': [str(__import__('pathlib').Path.cwd())], 'status': 'working',
                            'request_id': 'CHAT', 'display_name': name}, context)


def _task(title):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        return workshop_tasks.create_session(history, title, 'founder', select=False)['taskId']


def _thread(task):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        row = next(r for r in workshop_tasks.column(history) if r['id'] == task)
    return [m['text'] for m in row['agentLog'] + row['fileMessages']]


def test_a_thread_message_reaches_two_vendors_and_both_replies_land_in_that_thread(monkeypatch):
    from nodelang import workshop_live
    from nodelang.nograph_server import _route_to_agents
    from nodelang.workshop_mailbox import call
    pushed = []
    monkeypatch.setattr(workshop_live, 'push', lambda app, native, text, mid, **k: pushed.append(app) or ('delivered', 'workshop', ''))
    _declare({'claude/sessionID': 'chat-claude'}, 'Claude A')
    _declare({'threadId': 'chat-codex'}, 'Codex B')
    task, other = _task('Review sheets'), _task('Other work')
    sent = _route_to_agents('@claude-a @codex-b how many sheets?', ['claude-a', 'codex-b'], task=task)
    assert sorted(pushed) == ['claude', 'codex']
    call('send', {'to': 'Ahmed', 'text': 'Claude: 12 sheets', 'reply_to': sent['request_id']}, {'claude/sessionID': 'chat-claude'})
    call('send', {'to': 'Ahmed', 'text': 'Codex: 12 sheets, 2 unnumbered', 'reply_to': sent['request_id']}, {'threadId': 'chat-codex'})
    thread = '\n'.join(_thread(task))
    assert 'how many sheets?' in thread and 'Claude: 12 sheets' in thread and 'Codex: 12 sheets, 2 unnumbered' in thread
    assert not any('sheets' in text for text in _thread(other))


def test_a_thread_question_with_no_mention_is_answered_in_that_thread(monkeypatch):
    """BABOOM with its Goose brain up answers in the task thread; no composer fallthrough."""
    from nodelang import baboom_nograph, model_router, nograph_server
    monkeypatch.setattr(baboom_nograph, 'ask', lambda prompt, context='': {
        'text': 'There are 12 sheets.', 'steps': [],
        'via': {'family': 'openrouter', 'provider': 'Goose', 'model': 'openrouter/free'}, 'actions': []})
    monkeypatch.setattr(model_router, 'composer_chat', lambda body, on_delta=None: (_ for _ in ()).throw(
        AssertionError('BABOOM must not fall through to composer_chat')))
    task = _task('Review sheets')
    result = nograph_server._chat({'prompt': 'how many sheets?', 'agent': 'BABOOM', 'task': task}, lambda text: None)
    assert result['answer'] == 'There are 12 sheets.'
    assert result['provider'] == 'BABOOM (Goose)'
    thread = _thread(task)
    assert any('how many sheets?' in text for text in thread) and any('There are 12 sheets.' in text for text in thread)


def test_baboom_brain_down_refuses_instead_of_composer_fallthrough(monkeypatch):
    from nodelang import baboom_nograph, model_router, nograph_server
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', None)
    monkeypatch.setitem(baboom_nograph._STATE, 'error', 'BABOOM brain unavailable: packaged Goose missing.')
    called = []
    monkeypatch.setattr(model_router, 'composer_chat', lambda *a, **k: called.append(1) or {
        'ok': True, 'answer': 'fallthrough', 'provider': 'Fake', 'model': 'fake'})
    task = _task('Brain down')
    with pytest.raises(RuntimeError, match='packaged Goose missing'):
        nograph_server._chat({'prompt': 'how many sheets?', 'agent': 'BABOOM', 'task': task}, lambda text: None)
    assert called == []


def test_reply_task_survives_open_and_busy_writer(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import sqlite3
    import threading
    import time
    from nodelang import workshop_live, workshop_mailbox
    from nodelang.nograph_server import _route_to_agents
    from nodelang.workshop_mailbox import application_history, call, profile_database, ROOM
    context = {'threadId': 'chat-lock-codex'}
    _declare(context, 'Codex Lock')
    task, other = _task('Busy session'), _task('Other session')
    monkeypatch.setattr(workshop_live, 'push', lambda *_args, **_kwargs: ('delivered', 'workshop', ''))
    question = _route_to_agents('@codex-lock check the lock', ['codex-lock'], task=task)['request_id']
    with application_history() as history, history._transaction(write=True):
        history._db.execute('UPDATE messages SET created_at=? WHERE conversation_id=? AND id=?',
                            ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(), ROOM, question))
        history._db.execute('DELETE FROM workshop_waiting WHERE message_id=?', (question,))
    with application_history() as history:
        assert history._db.execute('SELECT id FROM messages WHERE id=?', (question,)).fetchone()
    holding = threading.Event()
    def writer():
        connection = sqlite3.connect(profile_database(), isolation_level=None, timeout=2)
        try:
            connection.execute('BEGIN IMMEDIATE')
            holding.set()
            time.sleep(3)
            connection.execute('ROLLBACK')
        finally:
            connection.close()
    opened = []
    real = workshop_mailbox.application_history
    def counted(*args, **kwargs):
        opened.append(kwargs.get('busy_timeout_seconds'))
        return real(*args, **kwargs)
    thread = threading.Thread(target=writer)
    thread.start()
    assert holding.wait(5)
    monkeypatch.setattr(workshop_mailbox, 'application_history', counted)
    try:
        sent = call('send', {'to': 'Ahmed', 'text': 'Reply after the writer', 'reply_to': question}, context)
    finally:
        thread.join()
    assert sent['message_id']
    tries = [wait for wait in opened if wait is not None]
    assert 1 <= len(tries) <= 4 and all(1.0 <= wait <= 2.0 for wait in tries)
    assert 'Reply after the writer' in '\n'.join(_thread(task))
    assert not any('Reply after the writer' in text for text in _thread(other))
    with application_history() as history:
        assert history._db.execute('SELECT id FROM messages WHERE id=?', (question,)).fetchone()
