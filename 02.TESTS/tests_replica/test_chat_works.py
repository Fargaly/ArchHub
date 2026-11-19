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
    from nodelang import baboom_nograph, nograph_server
    monkeypatch.setattr(baboom_nograph, 'ask', lambda prompt, context='': {
        'text': 'There are 12 sheets.', 'steps': [], 'via': {'model': 'fake-model'}, 'actions': []})
    task = _task('Review sheets')
    result = nograph_server._chat({'prompt': 'how many sheets?', 'agent': 'BABOOM', 'task': task}, lambda text: None)
    assert result['answer'] == 'There are 12 sheets.'
    thread = _thread(task)
    assert any('how many sheets?' in text for text in thread) and any('There are 12 sheets.' in text for text in thread)


@pytest.fixture
def no_brain(monkeypatch):
    """BABOOM's brain failed to start; the generic model would answer if anything fell through to it."""
    from nodelang import baboom_nograph, model_router
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', None)
    monkeypatch.setitem(baboom_nograph._STATE, 'error', 'BABOOM brain unavailable (Goose): goose.exe was not found')
    fallback = []
    monkeypatch.setattr(model_router, 'composer_chat', lambda body, on_delta=None: fallback.append(body) or {
        'ok': True, 'answer': 'generic answer', 'provider': 'Fake', 'model': 'fake-model'})
    return fallback


def _refusal(body):
    """The composer route as the Studio calls it: a refusal is a 400 with the reason, and the Studio puts the draft back."""
    from types import SimpleNamespace
    from nodelang.nograph_server import NoGraphServer, Refused
    owner = SimpleNamespace(admit_chat=lambda: (lambda: False))
    handler = SimpleNamespace(body=lambda: body)
    with pytest.raises(Refused) as refused:
        NoGraphServer._router_chat(owner, handler)
    return refused.value


@pytest.mark.parametrize('thread', ['fresh', 'task'])
def test_baboom_without_its_brain_says_why_and_never_falls_through(no_brain, thread):
    task = _task('Sheets') if thread == 'task' else None
    body = {'prompt': 'how many sheets?', 'agent': 'BABOOM', **({'task': task} if task else {})}
    refusal = _refusal(body)
    assert refusal.status == 400 and 'Goose' in str(refusal) and 'goose.exe was not found' in str(refusal)
    assert no_brain == []                                   # the generic model was never asked
    assert body['prompt'] == 'how many sheets?'             # the draft goes back unchanged
    if task:
        assert not any('generic answer' in text for text in _thread(task))


def _active(task):
    from nodelang import workshop_tasks
    from nodelang.workshop_mailbox import application_history
    with application_history() as history:
        return any(r['id'] == task for r in workshop_tasks.column(history))


def test_a_refused_baboom_start_from_home_leaves_no_empty_session_but_an_existing_one_stays(no_brain):
    fresh, existing = _task('New from Home'), _task('Existing')
    _refusal({'prompt': 'hello', 'agent': 'BABOOM', 'task': fresh, 'fresh': True})
    _refusal({'prompt': 'hello', 'agent': 'BABOOM', 'task': existing})
    assert not _active(fresh) and _active(existing)


def test_home_baboom_start_sends_before_it_opens_so_a_refusal_keeps_the_draft_on_home():
    """ui.jsx: Home → New session → BABOOM no longer opens the session first and drops the refusal; it takes the start
    path that opens only once answered and otherwise puts the typed text back in the Home composer (toast = reason)."""
    from pathlib import Path
    ui = (Path(__file__).resolve().parents[2] / '01.APP/nodelang/studio/ui.jsx').read_text(encoding='utf-8')
    start = ui[ui.index("if(u.route==='home'&&!taskId&&!onSent){"):]
    start = start[:start.index('if (typeof t.answer')]
    assert "agent==='BABOOM'" not in start
    assert start.index('fresh:true') < start.index('if(answered){await u.openTaskFile') < start.index('setDraft(current => current.text ? current : {text')


