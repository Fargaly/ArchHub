"""Optimize and Schedule on HiGHS: pure, time-bounded decision nodes with small textbook cases."""
import builtins
import random
import time
import types

import pytest


def test_optimize_knapsack_picks_the_best_pair():
    pytest.importorskip('highspy')
    from nodelang.decision_engines import optimize
    rows = [{'name': 'A', 'value': 6, 'weight': 1}, {'name': 'B', 'value': 10, 'weight': 2},
            {'name': 'C', 'value': 12, 'weight': 3}]
    out, _ = optimize({'objective': 'value', 'sense': 'Maximize', 'max_each': 1, 'whole_amounts': True,
                             'constraints': [{'field': 'weight', 'op': '<=', 'value': 5}]}, {'in': rows})
    assert [r['amount'] for r in out['out']] == [0, 1, 1] and out['objective'] == 22 and out['status'] == 'Optimal'


def test_optimize_cheapest_mix_meets_the_area():
    pytest.importorskip('highspy')
    from nodelang.decision_engines import optimize
    rows = [{'name': 'Tile', 'cost': 30, 'area': 1}, {'name': 'Panel', 'cost': 50, 'area': 2}]
    out, _ = optimize({'objective': 'cost', 'sense': 'Minimize', 'max_each': 100, 'whole_amounts': True},
                      {'in': rows, 'constraints': [{'field': 'area', 'op': '>=', 'value': 10}]})
    assert out['objective'] == 250 and [r['amount'] for r in out['out']] == [0, 5]


def test_optimize_infeasible_says_so_and_bad_input_is_refused():
    pytest.importorskip('highspy')
    from nodelang.decision_engines import optimize
    out, _ = optimize({'objective': 'cost', 'max_each': 1, 'constraints': [{'field': 'cost', 'op': '>=', 'value': 99}]},
                            {'in': [{'cost': 1}]})
    assert out['out'] == [] and 'Infeasible' in out['status']
    with pytest.raises(ValueError, match='finite number in cost'):
        optimize({'objective': 'cost'}, {'in': [{'cost': 'x'}]})


TASKS = [{'name': 'Survey', 'duration': 2}, {'name': 'Design', 'duration': 3, 'after': 'Survey'},
         {'name': 'Permit', 'duration': 4, 'after': ['Survey']}, {'name': 'Build', 'duration': 5, 'after': 'Design, Permit'}]


def _check(tasks, out, crews):
    at = {r['name']: r for r in out['out']}
    for task in tasks:
        after = task.get('after') or []
        for name in ([a.strip() for a in after.split(',')] if isinstance(after, str) else after):
            assert at[task['name']]['start'] >= at[name]['end']
    for day in range(out['finish']):
        assert sum(t.get('crew', 1) for t in tasks if at[t['name']]['start'] <= day < at[t['name']]['end']) <= crews


def test_schedule_respects_after_links_and_crews():
    pytest.importorskip('highspy')
    from nodelang.decision_engines import schedule
    out, _ = schedule({'crews': 2}, {'in': TASKS})
    _check(TASKS, out, 2)
    assert out['finish'] == 11 and out['status'] == 'Optimal'
    one, _ = schedule({'crews': 1}, {'in': TASKS})
    _check(TASKS, one, 1)
    assert one['finish'] == 14       # one crew: Design and Permit can no longer overlap
    with pytest.raises(ValueError, match='not a wired task'):
        schedule({}, {'in': [{'name': 'A', 'duration': 1, 'after': 'Ghost'}]})
    loop, _ = schedule({}, {'in': [{'name': 'A', 'duration': 1, 'after': 'B'}, {'name': 'B', 'duration': 1, 'after': 'A'}]})
    assert loop['out'] == [] and 'loop' in loop['status']


def test_schedule_thirty_tasks_stays_inside_two_seconds():
    pytest.importorskip('highspy')
    from nodelang.decision_engines import schedule
    pick = random.Random(7)
    tasks = []
    for i in range(30):
        earlier = pick.sample(range(i), min(i, pick.randint(0, 2)))
        tasks.append({'name': 'T%d' % i, 'duration': pick.randint(1, 6), 'crew': pick.randint(1, 2),
                      'after': ['T%d' % j for j in earlier]})
    began = time.perf_counter()
    out, _ = schedule({'crews': 3, 'time_limit': 2}, {'in': tasks})
    took = time.perf_counter() - began
    _check(tasks, out, 3)
    assert len(out['out']) == 30 and out['status'] in ('Optimal', 'Time limit reached')
    assert took < 2.0 + 1.0, took     # 2 s solver limit plus model building


