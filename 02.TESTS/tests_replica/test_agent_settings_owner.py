"""Settings › Agents rows: one owner (settings.json), validated writes, and the code that does the work reads them."""
import time

import pytest


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    from nodelang.nograph_server import JsonFile
    from nodelang.settings_owner import preference_settings
    settings = JsonFile(tmp_path / 'settings' / 'settings.json', {})

    def write(label, value):
        preference_settings('setAppearance', ['Agents.' + label, value], settings)
    return write


def test_rows_are_setting_nodes_with_defaults_and_refuse_bad_values(owner):
    from nodelang.canvas_documents import thing_items
    from nodelang.settings_owner import preference_settings
    rows = {row['label']: row for row in preference_settings()['appearanceSettings'] if row['id'].startswith('Agents.')}
    assert rows['Effort']['value'] == 'Medium' and rows['Effort']['options'] == ['Low', 'Medium', 'High']
    assert rows['Time per run']['control'] == 'range' and (rows['Time per run']['min'], rows['Time per run']['max']) == (10, 600)
    assert {'thing:setting:Agents.' + label for label in rows} <= {item['id'] for item in thing_items()}
    with pytest.raises(ValueError):
        owner('Effort', 'Extreme')
    with pytest.raises(ValueError):
        owner('Time per run', 5)
    owner('Effort', 'High')
    assert next(r for r in preference_settings()['appearanceSettings'] if r['id'] == 'Agents.Effort')['value'] == 'High'


def test_budget_trigger_reaction_stop_and_loop_follow_the_rows(owner):
    from nodelang import agent_budget
    from nodelang.baboom_reactions import emit
    from nodelang.canvas_triggers import missed_while_closed
    from nodelang.native_stop_hook import local_idle_stop_decision
    from nodelang.stem_graph_evaluation import run_stem_operation
    assert agent_budget.cap_for('x') is None and agent_budget.window_seconds() == 86400
    owner('Daily tokens per agent', '50k tokens')
    owner('Token budget counts over', '7 days')
    assert agent_budget.cap_for('x') == 50000 and agent_budget.window_seconds() == 604800
    last = time.time() - 3600
    assert not missed_while_closed({'every_seconds': '600'}, last)
    owner('Runs missed while closed', 'Run once')
    assert missed_while_closed({'every_seconds': '600'}, last)
    owner('Reactions', False)
    assert emit({'hook_event_name': 'Stop', 'session_id': 's'}, 'claude-code') is False
    owner('Agents finish and report', False)
    assert local_idle_stop_decision({'transcript_path': __file__}, 'claude-code') is None
    owner('Loop rounds', 10)
    produced, shown = run_stem_operation('control.foreach', {}, {'items': list(range(25))})
    assert produced['results'] == list(range(10)) and '10 of 25' in shown


def test_a_run_stops_at_its_model_calls_before_any_send(owner):
    from nodelang.model_router import RUN_CALLS, ModelRouteRefused, route_chat
    token = RUN_CALLS.set([1, 1])
    try:
        with pytest.raises(ModelRouteRefused, match='Model calls per run'):
            route_chat('openrouter/free', [{'role': 'user', 'content': 'hi'}], opener=lambda *a, **k: pytest.fail('sent'))
    finally:
        RUN_CALLS.reset(token)


def test_a_run_started_inside_a_run_never_waits_for_its_own_slot(owner, monkeypatch):
    import threading
    from nodelang import session_files
    owner('Running agents at once', 1)
    calls = []

    def inner(document, **options):
        calls.append(document)
        return session_files.run_document('nested') if document == 'outer' else {'ok': True}
    monkeypatch.setattr(session_files, '_run_document', inner)
    done = threading.Thread(target=session_files.run_document, args=('outer',), daemon=True)
    done.start()
    done.join(10)
    assert not done.is_alive() and calls == ['outer', 'nested']


def test_workshop_rules_refuse_by_setting_and_hold_questions_over_the_cap(owner):
    from nodelang.workshop_mailbox import _agent_send_rules, application_history
    identity = {'sender': 'Agent [agent:1:2]', 'sender_key': 'agent:1:2', 'sender_label': 'Agent'}
    question = {'to': 'ahmed', 'text': 'Which folder do you want?'}
    assert _agent_send_rules(None, {'to': 'codex', 'text': 'hi'}, identity)['to'] == 'codex'   # default: anyone
    owner('Who may message whom', 'Coordinator')
    with pytest.raises(ValueError, match='coordinator'):
        _agent_send_rules(None, {'to': 'codex', 'text': 'hi'}, identity)
    assert _agent_send_rules(None, {'to': '717', 'text': 'hi'}, identity)['to'] == '717'
    owner('Questions an agent may ask you a day', 0)
    with application_history() as history:
        held = _agent_send_rules(history, question, identity)
    assert held['to'] == 'workshop' and held['reply_to'] and held['text'].startswith('Waiting for you')


def test_every_program_archhub_opens_has_its_own_host_effects_switch():
    from nodelang.host_brokers import HOST_EFFECT_PROGRAMS, launch_effect_host
    assert {'revit', 'acad', 'max', 'rhino', 'blender', 'office', 'photoshop', 'teams', 'lmstudio'} <= set(HOST_EFFECT_PROGRAMS)
    assert [launch_effect_host(app) for app in ('Photoshop', 'LM Studio', 'teams', 'excel', 'notepad')] == \
        ['photoshop', 'lmstudio', 'teams', 'office', '']


_HOLDER = '''
import sys, time
sys.path.insert(0, sys.argv[1])
from nodelang.canvas_documents import locked
with locked(sys.argv[2]):
    print("held", flush=True)
    time.sleep(1.5)
'''


@pytest.mark.parametrize('writer', ['settings', 'router'])
def test_settings_and_router_writes_wait_for_another_process_and_fsync(tmp_path, monkeypatch, writer):
    """Agents write settings from their own processes: a write must wait for another process's
    read-modify-write (cross-process lock), and land flushed + fsynced through a unique temporary."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path))
    from nodelang.nograph_server import JsonFile
    from nodelang.settings_owner import SettingsOwner, router_settings_path
    target = tmp_path / 'settings' / 'settings.json' if writer == 'settings' else router_settings_path()
    app = str(Path(__file__).resolve().parents[2] / '01.APP')
    holder = subprocess.Popen([sys.executable, '-c', _HOLDER, app, str(target)], stdout=subprocess.PIPE, text=True,
                              env={**os.environ, 'ARCHHUB_TEST_STATE_DIR': str(tmp_path)})
    try:
        assert holder.stdout.readline().strip() == 'held'
        synced = []
        real_fsync = os.fsync
        monkeypatch.setattr(os, 'fsync', lambda fd: synced.append(fd) or real_fsync(fd))
        started = time.monotonic()
        if writer == 'settings':
            JsonFile(target, {}).update({'theme': 'dark'})
        else:
            SettingsOwner.setRouterSettings(object.__new__(SettingsOwner), {'free_first': True})
        waited = time.monotonic() - started
    finally:
        holder.wait(timeout=10)
    assert waited >= 0.5, waited          # it waited for the other process instead of writing over it
    assert synced                         # flushed to disk before the replace
    assert not list(target.parent.glob('*.tmp'))
