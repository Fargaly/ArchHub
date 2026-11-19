"""R31/R32: agent work never stacks cards or repeats one active order as many nodes, and never loses his edits."""
from hashlib import sha256


def _doc(*nodes):
    return {'nodes': list(nodes), 'wires': [], 'groups': [], 'properties': {}}


def _node(i, x, y, **extra):
    return {'id': i, 'type': 'note', 'title': i, 'params': {}, 'position': {'x': x, 'y': y}, **extra}


def test_free_spot_skips_taken_places_and_keeps_free_ones():
    from nodelang.canvas_documents import free_spot, CARD_W, CARD_GAP
    assert free_spot(_doc(), 0, 0) == {'x': 0, 'y': 0}
    assert free_spot(_doc(_node('a', 0, 0)), 0, 0) == {'x': CARD_W + CARD_GAP, 'y': 0}
    # A node inside a group does not block the top level.
    assert free_spot(_doc(_node('m', 0, 0, parent='g')), 0, 0) == {'x': 0, 'y': 0}


def test_free_spot_ten_agent_adds_never_overlap():
    from nodelang.canvas_documents import free_spot, CARD_W, CARD_H
    doc = _doc()
    for i in range(10):
        doc['nodes'].append(_node(str(i), **free_spot(doc, 0, 0)))
    points = [(n['position']['x'], n['position']['y']) for n in doc['nodes']]
    for i, (ax, ay) in enumerate(points):
        for bx, by in points[i + 1:]:
            assert abs(ax - bx) >= CARD_W or abs(ay - by) >= CARD_H


def _declare(i, task, work='R1'):
    return {'id': i, 'tool': 'declare', 'input': {'task': task, 'request_id': work}, 'turn': i}


def _read(i, path):
    return {'id': i, 'tool': 'Read', 'input': {'path': path}, 'turn': i}


def test_only_a_proven_active_repeat_is_one_step():
    from nodelang.agent_work import steps
    calls = [_declare('d1', 'Fix doors'), _read('c1', 'a'), _declare('d2', 'Fix doors'), _read('c2', 'b'),
             {'id': 'done', 'tool': 'task_complete', 'input': {}, 'turn': 'x'},
             _declare('d3', 'Fix doors'), _read('c3', 'c'),                 # same label after it finished: new
             _declare('d4', 'Fix doors', work='R2'),                        # same label, other work: new
             _declare('d5', 'Sheets', work='')]                             # no work identity: never merged
    groups = steps({'calls': calls})
    assert [(g['key'], [c['id'] for c in g['calls']]) for g in groups] == [
        ('d1', ['c1', 'c2']), ('d3', ['c3']), ('d4', []), ('d5', [])]
    unproven = steps({'calls': [_declare('a', 'Same', work=''), _declare('b', 'Same', work='')]})
    assert len(unproven) == 2


def _work_id(session, key):
    return 'work-' + sha256((session + '\0' + key).encode()).hexdigest()[:24]


def _old_step(session, key, path, calls, **extra):
    """A step exactly as the earlier projection wrote it (grid place, its paramDefs and ports, approval)."""
    from nodelang.agent_work import _definitions
    from nodelang.canvas_documents import THING_ENGINES
    spec = THING_ENGINES['thing.file']
    return {'id': _work_id(session, key), 'type': 'thing.file', 'title': 'Fix doors', 'params': {'path': path},
            'paramDefs': _definitions({'path': path}), 'ports': {'source': spec['out'], 'target': spec['in']},
            'approvalRequired': True, 'position': {'x': 464, 'y': 380}, **extra,
            'agentWork': {'role': 'step', 'owner': session, 'calls': calls, 'task': 'T', 'state': 'working'}}


def _migrate(tmp_path, document, calls, session='s'):
    """Write the file with the native writer, read it back, project, write and read again (the save must succeed)."""
    from nodelang import agent_work
    from nodelang.session_files import write_document, read_document
    path = tmp_path / 'migrate.archhub'
    write_document(path, document)
    opened = read_document(path)
    agent_work.project(opened, next(n for n in opened['nodes'] if n['id'] == session), {'task_id': 'T'}, {'calls': calls})
    write_document(path, opened)
    return read_document(path)


