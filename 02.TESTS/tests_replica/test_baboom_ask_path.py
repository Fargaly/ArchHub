"""BABOOM ask path (F20 / GOOSEFIT): Goose-fitted brain answers on the desktop composer/Workshop.

The Workshop TaskComposer must bind the ask to the selected task so the answer lands in that
thread. When the Goose brain is down, BABOOM refuses with the real reason instead of falling
through to the free-model composer. Explicit @agent routes stay separate.
"""
import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'TEMP', 'TMP'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    monkeypatch.delenv('ARCHHUB_TEST_STATE_DIR', raising=False)
    # Linux courts: canvas_documents.locked imports msvcrt; keep the lock a no-op here.
    import contextlib
    from nodelang import canvas_documents
    @contextlib.contextmanager
    def unlocked(path):
        yield
    monkeypatch.setattr(canvas_documents, 'locked', unlocked)
    yield tmp_path


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


def test_composer_baboom_ask_uses_goose_and_lands_in_the_task_thread(monkeypatch):
    from nodelang import baboom_nograph, model_router, nograph_server

    asked, composer = [], []

    def goose_ask(prompt, context=''):
        asked.append(prompt)
        return {'text': 'Revit is connected.', 'steps': [{'tool': 'hosts_state', 'status': 'ok'}],
                'via': {'family': 'openrouter', 'provider': 'Goose', 'model': 'openrouter/free'}, 'actions': []}

    monkeypatch.setattr(baboom_nograph, 'ask', goose_ask)
    monkeypatch.setattr(model_router, 'composer_chat', lambda *a, **k: composer.append(1) or {
        'ok': True, 'answer': 'composer fallthrough', 'provider': 'Fake', 'model': 'fake'})
    task = _task('Desktop ask')
    steps = []
    result = nograph_server._chat({'prompt': 'which programs are connected?', 'agent': 'BABOOM', 'task': task},
                                  lambda text: None, on_step=steps.append)
    assert result['provider'] == 'BABOOM (Goose)'
    assert result['answer'].startswith('Revit is connected.')
    assert 'hosts_state' in result['answer']
    assert asked == ['which programs are connected?']
    assert composer == []
    assert steps == [{'id': 'hosts_state', 'tool': 'hosts_state', 'status': 'ok'}]
    thread = '\n'.join(_thread(task))
    assert 'which programs are connected?' in thread and 'Revit is connected.' in thread


def test_baboom_without_brain_refuses_instead_of_composer_fallthrough(monkeypatch):
    from nodelang import baboom_nograph, model_router, nograph_server

    composer = []
    monkeypatch.setitem(baboom_nograph._STATE, 'brain', None)
    monkeypatch.setitem(baboom_nograph._STATE, 'error', 'BABOOM brain unavailable: packaged Goose missing.')
    monkeypatch.setattr(model_router, 'composer_chat', lambda *a, **k: composer.append(1) or {
        'ok': True, 'answer': 'composer fallthrough', 'provider': 'Fake', 'model': 'fake'})
    task = _task('Brain down')
    with pytest.raises(RuntimeError, match='packaged Goose missing'):
        nograph_server._chat({'prompt': 'how many sheets?', 'agent': 'BABOOM', 'task': task}, lambda text: None)
    assert composer == []
    assert not any('sheets' in text for text in _thread(task))


def test_persona_still_answers_when_goose_brain_is_down(monkeypatch):
    from nodelang import baboom_nograph, model_router, nograph_server

    monkeypatch.setitem(baboom_nograph._STATE, 'brain', None)
    monkeypatch.setitem(baboom_nograph._STATE, 'error', 'BABOOM is turned off in Settings.')
    monkeypatch.setattr(model_router, 'composer_chat', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no fallthrough')))
    result = nograph_server._chat({'prompt': 'Are you a human?', 'agent': 'BABOOM'}, lambda text: None)
    assert 'AI assistant' in result['answer']
    assert result['provider'] == 'BABOOM (Goose)'


def test_workshop_task_composer_source_binds_the_selected_task():
    """The Workshop dock must pass taskId into sendChatTurn so Goose answers join that thread."""
    from pathlib import Path
    source = Path(__file__).resolve().parents[2] / '01.APP/nodelang/studio/ds_workshop3.jsx'
    text = source.read_text(encoding='utf-8')
    assert 'taskId={task?.id}' in text
    assert 'api.sendChatTurn({...turn, prompt}, replyTo && replyTo.handle === to ? replyTo.id : undefined, taskId || undefined)' in text