def test_missing_solver_refuses_plainly(monkeypatch):
    from nodelang import decision_engines
    real = builtins.__import__
    monkeypatch.setattr(decision_engines, '_HIGHSPY', None)
    monkeypatch.setattr(builtins, '__import__', lambda name, *a, **k: (_ for _ in ()).throw(ImportError(name))
                        if name.startswith('highspy') else real(name, *a, **k))
    with pytest.raises(ValueError, match='Optimize needs the HiGHS solver.*Update ArchHub'):
        decision_engines.optimize({'objective': 'cost'}, {'in': [{'cost': 1}]})
    with pytest.raises(ValueError, match='Schedule needs the HiGHS solver'):
        decision_engines.schedule({}, {'in': [{'name': 'A', 'duration': 1}]})


def test_cards_are_pure_and_in_the_library():
    from nodelang.canvas_documents import is_pure
    from nodelang.library_engines import library_catalogue
    assert is_pure('decide.optimize') and is_pure('decide.schedule')
    cards = {i['id']: i for g in library_catalogue() for i in g['items']}
    assert cards['decide_optimize']['title'] == 'Optimize' and cards['decide_schedule']['title'] == 'Schedule'
    assert {p['id'] for p in cards['decide_optimize']['ports']['source']} >= {'out', 'objective', 'status'}
    assert next(d for d in cards['decide_optimize']['paramDefs'] if d['id'] == 'sense')['options'] == ['Minimize', 'Maximize']


def test_installer_ships_highspy_and_not_ortools():
    from pathlib import Path
    import colleague_setup
    root = Path(colleague_setup.__file__).resolve().parents[1]
    lines = (root / 'requirements.txt').read_text(encoding='utf-8').splitlines()
    assert 'highspy==1.16.0' in lines and not any(l.startswith(('ortools', 'pandas')) for l in lines)
    assert ('highspy', 'highspy') in colleague_setup.PACKAGES


@pytest.mark.parametrize('item,engine,key,good,bad', [
    ('decide_optimize', 'decide.optimize', 'sense', 'Maximize', 'Sideways'),
    ('decide_optimize', 'decide.optimize', 'time_limit', 5, 99),
    ('decide_schedule', 'decide.schedule', 'crews', 3, 0),
    ('decide_schedule', 'decide.schedule', 'time_limit', 1.5, 0),
])
def test_declared_parameters_set_promote_and_expose_typed(item, engine, key, good, bad):
    from nodelang import node_params
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES, library_catalogue
    for d in LIBRARY_ITEM_ENGINES[item]['paramDefs']:
        assert d['name'] and d['type'] in node_params.TYPES
    card = next(i for g in library_catalogue() for i in g['items'] if i['id'] == item)
    doc = {'nodes': [{'id': 'n', 'type': engine, 'item': item, 'title': card['title'], 'params': dict(card['params']),
                      'paramDefs': [dict(d) for d in card['paramDefs']], 'position': {'x': 0, 'y': 0}}],
           'wires': [], 'groups': [], 'notes': []}
    node_params.set_value(doc, 'n', key, good)
    with pytest.raises(ValueError):
        node_params.set_value(doc, 'n', key, bad)
    made = node_params.promote(doc, 'n', key)
    param = next(n for n in doc['nodes'] if n['id'] == made[0])
    node_params.set_value(doc, param['id'], 'value', good)
    assert doc['nodes'][0]['params'][key] == good
    with pytest.raises(ValueError):
        node_params.set_value(doc, param['id'], 'value', bad)


# A case the list schedule cannot prove best, so Schedule builds the solver model for it.
HARD = [{'name': 'T0', 'duration': 4, 'crew': 2}, {'name': 'T1', 'duration': 3, 'crew': 2, 'after': ['T0']},
        {'name': 'T2', 'duration': 4, 'crew': 2}, {'name': 'T3', 'duration': 2, 'crew': 2},
        {'name': 'T4', 'duration': 1, 'crew': 2}, {'name': 'T5', 'duration': 3, 'crew': 1}]


def test_schedule_refuses_more_work_than_the_horizon_before_building_anything():
    pytest.importorskip('highspy')
    from nodelang import decision_engines
    began = time.perf_counter()
    with pytest.raises(ValueError, match='at most 3650 days'):
        decision_engines.schedule({}, {'in': [{'name': 'Huge', 'duration': 10 ** 9}]})
    assert time.perf_counter() - began < 1
    with pytest.raises(ValueError, match='at most 1000 tasks'):
        decision_engines.schedule({}, {'in': [{'name': 'T%d' % i, 'duration': 0} for i in range(1001)]})