def test_two_copies_with_different_wires_into_one_input_both_stay_and_the_file_saves(tmp_path):
    from nodelang.session_files import new_document
    session, document = 's', new_document('Doors')
    document['nodes'] += [_node(session, 0, 0, type='thing.agent'), _node('x', 0, 600), _node('y', 300, 600),
                          _old_step(session, 'd1', 'a', ['c1']), _old_step(session, 'd2', 'a', ['c2']),
                          _old_step(session, 'd3', 'a', ['c3'], position={'x': 784, 'y': 380})]
    document['wires'] += [
        {'id': 'wx', 'from': {'node': 'x', 'socket': 'value'}, 'to': {'node': _work_id(session, 'd2'), 'socket': 'param:path'}, 'rule': 'value > 1'},
        {'id': 'wy', 'from': {'node': 'y', 'socket': 'value'}, 'to': {'node': _work_id(session, 'd3'), 'socket': 'param:path'}}]
    calls = [_declare('d1', 'Fix doors'), _read('c1', 'a'), _declare('d2', 'Fix doors'), _read('c2', 'a'),
             _declare('d3', 'Fix doors'), _read('c3', 'a')]
    after = _migrate(tmp_path, document, calls)
    ids = {n['id'] for n in after['nodes']}
    assert {_work_id(session, 'd2'), _work_id(session, 'd3')} <= ids          # ambiguous: both copies kept
    assert {w['id']: w['to']['node'] for w in after['wires'] if w['id'] in ('wx', 'wy')} == {
        'wx': _work_id(session, 'd2'), 'wy': _work_id(session, 'd3')}
    assert next(w for w in after['wires'] if w['id'] == 'wx')['rule'] == 'value > 1'


def test_a_copy_he_styled_or_moved_stays(tmp_path):
    from nodelang.session_files import new_document
    session, document = 's', new_document('Doors')
    document['nodes'] += [_node(session, 0, 0, type='thing.agent'), _old_step(session, 'd1', 'a', ['c1']),
                          _old_step(session, 'd2', 'a', ['c2'], icon='door-open', color='#d56045'),
                          _old_step(session, 'd3', 'a', ['c3'], position={'x': 500, 'y': 410})]   # moved by hand
    calls = [_declare('d1', 'Fix doors'), _read('c1', 'a'), _declare('d2', 'Fix doors'), _read('c2', 'a'),
             _declare('d3', 'Fix doors'), _read('c3', 'a')]
    after = _migrate(tmp_path, document, calls)
    styled = next(n for n in after['nodes'] if n['id'] == _work_id(session, 'd2'))
    assert styled['icon'] == 'door-open' and styled['color'] == '#d56045'
    assert _work_id(session, 'd3') in {n['id'] for n in after['nodes']}


def test_migration_on_a_real_file_keeps_his_wire_condition_group_and_the_distinct_task(tmp_path):
    from nodelang import agent_work
    from nodelang.session_files import new_document, write_document, read_document
    session = 's'
    document = new_document('Doors')
    survivor_id, copy_id, later_id = _work_id(session, 'd1'), _work_id(session, 'd2'), _work_id(session, 'd3')
    document['nodes'] += [
        _node(session, 0, 0, type='thing.agent', title='Agent'),
        _node('mine', 0, 600, title='My input'),
        _old_step(session, 'd1', 'a', ['c1']),
        _old_step(session, 'd2', 'a', ['c2']),                          # a repeat declare of the same active work
    ]
    document['wires'].append({'id': 'his', 'from': {'node': 'mine', 'socket': 'value'},
                              'to': {'node': copy_id, 'socket': 'param:path'}, 'rule': 'value != ""'})
    document['groups'].append({'id': 'g1', 'title': 'Doors work', 'nodes': [copy_id, 'mine']})
    path = tmp_path / 'doors.archhub'
    write_document(path, document)
    opened = read_document(path)
    calls = [_declare('d1', 'Fix doors'), _read('c1', 'a'), _declare('d2', 'Fix doors'), _read('c2', 'a'),
             {'id': 'done', 'tool': 'task_complete', 'input': {}, 'turn': 'x'},
             _declare('d3', 'Fix doors'), _read('c3', 'z'),
             _declare('d4', 'Fix doors', work='R2'), _read('c4', 'y')]   # another work, same name
    agent = next(n for n in opened['nodes'] if n['id'] == session)
    agent_work.project(opened, agent, {'task_id': 'T'}, {'calls': calls})
    write_document(path, opened)
    after = read_document(path)
    ids = {n['id'] for n in after['nodes']}
    assert copy_id not in ids and survivor_id in ids
    other_id = _work_id(session, 'd4')
    assert later_id in ids and other_id in ids and sum(n['title'] == 'Fix doors' for n in after['nodes']) == 3   # distinct same-named tasks stay
    wire = next(w for w in after['wires'] if w['id'] == 'his')
    assert wire['to'] == {'node': survivor_id, 'socket': 'param:path'} and wire['rule'] == 'value != ""'
    assert set(next(g for g in after['groups'] if g['id'] == 'g1')['nodes']) == {survivor_id, 'mine'}
    saved = after['properties']['checkpoints'][-1]
    assert saved['title'] == 'Before merging repeated steps' and copy_id in {n['id'] for n in saved['document']['nodes']}
    assert later_id not in {n['id'] for n in saved['document']['nodes']}      # the file as it was before projection