@pytest.mark.parametrize('question', ['Who are you?', 'Are you a human?'])
def test_off_or_brainless_baboom_gives_no_persona_answer_but_enabled_it_does(no_brain, monkeypatch, tmp_path, question):
    from nodelang import baboom_nograph
    assert 'goose.exe was not found' in str(_refusal({'prompt': question, 'agent': 'BABOOM'}))   # brain unavailable
    (tmp_path / 'settings').mkdir()
    (tmp_path / 'settings' / 'baboom.json').write_text('{"startup": "off"}', encoding='utf-8')
    monkeypatch.setitem(baboom_nograph._STATE, 'state_dir', tmp_path)
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', object())   # still loaded, but turned off since
    assert 'turned off in Settings' in str(_refusal({'prompt': question, 'agent': 'BABOOM'}))
    (tmp_path / 'settings' / 'baboom.json').write_text('{"startup": "on"}', encoding='utf-8')
    result = nograph_server_chat({'prompt': question, 'agent': 'BABOOM'})
    assert result['model'] == 'persona' and 'BABOOM' in result['answer'] and no_brain == []


def nograph_server_chat(body):
    from nodelang import nograph_server
    return nograph_server._chat(body, lambda text: None)


def test_baboom_never_started_names_its_brain(no_brain, monkeypatch):
    from nodelang import baboom_nograph
    monkeypatch.setitem(baboom_nograph._STATE, 'error', '')
    assert 'Goose' in str(_refusal({'prompt': 'how many sheets?', 'agent': 'BABOOM'})) and no_brain == []


def test_an_explicit_other_route_still_goes_through_without_the_brain(no_brain, monkeypatch):
    from nodelang import nograph_server
    result = nograph_server._chat({'prompt': 'how many sheets?', 'agent': 'openrouter/free'}, lambda text: None)
    assert result['answer'] == 'generic answer' and len(no_brain) == 1
    started = []
    monkeypatch.setattr(nograph_server, '_ask_installed', lambda agent, *a, **k: started.append(agent) or {
        'answer': 'claude answer', 'model': 'agent session'})
    assert nograph_server._chat({'prompt': 'how many sheets?', 'agent': 'claude'}, lambda text: None)['answer'] == 'claude answer'
    assert started == ['claude']


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


def test_baboom_task_continuity_is_strictly_isolated(monkeypatch):
    from nodelang import baboom_nograph
    
    contexts = []
    def fake_ask(prompt, context=''):
        contexts.append(context)
        return {'text': f"Answered: {prompt}", 'steps': [], 'via': {'model': 'fake-model'}, 'actions': []}
        
    monkeypatch.setattr(baboom_nograph, 'ask', fake_ask)
    
    task_a = _task('Task A')
    task_b = _task('Task B')
    
    res = nograph_server_chat({'prompt': 'A message 1', 'agent': 'BABOOM', 'task': task_a})
    assert res['answer'] == 'Answered: A message 1'
    assert contexts[-1] == ''
    
    res = nograph_server_chat({'prompt': 'B message 1', 'agent': 'BABOOM', 'task': task_b})
    assert res['answer'] == 'Answered: B message 1'
    assert contexts[-1] == ''
    
    # We must explicitly record the answer into the workshop live database because our fake_ask bypasses the actual writing? 
    # Actually, _chat calls `record_answer` at the end: 
    # `record_answer(prompt, result['answer'], result['model'], task=task)`
    # This persists it to the DB so `_bound_messages` will pick it up on the next turn.
    
    res = nograph_server_chat({'prompt': 'A message 2', 'agent': 'BABOOM', 'task': task_a})
    assert res['answer'] == 'Answered: A message 2'
    
    ctx_a2 = contexts[-1]
    assert 'A message 1' in ctx_a2
    assert 'Answered: A message 1' in ctx_a2
    assert 'B message 1' not in ctx_a2
    assert 'Answered: B message 1' not in ctx_a2
    
    res = nograph_server_chat({'prompt': 'B message 2', 'agent': 'BABOOM', 'task': task_b})
    assert res['answer'] == 'Answered: B message 2'
    ctx_b2 = contexts[-1]
    assert 'B message 1' in ctx_b2
    assert 'Answered: B message 1' in ctx_b2
    assert 'A message 1' not in ctx_b2
    assert 'A message 2' not in ctx_b2