def test_schedule_too_many_start_choices_keeps_the_list_schedule(monkeypatch):
    pytest.importorskip('highspy')
    from nodelang import decision_engines
    built = []
    monkeypatch.setattr(decision_engines, 'STARTS_MAX', 1)
    monkeypatch.setattr(decision_engines, '_starts_model', lambda *a, **k: built.append(1))
    out, _ = decision_engines.schedule({'crews': 2}, {'in': HARD})
    assert not built and out['status'] == 'Time limit reached'
    _check(HARD, out, 2)


def test_schedule_running_out_of_time_while_building_keeps_the_list_schedule(monkeypatch):
    pytest.importorskip('highspy')
    from nodelang import decision_engines
    clock = iter([0.0, 0.0] + [100.0] * 1000)   # start, the check before building, then far past the limit
    monkeypatch.setattr(decision_engines, 'time', types.SimpleNamespace(perf_counter=lambda: next(clock)))
    out, _ = decision_engines.schedule({'crews': 2, 'time_limit': 2}, {'in': HARD})
    assert out['status'] == 'Time limit reached'
    _check(HARD, out, 2)


@pytest.mark.parametrize('params,row,message', [
    ({'crews': 0}, {}, 'Crews must be at least 1'),
    ({'crews': True}, {}, 'not yes/no'),
    ({'crews': 1.5}, {}, 'whole number'),
    ({'crews': 2}, {'crew': 0}, 'at least 1'),
    ({'crews': 2}, {'crew': False}, 'not yes/no'),
    ({'time_limit': 0}, {}, 'positive number of seconds'),
    ({'time_limit': True}, {}, 'positive number of seconds'),
    ({'time_limit': float('nan')}, {}, 'positive number of seconds'),
])
def test_schedule_explicit_zero_and_yes_no_are_refused_not_defaulted(params, row, message):
    pytest.importorskip('highspy')
    from nodelang.decision_engines import schedule
    with pytest.raises(ValueError, match=message):
        schedule(params, {'in': [{'name': 'A', 'duration': 1, **row}]})


@pytest.mark.parametrize('params,message', [
    ({'max_each': True}, 'Max each'),
    ({'max_each': float('nan')}, 'Max each'),
    ({'max_each': -1}, 'Max each'),
    ({'max_each': 'lots'}, 'Max each'),
    ({'constraints': [{'field': 'cost', 'op': '<=', 'value': float('nan')}]}, 'finite number'),
    ({'constraints': [{'field': 'cost', 'op': '<=', 'value': float('inf')}]}, 'finite number'),
    ({'time_limit': 0}, 'positive number of seconds'),
])
def test_optimize_refuses_bad_limits(params, message):
    pytest.importorskip('highspy')
    from nodelang.decision_engines import optimize
    with pytest.raises(ValueError, match=message):
        optimize({'objective': 'cost', **params}, {'in': [{'cost': 1}]})


def test_optimize_max_each_zero_means_none_of_it():
    pytest.importorskip('highspy')
    from nodelang.decision_engines import optimize
    out, _ = optimize({'objective': 'cost', 'sense': 'Maximize', 'max_each': 0}, {'in': [{'cost': 5}]})
    assert out['out'][0]['amount'] == 0 and out['objective'] == 0

def test_optimize_and_schedule_wired_feeds_override_params():
    pytest.importorskip('highspy')
    from nodelang.decision_engines import optimize, schedule
    # optimize with wired objective, sense, max_each, whole_amounts, time_limit
    rows = [{'name': 'A', 'val': 10}, {'name': 'B', 'val': 20}]
    out, _ = optimize({'objective': 'other', 'sense': 'Minimize'},
                      {'in': rows, 'objective': 'val', 'sense': 'Maximize', 'max_each': 1, 'whole_amounts': True, 'time_limit': 1.5})
    assert [r['amount'] for r in out['out']] == [1, 1] and out['objective'] == 30

    # schedule with wired crews and time_limit
    tasks = [{'name': 'T1', 'duration': 2}, {'name': 'T2', 'duration': 2}]
    out_s, _ = schedule({'crews': 1}, {'in': tasks, 'crews': 2, 'time_limit': 1.0})
    assert out_s['finish'] == 2 and out_s['status'] == 'Optimal'

