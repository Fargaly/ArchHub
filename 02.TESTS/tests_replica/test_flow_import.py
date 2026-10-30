"""S8 importers: real public Node-RED, Langflow and skills.sh files open on the canvas as nodes and run.

Fixtures are unmodified public samples (fixtures/flow_import/NOTICE.md). Each test imports through the
canvas Open action, then runs the opened document through the same run/solve calls the window uses.
"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / 'fixtures' / 'flow_import'


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    yield tmp_path


def open_and_run(name, invoke=True):
    from nodelang.enforce import guard_effect
    from nodelang.session_files import SessionFiles
    files = SessionFiles()
    opened = files.dispatch({'action': 'open', 'path': str(FIXTURES / name)})
    reopened = files.dispatch({'action': 'open', 'path': opened['path']})   # the .archhub opens like any session
    assert reopened['document']['nodes'] == opened['document']['nodes']
    ran = files.dispatch({'action': 'run', 'document': opened['document']}, invoke=guard_effect if invoke else None)
    return opened, ran


def by_type(document, kind):
    return [n for n in document['nodes'] if n['type'] == kind]


def test_node_red_change_flow_opens_as_nodes_and_runs():
    opened, ran = open_and_run('nodered-change.json')
    doc = opened['document']
    assert opened['path'].endswith('.archhub') and {n['type'] for n in doc['nodes']} == {'note', 'trigger.emit', 'text.ops', 'watch.preview'}
    assert all(n['source']['format'] == 'node-red' and n['ports'] and 'pure' in n and n['budget'] for n in doc['nodes'])
    debug = by_type(doc, 'watch.preview')[0]
    assert ran['succeeded'] and ran['results'][debug['id']]['output']['out'] == 'Hello World!'


def test_node_red_switch_routes_like_the_source_and_skips_untaken_branches():
    opened, ran = open_and_run('nodered-switch.json')
    doc = opened['document']
    statuses = {n['title']: ran['results'][n['id']]['status'] for n in doc['nodes'] if n['type'] == 'text.ops'}
    assert statuses == {'Negative': 'Done', 'Zero': 'Skipped', 'Positive': 'Skipped'}
    assert ran['succeeded'] and len(by_type(doc, 'control.if')) == 3 and len(by_type(doc, 'control.merge')) == 2
    shown = [ran['results'][n['id']] for n in by_type(doc, 'watch.preview')]
    assert [r['output']['out'] for r in shown if r['status'] == 'Done'] == ['negative']


def test_node_red_template_and_json_parse_run_on_the_canvas_solve():
    from nodelang.canvas_documents import solve
    from nodelang.enforce import guard_effect
    opened, ran = open_and_run('nodered-json.json')
    doc = opened['document']
    debug = by_type(doc, 'watch.preview')[0]
    assert ran['results'][debug['id']]['output']['out'] == {'kind': 'Apple', 'price': 100, 'origin': 'Canada'}
    # Pure nodes re-solve on an edit; effect nodes (template, convert) wait for Run.
    solved = solve(doc, [by_type(doc, 'text.ops')[0]['id']], invoke=guard_effect)
    assert by_type(doc, 'text.ops')[0]['id'] in solved['stale'] and debug['id'] in solved['stale']


def test_rule1_rule2_unknown_and_code_nodes_are_side_effect_and_never_run():
    for name, kind in (('nodered-function.json', 'function'), ('nodered-exec.json', 'exec')):
        opened, ran = open_and_run(name)
        foreign = [n for n in opened['document']['nodes'] if n['type'] == 'import.foreign']
        assert [n['params']['kind'] for n in foreign] == [kind]
        assert foreign[0]['pure'] is False
        result = ran['results'][foreign[0]['id']]
        assert result['status'] == 'Error' and 'Not run' in result['error'] and 'untrusted' in result['error']
        assert not ran['succeeded']
    opened, ran = open_and_run('langflow-simple-agent.json')
    tools = [n for n in opened['document']['nodes'] if n['type'] == 'import.foreign']
    assert {n['source']['type'] for n in tools} == {'Agent', 'URLComponent', 'UnifiedWebSearch'}
    assert all(not n['pure'] and ran['results'][n['id']]['status'] in ('Error', 'Blocked') for n in tools)
    agent = next(n for n in tools if n['source']['type'] == 'Agent')
    assert {'tools', 'tools#2'} <= {p['id'] for p in agent['ports']['target']}   # each tool keeps its own wire


def test_rule3_every_node_has_a_budget_and_repeating_inject_has_a_cap():
    opened, _ = open_and_run('nodered-repeat.json')
    inject = by_type(opened['document'], 'trigger.emit')[0]
    assert inject['budget']['runs'] == 100 and inject['budget']['repeat_seconds'] == 5.0 and inject['budget']['stop']
    assert all(n['budget'].get('seconds') for n in opened['document']['nodes'])


def test_rule4_reimport_updates_nodes_in_place_and_keeps_founder_work():
    from nodelang.session_files import SessionFiles, read_document, write_document
    files = SessionFiles()
    first = files.dispatch({'action': 'open', 'path': str(FIXTURES / 'nodered-change.json')})
    doc = read_document(first['path'])
    doc['nodes'][1]['position'] = {'x': 999, 'y': 7}
    doc['nodes'].append({'id': 'mine', 'type': 'note', 'title': 'My note', 'params': {'text': 'keep'}, 'position': {'x': 0, 'y': 0}})
    write_document(first['path'], doc)
    second = files.dispatch({'action': 'open', 'path': str(FIXTURES / 'nodered-change.json')})
    again = second['document']
    assert second['path'] == first['path'] and len(again['nodes']) == len(first['document']['nodes']) + 1
    assert next(n for n in again['nodes'] if n['id'] == doc['nodes'][1]['id'])['position'] == {'x': 999, 'y': 7}
    assert any(n['id'] == 'mine' for n in again['nodes'])
    assert again['properties']['history'][-1]['by'] == 'Import'


def test_langflow_basic_prompting_runs_through_the_model_node(monkeypatch):
    import nodelang.model_router as router
    asked = []
    monkeypatch.setattr(router, 'composer_chat', lambda body: asked.append(body) or {'answer': 'Hi from the model', 'model': 'fixture'})
    opened, ran = open_and_run('langflow-basic-prompting.json')
    doc = opened['document']
    assert {n['source']['type'] for n in doc['nodes'] if n['type'] != 'note'} == {'ChatInput', 'Prompt', 'LanguageModelComponent', 'ChatOutput'}
    assert ran['succeeded'] and len(asked) == 1
    assert asked[0]['prompt'].startswith('Answer the user as if you were a GenAI expert') and asked[0]['prompt'].endswith('Hello')
    output = by_type(doc, 'watch.preview')[0]
    assert ran['results'][output['id']]['output']['out'] == 'Hi from the model'


def test_skills_sh_skill_becomes_a_library_skill_that_runs(monkeypatch):
    import nodelang.workshop_mailbox as mailbox
    from nodelang.enforce import guard_effect
    from nodelang.session_files import SessionFiles, catalogue, new_document
    sent = []
    monkeypatch.setattr(mailbox, 'call', lambda op, args, ctx: sent.append(args) or {'message_id': 'm1'})
    opened = SessionFiles().dispatch({'action': 'open', 'path': str(FIXTURES / 'SKILL.md')})
    assert opened['kind'] == 'skill' and opened['document']['title'] == 'frontend-design'
    card = next(i for i in catalogue() if i['id'] == 'skill:' + opened['document']['id'])
    assert {p['id'] for p in card['ports']['target']} == {'in:sk-task'}
    doc = new_document('Use the skill')
    doc['nodes'] = [{'id': 'brief', 'type': 'param.value', 'title': 'Brief', 'params': {'type': 'text', 'value': 'A cafe menu page'},
                     'position': {'x': 0, 'y': 0}},
                    {'id': 'skill', 'type': 'skill', 'item': card['id'], 'title': card['title'], 'params': dict(card['params']),
                     'position': {'x': 300, 'y': 0}}]
    doc['wires'] = [{'id': 'w', 'from': {'node': 'brief', 'socket': 'value'}, 'to': {'node': 'skill', 'socket': 'in:sk-task'}}]
    ran = SessionFiles().dispatch({'action': 'run', 'document': doc}, invoke=guard_effect)
    assert ran['succeeded'] and len(sent) == 1
    assert sent[0]['text'].startswith('---\nname: frontend-design') and sent[0]['text'].endswith('Task: A cafe menu page')


def test_import_refuses_what_is_not_a_flow(tmp_path):
    from nodelang.session_files import SessionFiles
    bad = tmp_path / 'x.json'
    bad.write_text(json.dumps({'hello': 'world'}), encoding='utf-8')
    with pytest.raises(ValueError, match='Not a Node-RED flow'):
        SessionFiles().dispatch({'action': 'open', 'path': str(bad)})