def test_an_edited_or_conflicting_copy_is_left_intact():
    from nodelang import agent_work
    session = 's'
    calls = [_declare('d1', 'Fix doors'), _read('c1', 'a'), _declare('d2', 'Fix doors'), _read('c2', 'a')]
    edited = _doc(_node(session, 0, 0, type='thing.agent'), _old_step(session, 'd1', 'a', ['c1']),
                  _old_step(session, 'd2', 'his own path', ['c2']))
    agent_work.project(edited, edited['nodes'][0], {'task_id': 'T'}, {'calls': calls})
    assert _work_id(session, 'd2') in {n['id'] for n in edited['nodes']} and 'checkpoints' not in edited['properties']
    clash = _doc(_node(session, 0, 0, type='thing.agent'), _node('x', 0, 0), _node('y', 0, 0),
                 _old_step(session, 'd1', 'a', ['c1']), _old_step(session, 'd2', 'a', ['c2']))
    clash['wires'] += [{'id': 'w1', 'from': {'node': 'x', 'socket': 'value'}, 'to': {'node': _work_id(session, 'd1'), 'socket': 'param:path'}},
                       {'id': 'w2', 'from': {'node': 'y', 'socket': 'value'}, 'to': {'node': _work_id(session, 'd2'), 'socket': 'param:path'}}]
    agent_work.project(clash, clash['nodes'][0], {'task_id': 'T'}, {'calls': calls})
    assert _work_id(session, 'd2') in {n['id'] for n in clash['nodes']} and len(clash['wires']) == 2


def test_bounded_sweep_every_one_or_two_hand_edges_across_repeats_migrates_and_saves(tmp_path):
    """Every placement of 1-2 hand-drawn wires among the survivor, two repeated copies and two user nodes:
    the projection never fails, every file saves, no wire is lost or bent onto a clash, and conditions survive."""
    from itertools import combinations
    from nodelang.session_files import new_document, write_document, read_document
    from nodelang import agent_work
    session = 's'
    names = {'S': _work_id(session, 'd1'), 'C1': _work_id(session, 'd2'), 'C2': _work_id(session, 'd3'), 'U1': 'u1', 'U2': 'u2'}
    edges = [(a, b) for a in names for b in names if a != b]
    cases = [c for k in (1, 2) for c in combinations(edges, k) if len({b for _a, b in c}) == len(c)]   # one wire per input
    calls = [_declare('d1', 'Fix doors'), _read('c1', 'a'), _declare('d2', 'Fix doors'), _read('c2', 'a'),
             _declare('d3', 'Fix doors'), _read('c3', 'a')]
    failures, saved, merged = [], 0, 0
    for number, case in enumerate(cases):
        document = new_document('Sweep')
        document['nodes'] += [_node(session, 0, 0, type='thing.agent'),
                              _old_step(session, 'd1', 'a', ['c1']), _old_step(session, 'd2', 'a', ['c2']),
                              _old_step(session, 'd3', 'a', ['c3'], position={'x': 784, 'y': 380}),
                              {**_old_step(session, 'u1', 'u', []), 'id': 'u1', 'agentWork': {}},
                              {**_old_step(session, 'u2', 'v', []), 'id': 'u2', 'agentWork': {}}]
        for index, (a, b) in enumerate(case):
            document['wires'].append({'id': 'h%d' % index, 'from': {'node': names[a], 'socket': 'path'},
                                      'to': {'node': names[b], 'socket': 'param:path'}, 'rule': 'rule %d' % index})
        path = tmp_path / ('sweep-%d.archhub' % number)
        write_document(path, document)
        try:
            opened = read_document(path)
            agent_work.project(opened, next(n for n in opened['nodes'] if n['id'] == session), {'task_id': 'T'}, {'calls': calls})
            write_document(path, opened)
            after = read_document(path)
        except Exception as error:   # the sweep reports every failing case, not just the first
            failures.append((case, repr(error)))
            continue
        saved += 1
        ids = {n['id'] for n in after['nodes']}
        merged += names['C1'] not in ids
        for wire in [w for w in after['wires'] if w['id'].startswith('h')]:
            assert wire['from']['node'] in ids and wire['to']['node'] in ids and wire['from']['node'] != wire['to']['node'], case
        assert {w['rule'] for w in after['wires'] if w['id'].startswith('h')} == {'rule %d' % i for i in range(len(case))}, case
    assert not failures, failures[:5]
    assert saved == len(cases) == 180, (saved, len(cases))
    assert 0 < merged < len(cases), merged   # copies merge where it is safe and stay where it is not
    print('NOJUNK sweep: %d files, %d saved, %d with the copy merged, 0 failures' % (len(cases), saved, merged))
