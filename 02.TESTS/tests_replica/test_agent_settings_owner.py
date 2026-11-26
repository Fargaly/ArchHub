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
