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
    from nodelang import model_router, nograph_server
    monkeypatch.setattr(nograph_server, '_baboom_brain', lambda: None)
    monkeypatch.setattr(model_router, 'composer_chat', lambda body, on_delta=None: {
        'ok': True, 'answer': 'There are 12 sheets.', 'provider': 'Fake', 'model': 'fake-model'})
    task = _task('Review sheets')
    result = nograph_server._chat({'prompt': 'how many sheets?', 'agent': 'BABOOM', 'task': task}, lambda text: None)
    assert result['answer'] == 'There are 12 sheets.'
    thread = _thread(task)
    assert any('how many sheets?' in text for text in thread) and any('There are 12 sheets.' in text for text in thread)
